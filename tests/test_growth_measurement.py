"""T01: inventario unificado, cohortes por edad real y reporte comparativo."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils import growth_measurement as gm
from utils import kpis
from utils.file_manager import load_json, save_json

HOUR = 3600
NOW = 1_793_300_000


class GrowthMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for target, name, value in (
            (kpis, "MEDIA_INSIGHTS_PATH", str(self.root / "ig_media_insights.json")),
            (kpis, "data_dir", lambda: self.root),
            (gm, "data_dir", lambda: self.root),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"GROWTH_METRICS_ENABLED": "false"})
        env.start()
        self.addCleanup(env.stop)

    def _write(self, name, data):
        save_json(str(self.root / name), data)

    # ── flag y compatibilidad ──
    def test_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(gm.growth_metrics_enabled())

    def test_flag_off_keeps_latest_shape_and_writes_no_cohorts(self):
        kpis.record_media_insights([{"media_id": "m1", "posted_at": NOW - 30 * HOUR, "seccion": "policiales", "reach": 10, "interactions": 2}], now=NOW)
        record = load_json(kpis.MEDIA_INSIGHTS_PATH, {}, expected_type=dict)["media"]["m1"]
        self.assertEqual({"posted_at", "seccion", "reach", "interactions", "updated_at"}, set(record))

    def test_merge_never_loses_history_even_with_flag_off(self):
        kpis.record_media_insights([{"media_id": "m1", "posted_at": NOW - 30 * HOUR, "reach": 10, "interactions": 2}], now=NOW, cohorts=True)
        kpis.record_media_insights([{"media_id": "m1", "posted_at": NOW - 30 * HOUR, "reach": 50, "interactions": 3}], now=NOW + HOUR, cohorts=False)
        record = load_json(kpis.MEDIA_INSIGHTS_PATH, {}, expected_type=dict)["media"]["m1"]
        self.assertEqual(50.0, record["reach"])
        self.assertEqual(10, record["cohorts"]["24h"]["reach"])

    # ── cohortes ──
    def test_eleven_hour_reading_is_never_labelled_72h(self):
        self.assertEqual("lt24h", gm.cohort_for(11))
        self.assertEqual("24h", gm.cohort_for(30))
        self.assertEqual("72h", gm.cohort_for(80))
        self.assertEqual("7d", gm.cohort_for(200))
        self.assertIsNone(gm.cohort_for(None))

    def test_cohorts_keep_first_reading_after_threshold_and_latest_early(self):
        posted = NOW - 26 * HOUR
        for offset, reach in ((-20 * HOUR, 5), (-16 * HOUR, 9), (0, 40), (HOUR, 45)):
            kpis.record_media_insights([{"media_id": "m", "posted_at": posted, "reach": reach, "interactions": 1}], now=NOW + offset, cohorts=True)
        cohorts = load_json(kpis.MEDIA_INSIGHTS_PATH, {}, expected_type=dict)["media"]["m"]["cohorts"]
        self.assertEqual(9, cohorts["lt24h"]["reach"])  # última lectura temprana
        self.assertEqual(40, cohorts["24h"]["reach"])  # primera ≥ 24 h, no la posterior
        self.assertEqual(26.0, cohorts["24h"]["age_h"])

    def test_missing_values_stay_none_in_cohorts(self):
        record = {"posted_at": NOW - 30 * HOUR}
        gm.update_cohorts(record, at=NOW, reach=None, interactions=None)
        self.assertIsNone(record["cohorts"]["24h"]["reach"])

    # ── inventario ──
    def _stores(self):
        self._write("ig_posted.json", {"posted": {
            "link:a": {"posted_at": NOW - 30 * HOUR, "external_id": "111", "titulo": "Nota A", "texto_instagram": "Caption A",
                       "seccion": "Policiales", "source": "infobae_policiales"},
            "link:b": {"posted_at": NOW - 30 * HOUR, "external_id": "222", "titulo": "Reel B", "seccion": "Espectaculos",
                       "source": "paparazzi", "media_type": "reel"},
            "link:c": {"posted_at": NOW - 30 * HOUR, "titulo": "Sin ID"},
        }})
        self._write("paparazzi_reels_posted.json", {"posted": {
            "reel:b": {"posted_at": NOW - 30 * HOUR, "instagram_id": "222", "titulo": "Reel B"},
        }})
        self._write("premium_ig_posted.json", {"posted": {"premium:x": {"posted_at": NOW - 30 * HOUR, "external_id": "333", "titulo": "Premium"}}})
        self._write("social_formats_state.json", {"brief": {"2026-10-29": {"ig_id": "444", "attempts": 1, "updated_at": NOW}}})
        self._write("web_feed_state.json", {"permalinks": {
            "111": {"media_type": "IMAGE", "permalink": "https://instagram.com/p/x"},
            "444": {"media_type": "CAROUSEL_ALBUM", "timestamp": "2026-10-29T10:00:00+0000"},
        }})

    def test_repeated_id_in_two_stores_counts_once(self):
        self._stores()
        items = {i["media_id"]: i for i in gm.load_inventory()}
        self.assertEqual({"111", "222", "333", "444"}, set(items))
        self.assertEqual("paparazzi_reels", items["222"]["workflow"])
        self.assertEqual(["automatic"], items["222"]["also_in"])

    def test_formats_are_confirmed_or_unknown_never_assumed_image(self):
        self._write("ig_posted.json", {"posted": {"k": {"posted_at": NOW, "external_id": "999", "titulo": "Sin formato"}}})
        self.assertEqual(("unknown", "none"), (gm.load_inventory()[0]["content_type"], gm.load_inventory()[0]["content_type_source"]))
        self._stores()
        items = {i["media_id"]: i for i in gm.load_inventory()}
        self.assertEqual(("image", "graph"), (items["111"]["content_type"], items["111"]["content_type_source"]))
        self.assertEqual(("reel", "publisher"), (items["222"]["content_type"], items["222"]["content_type_source"]))
        self.assertEqual("carousel", items["444"]["content_type"])
        # La hora de los formatos sociales sale de Graph, no del estado.
        self.assertIsNotNone(items["444"]["posted_at"])

    def test_inventory_keeps_final_title_caption_and_story_key(self):
        self._stores()
        item = {i["media_id"]: i for i in gm.load_inventory()}["111"]
        self.assertEqual(("Nota A", "Caption A", "link:a", "policiales"), (item["title"], item["caption"], item["story_key"], item["category"]))

    # ── reporte ──
    def test_report_missing_is_nd_not_zero_and_late_measurement_has_its_age(self):
        self._stores()
        kpis.record_media_insights([{"media_id": "111", "posted_at": NOW - 30 * HOUR, "reach": 100, "interactions": 4}], now=NOW, cohorts=True)
        report = gm.growth_report(days=30, now=NOW + HOUR)
        self.assertEqual(4, report["coverage"]["publications"])
        self.assertEqual(1, report["coverage"]["with_any_measurement"])
        self.assertEqual({"lt24h": 0, "24h": 1, "72h": 0, "7d": 0}, report["coverage"]["by_cohort"])
        self.assertNotIn("reel", report["by"]["content_type"])  # sin medición: no aparece como 0
        self.assertIsNone(report["extraordinary"]["24h"]["threshold"])  # muestra insuficiente

    def test_extraordinary_separated_from_habitual(self):
        inventory = [{"media_id": str(i), "posted_at": NOW - 30 * HOUR, "content_type": "image", "source": "s", "category": "c", "workflow": "automatic", "title": f"t{i}"} for i in range(6)]
        media = {str(i): {"posted_at": NOW - 30 * HOUR, "reach": r, "interactions": 1, "updated_at": NOW} for i, r in enumerate([100, 110, 90, 105, 95, 5000])}
        report = gm.growth_report(days=30, now=NOW, inventory=inventory, media=media)
        ex = report["extraordinary"]["24h"]
        self.assertEqual(["5"], [o["media_id"] for o in ex["outliers"]])
        self.assertEqual(100.0, ex["habitual"]["median"])
        self.assertGreater(ex["share_of_total"], 0.9)

    def test_evolution_with_multiple_snapshots(self):
        inventory = [{"media_id": "m", "posted_at": NOW - 80 * HOUR, "content_type": "reel", "workflow": "automatic", "title": "x"}]
        media = {"m": {"posted_at": NOW - 80 * HOUR, "reach": 900, "updated_at": NOW, "cohorts": {
            "lt24h": {"age_h": 3, "reach": 100, "interactions": 1}, "24h": {"age_h": 25, "reach": 600, "interactions": 3}}}}
        report = gm.growth_report(days=30, now=NOW, inventory=inventory, media=media)
        self.assertEqual(100, report["evolution"][0]["reach_from"])
        self.assertEqual(900, report["evolution"][0]["reach_to"])

    def test_due_for_cohort_skips_fresh_known_and_already_fetched(self):
        inventory = [
            {"media_id": "fresh", "posted_at": NOW - 5 * HOUR},
            {"media_id": "due", "posted_at": NOW - 30 * HOUR},
            {"media_id": "done", "posted_at": NOW - 30 * HOUR},
            {"media_id": "fetched", "posted_at": NOW - 30 * HOUR},
            {"media_id": "old_due", "posted_at": NOW - 100 * HOUR},
        ]
        media = {"done": {"cohorts": {"24h": {}}}}
        due = gm.due_for_cohort(inventory, media, now=NOW, exclude={"fetched"}, limit=5)
        self.assertEqual(["due", "old_due"], [i["media_id"] for i in due])
        self.assertEqual(["due"], [i["media_id"] for i in gm.due_for_cohort(inventory, media, now=NOW, exclude=set(), limit=1)][:1])


class IgInsightsCohortTests(unittest.TestCase):
    def _run_main(self, flag: str):
        import json
        from meta import ig_insights

        posted = {"posted": {"link:a": {"external_id": "recent", "seccion": "Politica", "posted_at": NOW - HOUR}}}
        payload = {"data": [{"name": "reach", "values": [{"value": 10}]}, {"name": "total_interactions", "values": [{"value": 1}]}]}
        calls = []

        class Resp:
            status_code = 200

            def json(self):
                return payload

        def fake_get(url, params=None, timeout=None):
            calls.append(url)
            return Resp()

        inventory = [{"media_id": "old", "posted_at": NOW - 30 * HOUR, "category": "policiales"}]
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "ig_posted.json"
            state.write_text(json.dumps(posted), encoding="utf-8")
            perf = Path(tmp) / "perf.json"
            with mock.patch.dict(os.environ, {"IG_STATS_ENABLED": "true", "GROWTH_METRICS_ENABLED": flag}),                     mock.patch.object(ig_insights, "IG_ACCOUNT_ID", "acc"),                     mock.patch.object(ig_insights, "IG_ACCESS_TOKEN", "token"),                     mock.patch.object(ig_insights, "IG_STATE_PATH", str(state)),                     mock.patch.object(ig_insights, "PERFORMANCE_PATH", str(perf)),                     mock.patch.object(ig_insights, "MEDIA_INSIGHTS_PATH", str(Path(tmp) / "m.json")),                     mock.patch("utils.growth_measurement.load_inventory", return_value=inventory),                     mock.patch.object(ig_insights.time, "time", return_value=NOW),                     mock.patch.object(ig_insights.requests, "get", side_effect=fake_get),                     mock.patch.object(ig_insights, "_record_kpis") as record:
                result = ig_insights.main()
            snapshot = json.loads(perf.read_text(encoding="utf-8"))
        return result, calls, record.call_args.args[0], snapshot

    def test_flag_off_makes_no_extra_requests(self):
        result, calls, entries, snapshot = self._run_main("false")
        self.assertEqual(1, len(calls))
        self.assertEqual(["recent"], [e["media_id"] for e in entries])
        self.assertNotIn("cohorts", result.details)

    def test_flag_on_adds_due_cohort_without_touching_category_performance(self):
        result, calls, entries, snapshot = self._run_main("true")
        self.assertEqual(2, len(calls))
        self.assertEqual(["recent", "old"], [e["media_id"] for e in entries])
        self.assertEqual(1, snapshot["overall"]["sample_size"])  # el router ve el mismo universo
        self.assertEqual(1, result.details["cohorts"]["measured"])
        self.assertEqual(1, result.succeeded)

    def test_cohort_entries_bounded_and_failures_skipped(self):
        from meta import ig_insights

        inventory = [{"media_id": str(i), "posted_at": NOW - 30 * HOUR, "category": "policiales"} for i in range(10)]
        values = {"0": {"reach": 5, "total_interactions": 1}}
        with mock.patch("utils.growth_measurement.load_inventory", return_value=inventory), \
                mock.patch.object(ig_insights, "load_json", return_value={"media": {}}), \
                mock.patch.object(ig_insights, "COHORT_MAX_PER_RUN", 3), \
                mock.patch.object(ig_insights.time, "time", return_value=NOW), \
                mock.patch.object(ig_insights, "_fetch_insights", side_effect=lambda mid: values.get(mid)) as fetch:
            out = ig_insights._cohort_entries(set())
        self.assertEqual(3, fetch.call_count)
        self.assertEqual({"due": 3, "measured": 1, "missing": 2}, {k: out[k] for k in ("due", "measured", "missing")})
        self.assertEqual("0", out["entries"][0]["media_id"])


if __name__ == "__main__":
    unittest.main()
