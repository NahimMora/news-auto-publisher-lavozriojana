"""Placas de servicio: cronograma de pagos (Hacienda) y sismos sentidos (INPRES)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from utils import service_data as sd

HACIENDA = [
    {
        "date": "2026-10-16T13:26:44",
        "link": "https://hacienda.larioja.gob.ar/quincena-octubre-lunes-19-10/",
        "title": {"rendered": "QUINCENA OCTUBRE &#8211; LUNES 19/10"},
        "content": {"rendered": "<p>Función Legislativa,<br>Jefatura de Gabinete,<br>Secretaría de Turismo, y<br>Cuatro Regiones (Valles y Llanos Norte y Sur)</p>"},
    },
    {
        "date": "2026-10-14T13:58:29",
        "link": "https://hacienda.larioja.gob.ar/quincena-octubre-martes-15-10/",
        "title": {"rendered": "QUINCENA OCTUBRE – JUEVES 15/10"},
        "content": {"rendered": "<p><strong>Banco Rioja</strong></p><p>Función Judicial,<br>Hospital Enrique Vera Barros, y<br>Ex Planta PIL (Capital).</p><p><strong>Banco Hipotecario</strong></p><p>Policía (Capital), y<br>Servicio Penitenciario.</p>"},
    },
    {
        "date": "2026-10-16T10:11:00",
        "link": "https://hacienda.larioja.gob.ar/chachos/",
        "title": {"rendered": "ESTE VIERNES 16 DE OCTUBRE, CONTINÚA EL PAGO DE CHACHOS"},
        "content": {"rendered": "<p>Texto</p>"},
    },
    {
        "date": "2025-12-30T12:00:00",
        "link": "https://hacienda.larioja.gob.ar/haberes-diciembre-lunes-5-1/",
        "title": {"rendered": "HABERES DICIEMBRE – LUNES 5/1"},
        "content": {"rendered": "<p>Ministerio de Educación (Capital).</p>"},
    },
]

# El feed dice ISO-8859-1 pero trae UTF-8 ("José" llega como bytes UTF-8).
INPRES = """<?xml version="1.0" encoding="ISO-8859-1"?>
<rss version="2.0"><channel>
<item><idSismo>20261013030411</idSismo><pubDate>13 Oct 00:04 hs.</pubDate><magnitude>4.2</magnitude>
<epiczone>48 km al NE de Chilecito; 50 km al SO de Aimogasta.</epiczone><depth>134 km.</depth>
<intensity>III -Chilecito, La Rioja; II a III -Ciudad de La Rioja; II a III -San José de Jáchal, San Juan</intensity>
<province>LA RIOJA</province></item>
<item><idSismo>20261021235532</idSismo><magnitude>3.3</magnitude><epiczone>46 km al NO de Catamarca.</epiczone>
<depth>10 km.</depth><intensity>II a III -Ciudad de San Fernando del Valle de Catamarca</intensity><province>CATAMARCA</province></item>
<item><idSismo>20261011003631</idSismo><magnitude>3.1</magnitude><epiczone>20 km al NE de Ischigualasto.</epiczone>
<depth>12 km.</depth><intensity>II a III -La Torre, La Rioja</intensity><province>SAN JUAN</province></item>
<item><idSismo>roto</idSismo><magnitude>x</magnitude></item>
</channel></rss>""".encode("utf-8")


class Response:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code


class PaymentScheduleTests(unittest.TestCase):
    def test_parses_only_payment_posts_with_groups_and_year(self):
        payments = sd.fetch_payment_schedule(fetcher=lambda _u: Response(json.dumps(HACIENDA).encode()))
        self.assertEqual(["2026-10-19", "2026-10-15", "2026-01-05"], [p["date"] for p in payments])
        first, banks, january = payments
        self.assertEqual("Quincena de octubre", first["concept"])
        self.assertEqual(
            [{"title": "", "items": ["Función Legislativa", "Jefatura de Gabinete", "Secretaría de Turismo", "Cuatro Regiones (Valles y Llanos Norte y Sur)"]}],
            first["groups"],
        )
        self.assertEqual(["Banco Rioja", "Banco Hipotecario"], [g["title"] for g in banks["groups"]])
        self.assertEqual(["Policía (Capital)", "Servicio Penitenciario"], banks["groups"][1]["items"])
        self.assertEqual("Haberes de diciembre", january["concept"])

    def test_bad_payload(self):
        with self.assertRaises(sd.ServiceDataError):
            sd.fetch_payment_schedule(fetcher=lambda _u: Response(b"<html>"))
        with self.assertRaises(sd.ServiceDataError):
            sd.fetch_payment_schedule(fetcher=lambda _u: Response(b"", 503))


class FeltQuakeTests(unittest.TestCase):
    def test_only_felt_in_la_rioja_or_epicenter_there(self):
        quakes = sd.parse_felt_quakes(INPRES)
        self.assertEqual(["20261013030411", "20261011003631"], [q["id"] for q in quakes])
        first = quakes[0]
        self.assertEqual((4.2, "134 km"), (first["magnitude"], first["depth"]))
        self.assertEqual("2026-10-13T03:04:11+00:00", first["at"])
        self.assertEqual(["Chilecito, La Rioja", "Ciudad de La Rioja", "San José de Jáchal, San Juan"], [f["place"] for f in first["felt"]])
        self.assertEqual("II a III", first["felt"][1]["intensity"])

    def test_invalid_xml(self):
        with self.assertRaises(sd.ServiceDataError):
            sd.parse_felt_quakes(b"<rss><channel>")


class DueServicePostsTests(unittest.TestCase):
    def setUp(self):
        self.payments = sd.fetch_payment_schedule(fetcher=lambda _u: Response(json.dumps(HACIENDA).encode()))
        self.quakes = sd.parse_felt_quakes(INPRES)

    def _at(self, iso: str) -> datetime:
        # Hora de Argentina (UTC-3).
        return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc) + (datetime(2000, 1, 1, 3) - datetime(2000, 1, 1))

    def test_payments_the_day_before_or_the_morning_of(self):
        from utils import service_posts as spost

        fetch = lambda: self.payments  # noqa: E731
        day_before = spost.due_payments(self._at("2026-10-18T15:00:00"), fetch=fetch)
        self.assertEqual(["2026-10-19"], [job["key"].split(":")[2] for job in day_before])
        self.assertEqual("Mañana lunes 19/10 cobran", day_before[0]["props"]["headline"])
        same_morning = spost.due_payments(self._at("2026-10-19T09:00:00"), fetch=fetch)
        self.assertEqual("Hoy lunes 19/10 cobran", same_morning[0]["props"]["headline"])
        self.assertEqual([], spost.due_payments(self._at("2026-10-19T13:00:00"), fetch=fetch))
        self.assertEqual([], spost.due_payments(self._at("2026-10-18T23:00:00"), fetch=fetch))

    def test_payment_caption_lists_banks_and_source(self):
        from utils import service_posts as spost

        caption = spost.payment_caption(self.payments[1], date(2026, 10, 14))
        self.assertIn("📅 Mañana jueves 15/10 cobran:", caption)
        self.assertIn("🏦 Banco Hipotecario\n▪️ Policía (Capital)", caption)
        self.assertIn("Fuente: Ministerio de Hacienda de La Rioja.", caption)

    def test_quakes_by_magnitude_and_age(self):
        from utils import service_posts as spost

        fetch = lambda: self.quakes  # noqa: E731
        with mock.patch.dict(os.environ, {"QUAKE_MIN_MAGNITUDE": "3.0", "QUAKE_MAX_AGE_HOURS": "12"}):
            fresh = spost.due_quakes(self._at("2026-10-13T08:00:00"), fetch=fetch)
            late = spost.due_quakes(self._at("2026-10-13T20:00:00"), fetch=fetch)
            night = spost.due_quakes(self._at("2026-10-13T02:00:00"), fetch=fetch)
        with mock.patch.dict(os.environ, {"QUAKE_MIN_MAGNITUDE": "4.5"}):
            strong_only = spost.due_quakes(self._at("2026-10-13T08:00:00"), fetch=fetch)
        self.assertEqual(["svcpost:sismo:20261013030411"], [job["key"] for job in fresh])
        self.assertEqual(([], [], []), (late, night, strong_only))
        props = fresh[0]["props"]
        self.assertEqual(("4,2", "Martes 13/10 · 00:04 h"), (props["magnitude"], props["timeLabel"]))
        # Sólo las localidades riojanas, sin el ", La Rioja".
        self.assertEqual(["Chilecito", "Ciudad de La Rioja"], [f["place"] for f in props["felt"]])
        self.assertIn("▪️ Chilecito (intensidad III)", fresh[0]["caption"])

    def test_flags_and_source_failures(self):
        from utils import service_posts as spost

        with mock.patch.dict(os.environ, {"PAYMENT_POSTS_ENABLED": "false", "QUAKE_POSTS_ENABLED": "false"}):
            self.assertEqual([], spost.due_service_posts())
        with mock.patch.dict(os.environ, {"PAYMENT_POSTS_ENABLED": "true", "QUAKE_POSTS_ENABLED": "true"}), mock.patch.object(
            spost, "due_payments", side_effect=sd.ServiceDataError("http_status:503")
        ), mock.patch.object(spost, "due_quakes", return_value=[{"key": "svcpost:sismo:1"}, {"key": "svcpost:sismo:2"}]):
            jobs = spost.due_service_posts(done=lambda key: key.endswith(":1"))
        self.assertEqual(["svcpost:sismo:2"], [job["key"] for job in jobs])


class PublishServicePostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from utils import social_formats, story_publisher

        root = Path(self.tmp.name)
        for target, value in ((social_formats, root / "formats.json"), (story_publisher, root / "stories.json")):
            patcher = mock.patch.object(target, "STATE_PATH", str(value))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.job = {"key": "svcpost:sismo:1", "kind": "quake", "props": {"kind": "quake"}, "caption": "Caption", "fb_link": "", "label": "Sismo"}

    def test_post_records_evidence_and_story_covers_the_automatic_one(self):
        from utils import service_posts as spost
        from utils import story_publisher as sp
        from utils.operation_result import OperationResult
        from utils.stage_result import StageStatus

        ok_ig = OperationResult(StageStatus.SUCCESS, external_id="ig-post")
        ok_fb = OperationResult(StageStatus.SUCCESS, external_id="fb-post")
        with mock.patch("utils.r2_storage.is_configured", return_value=True), mock.patch(
            "utils.r2_storage.upload_temp", return_value=("https://r2/x.jpg", "k")
        ), mock.patch("utils.r2_storage.delete"), mock.patch(
            "meta.ig_client.post_single_image", return_value=ok_ig
        ) as ig_post, mock.patch("meta.fb_client.post_photo", return_value=ok_fb):
            outcome = spost.publish_post(self.job, b"jpeg", instagram=True, facebook=True)
            again = spost.publish_post(self.job, b"jpeg", instagram=True, facebook=True)
        self.assertEqual(("success", "success", "ig-post"), (outcome["ig"], outcome["fb"], outcome["ig_id"]))
        self.assertEqual(("skipped", "skipped"), (again["ig"], again["fb"]))
        ig_post.assert_called_once()
        self.assertTrue(spost.already_done(self.job["key"]))

        with mock.patch.object(sp, "render_story", return_value=b"story"), mock.patch.object(
            sp, "publish_story", side_effect=lambda key, *_a, **_k: (sp._record(key, ig_id="ig-story", day="x"), {"ig": "success", "fb": "skipped"})[1]
        ):
            spost.publish_story(self.job, "ig-post", instagram=True, facebook=False)
        state = sp.load_state()["posted"]
        self.assertTrue(sp.already_done("post:ig-post"))
        self.assertNotIn("day", state["post:ig-post"])

    def test_ambiguous_instagram_blocks_facebook(self):
        from utils import service_posts as spost
        from utils.operation_result import OperationResult
        from utils.stage_result import StageStatus

        unknown = OperationResult(StageStatus.DEGRADED, error_type="network_error", details={"publication_outcome": "unknown"})
        with mock.patch("utils.r2_storage.is_configured", return_value=True), mock.patch(
            "utils.r2_storage.upload_temp", return_value=("https://r2/x.jpg", "k")
        ), mock.patch("utils.r2_storage.delete") as delete, mock.patch(
            "meta.ig_client.post_single_image", return_value=unknown
        ), mock.patch("meta.fb_client.post_photo") as fb_post:
            outcome = spost.publish_post(self.job, b"jpeg", instagram=True, facebook=True)
        self.assertEqual(("ambiguous", "skipped"), (outcome["ig"], outcome["fb"]))
        fb_post.assert_not_called()
        delete.assert_not_called()
        self.assertTrue(spost.already_done(self.job["key"]))


if __name__ == "__main__":
    unittest.main()
