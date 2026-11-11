"""Noticiero V5 (2026-11-01): apertura en frío, voz ajustada sin volver a
sintetizar, tomas por frase con mapa del nomenclador oficial, subtítulos
cinéticos, caption sin fuentes y publicación con portada y ubicación. Sin
red, sin IA, sin render."""
from __future__ import annotations

import array
import json
import math
import os
import tempfile
import unittest
import wave
from datetime import date
from unittest import mock

from utils import newscast_align as na
from utils import newscast_v3 as v3
from utils import newscast_v5 as v5
from utils import nightly_newscast as nn
from utils import social_caption
from tests.test_newscast_v3 import _asset, _block, _story, _tokens


def _wav(path: str, segments: list[tuple[str, int]], rate: int = 48000) -> None:
    """WAV de prueba: ('tono'|'silencio', ms)."""
    data = array.array("h")
    for kind, ms in segments:
        n = int(rate * ms / 1000)
        if kind == "tono":
            data.extend(int(9000 * math.sin(2 * math.pi * 220 * k / rate)) for k in range(n))
        else:
            data.extend([0] * n)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())


class GeoTests(unittest.TestCase):
    def test_only_exact_localities_or_unambiguous_aliases(self):
        self.assertEqual(v5.locate("Chilecito")["name"], "Chilecito")
        self.assertEqual(v5.locate("Sanagasta")["name"], "Villa Sanagasta")
        self.assertEqual(v5.locate("capital")["name"], "La Rioja")
        self.assertEqual(v5.locate("la localidad de Milagro")["name"], "Milagro")
        for place in ("barrio Independencia", "Aeropuerto", "Santa Rosa 2", "calle Santa Fe", ""):
            self.assertIsNone(v5.locate(place), place)

    def test_points_fall_inside_the_view(self):
        geo = v5._geo()
        for place in geo["places"].values():
            self.assertTrue(0 <= place["x"] <= geo["view"]["w"] and 0 <= place["y"] <= geo["view"]["h"], place)


class VoiceTests(unittest.TestCase):
    def test_long_pauses_are_shortened_by_punctuation_and_words_keep_their_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "a.wav"), os.path.join(tmp, "b.wav")
            # "Uno dos. Tres": pausa de 900 ms tras el punto, 500 ms entre palabras.
            _wav(src, [("silencio", 300), ("tono", 400), ("silencio", 500), ("tono", 400), ("silencio", 900), ("tono", 400), ("silencio", 400)])
            tokens = [{"text": "Uno", "start_ms": 300, "end_ms": 700, "method": "asr"},
                      {"text": "dos.", "start_ms": 1200, "end_ms": 1600, "method": "asr"},
                      {"text": "Tres", "start_ms": 2500, "end_ms": 2900, "method": "asr"}]
            out = v5.tighten_voice(src, dst, tokens, target_ppm=1, max_factor=1.08)
            self.assertEqual(out.factor, 1.0)
            starts = [t["start_ms"] for t in out.tokens]
            self.assertEqual(starts, sorted(starts))
            gap_word = out.tokens[1]["start_ms"] - out.tokens[0]["end_ms"]
            gap_sentence = out.tokens[2]["start_ms"] - out.tokens[1]["end_ms"]
            self.assertLessEqual(gap_word, v5.PAUSE_CAPS["word"] + 40)
            self.assertLessEqual(gap_sentence, v5.PAUSE_CAPS["sentence"] + 40)
            self.assertGreater(gap_sentence, gap_word)  # la pausa de punto sigue siendo más larga
            self.assertLess(out.ms, 3300)
            self.assertTrue(all(t["end_ms"] <= out.ms for t in out.tokens))

    def test_slow_take_is_stretched_with_a_capped_factor(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "a.wav"), os.path.join(tmp, "b.wav")
            _wav(src, [("tono", 3000)])
            tokens = [{"text": f"w{k}", "start_ms": k * 600, "end_ms": k * 600 + 500, "method": "asr"} for k in range(5)]

            def fake_stretch(a, b, factor):
                rate, data = v5._read_pcm(a)
                v5._write_pcm(b, rate, data[: int(len(data) / factor)])

            with mock.patch.object(v5, "_stretch", side_effect=fake_stretch) as stretch:
                out = v5.tighten_voice(src, dst, tokens, target_ppm=400, max_factor=1.08)
            self.assertAlmostEqual(stretch.call_args[0][2], 1.08)
            self.assertEqual(out.factor, 1.08)
            self.assertLess(out.tokens[-1]["start_ms"], 2400)


class FramingTests(unittest.TestCase):
    def test_mode_by_resolution_and_aspect(self):
        self.assertEqual(v5.base_mode(_asset("a", w=1400, h=787)), "band")
        self.assertEqual(v5.base_mode(_asset("b", w=700, h=446)), "card")
        self.assertEqual(v5.base_mode(_asset("c", w=900, h=1600)), "full")
        self.assertEqual(v5.base_mode(_asset("d", w=1400, h=1053)), "full")
        text = _asset("e", w=1400, h=1053, check={"corresponde": "si", "tipo": "registro_del_hecho", "zona_texto": "arriba", "nitidez": 4})
        self.assertNotEqual(v5.base_mode(text), "full")

    def test_detail_never_exceeds_the_upscale_limit(self):
        for w, h in ((1400, 787), (700, 446), (900, 1600), (1400, 1053), (500, 300)):
            a = _asset("x", w=w, h=h)
            mode = v5.base_mode(a)
            k = v5.detail_zoom(a, mode)
            base = {"full": max(1080 / w, 1920 / h), "band": v5.BAND_H / h, "card": v5.CARD_W / w}[mode]
            self.assertTrue(k == 0 or base * k <= v5.DETAIL_MAX_UPSCALE + 1e-6, (w, h, mode, k))


def _plan(blocks_assets, style="headline"):
    stories = [_story(b, a) for b, a in blocks_assets]
    return v5.build_plan_v5(stories, outro_voice="tmp/x/outro.wav", outro_ms=3000, outro_tokens=_tokens("Lo que pasa en La Rioja, lo sabés acá. Seguinos."),
                            date_label="SÁBADO 31 DE OCTUBRE", style=style), stories


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.lead = _block(["n1"], [(["n1"], "El viento Zonda reavivó un incendio de pastizales que afectó cuatro hectáreas cerca del aeropuerto. Un incendio destruyó un local comercial en Sanagasta.", "Sanagasta", "", "4 hectáreas")],
                           titulo="Zonda reavivó un incendio cerca del aeropuerto")
        self.robo = _block(["n2"], [(["n2"], "Un adolescente de 16 años fue demorado en Chilecito tras intentar robar una motocicleta. El joven fue interceptado por la policía mientras escapaba.", "Chilecito")],
                           titulo="Demoran a un menor por intentar robar una moto")
        self.choque = _block(["n3"], [(["n3"], "Dos mujeres sufrieron fracturas al chocar su motocicleta contra un auto estacionado en el barrio Independencia.", "barrio Independencia")],
                             titulo="Dos mujeres con fracturas tras chocar en moto")
        self.assets = {n: [_asset(n, w=1400, h=787)] for n in ("n1", "n2", "n3")}

    def build(self, style="headline"):
        return _plan([(self.lead, self.assets["n1"]), (self.robo, self.assets["n2"]), (self.choque, self.assets["n3"])], style)

    def test_plan_is_valid_and_opens_cold(self):
        plan, _ = self.build()
        self.assertEqual(v5.validate_plan_v5(plan), [])
        first = plan["stories"][0]
        self.assertEqual(first["from"], 0)
        self.assertTrue(first["lead"])
        self.assertEqual(first["wipe"], "cut")
        self.assertLessEqual(plan["voices"][0]["from"], 2)  # la voz del hecho empieza en el frame 2
        self.assertGreaterEqual(first["compactAt"], v3.ms_to_frame(v5.LEAD_HEADLINE_MS))
        self.assertEqual(plan["sfx"][0]["from"], 0)
        self.assertEqual(plan["opening"]["style"], "headline")

    def test_stories_are_cut_into_several_shots_on_real_pauses(self):
        plan, _ = self.build()
        for s in plan["stories"]:
            if s["durationInFrames"] >= 5 * 30:
                self.assertGreaterEqual(len(s["shots"]), 2, s["headline"])
            for shot in s["shots"]:
                self.assertGreaterEqual(shot["durationInFrames"], int(v5.SHOT_MIN_MS / 1000 * 30) - 2)

    def test_every_photo_is_presented_wide_before_its_detail(self):
        two = [_asset("n2", w=1400, h=787), _asset("n2", w=1400, h=787, sha="otra".ljust(64, "1"))]
        plan, _ = _plan([(self.lead, self.assets["n1"]), (self.robo, two)])
        seen = set()
        for shot in plan["stories"][1]["shots"]:
            if shot["kind"] != "image":
                continue
            if shot["framing"] == "detail":
                self.assertIn(shot["media"]["id"], seen)
            seen.add(shot["media"]["id"])
        self.assertEqual(len(seen), 2)

    def test_map_only_for_localities_of_the_gazetteer(self):
        plan, _ = self.build()
        maps = {s["headline"]: [sh["place"]["name"] for sh in s["shots"] if sh["kind"] == "map"] for s in plan["stories"]}
        self.assertEqual(maps["Demoran a un menor por intentar robar una moto"], ["Chilecito"])
        self.assertEqual(maps["Dos mujeres con fracturas tras chocar en moto"], [])
        lead_maps = [sh for sh in plan["stories"][0]["shots"] if sh["kind"] == "map"]
        for sh in lead_maps:  # nunca tapa el titular del gancho
            self.assertGreaterEqual(sh["from"], v3.ms_to_frame(v5.LEAD_HEADLINE_MS))

    def test_kinetic_captions_are_short_and_mark_at_most_one_word(self):
        plan, _ = self.build()
        self.assertTrue(plan["captions"])
        for c in plan["captions"]:
            self.assertLessEqual(len(c["words"]), 6)
            self.assertLessEqual(sum(1 for w in c["words"] if w["key"]), 1)
            self.assertLessEqual(c["to"], plan["outro"]["from"])
        marked = [w["text"] for c in plan["captions"] for w in c["words"] if w["key"]]
        self.assertIn("Chilecito", " ".join(marked))

    def test_transitions_rotate_and_brand_marks_the_middle(self):
        many = [(_block([f"n{k}"], [([f"n{k}"], "Un hecho policial ocurrió en la ciudad. La policía investiga lo que pasó.")], titulo=f"Hecho {k}"),
                 [_asset(f"n{k}", w=1400, h=787)]) for k in range(6)]
        plan, _ = _plan(many)
        wipes = [s["wipe"] for s in plan["stories"]]
        self.assertEqual(wipes[0], "cut")
        self.assertEqual(wipes.count("brand"), 1)
        self.assertEqual(v5.validate_plan_v5(plan), [])

    def test_validation_catches_foreign_media_and_overflow(self):
        plan, _ = self.build()
        plan["stories"][1]["shots"][0]["media"]["note"] = "n9"
        plan["stories"][2]["inserts"].append({"kind": "data", "text": "9 heridos", "value": "", "at": 5, "until": 10_000})
        errors = v5.validate_plan_v5(plan)
        self.assertTrue(any("recurso de n9" in e for e in errors), errors)
        self.assertTrue(any("fuera de su historia" in e for e in errors), errors)


class InsertRulesTests(unittest.TestCase):
    def test_ages_are_never_data_nor_highlighted(self):
        block = _block(["n1"], [(["n1"], "Un adolescente de 16 años fue demorado en Chilecito tras intentar robar una motocicleta. El joven fue interceptado por la policía.", "Chilecito", "", "16 años")],
                       titulo="Demoran a un menor por intentar robar una moto")
        plan, _ = _plan([(block, [_asset("n1", w=1400, h=787)])])
        self.assertFalse([i for i in plan["stories"][0]["inserts"] if "año" in i["text"].lower()])
        marked = [w["text"] for c in plan["captions"] for w in c["words"] if w["key"]]
        self.assertNotIn("16", marked)

    def test_route_numbers_are_not_highlighted_but_quantities_are(self):
        block = _block(["n1"], [(["n1"], "Dos mujeres resultaron heridas en la ruta nacional 77 cerca de Milagro esta mañana.", "Milagro")],
                       titulo="Heridas en un choque en Milagro")
        plan, _ = _plan([(block, [_asset("n1", w=1400, h=787)])])
        marked = [w["text"].strip(".,") for c in plan["captions"] for w in c["words"] if w["key"]]
        self.assertNotIn("77", marked)
        self.assertIn("Dos", marked)

    def test_data_waits_for_the_headline_and_never_overlaps_the_map(self):
        block = _block(["n1"], [(["n1"], "Bomberos combatieron un incendio que afectó cuatro hectáreas en Chilecito durante toda la tarde. Las dotaciones trabajaron hasta la noche para controlar el fuego.", "Chilecito", "", "4 hectáreas")],
                       titulo="Incendio de cuatro hectáreas en Chilecito")
        lead = _block(["n0"], [(["n0"], "Un hecho policial ocurrió en la ciudad y la policía investiga lo que pasó durante la madrugada.")], titulo="Hecho principal")
        plan, _ = _plan([(lead, [_asset("n0", w=1400, h=787)]), (block, [_asset("n1", w=1400, h=787)])])
        story = plan["stories"][1]
        maps = [(sh["from"], sh["from"] + sh["durationInFrames"]) for sh in story["shots"] if sh["kind"] == "map"]
        for item in story["inserts"]:
            self.assertGreaterEqual(item["at"], story["compactAt"])
            for a, b in maps:
                self.assertFalse(item["at"] < b and item["until"] > a, (item, maps))
        for a, _b in maps:
            self.assertLessEqual(story["compactAt"] + 12, a)  # el titular terminó de subir


class CaptionTests(unittest.TestCase):
    def blocks(self, n=7):
        out = []
        for k in range(n):
            b = _block([f"n{k}"], [([f"n{k}"], f"Un hecho número {k} ocurrió con consecuencias para los vecinos del lugar. La policía investiga.", "Chilecito" if k % 2 else "")],
                       titulo=f"Hecho {k}")
            b["lugar"] = "Chilecito" if k % 2 else ""
            out.append(b)
        return out

    def test_informative_short_and_without_sources(self):
        text = v5.caption_v5(date(2026, 10, 31), self.blocks())
        self.assertLess(len(text), 2200)
        self.assertTrue(text.startswith("Un hecho número 0"))
        self.assertEqual(text.count("#"), 4)
        for banned in ("Fuente", "Información e imágenes", "Fénix", "Nueva Rioja", "Medios Rioja", "Tiempo Popular"):
            self.assertNotIn(banned, text)
        self.assertFalse(any(ord(ch) > 0x2600 for ch in text), "sin emojis")
        self.assertIn("Chilecito: un hecho", text)

    def test_long_editions_stay_under_the_limit(self):
        blocks = self.blocks(40)
        text = v5.caption_v5(date(2026, 10, 31), blocks)
        self.assertLessEqual(len(text), 2200)
        self.assertTrue(text.endswith(v5.HASHTAGS_V5))

    def test_complete_caption_is_not_tagged_twice(self):
        item = {"texto_instagram": "Texto.\n\n#LaRioja #NoticiasLaRioja #Policiales #LaVozRiojana", "caption_complete": True, "locality": "La Rioja"}
        with mock.patch.dict(os.environ, {"IG_CAPTION_FROM_WEB_ENABLED": "false"}):
            self.assertEqual(social_caption.build_instagram_caption(item), item["texto_instagram"])
            plain = social_caption.build_instagram_caption({**item, "caption_complete": False})
        self.assertGreater(plain.count("#"), 4)


class PublishTests(unittest.TestCase):
    def test_cover_location_and_complete_caption_reach_instagram(self):
        from meta import fb_client, ig_client
        from utils import r2_storage

        with tempfile.TemporaryDirectory() as tmp:
            cover = os.path.join(tmp, "portada.jpg")
            with open(cover, "wb") as fh:
                fh.write(b"jpg")
            edition = nn.Edition(day=date(2026, 10, 31), video_path=os.path.join(tmp, "v.mp4"), caption="Texto #LaRioja", script=None, blocks=[],
                                 folder=tmp, cover_path=cover, caption_complete=True)
            ok = mock.Mock(ok=True, external_id="1", details={})
            uploads = iter([("https://r2/v.mp4", "k1"), ("https://r2/portada.jpg", "k2")])
            with mock.patch.object(nn, "load_state", return_value={}), mock.patch.object(nn, "mark_day"), \
                    mock.patch.object(r2_storage, "upload_temp", side_effect=lambda *a, **k: next(uploads)), \
                    mock.patch.object(ig_client, "post_reel_video_to_instagram", return_value=ok) as ig, \
                    mock.patch.object(fb_client, "post_reel_video_to_facebook", return_value=ok):
                outcome = nn.publish(edition, instagram=True, facebook=False)
        self.assertEqual(outcome["ig"], "success")
        item = ig.call_args[0][0]
        self.assertEqual(item["cover_url"], "https://r2/portada.jpg")
        self.assertEqual(item["locality"], "La Rioja")
        self.assertTrue(item["caption_complete"])

    def test_v4_editions_publish_as_before(self):
        from meta import ig_client
        from utils import r2_storage

        edition = nn.Edition(day=date(2026, 10, 31), video_path="v.mp4", caption="Texto", script=None, blocks=[], folder=".")
        ok = mock.Mock(ok=True, external_id="1", details={})
        with mock.patch.object(nn, "load_state", return_value={}), mock.patch.object(nn, "mark_day"), \
                mock.patch.object(r2_storage, "upload_temp", return_value=("https://r2/v.mp4", "k1")), \
                mock.patch.object(ig_client, "post_reel_video_to_instagram", return_value=ok) as ig:
            nn.publish(edition, instagram=True, facebook=False)
        item = ig.call_args[0][0]
        self.assertNotIn("cover_url", item)
        self.assertNotIn("locality", item)
        self.assertEqual(item["thumb_offset_ms"], 6000)


class ScriptTests(unittest.TestCase):
    def test_v5_prompt_and_limits_are_used(self):
        seen = {}

        def completion(messages, **kw):
            seen["system"] = messages[0]["content"]
            return '{"bloques": []}'

        cand = nn.Candidate(id="n1", title="Choque en Chilecito", section="policiales", source="fenix_locales", web_url="u", published_at=0, body="Choque.")
        v5.write_script_v5([cand], completion=completion)
        self.assertEqual(seen["system"], v5.SCRIPT_PROMPT_V5)
        self.assertIn("No inventes datos", v5.SCRIPT_PROMPT_V5)
        self.assertIn("Primero qué pasó", v5.SCRIPT_PROMPT_V5)

    def test_word_budget_feedback_uses_v5_numbers(self):
        cands = [nn.Candidate(id="n1", title="Incendio en Chilecito", section="policiales", source="fenix_locales", web_url="u", published_at=0,
                              body=" ".join(["El incendio destruyó una casa en Chilecito."] * 40))]
        text = " ".join(["El incendio destruyó una casa en Chilecito."] * 3)
        raw = {"bloques": [{"ids": ["n1"], "titulo": "Incendio en Chilecito", "tramos": [{"ids": ["n1"], "texto": text}]}] * 1}
        _s, warnings = v3.validate_script_v3(raw, cands, words=(140, 210, 20), block_words=v5.SCRIPT_BLOCK_WORDS_V5)
        self.assertTrue(any("155–210" in w for w in warnings), warnings)


def _wav_ms(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


class EditionTests(unittest.TestCase):
    """Armado completo con proveedores falsos: sin red, sin TTS, sin render."""

    def test_build_edition_v5_end_to_end_with_fallback_voice(self):
        from PIL import Image

        texts = {
            "n1": "Un incendio destruyó un comercio en Chilecito. Los bomberos trabajaron toda la tarde.",
            "n2": "Dos mujeres resultaron heridas al chocar en moto en Milagro. Fueron trasladadas al hospital.",
            "n3": "Robaron cables de un pozo de riego en Vichigasta. La policía investiga el hecho.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            cands = []
            for k, (note, text) in enumerate(texts.items()):
                photo = os.path.join(tmp, f"{note}.jpg")
                Image.new("RGB", (1400, 787), (40 * k, 60, 90)).save(photo)
                cands.append(nn.Candidate(id=note, title=text.split(".")[0], section="policiales", source="fenix_locales", web_url=f"https://x/{note}",
                                          published_at=0, body=text, photo_path=photo))
            blocks = []
            for note, text in texts.items():
                place = next(p for p in ("Chilecito", "Milagro", "Vichigasta") if p in text)
                b = _block([note], [([note], text, place)], titulo=text.split(".")[0][:46])
                b["lugar"] = place
                blocks.append(b)
            script = v3.ScriptV3(blocks=blocks)

            def tts(text, dest):
                _wav(dest, [("tono", 300 * len(text.split())), ("silencio", 200)])

            def align(wav, text, clip_ms, cache_dir=None):
                return na.Alignment(ok=True, tokens=_tokens(text, step=250), coverage=1.0, critical_ok=True)

            def render(props, out):
                with open(props, encoding="utf-8") as fh:
                    self.plan = json.load(fh)
                open(out, "wb").close()

            def fake_run(cmd, *a, **k):
                open(cmd[-1], "wb").close()  # loudnorm: el último argumento es la salida
                return mock.Mock(returncode=0)

            real_tighten = v5.tighten_voice
            calls = {"n": 0}

            def flaky_tighten(*a, **k):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise wave.Error("formato desconocido")
                return real_tighten(*a, **k)

            providers = {"tts": tts, "align": align, "vision": lambda *a, **k: {"corresponde": "si", "tipo": "registro_del_hecho", "zona_texto": "ninguna", "nitidez": 4},
                         "render": render, "render_cover": lambda props, out: open(out, "wb").close(), "inspect": False, "no_library": True,
                         "cache_dir": os.path.join(tmp, "cache")}
            env = {"LVR_OUTPUT_DIR": os.path.join(tmp, "out"), "LVR_DATA_DIR": os.path.join(tmp, "data"), "NIGHTLY_NEWSCAST_MUSIC": "false"}
            with mock.patch.dict(os.environ, env), mock.patch.object(nn, "media_duration", side_effect=_wav_ms), \
                    mock.patch.object(v5.subprocess, "run", side_effect=fake_run), mock.patch.object(v3, "ensure_tick"), \
                    mock.patch.object(v5, "ensure_ping"), mock.patch.object(v5, "tighten_voice", side_effect=flaky_tighten):
                edition = v5.build_edition_v5(date(2026, 10, 31), cands, script, providers=providers)
            self.assertTrue(edition.caption_complete)
            self.assertTrue(edition.cover_path.endswith("portada.jpg"))
            self.assertEqual(v5.validate_plan_v5(self.plan), [])
            self.assertEqual(self.plan["stories"][0]["ids"], ["n1"])  # abre el bloque que el guion puso primero
            with open(os.path.join(edition.folder, "visual_plan.json"), encoding="utf-8") as fh:
                saved = json.load(fh)
            self.assertTrue(any("voz sin ajuste" in d for d in saved["diagnostics"]))
            self.assertEqual(len(saved["voice"]), 3)
            with open(os.path.join(edition.folder, "guion.json"), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["version"], "v5")


class RunnerV5Tests(unittest.TestCase):
    def test_v5_flag_routes_to_the_v5_script_and_builder(self):
        from meta import run_nightly_newscast as run

        env = {"NIGHTLY_NEWSCAST_ENABLED": "true", "NIGHTLY_NEWSCAST_VISUAL": "v5", "NIGHTLY_NEWSCAST_PUBLISH": "false"}
        cands = [nn.Candidate(id=f"n{i}", title="T", section="policiales", source="fenix_locales", web_url="u", published_at=0, body="B") for i in range(5)]
        script = v3.ScriptV3(blocks=[_block(["n1"], [(["n1"], "Texto.")])])
        edition = nn.Edition(day=date(2026, 11, 1), video_path="x.mp4", caption="c", script=script, blocks=script.blocks, folder="f",
                             cover_path="f/portada.jpg", caption_complete=True)
        with mock.patch.dict(os.environ, env), mock.patch.object(nn, "load_state", return_value={}), mock.patch.object(nn, "note_attempt"), \
                mock.patch.object(nn, "mark_day"), mock.patch.object(v3, "collect_candidates_v3", return_value=(cands, {"candidates": 5})), \
                mock.patch.object(v3, "prescreen_media", return_value=(cands, {"kept": 5})), \
                mock.patch.object(v5, "write_script_v5", return_value=(script, [])) as write5, \
                mock.patch.object(v5, "build_edition_v5", return_value=edition) as build5, \
                mock.patch.object(v3, "write_script_v3") as write3, mock.patch.object(v3, "build_edition_v3") as build3, \
                mock.patch.object(nn, "publish") as publish:
            result = run.main([])
        self.assertTrue(write5.called and build5.called)
        self.assertFalse(write3.called or build3.called or publish.called)
        self.assertEqual(result.status.value, "success")


class CueTests(unittest.TestCase):
    def test_defaults_unchanged_and_short_groups_available(self):
        toks = _tokens("Un adolescente de 16 años fue demorado tras intentar robar una motocicleta y agredir a su dueña.")
        long_cues = na.build_cues(toks)
        short_cues = na.build_cues(toks, max_words=4, max_chars=24, min_ms=420, hold_gap_ms=300)
        self.assertTrue(all(len(c["words"]) >= 3 for c in long_cues[:-1]))
        self.assertGreater(len(short_cues), len(long_cues))
        self.assertTrue(all(len(c["text"]) <= 32 for c in short_cues))


if __name__ == "__main__":
    unittest.main()
