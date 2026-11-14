"""Noticiero de la Noche (2026-10-30): selección de notas, guion con control
factual, estado por día, salida a las 21 y publicación. Todo con mocks: sin
red, sin IA, sin render ni publicación real."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import date, datetime
from unittest import mock

from utils.operation_result import OperationResult
from utils.social_time import AR_TZ
from utils.stage_result import StageStatus


def _candidate(nn, cid, title, body, section="policiales", source="fenix_locales", video=""):
    return nn.Candidate(id=cid, title=title, section=section, source=source, web_url=f"https://lavozriojana.com/noticias/{cid}",
                        published_at=time.time(), body=body, photo_url=f"https://media.lavozriojana.com/{cid}.webp", video_url=video)


class _TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)


class CollectCandidatesTests(_TempDir):
    def test_local_fresh_non_sensitive_and_policiales_first(self):
        from utils import nightly_newscast as nn

        now = time.time()
        records = [
            {"titulo": "Detuvieron a un agente penitenciario", "web_url": "https://lavozriojana.com/noticias/a", "source": "nuevarioja_policiales", "published_at_ts": now - 3600},
            {"titulo": "Asume una diputada", "web_url": "https://lavozriojana.com/noticias/b", "source": "fenix_locales", "published_at_ts": now - 600},
            {"titulo": "Ganó Andino", "web_url": "https://lavozriojana.com/noticias/c", "source": "nuevarioja_deportes", "published_at_ts": now - 600},
            {"titulo": "Detenido por abuso sexual", "web_url": "https://lavozriojana.com/noticias/d", "source": "fenix_locales", "published_at_ts": now - 600},
            {"titulo": "El papa en Córdoba", "web_url": "https://lavozriojana.com/noticias/e", "source": "infobae_policiales", "published_at_ts": now - 600},
            {"titulo": "Nota vieja", "web_url": "https://lavozriojana.com/noticias/f", "source": "fenix_locales", "published_at_ts": now - 40 * 3600},
        ]
        with open(self.path("web.json"), "w", encoding="utf-8") as fh:
            json.dump(records, fh)
        categories = {"https://lavozriojana.com/noticias/a": {"category": "policiales", "localities": []},
                      "https://lavozriojana.com/noticias/b": {"category": "politica", "localities": []},
                      "https://lavozriojana.com/noticias/c": {"category": "deportes", "localities": []}}
        fetch = lambda url: {"title": url.rsplit("/", 1)[1].upper(), "body": "Texto de la nota con datos suficientes.", "photo_url": "", "section": ""}
        with mock.patch.object(nn, "data_dir", return_value=__import__("pathlib").Path(self.tmp.name)), \
             mock.patch.object(nn, "_archive_info", return_value=categories), mock.patch.object(nn, "_video_index", return_value={}):
            os.replace(self.path("web.json"), self.path("noticias_web_publicadas.json"))
            out = nn.collect_candidates(now=now, fetch=fetch)
        # Temas sensibles: entran marcados (decisión editorial 2026-10-31).
        self.assertEqual([c.title for c in out], ["A", "B", "D"])
        self.assertEqual(out[0].section, "policiales")
        self.assertTrue(out[2].sensitive)
        with mock.patch.dict(os.environ, {"NIGHTLY_NEWSCAST_SENSITIVE": "exclude"}),              mock.patch.object(nn, "data_dir", return_value=__import__("pathlib").Path(self.tmp.name)),              mock.patch.object(nn, "_archive_info", return_value=categories), mock.patch.object(nn, "_video_index", return_value={}):
            out = nn.collect_candidates(now=now, fetch=fetch)
        self.assertEqual([c.title for c in out], ["A", "B"])

    def test_article_body_skips_related_and_short_lines(self):
        from utils import nightly_newscast as nn

        page = ('<article><div class="container article-content-wrap"><p>Un incendio de pastizales afectó el acceso al aeropuerto local y movilizó a varias dotaciones.</p>'
                "<p>hoy, 19:32</p></div></article>")
        self.assertEqual(nn.parse_article_body(page), "Un incendio de pastizales afectó el acceso al aeropuerto local y movilizó a varias dotaciones.")


class ScriptTests(unittest.TestCase):
    def setUp(self):
        from utils import nightly_newscast as nn

        self.nn = nn
        self.cands = [
            _candidate(nn, "n1", "Detuvieron a un agente penitenciario", "Con allanamientos federales detuvieron a un agente penitenciario investigado por facilitar drogas y celulares a internos."),
            _candidate(nn, "n2", "Incendio en el acceso al aeropuerto", "Bomberos sofocaron un incendio de cuatro hectáreas en el acceso al aeropuerto.", section="sociedad"),
            _candidate(nn, "n3", "Incendio en avenida Los Cactus", "Un incendio de pastizales puso en peligro viviendas sobre avenida Los Cactus.", section="sociedad"),
            _candidate(nn, "n4", "Florencia López será candidata", "La senadora Florencia López confirmó que será candidata a gobernadora en 2027.", section="politica"),
            _candidate(nn, "n5", "Gasoducto de Chilecito", "La provincia financiará el final del gasoducto de Chilecito, con 93 por ciento de avance y ocho meses de plazo.", section="interior"),
        ]

    def _raw(self, **over):
        raw = {
            "gancho": {"locucion": "Detuvieron a un agente del penal y hubo incendios en la ciudad", "titulares": ["Drogas en el penal", "Fuego en la ciudad"], "ids_imagen": ["n1", "n2"]},
            "bloques": [
                {"ids": ["n4"], "seccion": "politica", "lugar": "", "titulo": "López va por la gobernación", "locucion": "La senadora Florencia López confirmó que será candidata a gobernadora en 2027."},
                {"ids": ["n1"], "seccion": "policiales", "lugar": "", "titulo": "Detuvieron a un agente penitenciario", "locucion": "Con allanamientos federales detuvieron a un agente penitenciario investigado por facilitar drogas a internos."},
                {"ids": ["n2", "n3"], "seccion": "sociedad", "lugar": "Los Cactus", "titulo": "Un día de fuego", "locucion": "Hubo incendios en el acceso al aeropuerto, donde se quemaron cuatro hectáreas, y sobre avenida Los Cactus."},
                {"ids": ["n5"], "seccion": "interior", "lugar": "Chilecito", "titulo": "Gasoducto de Chilecito", "locucion": "La provincia financiará el final del gasoducto, con 93 por ciento de avance."},
            ],
        }
        raw.update(over)
        return raw

    def test_valid_script_puts_policial_first_and_groups(self):
        script, warnings = self.nn.validate_script(self._raw(), self.cands)
        self.assertEqual(warnings, [])
        self.assertEqual(script.blocks[0]["seccion"], "policiales")
        self.assertEqual(script.blocks[2]["ids"], ["n2", "n3"])

    def test_invented_number_and_name_are_flagged(self):
        raw = self._raw()
        raw["bloques"][1]["locucion"] = "Detuvieron a 19 agentes en una causa del juez Ramírez."
        _script, warnings = self.nn.validate_script(raw, self.cands)
        self.assertTrue(any("'19'" in w for w in warnings))
        self.assertTrue(any("Ramírez" in w for w in warnings))

    def test_count_summed_across_notes_is_flagged(self):
        raw = self._raw()
        raw["bloques"][2]["locucion"] = "Tres incendios afectaron la ciudad: en el acceso al aeropuerto y sobre avenida Los Cactus."
        _script, warnings = self.nn.validate_script(raw, self.cands)
        self.assertTrue(any("'3'" in w for w in warnings))

    def test_article_led_generic_noun_at_sentence_start_is_not_a_name(self):
        raw = self._raw()
        raw["bloques"][1]["locucion"] = "Con allanamientos federales detuvieron a un agente penitenciario. La Justicia investiga si facilitaba drogas a internos."
        _script, warnings = self.nn.validate_script(raw, self.cands)
        self.assertEqual(warnings, [])

    def test_last_resort_drops_only_flagged_blocks(self):
        raw = self._raw()
        raw["bloques"].append({"ids": ["n3"], "seccion": "sociedad", "lugar": "", "titulo": "Otro incendio", "locucion": "El fuego llegó a 19 casas."})
        raw["bloques"][2].update(ids=["n2"], lugar="", locucion="Bomberos sofocaron un incendio de cuatro hectáreas en el acceso al aeropuerto.")
        with mock.patch.object(self.nn.time, "sleep"):
            script, warnings = self.nn.write_script(self.cands, completion=lambda **_: json.dumps(raw))
        self.assertEqual(warnings, [])
        self.assertEqual(len(script.blocks), 4)
        self.assertNotIn(["n3"], [b["ids"] for b in script.blocks])
        self.assertTrue(all("_warnings" not in b for b in script.blocks))

    def test_weekday_not_in_source_is_flagged(self):
        raw = self._raw()
        raw["bloques"][2]["locucion"] = "El jueves hubo incendios en el acceso al aeropuerto."
        _script, warnings = self.nn.validate_script(raw, self.cands)
        self.assertTrue(any("jueves" in w for w in warnings))

    def test_repeated_note_is_not_used_twice(self):
        raw = self._raw()
        raw["bloques"].append({"ids": ["n1"], "seccion": "policiales", "lugar": "", "titulo": "Otra vez el penal", "locucion": "Detuvieron a un agente penitenciario."})
        script, warnings = self.nn.validate_script(raw, self.cands)
        self.assertEqual(sum(1 for b in script.blocks if "n1" in b["ids"]), 1)
        self.assertTrue(any("repetidas" in w for w in warnings))

    def test_unknown_place_is_dropped(self):
        raw = self._raw()
        raw["bloques"][3]["lugar"] = "Famatina"
        script, _ = self.nn.validate_script(raw, self.cands)
        self.assertEqual(script.blocks[3]["lugar"], "")

    def test_place_label_rejects_origin_street_and_mixed_places(self):
        nn = self.nn
        estafa = _candidate(nn, "e1", "Detienen a una mujer", "Una mujer oriunda de Patquía fue detenida acusada de estafas.")
        antena = _candidate(nn, "a1", "Operario cayó", "El hecho ocurrió en calle Proyectada.")
        self.assertEqual(nn.place_label("Patquía", [estafa]), "")
        self.assertEqual(nn.place_label("Calle Proyectada", [antena]), "")
        self.assertEqual(nn.place_label("Chilecito", [self.cands[4]]), "Chilecito")
        self.assertEqual(nn.place_label("chilecito", [self.cands[4]]), "Chilecito")
        self.assertEqual(nn.place_label("La Rioja", [self.cands[4]]), "")
        self.assertEqual(nn.place_label("Los Cactus", [self.cands[1], self.cands[2]]), "")

    def test_write_script_retries_with_feedback_and_never_relaxes(self):
        bad = self._raw()
        bad["bloques"][1]["locucion"] = "Detuvieron a 19 agentes."
        calls = []

        def completion(**kwargs):
            calls.append(kwargs["messages"][1]["content"])
            return json.dumps(bad if len(calls) == 1 else self._raw())

        with mock.patch.object(self.nn.time, "sleep"):
            script, warnings = self.nn.write_script(self.cands, completion=completion)
        self.assertIsNotNone(script)
        self.assertEqual(warnings, [])
        self.assertIn("'19'", calls[1])

    def test_write_script_gives_up_when_facts_never_check(self):
        bad = self._raw()
        bad["bloques"][1]["locucion"] = "Detuvieron a 19 agentes."
        with mock.patch.object(self.nn.time, "sleep"):
            script, warnings = self.nn.write_script(self.cands, completion=lambda **_: json.dumps(bad))
        self.assertIsNone(script)
        self.assertTrue(warnings)

    def test_caption_lists_blocks_and_place_tags(self):
        script, _ = self.nn.validate_script(self._raw(), self.cands)
        text = self.nn.caption_for(date(2026, 10, 30), script.blocks, {})
        self.assertIn("Viernes 30 de octubre", text)
        self.assertIn("1️⃣ Detuvieron a un agente penitenciario", text)
        self.assertIn("#Chilecito", text)
        self.assertIn("Seguinos", text)


class MediaRulesTests(unittest.TestCase):
    def test_no_faces_in_policiales_and_flyers_last(self):
        from utils import nightly_newscast as nn

        items = [
            {"type": "image", "file": "fichaje.jpg", "face": True, "flyer": False},
            {"type": "image", "file": "placa.jpg", "face": False, "flyer": True},
            {"type": "image", "file": "lugar.jpg", "face": False, "flyer": False},
            {"type": "video", "file": "v.mp4"},
        ]
        self.assertEqual([m["file"] for m in nn.usable_media(items, policial=True)], ["v.mp4", "lugar.jpg", "placa.jpg"])
        self.assertIn("fichaje.jpg", [m["file"] for m in nn.usable_media(items, policial=False)])

    def test_photo_check_fails_open_without_key(self):
        from utils import nightly_newscast as nn

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            self.assertEqual(nn.check_photo("no-existe.jpg"), {})


class StateAndScheduleTests(_TempDir):
    def setUp(self):
        super().setUp()
        from utils import nightly_newscast as nn

        self.nn = nn
        patcher = mock.patch.object(nn, "STATE_PATH", self.path("state.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_due_until_generated_or_published(self):
        self.assertTrue(self.nn.due("2026-10-30", publish_enabled=False))
        self.nn.mark_day("2026-10-30", video="x.mp4")
        self.assertFalse(self.nn.due("2026-10-30", publish_enabled=False))
        self.assertTrue(self.nn.due("2026-10-30", publish_enabled=True))
        self.nn.mark_day("2026-10-30", ig_id="1")
        self.assertFalse(self.nn.due("2026-10-30", publish_enabled=True))

    def test_ambiguous_or_exhausted_day_is_not_retried(self):
        self.nn.mark_day("2026-10-30", ambiguous="instagram")
        self.assertFalse(self.nn.due("2026-10-30", publish_enabled=True))
        self.nn.note_attempt("2026-10-31")
        self.nn.note_attempt("2026-10-31")
        self.assertFalse(self.nn.due("2026-10-31", publish_enabled=False))

    def test_corrupt_state_fails_instead_of_resetting(self):
        from utils.file_manager import JsonStateError

        with open(self.path("state.json"), "w", encoding="utf-8") as fh:
            fh.write("{roto")
        with self.assertRaises(JsonStateError):
            self.nn.load_state()

    def test_waits_until_21(self):
        slept = []
        self.nn.wait_until_hour(21, now_fn=lambda: datetime(2026, 10, 30, 20, 52, tzinfo=AR_TZ), sleep=slept.append)
        self.assertEqual(slept, [480.0])
        slept.clear()
        self.nn.wait_until_hour(21, now_fn=lambda: datetime(2026, 10, 30, 21, 5, tzinfo=AR_TZ), sleep=slept.append)
        self.assertEqual(slept, [])


class PublishTests(_TempDir):
    def setUp(self):
        super().setUp()
        from utils import nightly_newscast as nn

        self.nn = nn
        patcher = mock.patch.object(nn, "STATE_PATH", self.path("state.json"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.edition = nn.Edition(day=date(2026, 10, 30), video_path=self.path("v.mp4"), caption="texto", script=None, blocks=[], folder=self.tmp.name)

    def _run(self, ig, fb):
        with mock.patch("utils.r2_storage.upload_temp", return_value=("https://media/x.mp4", "k")), \
             mock.patch("meta.ig_client.post_reel_video_to_instagram", return_value=ig) as ig_call, \
             mock.patch("meta.fb_client.post_reel_video_to_facebook", return_value=fb) as fb_call:
            out = self.nn.publish(self.edition, instagram=True, facebook=True)
        return out, ig_call, fb_call

    def test_success_records_ids(self):
        out, _, _ = self._run(OperationResult(StageStatus.SUCCESS, external_id="ig1"), OperationResult(StageStatus.SUCCESS, external_id="fb1"))
        self.assertEqual(out, {"ig": "success", "fb": "success"})
        self.assertEqual(self.nn.load_state()["2026-10-30"]["ig_id"], "ig1")

    def test_success_without_id_is_not_success(self):
        out, _, _ = self._run(OperationResult(StageStatus.SUCCESS), OperationResult(StageStatus.SUCCESS, external_id="fb1"))
        self.assertEqual(out["ig"], "failed")

    def test_ambiguous_instagram_blocks_facebook_and_retries(self):
        ambiguous = OperationResult(StageStatus.FAILED, error_type="timeout", details={"publication_outcome": "unknown"})
        out, _, fb_call = self._run(ambiguous, OperationResult(StageStatus.SUCCESS, external_id="fb1"))
        self.assertEqual(out["ig"], "ambiguous")
        fb_call.assert_not_called()
        self.assertFalse(self.nn.due("2026-10-30", publish_enabled=True))

    def test_rate_limit_is_reported(self):
        out, _, _ = self._run(OperationResult(StageStatus.DEGRADED, error_type="rate_limit"), OperationResult(StageStatus.SUCCESS, external_id="fb1"))
        self.assertEqual(out, {"ig": "rate_limit", "fb": "success"})


class RunnerTests(unittest.TestCase):
    def test_disabled_by_default(self):
        from meta import run_nightly_newscast as runner

        with mock.patch.dict(os.environ, {"NIGHTLY_NEWSCAST_ENABLED": "false"}):
            result = runner.main([])
        self.assertEqual(result.status, StageStatus.NO_WORK)
        self.assertTrue(result.details.get("disabled"))

    def test_rejected_script_fails_without_render(self):
        from meta import run_nightly_newscast as runner

        nn = runner.nn
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"NIGHTLY_NEWSCAST_ENABLED": "true", "NIGHTLY_NEWSCAST_PUBLISH": "false"}), \
             mock.patch.object(nn, "STATE_PATH", os.path.join(tmp, "s.json")), \
             mock.patch.object(nn, "collect_candidates", return_value=[object()] * 6), \
             mock.patch.object(nn, "write_script", return_value=(None, ["bloque 1: la cifra '19' no está en las notas"])), \
             mock.patch.object(nn, "build_edition") as build:
            result = runner.main([])
        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.error_type, "script_rejected")
        build.assert_not_called()


class QuotaTests(unittest.TestCase):
    def test_tts_quota_is_rate_limit_not_failure(self):
        from meta import run_nightly_newscast as runner

        nn = runner.nn
        script = nn.Script(hook="h", teasers=[], hook_ids=[], blocks=[])
        with tempfile.TemporaryDirectory() as tmp,              mock.patch.dict(os.environ, {"NIGHTLY_NEWSCAST_ENABLED": "true", "NIGHTLY_NEWSCAST_PUBLISH": "false"}),              mock.patch.object(nn, "STATE_PATH", os.path.join(tmp, "s.json")),              mock.patch.object(nn, "collect_candidates", return_value=[object()] * 6),              mock.patch.object(nn, "write_script", return_value=(script, [])),              mock.patch.object(nn, "build_edition", side_effect=nn.TTSQuotaError("cupo")):
            result = runner.main([])
        self.assertEqual(result.status, StageStatus.DEGRADED)
        self.assertEqual(result.error_type, "rate_limit")

    def test_quota_error_is_not_retried(self):
        from utils import nightly_newscast as nn

        calls = []

        class Models:
            def generate_content(self, **_):
                calls.append(1)
                raise RuntimeError("429 RESOURCE_EXHAUSTED")

        class Client:
            def __init__(self, **_):
                self.models = Models()

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}), mock.patch("google.genai.Client", Client),              mock.patch.object(nn.time, "sleep"):
            with self.assertRaises(nn.TTSQuotaError):
                nn.synthesize("hola", "x.wav")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
