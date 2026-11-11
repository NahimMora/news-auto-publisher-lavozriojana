"""Noticiero V3 (2026-10-31): guion por tramos, puertas de recursos, plan
audiovisual (familias, tomas, frames, subtítulos), alineamiento y caché.
Todo con fixtures locales: sin red, sin IA, sin render ni publicación."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import wave
from datetime import date
from unittest import mock

from utils import newscast_align as na
from utils import newscast_v3 as v3
from utils import nightly_newscast as nn


def _cand(cid, title, body, section="policiales", photo=True, video=""):
    return nn.Candidate(id=cid, title=title, section=section, source="fenix_locales", web_url=f"https://lavozriojana.com/noticias/{cid}",
                        published_at=time.time(), body=body, photo_url=f"https://media.lavozriojana.com/{cid}.webp" if photo else "", video_url=video)


def _tokens(text, start=0, step=300):
    """Tokens alineados de prueba (como si vinieran del alineador)."""
    out = []
    t = start
    for w in text.split():
        out.append(na.Token(w, t, t + step - 40, "asr", 0.9, False))
        t += step + (200 if w.endswith(".") else 0)
    return out


def _asset(note, kind="image", w=1080, h=1920, check=None, duration_ms=0, sha=None):
    a = v3.Asset(note, kind, f"tmp/x/{note}.{'mp4' if kind == 'video' else 'jpg'}", "", w, h, duration_ms=duration_ms,
                 sha=sha or (note + kind).ljust(64, "0"), check=dict(check or {"corresponde": "si", "tipo": "registro_del_hecho", "zona_texto": "ninguna", "nitidez": 4}))
    return v3.assess(a, policial=False, sensitive=False)


def _story(block, assets, align=True, voice_ms=None):
    toks = _tokens(block["locucion"]) if align else []
    voice_ms = voice_ms or (toks[-1].end_ms + 300 if toks else 6000)
    return v3.StoryInput(block=block, voice_file="tmp/x/b.wav", voice_ms=voice_ms, tokens=toks, assets=assets, credit="Fuente: Fénix",
                         align_ok=align, note_sources={x: "Fénix" for x in block["ids"]})


def _block(ids, tramos, tipo="hecho", seccion="policiales", titulo="Titular de prueba"):
    return {"ids": ids, "seccion": seccion, "tipo": tipo, "titulo": titulo, "titulo_corto": "", "lugar": "", "servicio": {},
            "relevancia": {"interes": 3, "novedad": 3, "impacto_local": 3, "utilidad": 3, "seguimiento": 3},
            "tramos": [{"ids": t[0], "lugar": t[2] if len(t) > 2 else "", "texto": t[1], "momento": t[3] if len(t) > 3 else "", "dato": t[4] if len(t) > 4 else ""} for t in tramos],
            "locucion": " ".join(t[1] for t in tramos)}


class SpokenFormsAndMappingTests(unittest.TestCase):
    def test_numbers_currency_percent_and_hours(self):
        self.assertEqual(na.spoken_forms("62%"), ["sesenta", "y", "dos", "por", "ciento"])
        self.assertEqual(na.spoken_forms("28,8"), ["veintiocho", "coma", "ocho"])
        self.assertEqual(na.spoken_forms("1.500"), ["mil", "quinientos"])
        self.assertEqual(na.spoken_forms("$300"), ["trescientos", "pesos"])
        self.assertEqual(na.spoken_forms("21:30"), ["veintiuno", "treinta"])
        self.assertEqual(na.spoken_forms("0"), ["cero"])

    def test_digits_from_recognizer_anchor_the_written_figure(self):
        asr = [("La", 0, 100, 1), ("carne", 100, 400, 1), ("subió", 400, 800, 1), ("62%", 800, 1600, 1)]
        out = na.map_words("La carne subió 62%".split(), asr, 1700)
        self.assertEqual([t.method for t in out.tokens], ["asr"] * 4)
        self.assertTrue(out.critical_ok)
        self.assertEqual(out.tokens[3].start_ms, 800)

    def test_unmatched_word_is_bounded_by_real_anchors(self):
        asr = [("El", 0, 200, 1), ("hombre", 200, 600, 1), ("Xqz", 600, 900, 0.2), ("detenido", 1500, 2000, 1)]
        out = na.map_words("El hombre fue detenido".split(), asr, 2100)
        fue = out.tokens[2]
        self.assertEqual(fue.method, "interpolated")
        self.assertGreaterEqual(fue.start_ms, 600)
        self.assertLessEqual(fue.end_ms, 1500)

    def test_audio_that_differs_from_script_fails(self):
        asr = [("Hoy", 0, 300, 1), ("llueve", 300, 700, 1), ("en", 700, 800, 1), ("Chilecito", 800, 1400, 1)]
        out = na._verdict(na.map_words("Fue procesado por robo en la obra".split(), asr, 1500))
        self.assertFalse(out.ok)

    def test_unanchored_negation_is_critical(self):
        asr = [("El", 0, 200, 1), ("acusado", 200, 700, 1), ("declaró", 1000, 1500, 1)]
        out = na.map_words("El acusado no declaró".split(), asr, 1600)
        self.assertFalse(out.critical_ok)


class CueTests(unittest.TestCase):
    def test_cues_keep_number_and_unit_and_article_together(self):
        cues = na.build_cues(_tokens("Bomberos sofocaron un incendio que afectó cuatro hectáreas de vegetación en el acceso al aeropuerto local."))
        for cue in cues:
            words = cue["text"].split()
            self.assertNotIn(words[-1].lower(), {"cuatro", "el", "la", "un", "de", "al"})
            self.assertLessEqual(len(cue["text"]), na.CUE_MAX_CHARS + 8)
        self.assertNotEqual(cues[-1]["text"], "local.")

    def test_cues_cut_at_sentence_end(self):
        cues = na.build_cues(_tokens("Una mujer fue detenida. La causa sigue abierta."))
        self.assertTrue(cues[0]["text"].endswith("detenida."))


class ScriptValidationTests(unittest.TestCase):
    def setUp(self):
        self.cands = [
            _cand("n1", "Incendio en el acceso al aeropuerto", "Bomberos sofocaron un incendio que afectó cuatro hectáreas en el acceso al aeropuerto."),
            _cand("n2", "Incendio en el barrio Emeli Bestani", "Un incendio de pastizales puso en riesgo a dos caballos en el barrio Emeli Bestani el viernes."),
            _cand("n3", "Detienen a mujer en el penal", "Una mujer de 58 años fue detenida con 28,8 gramos de cocaína y 6,1 gramos de marihuana."),
        ]

    def test_tramo_cannot_take_figures_from_another_event(self):
        raw = {"bloques": [{"ids": ["n1", "n2"], "seccion": "sociedad", "tipo": "hechos_relacionados", "titulo": "Incendios de pastizales",
                            "tramos": [{"ids": ["n1"], "texto": "Un incendio puso en riesgo a dos caballos."},
                                       {"ids": ["n2"], "texto": "Otro incendio afectó al barrio Emeli Bestani."}]}]}
        _script, warnings = v3.validate_script_v3(raw, self.cands)
        self.assertTrue(any("tramo 1" in w and "'2'" in w for w in warnings), warnings)

    def test_related_requires_distinct_events(self):
        raw = {"bloques": [{"ids": ["n1"], "seccion": "sociedad", "tipo": "hechos_relacionados", "titulo": "Incendio en el aeropuerto",
                            "tramos": [{"ids": ["n1"], "texto": "Bomberos sofocaron un incendio."}, {"ids": ["n1"], "texto": "Afectó el acceso al aeropuerto."}]}]}
        script, _ = v3.validate_script_v3(raw, self.cands)
        self.assertEqual(script.blocks[0]["tipo"], "hecho")

    def test_summed_figure_as_dato_is_dropped(self):
        raw = {"bloques": [{"ids": ["n3"], "seccion": "policiales", "tipo": "dato", "titulo": "Detienen a mujer en el penal",
                            "tramos": [{"ids": ["n3"], "dato": "34,9 gramos", "texto": "Una mujer de 58 años fue detenida con 28,8 gramos de cocaína y 6,1 gramos de marihuana."}]}]}
        script, warnings = v3.validate_script_v3(raw, self.cands)
        self.assertFalse([w for w in warnings if not w.startswith(("hay ", "cobertura"))])
        self.assertEqual(script.blocks[0]["tramos"][0]["dato"], "")
        self.assertEqual(script.blocks[0]["tipo"], "hecho")

    def test_timeline_without_proven_moments_is_not_a_timeline(self):
        raw = {"bloques": [{"ids": ["n2"], "seccion": "sociedad", "tipo": "cronologia", "titulo": "Incendio en el barrio Emeli Bestani",
                            "tramos": [{"ids": ["n2"], "momento": "21:30", "texto": "Un incendio de pastizales puso en riesgo a dos caballos."},
                                       {"ids": ["n2"], "momento": "viernes", "texto": "Ocurrió en el barrio Emeli Bestani."}]}]}
        script, _ = v3.validate_script_v3(raw, self.cands)
        self.assertEqual(script.blocks[0]["tramos"][0]["momento"], "")
        self.assertEqual(script.blocks[0]["tipo"], "hecho")

    def test_expired_service_is_not_presented_as_current(self):
        self.assertTrue(v3.service_expired("sábado 24 de octubre de 8 a 14", today=date(2026, 10, 30)))
        self.assertFalse(v3.service_expired("sábado 7 de noviembre de 8 a 14", today=date(2026, 10, 30)))
        self.assertFalse(v3.service_expired("este sábado", today=date(2026, 10, 30)))


class AssetGateTests(unittest.TestCase):
    def test_media_of_another_event_is_excluded_even_if_sharp(self):
        a = _asset("n6", "video", 1080, 608, {"corresponde": "no", "tipo": "registro_del_hecho", "nitidez": 5, "texto_incrustado": "ALLANAMIENTOS EN ZONA NORTE"}, 60000)
        self.assertFalse(a.eligible)
        self.assertIn("ALLANAMIENTOS", a.reasons[0])

    def test_face_in_policiales_or_sensitive_is_excluded(self):
        check = {"corresponde": "si", "tipo": "retrato", "persona_primer_plano": True, "nitidez": 5}
        a = v3.assess(v3.Asset("n1", "image", "x", "", 990, 613, sha="a" * 64, check=dict(check)), policial=False, sensitive=True)
        self.assertFalse(a.eligible)

    def test_studio_talk_is_not_evidence(self):
        self.assertFalse(_asset("n4", "video", 1080, 608, {"corresponde": "dudoso", "tipo": "estudio_o_entrevista", "nitidez": 4}, 60000).eligible)

    def test_unverified_video_is_excluded_and_unverified_photo_is_context(self):
        video = v3.assess(v3.Asset("n1", "video", "x", "", 1080, 608, duration_ms=9000, sha="b" * 64), policial=False, sensitive=False)
        photo = v3.assess(v3.Asset("n1", "image", "x", "", 1280, 853, sha="c" * 64), policial=False, sensitive=False)
        self.assertFalse(video.eligible)
        self.assertTrue(photo.eligible)
        self.assertEqual((photo.role, photo.label), ("context", "Imagen ilustrativa"))

    def test_layout_protects_text_subjects_and_resolution(self):
        self.assertEqual(_asset("a", w=900, h=1600).layout, "full")
        self.assertEqual(_asset("b", w=1280, h=960).layout, "full")
        self.assertEqual(_asset("c", w=975, h=584).layout, "window")  # ampliaría 3,3×
        self.assertEqual(_asset("d", w=1400, h=1050, check={"corresponde": "si", "tipo": "registro_del_hecho", "zona_texto": "abajo", "nitidez": 4}).layout, "window")
        self.assertEqual(_asset("e", w=1400, h=1050, check={"corresponde": "si", "tipo": "registro_del_hecho", "sujetos_en_bordes": True, "nitidez": 4}).layout, "window")


class PlanTests(unittest.TestCase):
    def _plan(self, stories, **kw):
        return v3.build_plan(stories, outro_voice="tmp/x/o.wav", outro_ms=2100, date_label="VIERNES 30 DE OCTUBRE", **kw)

    def test_related_events_never_cross_media(self):
        block = _block(["a", "b"], [(["a"], "Un incendio afectó el acceso al aeropuerto local.", "aeropuerto"),
                                    (["b"], "Otro incendio afectó al barrio Emeli Bestani.", "Emeli Bestani")], tipo="hechos_relacionados", seccion="sociedad")
        story = _story(block, [_asset("a", w=1280, h=960)])  # el hecho b no tiene material
        plan = self._plan([story])
        s = plan["stories"][0]
        self.assertEqual(s["family"], "related")
        self.assertEqual([sh["media"]["note"] if sh["media"] else None for sh in s["shots"]], ["a", None])
        self.assertEqual(v3.validate_plan(plan), [])
        self.assertEqual([e["lugar"] for e in s["events"]], ["aeropuerto", "Emeli Bestani"])

    def test_cross_event_asset_is_rejected_by_validation(self):
        block = _block(["a", "b"], [(["a"], "Un incendio afectó el acceso al aeropuerto."), (["b"], "Otro incendio afectó al barrio.")], tipo="hechos_relacionados")
        plan = self._plan([_story(block, [_asset("a", w=1280, h=960), _asset("b", w=1280, h=960)])])
        plan["stories"][0]["shots"][1]["media"]["note"] = "a"
        self.assertTrue(any("sobre el hecho" in e for e in v3.validate_plan(plan)))

    def test_related_without_alignment_falls_back_to_type(self):
        block = _block(["a", "b"], [(["a"], "Uno."), (["b"], "Dos.")], tipo="hechos_relacionados")
        plan = self._plan([_story(block, [_asset("a"), _asset("b")], align=False)])
        self.assertEqual(plan["stories"][0]["family"], "limited")
        self.assertIsNone(plan["stories"][0]["shots"][0]["media"])
        self.assertEqual(plan["captions"], [])

    def test_frames_are_contiguous_without_drift(self):
        stories = [_story(_block([f"n{i}"], [([f"n{i}"], "Una noticia de prueba con varias palabras para durar. Y una segunda oración.")]), [_asset(f"n{i}")]) for i in range(6)]
        plan = self._plan(stories)
        self.assertEqual(v3.validate_plan(plan), [])
        total_ms = sum((v3.LEAD_FIRST_MS if i == 0 else v3.LEAD_MS) + s.voice_ms + v3.GAP_MS for i, s in enumerate(stories))
        self.assertEqual(plan["outro"]["from"], v3.ms_to_frame(total_ms))
        self.assertEqual(plan["stories"][0]["from"], 0)

    def test_video_is_never_read_past_its_end_nor_looped(self):
        block = _block(["v"], [(["v"], "Una noticia larga con muchas palabras para que la toma sea más larga que el video disponible. Y otra oración más para seguir hablando del hecho.")])
        short = _asset("v", "video", 1080, 1920, duration_ms=4000)
        plan = self._plan([_story(block, [short])])
        self.assertEqual(v3.validate_plan(plan), [])
        reads = [(sh["media"]["sourceInFrames"], sh["durationInFrames"]) for sh in plan["stories"][0]["shots"] if sh["media"]]
        self.assertEqual(len(reads), 1)
        self.assertGreaterEqual(plan["stories"][0]["durationInFrames"], 120)

    def test_distinct_video_spans_are_used_without_overlap(self):
        block = _block(["v"], [(["v"], "Primera oración del hecho con detalles suficientes."), (["v"], "Segunda oración del hecho con más detalles para cortar.")])
        clip = _asset("v", "video", 1080, 1920, duration_ms=60000)
        plan = self._plan([_story(block, [clip])])
        spans = sorted(plan["ledger"][clip.id])
        for (a0, a1), (b0, _b1) in zip(spans, spans[1:]):
            self.assertLessEqual(a1, b0)
        self.assertEqual(v3.validate_plan(plan), [])

    def test_same_input_same_plan(self):
        mk = lambda: [_story(_block(["a"], [(["a"], "Una noticia de prueba. Con dos oraciones.")]), [_asset("a")])]
        self.assertEqual(json.dumps(self._plan(mk()), sort_keys=True), json.dumps(self._plan(mk()), sort_keys=True))

    def test_captions_stay_inside_their_story(self):
        stories = [_story(_block([f"n{i}"], [([f"n{i}"], "Una noticia con texto suficiente para dos subtítulos distintos.")]), [_asset(f"n{i}")]) for i in range(3)]
        plan = self._plan(stories)
        for c in plan["captions"]:
            s = plan["stories"][c["story"]]
            self.assertGreaterEqual(c["from"], s["from"])
            self.assertLessEqual(c["to"], s["from"] + s["durationInFrames"])

    def test_outro_is_brief(self):
        plan = self._plan([_story(_block(["a"], [(["a"], "Una noticia.")]), [_asset("a")])])
        self.assertLessEqual(plan["outro"]["durationInFrames"], 90)
        self.assertGreaterEqual(plan["outro"]["durationInFrames"], 45)

    def test_ineligible_media_never_reaches_a_shot(self):
        bad = _asset("a", check={"corresponde": "no", "tipo": "registro_del_hecho", "nitidez": 5})
        plan = self._plan([_story(_block(["a"], [(["a"], "Una noticia sin material propio.")]), [bad])])
        self.assertEqual(plan["stories"][0]["family"], "limited")
        self.assertEqual(len(plan["stories"][0]["rejected"]), 1)


class PortfolioTests(unittest.TestCase):
    def test_three_policiales_in_a_row_promote_comparable_alternative(self):
        mk = lambda sec, interes: {**_block(["x"], [(["x"], "Texto de prueba.")], seccion=sec), "relevancia": {"interes": interes, "novedad": 3, "impacto_local": 3, "utilidad": 3, "seguimiento": 3}}
        blocks = [mk("policiales", 5), mk("policiales", 5), mk("policiales", 5), mk("salud", 5)]
        order, notes = v3.order_portfolio(blocks, {})
        self.assertEqual([blocks[i]["seccion"] for i in order][:3], ["policiales", "policiales", "salud"])
        self.assertTrue(any("tres policiales" in n for n in notes))

    def test_no_promotion_when_alternative_is_much_less_important(self):
        mk = lambda sec, interes: {**_block(["x"], [(["x"], "Texto.")], seccion=sec), "relevancia": {"interes": interes, "novedad": interes, "impacto_local": interes, "utilidad": 3, "seguimiento": 3}}
        blocks = [mk("policiales", 5), mk("policiales", 5), mk("policiales", 5), mk("cultura", 1)]
        order, _ = v3.order_portfolio(blocks, {})
        self.assertEqual([blocks[i]["seccion"] for i in order], ["policiales"] * 3 + ["cultura"])


class CacheTests(unittest.TestCase):
    def test_new_voice_hash_invalidates_alignment_with_same_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for k in (1, 2):
                path = os.path.join(tmp, f"{k}.wav")
                with wave.open(path, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)
                    w.writeframes(bytes([k]) * 3200)
                paths.append(path)
            self.assertNotEqual(na.cache_key(paths[0], "texto"), na.cache_key(paths[1], "texto"))
            calls = []
            runner = lambda wav, hint: calls.append(wav) or [("texto", 0, 400, 1.0)]
            na.align_clip(paths[0], "texto", 500, cache_dir=tmp, runner=runner)
            na.align_clip(paths[0], "texto", 500, cache_dir=tmp, runner=runner)
            self.assertEqual(len(calls), 1)  # misma voz: caché
            na.align_clip(paths[1], "texto", 500, cache_dir=tmp, runner=runner)
            self.assertEqual(len(calls), 2)  # voz regenerada: se realinea

    def test_cached_tts_does_not_call_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def synth(text, dest):
                calls.append(text)
                with wave.open(dest, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)
                    w.writeframes(b"\0" * 3200)
                return 0.1

            counter = {}
            with mock.patch.object(nn, "media_duration", return_value=0.1):
                v3.cached_tts("Hola.", os.path.join(tmp, "a.wav"), os.path.join(tmp, "c"), synth, counter)
                v3.cached_tts("Hola.", os.path.join(tmp, "b.wav"), os.path.join(tmp, "c"), synth, counter)
            self.assertEqual(len(calls), 1)
            self.assertEqual(counter["tts"], 1)

    def test_aligner_missing_means_no_captions_not_fake_ones(self):
        with mock.patch.object(na, "aligner_status", return_value={"ok": False}), tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.wav")
            with open(path, "wb") as fh:
                fh.write(b"x")
            out = na.align_clip(path, "texto", 500)
        self.assertFalse(out.ok)
        self.assertEqual(out.tokens, [])


class RenderTests(unittest.TestCase):
    def test_headless_timeout_is_retried_once_other_errors_fail(self):
        timeout = mock.Mock(returncode=1, stderr="Timed out after 30000ms while setting up the headless browser.", stdout="")
        boom = mock.Mock(returncode=1, stderr="TypeError", stdout="")
        with mock.patch.object(v3, "_render_once", side_effect=[timeout, boom]) as run, mock.patch.object(v3.time, "sleep"):
            with self.assertRaises(RuntimeError):
                v3.render_v3("p.json", "out.mp4")
        self.assertEqual(run.call_count, 2)
        with mock.patch.object(v3, "_render_once", side_effect=[boom]) as run:
            with self.assertRaises(RuntimeError):
                v3.render_v3("p.json", "out.mp4")
        self.assertEqual(run.call_count, 1)


class RunnerV3Tests(unittest.TestCase):
    def test_v3_flag_routes_script_and_build_and_keeps_publication_off(self):
        from meta import run_nightly_newscast as run

        env = {"NIGHTLY_NEWSCAST_ENABLED": "true", "NIGHTLY_NEWSCAST_VISUAL": "v3", "NIGHTLY_NEWSCAST_PUBLISH": "false"}
        cands = [_cand(f"n{i}", "T", "B") for i in range(5)]
        script = v3.ScriptV3(blocks=[_block(["n1"], [(["n1"], "Texto.")])])
        edition = nn.Edition(day=date(2026, 10, 30), video_path="x.mp4", caption="c", script=script, blocks=script.blocks, folder="f")
        with mock.patch.dict(os.environ, env), mock.patch.object(nn, "load_state", return_value={}), mock.patch.object(nn, "note_attempt"), \
             mock.patch.object(nn, "mark_day"), mock.patch.object(v3, "collect_candidates_v3", return_value=(cands, {"candidates": len(cands)})), \
             mock.patch.object(v3, "prescreen_media", return_value=(cands, {"kept": len(cands)})) as screen, \
             mock.patch.object(v3, "write_script_v3", return_value=(script, [])) as write, \
             mock.patch.object(v3, "build_edition_v3", return_value=edition) as build, \
             mock.patch.object(nn, "write_script") as v2_write, mock.patch.object(nn, "publish") as publish:
            result = run.main([])
        self.assertTrue(screen.called and write.called and build.called)
        self.assertFalse(v2_write.called)
        self.assertFalse(publish.called)
        self.assertEqual(result.status.value, "success")


if __name__ == "__main__":
    unittest.main()
