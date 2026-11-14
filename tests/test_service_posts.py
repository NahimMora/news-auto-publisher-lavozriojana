"""Placas de servicio: cronograma de pagos (Hacienda) y sismos (INPRES)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

# Listado de INPRES (sismos.xml): azul 00f = automático, negro 000 = revisado.
# idSismo en UTC: 20261023051500 = 02:15 del 23/10 en La Rioja.
INPRES_LIST = """<?xml version="1.0" encoding="UTF-8"?>
<lista>
<item><idSismo>20261023051500</idSismo><prof>112</prof><mg>4.3</mg><prov>LA RIOJA</prov><color_link>00f</color_link></item>
<item><idSismo>20261023040000</idSismo><prof>20</prof><mg>3.6</mg><prov>LA RIOJA</prov><color_link>000</color_link></item>
<item><idSismo>20261023030000</idSismo><prof>15</prof><mg>4.8</mg><prov>SAN JUAN</prov><color_link>000</color_link></item>
<item><idSismo>roto</idSismo><mg>x</mg></item>
</lista>""".encode("utf-8")

INPRES_DETAIL = """<html><body><td>Sismo</td><td>con epicentro en LA RIOJA</td>
<td>&nbsp;Tiempo local:&nbsp;</td><td>2026-10-23 02:15:00</td>
<td>&nbsp;Epicentro:&nbsp;</td><td>48 km al NE de Chilecito; 50 km al SO de Aimogasta; 61 km al N de Famatina&nbsp; -28.900 (lat) -67.200 (long)</td>
<td>Magnitud:</td><td>4.3</td><p>Sismo calculado automáticamente, sujeto a revisión.</p></body></html>"""


class Response:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code


def _at(iso: str) -> datetime:
    """Hora de Argentina (UTC-3) a datetime con zona."""
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc) + timedelta(hours=3)


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


class QuakeSourceTests(unittest.TestCase):
    def test_list_with_review_status(self):
        quakes = sd.fetch_quakes(fetcher=lambda _u: Response(INPRES_LIST))
        self.assertEqual(["20261023051500", "20261023040000", "20261023030000"], [q["id"] for q in quakes])
        first = quakes[0]
        self.assertEqual((4.3, 112, "LA RIOJA", "automatic"), (first["magnitude"], first["depth_km"], first["province"], first["status"]))
        self.assertEqual("2026-10-23T05:15:00+00:00", first["at"])
        self.assertEqual("revised", quakes[1]["status"])

    def test_detail_places_nearest_first_and_automatic(self):
        detail = sd.parse_quake_detail(INPRES_DETAIL)
        self.assertEqual(["48 km al NE de Chilecito", "50 km al SO de Aimogasta", "61 km al N de Famatina"], detail["places"])
        self.assertTrue(detail["automatic"])
        self.assertFalse(sd.parse_quake_detail(INPRES_DETAIL.replace("calculado automáticamente, sujeto a revisión", "revisado"))["automatic"])

    def test_invalid_xml(self):
        with self.assertRaises(sd.ServiceDataError):
            sd.parse_quake_list(b"<lista><item>")


class PlateTests(unittest.TestCase):
    def test_word_limit_drops_optional_lines_then_refuses(self):
        from utils import service_posts as spost

        now = _at("2026-10-23T10:00:00")
        long_optional = " ".join(["palabra"] * 20)
        props = spost.plate_props(kind="quake", status="hoy", kicker="Sismo", hero="4,3", hero_label="Magnitud", lines=[("Uno dos", True), (long_optional, False)], source="Fuente: INPRES", now=now)
        self.assertEqual(["Uno dos"], props["lines"])
        self.assertLessEqual(spost.plate_words(props), spost.MAX_WORDS)
        self.assertEqual("Fuente: INPRES · actualizado 10:00", props["footer"])
        with self.assertRaises(ValueError):
            spost.plate_props(kind="quake", status="hoy", kicker="", hero="4,3", hero_label="", lines=[(long_optional + " " + long_optional, True)], source="Fuente: INPRES", now=now)


class DuePaymentsTests(unittest.TestCase):
    def setUp(self):
        self.payments = sd.fetch_payment_schedule(fetcher=lambda _u: Response(json.dumps(HACIENDA).encode()))
        self.fetch = lambda: self.payments  # noqa: E731

    def test_only_on_pay_day_from_seven(self):
        from utils import service_posts as spost

        self.assertEqual([], spost.due_payments(_at("2026-10-18T15:00:00"), fetch=self.fetch))
        self.assertEqual([], spost.due_payments(_at("2026-10-19T06:30:00"), fetch=self.fetch))
        self.assertEqual([], spost.due_payments(_at("2026-10-19T22:30:00"), fetch=self.fetch))
        self.assertEqual(1, len(spost.due_payments(_at("2026-10-19T07:00:00"), fetch=self.fetch)))

    def test_instagram_post_only_first_day_facebook_every_day(self):
        from utils import service_posts as spost

        first = spost.due_payments(_at("2026-10-15T07:05:00"), fetch=self.fetch)[0]
        later = spost.due_payments(_at("2026-10-19T07:05:00"), fetch=self.fetch)[0]
        self.assertEqual((True, True, True), (first["post_ig"], first["post_fb"], first["story"]))
        self.assertEqual((False, True, True), (later["post_ig"], later["post_fb"], later["story"]))

    def test_plate_and_caption(self):
        from utils import service_posts as spost

        job = spost.due_payments(_at("2026-10-15T07:05:00"), fetch=self.fetch)[0]
        props = job["props"]
        self.assertEqual(("hoy", "Cobran estatales", "Jueves 15/10"), (props["status"], props["hero"], props["heroLabel"]))
        self.assertEqual(["Quincena de octubre", "Próximo pago: lunes 19/10"], props["lines"])
        self.assertEqual("Fuente: Hacienda La Rioja · actualizado 07:05", props["footer"])
        self.assertLessEqual(spost.plate_words(props), spost.MAX_WORDS)
        # Los organismos van al texto del post, no a la placa.
        self.assertIn("🏦 Banco Hipotecario\n▪️ Policía (Capital)", job["caption"])
        self.assertIn("📅 Hoy jueves 15/10 cobran:", job["caption"])
        self.assertIn("⏭️ Próximo pago anunciado: lunes 19/10.", job["caption"])
        last = spost.due_payments(_at("2026-10-19T08:00:00"), fetch=self.fetch)[0]
        self.assertEqual(["Quincena de octubre"], last["props"]["lines"])


class DueQuakesTests(unittest.TestCase):
    def setUp(self):
        self.quakes = sd.parse_quake_list(INPRES_LIST)
        self.detail = lambda _id: sd.parse_quake_detail(INPRES_DETAIL)  # noqa: E731

    def _due(self, iso: str, quakes=None, state=None, **env):
        from utils import service_posts as spost

        with mock.patch.dict(os.environ, {"QUAKE_MIN_MAGNITUDE": "4.0", "QUAKE_MAX_AGE_HOURS": "12", **env}):
            return spost.due_quakes(_at(iso), fetch=lambda: quakes or self.quakes, detail=self.detail, state=state)

    def test_only_la_rioja_from_magnitude_four_at_any_hour(self):
        from utils import service_posts as spost

        night = self._due("2026-10-23T02:20:00")
        self.assertEqual(["svcpost:sismo:20261023051500"], [job["key"] for job in night])
        self.assertEqual([], self._due("2026-10-23T15:00:00"))  # más de 12 h
        self.assertEqual([], self._due("2026-10-23T02:20:00", QUAKE_MIN_MAGNITUDE="4.5"))
        job = night[0]
        props = job["props"]
        self.assertEqual(("hoy", "4,3", "Magnitud", "Sismo en La Rioja"), (props["status"], props["hero"], props["heroLabel"], props["kicker"]))
        self.assertEqual(["48 km al NE de Chilecito", "Dato automático", "02:15 h · 112 km de profundidad"], props["lines"])
        self.assertLessEqual(spost.plate_words(props), spost.MAX_WORDS)
        self.assertEqual((True, True, True), (job["post_ig"], job["post_fb"], job["story"]))
        self.assertIn("¿Lo sentiste? ¿Desde dónde?", job["caption"])
        self.assertIn("⚠️ Dato automático de INPRES", job["caption"])
        self.assertEqual(
            {"id": "20261023051500", "at": "2026-10-23T05:15:00+00:00", "magnitude": "4,3", "place": "48 km al NE de Chilecito", "status": "automatic"},
            job["snapshot"],
        )

    def _state_after_post(self) -> dict:
        job = self._due("2026-10-23T02:20:00")[0]
        return {"service_posts": {job["key"]: {"kind": "quake", "ig_id": "ig-1", "snapshot": job["snapshot"]}}}

    def test_revision_with_other_value_gives_updated_story(self):
        state = self._state_after_post()
        # INPRES lo revisa: otra magnitud y el id corrido 40 s.
        revised = [dict(self.quakes[0], id="20261023051540", at="2026-10-23T05:15:40+00:00", magnitude=4.1, status="revised")]
        jobs = self._due("2026-10-23T03:30:00", quakes=revised, state=state)
        self.assertEqual(["svcpost:sismo:20261023051500:actualizado"], [job["key"] for job in jobs])
        job = jobs[0]
        self.assertEqual((False, False, True), (job["post_ig"], job["post_fb"], job["story"]))
        self.assertEqual(("actualizado", "4,1"), (job["props"]["status"], job["props"]["hero"]))
        self.assertIn("Antes informado: magnitud 4,3", job["props"]["lines"])

    def test_same_quake_is_not_posted_twice(self):
        state = self._state_after_post()
        moved = [dict(self.quakes[0], id="20261023051540", at="2026-10-23T05:15:40+00:00")]
        self.assertEqual([], self._due("2026-10-23T03:30:00", quakes=moved, state=state))
        confirmed = [dict(self.quakes[0], status="revised")]
        self.assertEqual([], self._due("2026-10-23T03:30:00", quakes=confirmed, state=state))

    def test_unreadable_detail_skips_only_that_quake(self):
        from utils import service_posts as spost

        def broken(_id):
            raise sd.ServiceDataError("http_status:500")

        with mock.patch.dict(os.environ, {"QUAKE_MIN_MAGNITUDE": "4.0"}):
            self.assertEqual([], spost.due_quakes(_at("2026-10-23T02:20:00"), fetch=lambda: self.quakes, detail=broken))
            no_place = spost.due_quakes(_at("2026-10-23T02:20:00"), fetch=lambda: self.quakes, detail=lambda _id: {"places": [], "automatic": False})
        self.assertEqual([], no_place)


class DueServicePostsTests(unittest.TestCase):
    def test_flags_and_source_failures(self):
        from utils import service_posts as spost

        with mock.patch.dict(os.environ, {"PAYMENT_POSTS_ENABLED": "false", "QUAKE_POSTS_ENABLED": "false"}):
            self.assertEqual([], spost.due_service_posts())
        with mock.patch.dict(os.environ, {"PAYMENT_POSTS_ENABLED": "true", "QUAKE_POSTS_ENABLED": "true"}), mock.patch.object(
            spost, "due_payments", side_effect=sd.ServiceDataError("http_status:503")
        ), mock.patch.object(spost, "due_quakes", return_value=[{"key": "svcpost:sismo:1"}, {"key": "svcpost:sismo:2"}]):
            jobs = spost.due_service_posts(wanted=lambda job: not job["key"].endswith(":1"))
        self.assertEqual(["svcpost:sismo:2"], [job["key"] for job in jobs])

    def test_pending_parts(self):
        from utils import service_posts as spost

        job = {"key": "svcpost:pagos:x", "post_ig": False, "post_fb": True, "story": True}
        state = {"service_posts": {"svcpost:pagos:x": {"fb_id": "fb-1"}}}
        self.assertEqual({"ig": False, "fb": False, "story": True}, spost.pending_parts(job, state, {}, instagram=True, facebook=True, stories=True))
        stories = {"posted": {"svc:svcpost:pagos:x": {"ig_id": "s-1"}}}
        self.assertEqual({"ig": False, "fb": True, "story": False}, spost.pending_parts(job, {}, stories, instagram=True, facebook=True, stories=True))
        ambiguous = {"service_posts": {"svcpost:pagos:x": {"ambiguous": "facebook"}}}
        self.assertFalse(spost.pending_parts(job, ambiguous, {}, instagram=True, facebook=True, stories=False)["fb"])


class ServicePostsStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from utils import social_formats, story_publisher

        root = Path(self.tmp.name)
        for target, value in ((social_formats, root / "formats.json"), (story_publisher, root / "stories.json")):
            patcher = mock.patch.object(target, "STATE_PATH", str(value))
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, jobs, post=None, story=None):
        from meta import run_social_formats as rsf
        from utils import service_posts as spost

        post = post or {"ig": "skipped", "fb": "success", "ig_id": ""}
        story = story or {"ig": "success", "fb": "skipped"}
        with mock.patch.dict(os.environ, {"IG_STORIES_ENABLED": "true", "FB_STORIES_ENABLED": "false"}), mock.patch.object(
            spost, "due_service_posts", side_effect=lambda **kw: [j for j in jobs if kw["wanted"](j)]
        ), mock.patch.object(spost, "render_card", return_value=b"card") as render, mock.patch.object(
            spost, "publish_post", return_value=post
        ) as publish_post, mock.patch.object(spost, "publish_story", return_value=story) as publish_story:
            counts = rsf._service_posts(True, True)
        return counts, render, publish_post, publish_story

    def test_payment_day_without_instagram_post(self):
        job = {"key": "svcpost:pagos:2026-10-19:x", "kind": "payments", "props": {}, "post_ig": False, "post_fb": True, "story": True}
        counts, render, publish_post, publish_story = self._run([job])
        self.assertEqual((1, 0), counts)
        render.assert_called_once()
        self.assertEqual({"instagram": False, "facebook": True}, publish_post.call_args.kwargs)
        publish_story.assert_called_once()

    def test_story_only_update_does_not_render_a_post(self):
        job = {"key": "svcpost:sismo:1:actualizado", "kind": "quake", "props": {}, "post_ig": False, "post_fb": False, "story": True}
        counts, render, publish_post, publish_story = self._run([job])
        self.assertEqual((1, 0), counts)
        render.assert_not_called()
        publish_post.assert_not_called()
        publish_story.assert_called_once()

    def test_failed_post_holds_the_story(self):
        job = {"key": "svcpost:sismo:2", "kind": "quake", "props": {}, "post_ig": True, "post_fb": True, "story": True}
        counts, _render, _post, publish_story = self._run([job], post={"ig": "failed", "fb": "failed", "ig_id": ""})
        self.assertEqual((0, 1), counts)
        publish_story.assert_not_called()


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
