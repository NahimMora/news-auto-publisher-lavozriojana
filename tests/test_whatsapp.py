"""Canal y grupo de WhatsApp y la historia "Sumate a nuestro WhatsApp"."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from unittest import mock

from utils.social_time import AR_TZ

NOW = time.time()
ENV = {
    "WHATSAPP_ENABLED": "true",
    "WHATSAPP_DRY_RUN": "false",
    "WHATSAPP_GROUP_JID": "1@g.us",
    "WHATSAPP_CHANNEL_JID": "2@newsletter",
    "WHATSAPP_QUIET_HOURS": "",
}


def _note(n: int, **extra) -> dict:
    return {"titulo": f"Inauguraron la plaza número {n} en Chilecito", "canonical_url": f"https://src/{n}",
            "web_url": f"https://lavozriojana.com/noticias/plaza-{n}", "excerpt": "Texto del copete.",
            "seccion": "sociedad", "imagen_url": "", **extra}


class _Data(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {**ENV, "LVR_DATA_DIR": self.tmp.name, "LVR_OUTPUT_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name: str, value) -> None:
        with open(os.path.join(self.tmp.name, name), "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)

    def read(self, name: str):
        with open(os.path.join(self.tmp.name, name), encoding="utf-8") as handle:
            return json.load(handle)

    def seed(self, notes: list[dict], *, ages_min: list[float], reels: dict | None = None) -> None:
        self.write("noticias_meta.json", notes)
        self.write("noticias_web_publicadas.json", [])
        self.write("fb_posted.json", {"posted": {
            n["canonical_url"]: {"canonical_url": n["canonical_url"], "titulo": n["titulo"], "external_id": f"fb{i}",
                                 "posted_at": NOW - age * 60}
            for i, (n, age) in enumerate(zip(notes, ages_min))
        }})
        self.write("paparazzi_reels_posted.json", {"posted": reels or {}})


class ComposeTests(unittest.TestCase):
    def test_kinds_and_utm(self):
        from utils import whatsapp_feed as wf

        normal = wf.compose({"item": _note(1), "video": False}, medium="grupo")
        self.assertTrue(normal["text"].startswith("📰 *Inauguraron"))
        self.assertIn("plaza-1?utm_source=whatsapp&utm_medium=grupo", normal["text"])
        self.assertNotIn("copete", normal["text"])
        video = wf.compose({"item": _note(2), "video": True}, medium="grupo")
        self.assertTrue(video["text"].startswith("🎥 *VIDEO* | *Inauguraron"))
        breaking = wf.compose({"item": _note(3, titulo="Último momento: grave choque en la Ruta 38"), "video": False},
                              medium="canal")
        self.assertTrue(breaking["breaking"])
        self.assertIn("Texto del copete.", breaking["text"])
        self.assertIsNone(wf.compose({"item": {**_note(4), "web_url": ""}, "video": False}, medium="grupo"))

    def test_utm_replaces_previous(self):
        from utils.whatsapp_feed import with_utm

        self.assertEqual(with_utm("https://x.com/a?utm_source=fb&id=3", "canal"),
                         "https://x.com/a?id=3&utm_source=whatsapp&utm_medium=canal")


class PlanTests(_Data):
    def test_bootstrap_sends_nothing_old(self):
        from utils import whatsapp_feed as wf

        self.seed([_note(1)], ages_min=[5])
        wf.start_watermark()
        self.assertEqual(wf.plan(wf.load_state())[0], [])

    def test_group_gets_everything_channel_only_breaking(self):
        from utils import whatsapp_feed as wf

        breaking = _note(2, titulo="Último momento: grave choque en la Ruta 38")
        reel = {"canonical_url": "https://src/3", "titulo": "Video", "facebook_id": "f3", "posted_at": NOW - 60}
        self.seed([_note(1), breaking, _note(3)], ages_min=[10, 5, 999], reels={"r": reel})
        self.write("fb_posted.json", {"posted": {k: v for k, v in self.read("fb_posted.json")["posted"].items()
                                                 if k != "https://src/3"}})
        wf.start_watermark(NOW - 3600)
        messages, stale = wf.plan(wf.load_state(), now=NOW)
        keys = [m["key"] for m in messages]
        # Último momento primero (grupo y canal), después el resto en orden.
        self.assertEqual(keys[:2], ["grupo:https://src/2", "canal:https://src/2"])
        self.assertEqual(set(keys[2:]), {"grupo:https://src/1", "grupo:https://src/3"})
        self.assertTrue(next(m for m in messages if m["key"] == "grupo:https://src/3")["text"].startswith("🎥"))
        self.assertEqual(stale, [])

    def test_quiet_hours_only_breaking_and_stale(self):
        from utils import whatsapp_feed as wf

        breaking = _note(2, titulo="Último momento: grave choque en la Ruta 38")
        self.seed([_note(1), breaking, _note(5)], ages_min=[10, 5, 300])
        wf.start_watermark(NOW - 6 * 3600)
        with mock.patch.dict(os.environ, {"WHATSAPP_QUIET_HOURS": "0-24"}), \
                mock.patch.object(wf, "quiet_hours", return_value=True):
            messages, stale = wf.plan(wf.load_state(), now=NOW)
        self.assertEqual({m["key"] for m in messages}, {"grupo:https://src/2", "canal:https://src/2"})
        self.assertEqual(stale, ["grupo:https://src/5"])

    def test_results_and_retries(self):
        from utils import whatsapp_feed as wf

        self.seed([_note(1), _note(2), _note(3)], ages_min=[3, 2, 1])
        wf.start_watermark(NOW - 3600)
        lines = [json.dumps(r) for r in (
            {"key": "grupo:https://src/1", "phase": "sending"},
            {"key": "grupo:https://src/1", "phase": "sent", "message_id": "M1"},
            {"key": "grupo:https://src/2", "phase": "sending"},
            {"key": "grupo:https://src/2", "phase": "failed", "error": "boom"},
            {"key": "grupo:https://src/3", "phase": "sending"},
        )]
        keys = ["grupo:https://src/1", "grupo:https://src/2", "grupo:https://src/3"]
        results = wf.parse_results(lines, keys)
        self.assertEqual({k: r["status"] for k, r in results.items()},
                         {keys[0]: wf.SENT, keys[1]: wf.FAILED, keys[2]: wf.UNVERIFIED})
        with mock.patch.dict(os.environ, {"WHATSAPP_MAX_ATTEMPTS": "2"}):
            wf.record(results, {})
            # Lo enviado y lo dudoso no se repiten; el fallido sí, hasta agotar intentos.
            self.assertEqual([m["key"] for m in wf.plan(wf.load_state(), now=NOW)[0]], [keys[1]])
            wf.record({keys[1]: {"status": wf.FAILED, "error": "x"}}, {})
            self.assertEqual(wf.load_state()["messages"][keys[1]]["status"], wf.DEAD)
            self.assertEqual(wf.plan(wf.load_state(), now=NOW)[0], [])
        self.assertEqual(wf.load_state()["messages"][keys[0]]["message_id"], "M1")


class StageTests(_Data):
    def test_disabled_by_default(self):
        from meta import run_whatsapp

        with mock.patch.dict(os.environ, {"WHATSAPP_ENABLED": "false"}):
            self.assertEqual(run_whatsapp.main().status.value, "no_work")

    def test_dry_run_writes_preview_without_sending(self):
        from meta import run_whatsapp
        from utils import whatsapp_feed as wf

        self.seed([_note(1)], ages_min=[2])
        wf.start_watermark(NOW - 3600)
        with mock.patch.dict(os.environ, {"WHATSAPP_DRY_RUN": "true"}), mock.patch.object(run_whatsapp, "send") as send:
            result = run_whatsapp.main()
        send.assert_not_called()
        self.assertTrue(result.details["dry_run"])
        self.assertNotIn("messages", wf.load_state())

    def test_stage_queues_and_worker_sends_spaced(self):
        from meta import run_whatsapp, whatsapp_worker
        from utils import whatsapp_feed as wf

        breaking = _note(2, titulo="Último momento: grave choque en la Ruta 38")
        self.seed([_note(1), breaking], ages_min=[3, 2])
        wf.start_watermark(NOW - 3600)
        with mock.patch.object(run_whatsapp, "spawn_worker", return_value=7) as spawn,                 mock.patch.object(whatsapp_worker, "worker_running", return_value=False):
            result = run_whatsapp.main()
        spawn.assert_called_once()
        self.assertEqual(result.details["queued"], 3)
        # Encolado: el ciclo siguiente no lo vuelve a planificar.
        self.assertEqual(wf.plan(wf.load_state(), now=NOW)[0], [])

        sent_order, pauses = [], []

        def fake_send(messages):
            [m] = messages
            sent_order.append(m["key"])
            return 0, [json.dumps({"key": m["key"], "phase": "sent", "message_id": f"M{len(sent_order)}"})]

        with mock.patch.object(run_whatsapp, "send", side_effect=fake_send):
            self.assertEqual(whatsapp_worker.run(sleep=pauses.append), 3)
        # Último momento primero (grupo y canal) y una pausa entre cada mensaje.
        self.assertEqual(set(sent_order[:2]), {"grupo:https://src/2", "canal:https://src/2"})
        self.assertEqual(len(pauses), 2)
        self.assertTrue(all(90 <= p <= 240 for p in pauses))
        self.assertEqual({v["status"] for v in wf.load_state()["messages"].values()}, {wf.SENT})

    def test_worker_without_session_keeps_queue(self):
        from meta import run_whatsapp, whatsapp_worker
        from utils import whatsapp_feed as wf

        self.seed([_note(1)], ages_min=[2])
        wf.start_watermark(NOW - 3600)
        wf.enqueue(wf.plan(wf.load_state(), now=NOW)[0])
        with mock.patch.object(run_whatsapp, "send", return_value=(run_whatsapp.EXIT_NEEDS_AUTH, [])):
            self.assertEqual(whatsapp_worker.run(sleep=lambda _s: None), 0)
        self.assertEqual(wf.load_state()["messages"]["grupo:https://src/1"]["status"], wf.QUEUED)

    def test_interrupted_send_is_never_repeated(self):
        from utils import whatsapp_feed as wf

        self.seed([_note(1)], ages_min=[2])
        wf.start_watermark(NOW - 3600)
        wf.enqueue(wf.plan(wf.load_state(), now=NOW)[0])
        wf.mark_status("grupo:https://src/1", wf.SENDING)
        self.assertEqual(wf.recover_in_flight(), 1)
        self.assertEqual(wf.load_state()["messages"]["grupo:https://src/1"]["status"], wf.UNVERIFIED)
        self.assertIsNone(wf.next_queued(wf.load_state()))


class JoinStoryTests(_Data):
    def at(self, weekday_date: str, hour: int) -> datetime:
        return datetime.fromisoformat(f"{weekday_date}T{hour:02d}:10:00").replace(tzinfo=AR_TZ)

    def test_due_days_window_and_once(self):
        from utils import wa_join_story as js

        friday, saturday = "2026-10-30", "2026-10-31"
        self.assertTrue(js.due(self.at(friday, 20), state={}))
        self.assertFalse(js.due(self.at(friday, 19), state={}))
        self.assertFalse(js.due(self.at(friday, 23), state={}))
        self.assertFalse(js.due(self.at(saturday, 20), state={}))
        self.assertFalse(js.due(self.at(friday, 21), state={"days": {friday: {"status": "unverified"}}}))

    def test_join_url_only_whatsapp(self):
        from utils import wa_join_story as js

        for url in ("https://whatsapp.com/channel/0029Vb", "https://chat.whatsapp.com/HIeEAR"):
            with mock.patch.dict(os.environ, {"WHATSAPP_JOIN_URL": url}):
                self.assertEqual(js.join_url(), url)
        for url in ("http://whatsapp.com/channel/0029Vb", "https://evil.com/channel/x", ""):
            with mock.patch.dict(os.environ, {"WHATSAPP_JOIN_URL": url}), self.assertRaises(ValueError):
                js.join_url()

    def test_image_size(self):
        from utils import wa_join_story as js

        self.assertEqual(js.compose().size, (1080, 1920))

    def test_stage_publishes_once_and_unverified_blocks_retry(self):
        from meta import instagrapi_client as igc
        from meta import run_wa_join_story as stage
        from utils import wa_join_story as js

        env = {"WA_JOIN_STORY_ENABLED": "true", "WHATSAPP_JOIN_URL": "https://whatsapp.com/channel/0029Vb"}
        plan = mock.Mock(channel_enabled=mock.Mock(return_value=True))
        with mock.patch.dict(os.environ, env), mock.patch.object(stage, "deployment_plan", return_value=plan), \
                mock.patch.object(js, "due", return_value=True), \
                mock.patch.object(stage, "publish", side_effect=igc.NativeStoryError(igc.UNVERIFIED, "timeout")):
            self.assertEqual(stage.main().status.value, "degraded")
        [(day, entry)] = self.read("wa_join_story.json")["days"].items()
        self.assertEqual(entry["status"], "unverified")
        # Ese día ya no vuelve a estar pendiente, aunque esté en la ventana.
        self.assertFalse(js.due(datetime.fromisoformat(f"{day}T20:30:00").replace(tzinfo=AR_TZ)))


if __name__ == "__main__":
    unittest.main()
