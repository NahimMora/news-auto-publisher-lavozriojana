"""Reels de formato propio (Último momento y Datos útiles): sin red ni IA reales."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import dataclass
from unittest import mock

from utils import format_reels as fr
from utils import nightly_newscast as nn

BODY = (
    "Un incendio de pastizales se registró el viernes en el camping de ATUR, sobre la avenida Santa Rosa. "
    "Dos dotaciones de bomberos controlaron las llamas. No hubo heridos."
)


def cand(**kw) -> nn.Candidate:
    base = dict(id="n1", title="Incendio en el camping de ATUR", section="sociedad", source="fenix_locales",
                web_url="https://lavozriojana.com/noticias/x", published_at=1000.0, body=BODY)
    base.update(kw)
    return nn.Candidate(**base)


UM_OK = {
    "gancho": "Fuego en el camping de ATUR",
    "lugar": "",
    "tramos": [
        {"tipo": "chips", "locucion": "Se quemaron pastizales el viernes en el camping de ATUR, sobre la avenida Santa Rosa.", "items": ["pastizales", "viernes", "avenida Santa Rosa"]},
        {"tipo": "cifra", "locucion": "Dos dotaciones de bomberos controlaron las llamas y no hubo heridos.", "items": [],
         "valor": "2", "etiqueta": "dotaciones de bomberos", "detalle": "sin heridos"},
    ],
}


@dataclass
class Tok:
    text: str
    start_ms: int
    end_ms: int


class ValidationTests(unittest.TestCase):
    def test_um_valid_plan(self):
        plan, warnings = fr.validate_um(UM_OK, cand())
        self.assertEqual(warnings, [])
        self.assertEqual([b.layout for b in plan.beats], ["hook", "chips", "number", "outro"])
        self.assertEqual(plan.beats[-1].text, fr.CLOSING["um"])

    def test_um_rejects_invented_figure_and_name(self):
        raw = json.loads(json.dumps(UM_OK))
        raw["tramos"][1]["locucion"] = "Cinco dotaciones y el comisario Juan Pérez controlaron las llamas."
        raw["tramos"][1]["valor"] = "5"
        _plan, warnings = fr.validate_um(raw, cand())
        self.assertTrue(any("'5'" in w for w in warnings), warnings)
        self.assertTrue(any("Juan Pérez" in w for w in warnings), warnings)

    def test_um_requires_distinct_layouts(self):
        raw = json.loads(json.dumps(UM_OK))
        raw["tramos"][1] = dict(raw["tramos"][0])
        _plan, warnings = fr.validate_um(raw, cand())
        self.assertTrue(any("tipo distinto" in w for w in warnings))

    def test_question_opening_capital_is_not_a_proper_noun(self):
        c = cand(body="Se pagan los Chachos desde el lunes 16 de noviembre en Chilecito.")
        self.assertEqual(fr._fact_check(["¿Cobrás Chachos? Mirá esto."], c, "gancho"), [])
        self.assertTrue(fr._fact_check(["Lo dijo Juan Pérez en Chilecito."], c, "gancho"))

    def test_du_not_qualifying_is_final(self):
        plan, warnings, qualifies = fr.validate_du({"apta": True, "interes": 4, "motivo": "poco interés"}, cand())
        self.assertIsNone(plan)
        self.assertFalse(qualifies)
        self.assertIn("no califica", warnings[0])

    def test_du_needs_min_cards(self):
        c = cand(body="Inscripciones hasta el 27 de diciembre. Cuesta $20.000. Hay 106 carreras. Modalidad presencial o virtual.")
        raw = {"apta": True, "interes": 9, "gancho": "¿Vas a estudiar? Anotá esto.", "tarjetas": [
            {"etiqueta": "Inscripciones", "valor": "27 de diciembre", "locucion": "Te anotás hasta el 27 de diciembre."},
            {"etiqueta": "Costo", "valor": "$20.000", "locucion": "Cuesta $20.000."},
        ]}
        _plan, warnings, qualifies = fr.validate_du(raw, c)
        self.assertTrue(qualifies)
        self.assertTrue(any("al menos 4" in w for w in warnings))


class SelectionTests(unittest.TestCase):
    def test_riojan_sources_and_text(self):
        self.assertTrue(fr.is_riojan(cand(source="tiempopopular_locales", body="Corte en la ruta.")))
        self.assertTrue(fr.is_riojan(cand(source="nuevarioja_sociedad", body="Pasó en La Rioja.")))
        self.assertFalse(fr.is_riojan(cand(source="nuevarioja_sociedad", section="sociedad", body="Explosión en Lanús, provincia de Buenos Aires.")))

    def test_scoop_rejects_follow_ups(self):
        note = fr.Note(url="u2", title="Incendio en el camping de ATUR controlado", category="sociedad", localities=[],
                       published_at=10_000, source="fenix_locales")
        earlier = [{"web_url": "u1", "titulo": "Incendio en el camping de ATUR", "published_at_ts": 9_000}]
        self.assertFalse(fr.is_scoop(note, records=earlier))
        self.assertTrue(fr.is_scoop(note, records=[{"web_url": "u3", "titulo": "Asumió el nuevo intendente", "published_at_ts": 9_000}]))

    def test_clean_body_skips_context_boxes(self):
        page = (
            "<div class='article-lead'><p>Desde el lunes 16 se pagan los Chachos en el interior.</p></div>"
            "<div class='lr-article'><p>El cronograma sigue el martes 17 en Sanagasta y Aminga.</p></div>"
            "<section class='context-note-box'><p>El miércoles 19 de agosto continuó el pago en Chilecito.</p></section>"
            "<aside class='author-box'><p>Responsable editorial de La Voz Riojana con foco en la actualidad.</p></aside>"
        )
        body = fr.clean_body(page)
        self.assertIn("martes 17", body)
        self.assertNotIn("agosto", body)
        self.assertNotIn("Responsable editorial", body)


class TimelineTests(unittest.TestCase):
    def test_beats_follow_voice_and_items_sync(self):
        plan, _ = fr.validate_um(UM_OK, cand())
        words = plan.text.split()
        tokens = [Tok(w, i * 300, i * 300 + 250) for i, w in enumerate(words)]
        beats, total = fr.timeline(plan, tokens, len(words) * 300)
        self.assertEqual(beats[0]["from"], 0)
        self.assertTrue(all(a["to"] == b["from"] for a, b in zip(beats, beats[1:])))
        self.assertGreaterEqual(total - beats[-1]["from"], 72)  # cierre de al menos 2,4 s
        chips = beats[1]
        viernes = next(i for i, t in enumerate(tokens) if t.text.startswith("viernes"))
        self.assertEqual(chips["items"][1]["at"], round(tokens[viernes].start_ms / 1000 * fr.FPS))

    def test_timeline_refuses_mismatched_alignment(self):
        plan, _ = fr.validate_um(UM_OK, cand())
        with self.assertRaises(ValueError):
            fr.timeline(plan, [Tok("hola", 0, 100)], 100)


class VideoTests(unittest.TestCase):
    def test_scene_clip_rejects_studio_in_final_check(self):
        with tempfile.TemporaryDirectory() as work, \
                mock.patch.object(fr, "_duration", return_value=20.0), \
                mock.patch.object(fr, "shot_cuts", return_value=[5.0, 12.0]), \
                mock.patch.object(fr, "_frame_at", side_effect=lambda v, t, d: d), \
                mock.patch.object(fr, "classify_frames", side_effect=[["estudio", "lugar", "lugar"], ["lugar"] * 5 + ["estudio"]]), \
                mock.patch("utils.format_reels.subprocess.run") as run, \
                mock.patch("utils.format_reels.os.path.isfile", return_value=True):
            run.return_value = mock.Mock(returncode=0, stderr="")
            clip, why = fr.scene_clip("v.mp4", work)
        self.assertEqual(clip, "")
        self.assertIn("estudio", why)

    def test_scene_clip_needs_enough_scene_seconds(self):
        with tempfile.TemporaryDirectory() as work, \
                mock.patch.object(fr, "_duration", return_value=20.0), \
                mock.patch.object(fr, "shot_cuts", return_value=[16.0]), \
                mock.patch.object(fr, "_frame_at", side_effect=lambda v, t, d: d), \
                mock.patch.object(fr, "classify_frames", return_value=["estudio", "lugar"]):
            clip, why = fr.scene_clip("v.mp4", work)
        self.assertEqual(clip, "")
        self.assertIn("menos de", why)

    def test_strong_photo_rules(self):
        self.assertFalse(fr.strong_photo("x", (500, 300), policial=False, checker=lambda p: {})[0])
        self.assertFalse(fr.strong_photo("x", (1200, 800), policial=False, checker=lambda p: {"flyer": True})[0])
        self.assertFalse(fr.strong_photo("x", (1200, 800), policial=True, checker=lambda p: {"face": True})[0])
        self.assertTrue(fr.strong_photo("x", (1200, 800), policial=False, checker=lambda p: {"face": True, "flyer": False})[0])


class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LVR_DATA_DIR": self.tmp.name, "LVR_LOGS_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_disabled_by_default(self):
        from meta import run_format_reels as stage

        with mock.patch.dict(os.environ, {"FORMAT_REELS_UM_ENABLED": "false", "FORMAT_REELS_DU_ENABLED": "false"}):
            self.assertEqual(stage.main().status.value, "no_work")

    def test_um_daily_cap(self):
        from meta import run_format_reels as stage

        day = fr.now_ar().date().isoformat()
        state = {"items": {"um:a": {"day": day, "ig_id": "1"}, "um:b": {"day": day, "status": "ambiguous"}}}
        status, info = stage.run_um(state, [])
        self.assertEqual((status, info), ("no_work", {"um": "tope diario"}))

    def test_du_rejection_is_recorded_once(self):
        from meta import run_format_reels as stage

        note = fr.Note(url="https://lavozriojana.com/noticias/a", title="Nota", category="sociedad", localities=["Chilecito"],
                       published_at=0, source="fenix_locales")
        with mock.patch.object(fr, "recent_notes", return_value=[note]), \
                mock.patch.object(stage, "_candidate", return_value=cand(web_url=note.url)), \
                mock.patch.object(fr, "write_plan", return_value=(None, ["no califica: apta=False"], False)) as plan:
            self.assertEqual(stage.run_du({})[0], "no_work")
            state = fr.load_state()
            self.assertEqual(state["items"][f"du:{note.url}"]["status"], "rejected")
            self.assertEqual(stage.run_du(state)[0], "no_work")
        self.assertEqual(plan.call_count, 1)


if __name__ == "__main__":
    unittest.main()
