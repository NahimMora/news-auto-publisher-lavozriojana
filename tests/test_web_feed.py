"""Datos para la web en R2 (utils/web_feed.py): armado puro, fallas por fuente y subida."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock

from utils.operation_result import OperationResult
from utils.social_time import AR_TZ
from utils.stage_result import StageStatus

NOW = 1_792_780_000.0
WEB = [
    {"titulo": "MURIÓ EL JOVEN", "canonical_url": "https://nr/2", "web_url": "https://lvr/murio", "published_at_ts": NOW - 3600,
     "event_update": {"of_canonical_url": "https://nr/1", "of_title": "Muerte cerebral", "novedad": "Murió en el hospital"}},
    {"titulo": "MUERTE CEREBRAL", "canonical_url": "https://nr/1", "web_url": "https://lvr/cerebral", "published_at_ts": NOW - 20 * 3600},
    {"titulo": "VIEJA", "canonical_url": "https://nr/3", "web_url": "https://lvr/vieja", "published_at_ts": NOW - 5 * 86400},
]
IG_POSTED = {
    "a": {"external_id": "m1", "canonical_url": "https://nr/1", "titulo": "Muerte cerebral", "posted_at": NOW - 20 * 3600},
    "b": {"external_id": "m2", "canonical_url": "https://nr/2", "titulo": "Murió el joven", "posted_at": NOW - 3600},
    "c": {"external_id": "m3", "canonical_url": "https://nr/3", "titulo": "Vieja", "posted_at": NOW - 5 * 86400},
    "d": {"external_id": "m4", "canonical_url": "https://sin-web/4", "titulo": "Sin web", "posted_at": NOW - 3600},
}
INSIGHTS = {
    "m1": {"posted_at": NOW - 20 * 3600, "seccion": "policiales", "reach": 900, "interactions": 10},
    "m2": {"posted_at": NOW - 3600, "seccion": "policiales", "reach": 1500, "interactions": 30},
    "m3": {"posted_at": NOW - 5 * 86400, "seccion": "sociedad", "reach": 9000, "interactions": 100},
    "m4": {"posted_at": NOW - 3600, "seccion": "policiales", "reach": 99999, "interactions": 1},
}


class MostViewedTests(unittest.TestCase):
    def test_windows_rank_by_reach_and_need_a_web_url(self):
        from utils.web_feed import build_most_viewed

        doc = build_most_viewed(INSIGHTS, IG_POSTED, WEB, {"m2": {"permalink": "https://www.instagram.com/p/X/"}}, now=NOW)
        self.assertEqual([r["url"] for r in doc["ventanas"]["24h"]], ["https://lvr/murio", "https://lvr/cerebral"])
        self.assertEqual([r["url"] for r in doc["ventanas"]["7d"]], ["https://lvr/vieja", "https://lvr/murio", "https://lvr/cerebral"])
        top = doc["ventanas"]["24h"][0]
        self.assertEqual(top["instagram"], {"url": "https://www.instagram.com/p/X/", "alcance": 1500, "interacciones": 30})
        self.assertEqual(top["seccion"], "policiales")
        # La que no está en la web no entra aunque tenga más alcance.
        self.assertNotIn("Sin web", json.dumps(doc))
        self.assertEqual([r["url"] for r in doc["por_seccion_7d"]["policiales"]], ["https://lvr/murio", "https://lvr/cerebral"])


class UpdatesAndVideosTests(unittest.TestCase):
    def test_updates_point_to_the_previous_note(self):
        from utils.web_feed import build_updates

        [item] = build_updates(WEB, now=NOW)["items"]
        self.assertEqual(item["nota"]["url"], "https://lvr/murio")
        self.assertEqual(item["actualiza"], {"titulo": "MUERTE CEREBRAL", "url": "https://lvr/cerebral"})
        self.assertEqual(item["novedad"], "Murió en el hospital")

    def test_videos_only_with_verified_link(self):
        from utils.web_feed import build_videos, reel_records

        x = {"r1": {"status": "completed", "instagram_id": "v1", "titulo": "Choque", "url": "https://x.com/a/status/1", "completed_at": NOW - 60},
             "r2": {"status": "pending", "instagram_id": "v2"}}
        jobs = {"jobs": {"j1": {"status": "completed", "instagram_id": "v3", "completed_at": NOW - 30,
                                "noticia": {"titulo_instagram": "Nota con video", "canonical_url": "https://nr/2"}}}}
        reels = reel_records(x, jobs, WEB)
        self.assertEqual([r["media_id"] for r in reels], ["v3", "v1"])
        self.assertEqual(reels[0]["url_nota"], "https://lvr/murio")
        doc = build_videos(reels, {"v1": {"permalink": "https://www.instagram.com/reel/A/", "media_type": "VIDEO"}})
        self.assertEqual([i["instagram"]["url"] for i in doc["items"]], ["https://www.instagram.com/reel/A/"])
        self.assertEqual(doc["items"][0]["fuente_video"], "https://x.com/a/status/1")

    def test_permalinks_are_read_once_and_validated(self):
        from utils.web_feed import fetch_permalinks

        getter = mock.Mock(side_effect=lambda m: {"permalink": f"https://www.instagram.com/reel/{m}/"} if m != "bad" else {"permalink": "https://evil/"})
        new = fetch_permalinks(["a", "known", "bad", "a"], {"known": {}}, getter=getter)
        self.assertEqual(sorted(new), ["a"])
        self.assertEqual(getter.call_count, 2)


class StoriesAndBreakingTests(unittest.TestCase):
    def test_stories_come_only_from_verified_update_chains(self):
        from utils.web_feed import build_stories

        third = {"titulo": "DETUVIERON AL CONDUCTOR", "canonical_url": "https://nr/9", "web_url": "https://lvr/detenido", "published_at_ts": NOW - 60,
                 "event_update": {"of_canonical_url": "https://nr/2", "novedad": "Detuvieron al conductor"}}
        doc = build_stories(WEB + [third], now=NOW, story_key_for=lambda url: "event:abc" if url == "https://lvr/cerebral" else "")
        [story] = doc["items"]
        self.assertEqual([n["url"] for n in story["notas"]], ["https://lvr/cerebral", "https://lvr/murio", "https://lvr/detenido"])
        self.assertEqual((story["storyKey"], story["titulo"]), ("event:abc", "DETUVIERON AL CONDUCTOR"))
        self.assertEqual(story["notas"][2]["novedad"], "Detuvieron al conductor")
        # Sin actualizaciones no hay historias (nunca se agrupa por parecido).
        self.assertEqual(build_stories([WEB[2]], now=NOW)["items"], [])

    def test_breaking_note_and_alert(self):
        from utils.web_feed import build_breaking

        flags = {"breaking": {"post_id": "6321", "activated_at": "2026-10-23T19:02:41Z"}}
        lookup = lambda pid: {"titulo": "Detuvieron a dos ladrones", "url": "https://lvr/robo", "seccion": "policiales"} if pid == "6321" else None  # noqa: E731
        activated = datetime.fromisoformat("2026-10-23T19:02:41+00:00").timestamp()
        doc = build_breaking(flags, alert={"estado": "activa", "nivel": "amarilla"}, now=activated + 3600, lookup=lookup)
        self.assertEqual((doc["nota"]["url"], doc["nota"]["vigente"]), ("https://lvr/robo", True))
        self.assertEqual(doc["alerta"]["nivel"], "amarilla")
        late = build_breaking(flags, alert={"estado": "sin_alerta"}, now=activated + 7 * 3600, lookup=lookup)
        self.assertFalse(late["nota"]["vigente"])
        self.assertIsNone(late["alerta"])
        self.assertEqual(build_breaking({"breaking": None}, alert=None, now=NOW), {"nota": None, "alerta": None})


class ServicesTests(unittest.TestCase):
    def test_each_source_fails_alone_and_keeps_last_good(self):
        from utils.web_feed import build_services

        def boom():
            raise RuntimeError("smn caído")

        previous = {"clima": {"temperatura": 20, "actualizado": "2026-10-23T09:00:00-03:00"}}
        fetchers = {name: (lambda: {"ok": True}) for name in ("alerta", "dolar", "feriados", "pagos", "sismos", "cortes")}
        doc, failed = build_services(previous, now=datetime(2026, 10, 23, 12, 0, tzinfo=AR_TZ), fetchers={**fetchers, "clima": boom})
        self.assertEqual(failed, ["clima"])
        self.assertEqual(doc["clima"], previous["clima"])
        self.assertTrue(doc["dolar"]["ok"])
        self.assertTrue(doc["dolar"]["actualizado"].startswith("2026-10-23T12:00"))

    def test_blocks(self):
        from utils.web_feed import alert_block, dollar_block, payments_block, quakes_block

        self.assertEqual(alert_block({"status": "none"})["estado"], "sin_alerta")
        alert = alert_block({"status": "active", "kind": "aviso", "level": "naranja", "phenomenon": "tormentas", "zones": ["Capital"], "expires": "x"})
        self.assertEqual((alert["tipo"], alert["nivel"], alert["zonas"]), ("aviso a muy corto plazo", "naranja", ["Capital"]))
        dollar = dollar_block([{"house": "oficial", "name": "Oficial", "buy": 1500, "sell": 1550}, {"house": "blue", "name": "Blue", "buy": None, "sell": 1565}])
        self.assertEqual(dollar["brecha_blue_pct"], 1.0)
        pays = payments_block([{"date": "2026-10-23", "concept": "Quincena", "groups": [{"title": "Banco Rioja", "items": ["Salud"]}], "url": "u"},
                               {"date": "2026-10-20", "concept": "Vieja"}], date(2026, 10, 23))
        self.assertEqual([p["concepto"] for p in pays["hoy"]], ["Quincena"])
        self.assertEqual(pays["proximos"][0]["dia"], "viernes")
        quakes = quakes_block([
            {"id": "1", "at": "2026-10-23T13:25:57+00:00", "magnitude": 2.7, "depth_km": 130, "province": "LA RIOJA", "status": "revised"},
            {"id": "2", "at": "2026-10-23T13:00:00+00:00", "magnitude": 4.0, "depth_km": 10, "province": "SAN JUAN", "status": "revised"},
        ], {"1": {"places": ["35 km al O de Cerro Bonete"]}}, now=datetime(2026, 10, 23, 12, 0, tzinfo=AR_TZ))
        self.assertEqual([(q["id"], q["lugar"], q["estado"]) for q in quakes["ultimos_7_dias"]], [("1", "35 km al O de Cerro Bonete", "revisado")])


class PublishTests(unittest.TestCase):
    def test_uploads_each_document_and_index(self):
        from utils import web_feed

        seen = {}

        def uploader(path, key, content_type, *, cache_control):
            with open(path, encoding="utf-8") as handle:
                seen[key] = json.load(handle)
            self.assertEqual((content_type, cache_control), ("application/json; charset=utf-8", "public, max-age=300"))
            return OperationResult(StageStatus.SUCCESS if key != "feed/v1/videos.json" else StageStatus.DEGRADED)

        docs = {"mas-visto": {"version": 1, "actualizado": "t"}, "videos": {"version": 1, "actualizado": "t"}}
        with mock.patch.dict(os.environ, {"R2_PUBLIC_URL": "https://media.lavozriojana.com"}):
            ok, bad = web_feed.publish(docs, uploader=uploader)
        self.assertEqual((ok, bad), (["mas-visto", "index"], ["videos"]))
        self.assertEqual(seen["feed/v1/index.json"]["feeds"]["mas-visto"], "https://media.lavozriojana.com/feed/v1/mas-visto.json")

    def test_stage_disabled_by_default(self):
        from meta import run_web_feed

        with mock.patch.dict(os.environ, {"WEB_FEED_ENABLED": "false"}):
            self.assertEqual(run_web_feed.main().status, StageStatus.NO_WORK)

    def test_collect_writes_only_its_own_state(self):
        from utils import web_feed

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"LVR_DATA_DIR": tmp}), \
                mock.patch.object(web_feed, "STATE_PATH", os.path.join(tmp, "web_feed_state.json")), \
                mock.patch.object(web_feed, "build_services", return_value=({"dolar": {"ok": True}}, [])):
            for name, value in (("ig_media_insights.json", {"media": INSIGHTS}), ("ig_posted.json", {"posted": IG_POSTED}),
                                ("noticias_web_publicadas.json", WEB)):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as handle:
                    json.dump(value, handle)
            docs, failed = web_feed.collect(now=datetime.fromtimestamp(NOW, tz=AR_TZ), fetch_links=False)
            self.assertEqual(sorted(docs), ["actualizaciones", "historias", "mas-visto", "servicios", "ultimo-momento", "videos"])
            self.assertEqual(docs["servicios"]["dolar"], {"ok": True})
            with open(os.path.join(tmp, "web_feed_state.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["servicios"], {"dolar": {"ok": True}})


if __name__ == "__main__":
    unittest.main()
