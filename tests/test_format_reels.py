"""Reels de formato propio (Último momento, Datos útiles y Efemérides): sin red ni IA reales."""
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
    "gancho": "¡Incendio en el camping de ATUR!",
    "lugar": "",
    "tramos": [
        {"tipo": "mapa", "locucion": "Un incendio de pastizales se registró el viernes sobre la avenida Santa Rosa.",
         "chips": ["Incendio de pastizales", "Viernes", "Avenida Santa Rosa"], "claves": ["pastizales", "viernes"]},
        {"tipo": "cifra", "locucion": "Dos dotaciones de bomberos controlaron las llamas en el camping de ATUR.",
         "valor": "2", "etiqueta": "dotaciones de bomberos", "sello": "Llamas controladas", "claves": ["bomberos"]},
        {"tipo": "balance", "locucion": "No hubo heridos según los bomberos en el camping de ATUR.", "claves": ["heridos"]},
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
        self.assertEqual([b.layout for b in plan.beats], ["hook", "mapchips", "number", "check", "outro"])
        self.assertEqual(plan.beats[1].items[2], ("Avenida Santa Rosa", "pin"))
        self.assertEqual(plan.beats[-1].text, fr.CLOSING["um"])

    def test_um_rejects_invented_figure_and_name(self):
        raw = json.loads(json.dumps(UM_OK))
        raw["tramos"][1]["locucion"] = "Cinco dotaciones y el comisario Juan Pérez controlaron las llamas."
        raw["tramos"][1]["valor"] = "5"
        _plan, warnings = fr.validate_um(raw, cand())
        self.assertTrue(any("'5'" in w for w in warnings), warnings)
        self.assertTrue(any("Juan Pérez" in w for w in warnings), warnings)

    def test_um_repeated_type_is_rejected(self):
        raw = json.loads(json.dumps(UM_OK))
        raw["tramos"][2] = dict(raw["tramos"][0])
        _plan, warnings = fr.validate_um(raw, cand())
        self.assertTrue(any("ya se usó" in w for w in warnings))

    def test_screen_text_cannot_invent_causes_or_relative_days(self):
        c = cand(body="La línea 6 desvía por calle Vilcapugio por las calles dañadas tras el temporal.")
        self.assertTrue(fr._screen_check(["Desvío por obras"], c, "t"))
        self.assertEqual(fr._screen_check(["Calles dañadas", "Calle Vilcapugio"], c, "t"), [])
        self.assertTrue(fr._fact_check(["La línea 6 desvía hoy."], c, "t"))

    def test_grammar_words_are_not_invented_facts(self):
        # Frenaban guiones correctos de Datos útiles todo el día ("también", "pueden", "comienza").
        c = cand(body="La inscripción se abrirá el lunes en la Municipalidad. Se entregarán formularios.")
        self.assertEqual(fr._screen_check(["También pueden otros vecinos", "Comienza el lunes"], c, "t"), [])
        self.assertTrue(fr._screen_check(["Entregan libros"], c, "t"))

    def test_figures_with_units_match_other_spellings(self):
        def warn(text, body):
            return nn.factual_warnings(text, [cand(body=body)], "t")

        self.assertEqual(warn("Dura 30 horas.", "La jornada dura 30 hs."), [])
        self.assertEqual(warn("Subió 5 metros.", "El dique subió cinco metros."), [])
        self.assertEqual(warn("A 907 metros.", "a 907 m de profundidad"), [])
        self.assertTrue(warn("Dura 30 horas.", "Cuesta 30 pesos."))
        self.assertTrue(warn("Subió 5 metros.", "Subió 5 kilómetros."))

    def test_question_opening_capital_is_not_a_proper_noun(self):
        c = cand(body="Se pagan los Chachos desde el lunes 16 de noviembre en Chilecito.")
        self.assertEqual(fr._fact_check(["¿Cobrás Chachos? Mirá esto."], c, "gancho"), [])
        self.assertTrue(fr._fact_check(["Lo dijo Juan Pérez en Chilecito."], c, "gancho"))

    def test_du_not_qualifying_is_final(self):
        plan, warnings, qualifies = fr.validate_du({"apta": True, "interes": 4, "motivo": "poco interés"}, cand())
        self.assertIsNone(plan)
        self.assertFalse(qualifies)
        self.assertIn("no califica", warnings[0])

    def test_du_valid_plan_with_card_kinds(self):
        c = cand(body="Las inscripciones cierran el 27 de diciembre. Se puede anotar de forma presencial o virtual. "
                      "Cuesta $20.000. Hay 106 carreras en la UNLaR.")
        raw = {"apta": True, "interes": 9, "pregunta": "¿Vas a estudiar en la UNLaR?", "llamado": "Anotá esto.", "tarjetas": [
            {"tipo": "fecha", "rotulo": "Inscripciones", "resumen": "27 de diciembre", "capsula": "Cierran el", "valor": "27 de diciembre",
             "locucion": "Las inscripciones cierran el 27 de diciembre."},
            {"tipo": "lista", "rotulo": "Cómo anotarte", "resumen": "Presencial o virtual", "opciones": [{"icono": "🏫", "texto": "Presencial"}, {"icono": "💻", "texto": "Virtual"}],
             "locucion": "Te podés anotar de forma presencial o virtual."},
            {"tipo": "monto", "rotulo": "Cuánto cuesta", "resumen": "$20.000", "valor": "$20.000", "locucion": "La inscripción cuesta $20.000 en la UNLaR."},
            {"tipo": "cifra", "rotulo": "La oferta", "resumen": "106 carreras", "valor": "106", "unidad": "carreras", "locucion": "Hay 106 carreras para elegir en la UNLaR."},
        ]}
        plan, warnings, qualifies = fr.validate_du(raw, c)
        self.assertTrue(qualifies)
        self.assertEqual(warnings, [])
        self.assertEqual([b.card for b in plan.beats if b.layout == "card"], ["fecha", "lista", "monto", "cifra"])
        self.assertEqual(plan.beats[0].cta_from, 6)
        self.assertEqual([b.head for b in plan.beats if b.layout == "card"][2], "$20.000")

    def _du_raw(self, extra_card, detail=""):
        c = cand(body="Las inscripciones cierran el 27 de diciembre. Se puede anotar de forma presencial o virtual. "
                      "Cuesta $20.000. Hay 106 carreras en la UNLaR.")
        cards = [
            {"tipo": "fecha", "rotulo": "Inscripciones", "resumen": "27 de diciembre", "valor": "27 de diciembre", "detalle": detail,
             "locucion": "Las inscripciones cierran el 27 de diciembre."},
            {"tipo": "lista", "rotulo": "Cómo anotarte", "resumen": "Presencial o virtual", "opciones": [{"icono": "🏫", "texto": "Presencial"}, {"icono": "💻", "texto": "Virtual"}],
             "locucion": "Te podés anotar de forma presencial o virtual."},
            {"tipo": "monto", "rotulo": "Cuánto cuesta", "resumen": "$20.000", "valor": "$20.000", "locucion": "La inscripción cuesta $20.000 en la UNLaR."},
            {"tipo": "cifra", "rotulo": "La oferta", "resumen": "106 carreras", "valor": "106", "unidad": "carreras", "locucion": "Hay 106 carreras para elegir en la UNLaR."},
        ] + ([extra_card] if extra_card else [])
        return {"apta": True, "interes": 9, "pregunta": "¿Vas a estudiar en la UNLaR?", "llamado": "Anotá esto.", "tarjetas": cards}, c

    def test_du_card_with_invented_figure_is_dropped_not_the_reel(self):
        invented = {"tipo": "cifra", "rotulo": "Duración", "resumen": "30 horas", "valor": "30", "unidad": "horas",
                    "locucion": "El curso dura 30 horas en la UNLaR."}
        raw, c = self._du_raw(invented)
        plan, warnings, _ = fr.validate_du(raw, c)
        self.assertEqual(warnings, [])
        self.assertEqual(4, sum(1 for b in plan.beats if b.layout == "card"))
        self.assertNotIn("30", plan.text)

    def test_du_invented_detail_is_stripped_and_card_kept(self):
        raw, c = self._du_raw(None, detail="Sucursales bancarias")
        plan, warnings, _ = fr.validate_du(raw, c)
        self.assertEqual(warnings, [])
        first = next(b for b in plan.beats if b.layout == "card")
        self.assertEqual(("27 de diciembre", ""), (first.head, first.detail))

    def test_du_needs_min_cards(self):
        c = cand(body="Inscripciones hasta el 27 de diciembre. Cuesta $20.000.")
        raw = {"apta": True, "interes": 9, "pregunta": "¿Vas a estudiar?", "llamado": "Anotá esto.", "tarjetas": [
            {"tipo": "fecha", "rotulo": "Inscripciones", "resumen": "27 de diciembre", "valor": "27 de diciembre", "locucion": "Te anotás hasta el 27 de diciembre."},
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
        self.assertEqual(chips["words"][0]["t"], "Un")
        self.assertEqual(chips["items"][2]["icon"], "pin")

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

    def test_scene_clip_rejects_unverified_frames(self):
        with tempfile.TemporaryDirectory() as work,                 mock.patch.object(fr, "_duration", return_value=20.0),                 mock.patch.object(fr, "shot_cuts", return_value=[5.0, 12.0]),                 mock.patch.object(fr, "_frame_at", side_effect=lambda v, t, d: d),                 mock.patch.object(fr, "classify_frames", side_effect=[["estudio", "lugar", "lugar"], ["lugar"] * 5 + ["?"]]),                 mock.patch("utils.format_reels.subprocess.run") as run,                 mock.patch("utils.format_reels.os.path.isfile", return_value=True):
            run.return_value = mock.Mock(returncode=0, stderr="")
            clip, why = fr.scene_clip("v.mp4", work)
        self.assertEqual(clip, "")
        self.assertIn("sin verificar", why)

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

    def _main_with_du(self, outcome):
        from meta import run_format_reels as stage

        env = {"FORMAT_REELS_UM_ENABLED": "false", "FORMAT_REELS_DU_ENABLED": "true", "FORMAT_REELS_EF_ENABLED": "false",
               "FORMAT_REELS_DU_HOURS": "0-24"}
        plan = mock.Mock()
        plan.channel_enabled.return_value = True
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(stage, "deployment_plan", return_value=plan), \
                mock.patch.object(stage.shutil, "which", return_value="ffmpeg"), \
                mock.patch.object(stage, "run_du", return_value=outcome):
            return stage.main()

    def test_published_reel_reports_success(self):
        # Regresión: un Reel publicado (dict) se comparaba contra un set y tiraba TypeError,
        # el proceso moría sin StageResult y la etapa quedaba "failed" aunque hubiera publicado.
        result = self._main_with_du(("done", {"du": {"ig": "success", "fb": "success"}}))
        self.assertEqual((result.status.value, result.succeeded, result.failed), ("success", 1, 0))

    def test_failed_reel_reports_degraded(self):
        self.assertEqual(self._main_with_du(("done", {"du": {"ig": "failed", "fb": "skipped"}})).status.value, "degraded")
        self.assertEqual(self._main_with_du(("error", {"du": "render_failed"})).status.value, "degraded")


EF_BODY = (
    "El 12 de noviembre de 1863, el Chacho Peñaloza fue capturado en Olta y, tras entregar las armas, fue asesinado. "
    "El general Ángel Vicente Peñaloza lideró las montoneras federales en los Llanos. "
    "La fecha es feriado provincial por la Ley 10.298."
)
EF_ENTRY = {
    "id": "chacho", "fecha": "11-12", "anio": 1863, "aprobada": True, "foto_licencia_verificada": True,
    "fuente_url": "https://lavozriojana.com/noticias/chacho", "foto_url": "https://media.lavozriojana.com/x.webp", "lugar": "Olta",
    "gancho": "Un 12 de noviembre de 1863, en Olta, asesinaban al Chacho Peñaloza.",
    "quien": {"locucion": "General federal, líder de las montoneras de los Llanos.", "apodo": "El Chacho", "nombre": "Ángel Vicente Peñaloza",
              "chips": ["General federal", "Líder de los Llanos"]},
    "donde": {"locucion": "Lo capturaron en Olta y, tras entregar las armas, lo asesinaron.", "chips": ["Capturado en Olta"]},
    "anios": {"locucion": "Hoy se cumplen {anios} años."},
    "fecha_hoy": {"locucion": "Cada 12 de noviembre es feriado provincial.", "sello": "Feriado provincial", "detalle": "Ley 10.298"},
}


NR_HTML = """<html><body>
<article class="cont-cuerpo"><div class="cont-foto"><figure class="nota-foto"><img src="/galeria/fotos/2026/11/13/l_1.webp"></figure></div>
<section class="texto"><span class="autor"><figure class="avatar"><img src="/galeria/fotos-autor/m_9.webp"></figure></span>
<p>Texto</p><figure class="embed"><img src="https://nuevarioja.com.ar/galeria/fotos/2026/11/13/e_2.webp"></figure>
<figure class="embed"><img src="https://nuevarioja.com.ar/galeria/fotos/2026/11/13/e_2.webp?w=1"></figure></section></article>
<aside class="sidebar"><div class="lo-mas-visto"><article><img src="/galeria/fotos/2026/11/18/m_7.webp"></article></div></aside>
</body></html>"""


class UmPhotoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_gallery_only_takes_body_photos(self):
        url = "https://nuevarioja.com.ar/policiales/nota.htm"
        self.assertEqual(fr.source_gallery(url, html=NR_HTML), [
            "https://nuevarioja.com.ar/galeria/fotos/2026/11/13/l_1.webp",
            "https://nuevarioja.com.ar/galeria/fotos/2026/11/13/e_2.webp",
        ])
        self.assertEqual(fr.source_gallery(url, html=NR_HTML, limit=1), ["https://nuevarioja.com.ar/galeria/fotos/2026/11/13/l_1.webp"])
        self.assertEqual(fr.source_gallery("", html=NR_HTML), [])

    def _media(self, urls, strong=True):
        from meta import run_format_reels as stage

        note = fr.Note(url="https://lavozriojana.com/noticias/x", title="t", category="policiales", localities=[], published_at=0,
                       source="nuevarioja_policiales", canonical="https://nuevarioja.com.ar/x.htm")
        photo = {"type": "photo", "file": os.path.join(self.tmp.name, "foto.jpg"), "width": 1200, "height": 800}
        with mock.patch.object(fr, "source_gallery", return_value=urls), \
                mock.patch.object(nn, "prepare_photo", return_value=(1200, 800)), \
                mock.patch.object(fr, "strong_photo", return_value=(strong, "")):
            return stage._photo_media(note, cand(section="policiales"), photo, self.tmp.name)

    def test_photo_media_uses_gallery_with_two_or_more_strong_photos(self):
        media = self._media(["https://a/1.jpg", "https://a/2.jpg", "https://a/3.jpg"])
        self.assertEqual(3, len(media["gallery"]))
        self.assertEqual("photo", media["type"])

    def test_photo_media_falls_back_to_single_photo(self):
        self.assertNotIn("gallery", self._media(["https://a/1.jpg"]))
        self.assertNotIn("gallery", self._media(["https://a/1.jpg", "https://a/2.jpg"], strong=False))

    def _run_um(self, photo_mode: bool):
        from meta import run_format_reels as stage

        note = fr.Note(url="https://lavozriojana.com/noticias/u", title="Choque fatal en la ruta 38", category="policiales",
                       localities=["Chilecito"], published_at=0, source="nuevarioja_policiales", canonical="https://nuevarioja.com.ar/u.htm")
        photo = {"type": "photo", "file": "f.jpg", "width": 1200, "height": 800}
        env = {"FORMAT_REELS_UM_PHOTO_ENABLED": "true" if photo_mode else "false", "LVR_DATA_DIR": self.tmp.name}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(fr, "new_workdir", return_value=self.tmp.name), \
                mock.patch.object(fr, "cleanup"), \
                mock.patch.object(fr, "recent_notes", return_value=[note]), \
                mock.patch.object(stage, "is_breaking", return_value=True), \
                mock.patch.object(fr, "is_scoop", return_value=True), \
                mock.patch.object(fr, "is_riojan", return_value=True), \
                mock.patch.object(stage, "_candidate", return_value=cand(section="policiales")), \
                mock.patch.object(stage, "_photo", return_value=(photo, "")), \
                mock.patch.object(stage, "_photo_media", side_effect=lambda n, c, p, w: {**p, "credit": "FOTO: X"}) as media, \
                mock.patch.object(fr, "write_plan", return_value=(mock.Mock(), [], True)), \
                mock.patch.object(stage, "_produce", return_value={"ig": "success", "fb": "success"}) as produce:
            result = stage.run_um({}, [])
        return result, media, produce

    def test_um_without_video_uses_photos_only_with_flag(self):
        (status, _info), media, produce = self._run_um(photo_mode=True)
        self.assertEqual("done", status)
        media.assert_called_once()
        self.assertEqual("photo", produce.call_args.args[3]["type"])
        (status, _info), media, produce = self._run_um(photo_mode=False)
        self.assertEqual("no_work", status)
        produce.assert_not_called()


class PhotoUserAgentTests(unittest.TestCase):
    def test_wikimedia_gets_descriptive_user_agent(self):
        # Wikimedia devolvía 429 al User-Agent genérico y la foto de la EF no bajaba.
        from utils import story_publisher as sp

        with mock.patch.object(sp, "safe_get", return_value=mock.Mock(status_code=429, content=b"x")) as get:
            self.assertIsNone(sp.download_image("https://upload.wikimedia.org/wikipedia/commons/c/cc/x.jpg"))
            self.assertIn("lavozriojana.com", get.call_args.kwargs["headers"]["User-Agent"])
            sp.download_image("https://media.lavozriojana.com/x.webp")
            self.assertEqual("LaVozRiojanaBot/1.0", get.call_args.kwargs["headers"]["User-Agent"])


class EfemeridesTests(unittest.TestCase):
    def ef_cand(self):
        return cand(title="163 años del asesinato del Chacho Peñaloza", body=EF_BODY)

    def test_valid_plan_computes_years(self):
        import datetime

        plan, warnings = fr.validate_ef(EF_ENTRY, self.ef_cand(), datetime.date(2027, 11, 12))
        self.assertEqual(warnings, [])
        self.assertEqual([b.layout for b in plan.beats], ["hook", "who", "efmap", "years", "calendar", "outro"])
        years = plan.beats[3]
        self.assertEqual((years.text, years.value), ("Hoy se cumplen 164 años.", "164"))
        self.assertEqual(plan.beats[4].value, "12 de noviembre")
        self.assertEqual(plan.ef, {"day": "12", "month": "NOV", "year": "1863", "now": "2027"})
        self.assertEqual(plan.place, "Olta")
        self.assertIn("#UnDíaComoHoy", fr.caption_for(plan, self.ef_cand()))

    def test_invented_screen_text_or_name_is_rejected(self):
        import copy
        import datetime

        entry = copy.deepcopy(EF_ENTRY)
        entry["quien"]["chips"] = ["Caudillo federal"]
        entry["donde"]["locucion"] = "Lo capturó el coronel Pablo Irrazábal en Olta."
        _plan, warnings = fr.validate_ef(entry, self.ef_cand(), datetime.date(2027, 11, 12))
        self.assertTrue(any("caudillo" in w for w in warnings), warnings)
        self.assertTrue(any("Pablo Irrazábal" in w for w in warnings), warnings)

    def test_screen_text_longer_than_its_slot_is_asked_again(self):
        import copy
        import datetime

        entry = copy.deepcopy(EF_ENTRY)
        entry["quien"]["chips"] = ["General federal de los Llanos riojanos"]
        _plan, warnings = fr.validate_ef(entry, self.ef_cand(), datetime.date(2027, 11, 12))
        self.assertTrue(any("más de 26 caracteres" in w for w in warnings), warnings)

    def test_blockers_and_dates(self):
        import datetime

        self.assertEqual(fr.ef_blockers(EF_ENTRY), [])
        pending = dict(EF_ENTRY, foto_licencia_verificada=False, aprobada=False)
        self.assertEqual(len(fr.ef_blockers(pending)), 2)
        self.assertTrue(fr.ef_blockers(dict(EF_ENTRY, fuente_url="https://otro.com/x")))
        rows = [EF_ENTRY, dict(EF_ENTRY, id="otro", fecha="03-01")]
        self.assertEqual([r["id"] for r in fr.efemerides_for(datetime.date(2027, 11, 12), rows)], ["chacho"])

    def test_repo_list_is_valid(self):
        rows = fr.load_efemerides(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "efemerides_riojanas.json"))
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNotNone(fr.ef_month_day(row), row.get("id"))
            self.assertIn("{anios}", row["anios"]["locucion"])

    def test_corrupt_list_fails(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            fh.write("{roto")
        self.addCleanup(os.remove, fh.name)
        with self.assertRaises(ValueError):
            fr.load_efemerides(fh.name)


class EfStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # EF automática apagada: con el .env del host (FORMAT_REELS_EF_AUTO=true) iba a Wikipedia real.
        patcher = mock.patch.dict(os.environ, {"LVR_DATA_DIR": self.tmp.name, "LVR_LOGS_DIR": self.tmp.name,
                                               "FORMAT_REELS_EF_AUTO": "false"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unapproved_entry_is_recorded_once_without_fetching(self):
        from meta import run_format_reels as stage

        entry = dict(EF_ENTRY, foto_licencia_verificada=False)
        with mock.patch.object(fr, "load_efemerides", return_value=[entry]), \
                mock.patch.object(fr, "efemerides_for", return_value=[entry]), \
                mock.patch.object(stage, "_candidate") as fetch:
            self.assertEqual(stage.run_ef({})[0], "no_work")
            state = fr.load_state()
            key = f"ef:chacho:{fr.now_ar().year}"
            self.assertEqual(state["items"][key]["status"], "rejected")
            self.assertIn("licencia", state["items"][key]["reason"])
            self.assertEqual(stage.run_ef(state)[0], "no_work")
        fetch.assert_not_called()

    def test_unreadable_source_is_retried_later(self):
        from meta import run_format_reels as stage

        with mock.patch.object(fr, "load_efemerides", return_value=[EF_ENTRY]), \
                mock.patch.object(fr, "efemerides_for", return_value=[EF_ENTRY]), \
                mock.patch.object(stage, "_candidate", return_value=None):
            self.assertEqual(stage.run_ef({}), ("error", {"ef": "fuente_ilegible"}))
        self.assertEqual(fr.load_state(), {})

    def test_corrupt_list_is_an_error(self):
        from meta import run_format_reels as stage

        with mock.patch.object(fr, "load_efemerides", side_effect=ValueError("roto")), mock.patch.object(stage, "logger"):
            self.assertEqual(stage.run_ef({}), ("error", {"ef": "lista_ilegible"}))


class OpeningGapTests(unittest.TestCase):
    def test_late_start_or_gap_rejects_voice(self):
        ok = [Tok("Un", 0, 200), Tok("12", 220, 500), Tok("de", 520, 600)]
        fr.opening_gap(ok)
        with self.assertRaises(RuntimeError):
            fr.opening_gap([Tok("Un", 0, 260), Tok("12", 3240, 3360), Tok("de", 3360, 3480)])
        with self.assertRaises(RuntimeError):
            fr.opening_gap([Tok("Un", 2900, 3100), Tok("12", 3200, 3300)])

    def test_radio_noise_after_last_word_is_trimmed(self):
        calls = []

        def runner(args, **kw):
            calls.append(args)
            if "silencedetect" in " ".join(args):
                err = ("silence_start: 15.28\nsilence_end: 15.41 | silence_duration: 0.13\n"
                       "silence_start: 18.73\nsilence_end: 18.91 | silence_duration: 0.18\n")
                return mock.Mock(stderr=err)
            open(args[-1], "wb").close()
            return mock.Mock(stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "voz.wav")
            open(wav, "wb").close()
            self.assertAlmostEqual(fr.trim_tail_noise(wav, 19.07, runner=runner), 18.79, places=2)
        self.assertIn("atrim=0:18.790", " ".join(calls[-1]))

    def test_voice_ending_on_a_word_is_not_trimmed(self):
        def runner(args, **kw):
            # el último sonido dura 1,2 s (la frase de cierre), no es un ruido
            return mock.Mock(stderr="silence_start: 17.5\nsilence_end: 17.8 | silence_duration: 0.3\n")

        self.assertEqual(fr.trim_tail_noise("x.wav", 19.0, runner=runner), 19.0)
        late_silence = lambda args, **kw: mock.Mock(stderr="silence_start: 18.7\nsilence_end: 19.0\n")  # noqa: E731
        self.assertEqual(fr.trim_tail_noise("x.wav", 19.0, runner=late_silence), 19.0)

    def test_trim_matches_numbers_heard_as_words(self):
        words = [("Un", 0, 260, 0.9), ("doce", 260, 390, 0.9), ("de", 390, 520, 0.9), ("noroeste", 520, 1030, 0.9),
                 ("urgente", 2490, 2900, 0.9), ("Un", 3000, 3240, 0.9), ("doce", 3240, 3360, 0.9), ("de", 3360, 3480, 0.9),
                 ("noviembre", 3480, 4040, 0.9)] + [(f"w{i}", 4100 + i * 300, 4300 + i * 300, 0.9) for i in range(20)]
        text = "Un 12 de noviembre " + " ".join(f"w{i}" for i in range(20))
        with mock.patch("utils.nightly_newscast.subprocess.run"), mock.patch("utils.nightly_newscast.os.replace"):
            cut = nn.trim_spoken_preamble("x.wav", text, asr=lambda wav, hint: words)
        self.assertAlmostEqual(cut, 2.88, places=2)

    def test_trim_retries_broken_whisper_json(self):
        calls = []

        def asr(wav, hint):
            calls.append(1)
            if len(calls) == 1:
                raise json.JSONDecodeError("roto", "", 0)
            return [("Controlaron", 100, 400, 0.9), ("un", 400, 500, 0.9), ("incendio", 500, 900, 0.9)]

        with mock.patch("utils.nightly_newscast.subprocess.run"):
            self.assertEqual(nn.trim_spoken_preamble("x.wav", "Controlaron un incendio en ATUR.", asr=asr), 0.0)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()


class TtsPreambleTests(unittest.TestCase):
    TEXT = "Controlaron un incendio en el camping de ATUR."

    def test_tts3_uses_short_tag_and_2_5_keeps_direction(self):
        self.assertTrue(nn._tts_prompt("gemini-3.8-flash-tts", "Hola.", None).startswith("[tonada"))
        self.assertTrue(nn._tts_prompt("gemini-2.5-pro-preview-tts", "Hola.", None).startswith(nn.VOICE_DIRECTION))

    def test_no_trim_when_text_starts_right_away(self):
        asr = lambda wav, hint: [("Controlaron", 120, 400, 0.9), ("un", 400, 500, 0.9), ("incendio", 500, 900, 0.9)]
        with mock.patch("utils.nightly_newscast.subprocess.run") as run:
            self.assertEqual(nn.trim_spoken_preamble("x.wav", self.TEXT, asr=asr), 0.0)
        run.assert_not_called()

    def test_trims_spoken_preamble_using_last_match(self):
        words = [("Controlaron", 0, 300, 0.9), ("un", 300, 400, 0.9), ("incendio", 400, 800, 0.9), ("en", 800, 900, 0.9),
                 ("una", 900, 1000, 0.9), ("radio", 1000, 1400, 0.9), ("enérgico", 1400, 2000, 0.9),
                 ("Controlaron", 3000, 3300, 0.9), ("un", 3300, 3400, 0.9), ("incendio", 3400, 3800, 0.9),
                 ("en", 3800, 3900, 0.9), ("el", 3900, 4000, 0.9), ("camping", 4000, 4400, 0.9), ("de", 4400, 4500, 0.9), ("ATUR", 4500, 5000, 0.9)]
        with mock.patch("utils.nightly_newscast.subprocess.run") as run, mock.patch("utils.nightly_newscast.os.replace"):
            cut = nn.trim_spoken_preamble("x.wav", self.TEXT, asr=lambda wav, hint: words)
        self.assertAlmostEqual(cut, 2.88, places=2)
        self.assertIn("-ss", run.call_args.args[0])
