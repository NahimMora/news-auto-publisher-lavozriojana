"""Noticiero policial V4 (2026-10-31): biblioteca de notas propias, gancho
determinista, control visual por cuadros, sellos de datos seguros, barrera de
agrupamiento y cierre sin subtítulos. Sin red, sin IA, sin render."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from utils import newscast_align as na
from utils import newscast_library as lib
from utils import newscast_v3 as v3
from utils import nightly_newscast as nn
from tests.test_newscast_v3 import _asset, _block, _story, _tokens


def _cand(cid, title, body="Texto de la nota con datos suficientes.", localities=None):
    return nn.Candidate(id=cid, title=title, section="policiales", source="fenix_locales", web_url=f"https://lavozriojana.com/noticias/{cid}",
                        published_at=time.time(), body=body, localities=list(localities or []))


class GroupingTests(unittest.TestCase):
    def test_same_event_needs_place_or_two_title_words(self):
        moto_a = _cand("a", "Dos jóvenes heridas tras caer de una moto en el centro")
        moto_b = _cand("b", "Dos jóvenes heridas tras caer de una moto en la zona sur")
        sanagasta = _cand("c", "Incendio en Sanagasta: destruyó el Polirrubro Hilda")
        zonda = _cand("d", "El viento Zonda reavivó un incendio cerca del Aeropuerto")
        acceso = _cand("e", "Incendio de pastizales en el acceso al aeropuerto")
        self.assertTrue(v3.same_event_ok([moto_a, moto_b]))
        self.assertFalse(v3.same_event_ok([sanagasta, zonda]))
        self.assertTrue(v3.same_event_ok([zonda, acceso]))
        self.assertTrue(v3.same_event_ok([_cand("f", "Choque", localities=["Chilecito"]), _cand("g", "Vuelco", localities=["Chilecito"])]))

    def test_grouping_of_different_events_is_sent_back(self):
        cands = [_cand("n1", "Incendio en Sanagasta: destruyó el Polirrubro Hilda", "Un incendio destruyó el Polirrubro Hilda en Sanagasta."),
                 _cand("n2", "El viento Zonda reavivó un incendio cerca del Aeropuerto", "El viento reavivó un incendio cerca del aeropuerto.")]
        raw = {"bloques": [{"ids": ["n1", "n2"], "seccion": "policiales", "tipo": "hecho", "titulo": "Incendio en Sanagasta",
                            "tramos": [{"ids": ["n1", "n2"], "texto": "Un incendio destruyó el Polirrubro Hilda."}]}]}
        _script, warnings = v3.validate_script_v3(raw, cands)
        self.assertTrue(any("no parecen el mismo hecho" in w for w in warnings), warnings)

    def test_court_seat_is_not_the_place_of_the_event(self):
        note = _cand("n1", "Liberaron a una mujer acusada en Milagro", "La Cámara en lo Criminal de Chamical dictó la falta de mérito. La causa sigue en los tribunales de Chamical.")
        self.assertTrue(v3._court_seat_only("Chamical", [note]))
        self.assertFalse(v3._court_seat_only("Milagro", [note]))


class VisionMergeTests(unittest.TestCase):
    def test_per_frame_answer_is_merged_into_one_check(self):
        merged = v3.merge_frame_checks([
            {"corresponde": "dudoso", "tipo": "estudio_o_entrevista", "nitidez": 4},
            {"corresponde": "si", "tipo": "registro_del_hecho", "foco_x": 0.4, "nitidez": 4, "zona_texto": "abajo", "texto_incrustado": "INCENDIO"},
            {"corresponde": "si", "tipo": "registro_del_hecho", "foco_x": 0.6, "nitidez": 5},
        ])
        self.assertEqual(merged["corresponde"], "si")
        self.assertEqual(merged["cuadros_utiles"], [1, 2])
        self.assertEqual(merged["tipo"], "registro_del_hecho")
        self.assertEqual(merged["zona_texto"], "abajo")
        self.assertAlmostEqual(merged["foco_x"], 0.5)

    def test_frames_of_another_event_stay_rejected(self):
        merged = v3.merge_frame_checks([{"corresponde": "no", "texto_incrustado": "ALLANAMIENTOS EN ZONA NORTE"}] * 3)
        self.assertEqual(merged["corresponde"], "no")
        self.assertEqual(merged["cuadros_utiles"], [])

    def test_usable_range_starts_at_first_verified_frame(self):
        lo, hi = v3.usable_range({"cuadros_utiles": [1, 2, 3]}, 60000)
        self.assertEqual(lo, int(60000 * (0.06 + 0.88 * 1 / 4)))
        self.assertLessEqual(hi, 60000)
        self.assertEqual(v3.usable_range({"cuadros_utiles": []}, 60000), (0, 0))


class HookTests(unittest.TestCase):
    def test_hook_uses_short_titles_of_events_with_images_video_first(self):
        mk = lambda i, interes, corto: {**_block([i], [([i], "Texto del hecho.")], titulo=f"Titular {i}"), "titulo_corto": corto,
                                        "relevancia": {"interes": interes, "novedad": 3, "impacto_local": 3, "utilidad": 3, "seguimiento": 3}}
        blocks = [mk("a", 5, "Droga en el penal"), mk("b", 4, "Incendio en Sanagasta"), mk("c", 4, "Detenida por estafas"), mk("d", 3, "Choque en la ruta")]
        assets = {"a": [], "b": [_asset("b", "video", 1080, 1920, duration_ms=30000)], "c": [_asset("c")], "d": [_asset("d")]}
        hook = v3.derive_hook(blocks, assets)
        self.assertEqual([h["texto"] for h in hook], ["Incendio en Sanagasta.", "Detenida por estafas.", "Choque en la ruta."])
        order, _ = v3.order_police(blocks, hook, {})
        self.assertEqual([blocks[i]["ids"][0] for i in order][:3], ["b", "c", "d"])

    def test_intro_shows_each_phrase_with_its_own_event_media(self):
        frases = [{"ids": ["b"], "texto": "Incendio en Sanagasta.", "assets": [_asset("b")]},
                  {"ids": ["c"], "texto": "Detenida por estafas.", "assets": [_asset("c")]}]
        text = " ".join(f["texto"] for f in frases)
        intro = v3.IntroInput(voice_file="tmp/x/h.wav", voice_ms=3000, tokens=_tokens(text), frases=frases, align_ok=True)
        stories = [_story(_block(["b"], [(["b"], "Un incendio destruyó un comercio.")]), [_asset("b")])]
        plan = v3.build_plan(stories, outro_voice="tmp/x/o.wav", outro_ms=2500, date_label="X", intro=intro)
        beats = plan["intro"]["beats"]
        self.assertEqual([b["shot"]["media"]["note"] for b in beats], ["b", "c"])
        self.assertEqual(plan["stories"][0]["from"], plan["intro"]["durationInFrames"])
        self.assertLessEqual(plan["intro"]["durationInFrames"], 7 * 30)
        self.assertEqual(v3.validate_plan(plan), [])
        beats[1]["shot"]["media"]["note"] = "b"
        self.assertTrue(any("gancho" in e for e in v3.validate_plan(plan)))


class EmphasisTests(unittest.TestCase):
    def test_place_count_and_tag_appear_when_spoken(self):
        block = _block(["a"], [(["a"], "Dos jóvenes resultaron heridas en Chilecito y fueron trasladadas al hospital local tras un choque.", "Chilecito")])
        items = v3.detect_emphasis(block, _tokens(block["locucion"]), 200, 9000)
        kinds = {i["kind"]: i for i in items}
        self.assertEqual(kinds["count"]["value"], "2")
        self.assertEqual(kinds["count"]["text"], "JÓVENES")
        self.assertIn("place", kinds)
        self.assertEqual(kinds["tag"]["text"], "CHOQUE")
        self.assertEqual(sorted(i["atMs"] for i in items), [i["atMs"] for i in items])

    def test_no_keyword_tag_on_portraits_judicial_or_repeated(self):
        block = _block(["a"], [(["a"], "La Justicia procesó a un hombre por el robo de una obra.")], tipo="judicial")
        plan = v3.build_plan([_story(block, [_asset("a")])], outro_voice="", outro_ms=2000, date_label="X")
        self.assertFalse([e for e in plan["stories"][0]["emphasis"] if e["kind"] == "tag"])
        portrait = _asset("p", check={"corresponde": "si", "tipo": "retrato", "persona_primer_plano": True, "nitidez": 5})
        block = _block(["p"], [(["p"], "Detuvieron a un hombre por un robo en una obra.")])
        plan = v3.build_plan([_story(block, [portrait])], outro_voice="", outro_ms=2000, date_label="X")
        self.assertFalse([e for e in plan["stories"][0]["emphasis"] if e["kind"] == "tag"])
        fires = [_story(_block([f"i{k}"], [([f"i{k}"], "Un incendio afectó un terreno baldío durante la tarde.")]), [_asset(f"i{k}")]) for k in range(3)]
        plan = v3.build_plan(fires, outro_voice="", outro_ms=2000, date_label="X")
        tags = [e["text"] for s in plan["stories"] for e in s["emphasis"] if e["kind"] == "tag"]
        self.assertEqual(tags, ["INCENDIO"])

    def test_adult_face_is_allowed_minor_and_sensitive_are_not(self):
        face = {"corresponde": "si", "tipo": "retrato", "persona_primer_plano": True, "nitidez": 5}
        self.assertTrue(v3.assess(v3.Asset("a", "image", "x", "", 1080, 1350, sha="a" * 64, check=dict(face)), policial=True, sensitive=False).eligible)
        self.assertFalse(v3.assess(v3.Asset("a", "image", "x", "", 1080, 1350, sha="b" * 64, check=dict(face)), policial=True, sensitive=True).eligible)
        minor = {**face, "menor_identificable": True}
        self.assertFalse(v3.assess(v3.Asset("a", "image", "x", "", 1080, 1350, sha="c" * 64, check=minor), policial=False, sensitive=False).eligible)


class OutroTests(unittest.TestCase):
    def test_outro_has_no_captions_and_shows_spoken_lines(self):
        stories = [_story(_block(["a"], [(["a"], "Una noticia con texto suficiente para subtítulos.")]), [_asset("a")])]
        outro_tokens = _tokens(v3.OUTRO_TEXT_V3)
        plan = v3.build_plan(stories, outro_voice="tmp/x/o.wav", outro_ms=3000, date_label="X", outro_tokens=outro_tokens)
        self.assertTrue(all(c["to"] <= plan["outro"]["from"] for c in plan["captions"]))
        self.assertEqual([l["text"] for l in plan["outro"]["lines"]], ["Lo que pasa en La Rioja", "lo sabés acá", "Seguinos"])
        self.assertTrue(all(l["at"] >= plan["outro"]["from"] for l in plan["outro"]["lines"]))
        self.assertEqual(v3.CTA_DEFAULT, "@lavozriojana.ok")


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "data").mkdir()
        (root / "output" / "web_media").mkdir(parents=True)
        Image.new("RGB", (1200, 800), "red").save(root / "output" / "web_media" / "abc.webp")
        self.patches = [mock.patch.object(lib, "data_dir", return_value=root / "data"), mock.patch.object(lib, "output_dir", return_value=root / "output")]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.root = root

    def _records(self, now):
        return [
            {"titulo": "Incendio en Sanagasta", "web_url": "https://lavozriojana.com/noticias/a", "source": "fenix_locales", "published_at_ts": now - 3600},
            {"titulo": "Asume una diputada", "web_url": "https://lavozriojana.com/noticias/b", "source": "nuevarioja_politica", "published_at_ts": now - 3600},
            {"titulo": "Ganó Andino", "web_url": "https://lavozriojana.com/noticias/c", "source": "nuevarioja_deportes", "published_at_ts": now - 3600},
            {"titulo": "Robo en Buenos Aires", "web_url": "https://lavozriojana.com/noticias/d", "source": "infobae_policiales", "published_at_ts": now - 3600},
            {"titulo": "Choque viejo", "web_url": "https://lavozriojana.com/noticias/e", "source": "fenix_locales", "published_at_ts": now - 100 * 3600},
        ]

    def test_refresh_keeps_police_and_politics_with_processed_photo(self):
        now = time.time()
        with open(self.root / "data" / "noticias_web_publicadas.json", "w", encoding="utf-8") as fh:
            json.dump(self._records(now), fh)
        info = {"https://lavozriojana.com/noticias/a": {"category": "sociedad", "localities": ["Sanagasta"]},
                "https://lavozriojana.com/noticias/b": {"category": "politica", "localities": []},
                "https://lavozriojana.com/noticias/c": {"category": "deportes", "localities": []},
                "https://lavozriojana.com/noticias/d": {"category": "policiales", "localities": []}}
        fetch = lambda url: {"title": url[-1].upper(), "body": "Cuerpo de la nota.", "photo_url": "https://media.lavozriojana.com/noticias/2026/10/abc.webp"}
        download = mock.Mock(return_value=None)
        report = lib.refresh(now=now, fetch=fetch, download=download, archive_info=lambda urls: info, video_index=lambda: {})
        self.assertEqual(report["added"], 2)
        self.assertEqual({e["motivo"] for e in report["excluded"]}, {"sección deportes sin palabra clave policial", "fuente no riojana"})
        police = lib.entries("policiales", now=now)
        politics = lib.entries("politica", now=now)
        self.assertEqual([e["web_url"][-1] for e in police], ["a"])
        self.assertEqual([e["web_url"][-1] for e in politics], ["b"])
        self.assertTrue(os.path.isfile(police[0]["photo"]["path"]))
        download.assert_not_called()  # la foto procesada local se reutiliza
        # Segunda corrida: nada que pedir de nuevo.
        fetch2 = mock.Mock()
        self.assertEqual(lib.refresh(now=now, fetch=fetch2, download=download, archive_info=lambda urls: info, video_index=lambda: {})["added"], 0)
        fetch2.assert_not_called()

    def test_expired_entries_and_files_are_removed(self):
        now = time.time()
        old_dir = Path(lib.media_root()) / "viejo"
        old_dir.mkdir(parents=True)
        with open(lib.library_path(), "w", encoding="utf-8") as fh:
            json.dump({"viejo": {"kind": "policiales", "published_at": now - 200 * 3600, "body": "x"}}, fh)
        with open(self.root / "data" / "noticias_web_publicadas.json", "w", encoding="utf-8") as fh:
            json.dump([], fh)
        report = lib.refresh(now=now, fetch=mock.Mock(), archive_info=lambda urls: {}, video_index=lambda: {})
        self.assertEqual(report["expired"], 1)
        self.assertFalse(old_dir.exists())

    def test_check_and_video_are_remembered(self):
        with open(lib.library_path(), "w", encoding="utf-8") as fh:
            json.dump({"k": {"kind": "policiales", "published_at": time.time(), "body": "x", "checks": {}}}, fh)
        lib.remember("k", check=("sha", {"corresponde": "si"}), video={"path": "v.mp4", "width": 1920, "height": 1080})
        entry = json.load(open(lib.library_path(), encoding="utf-8"))["k"]
        self.assertEqual(entry["checks"]["sha"]["corresponde"], "si")
        self.assertEqual(entry["video"]["width"], 1920)


class VoiceTests(unittest.TestCase):
    def test_slow_take_is_brought_to_target_rate_within_limit(self):
        calls = []
        durations = iter([12.0, 10.7])
        with mock.patch.object(nn, "synthesize") as synth, mock.patch.object(nn, "media_duration", side_effect=lambda p: next(durations)), \
             mock.patch.object(v3.subprocess, "run", side_effect=lambda *a, **k: calls.append(a[0])), mock.patch.object(v3.os, "replace"):
            v3.synth_energetic(" ".join(["palabra"] * 28), "x.wav")
        self.assertEqual(synth.call_args.kwargs["direction"], v3.VOICE_DIRECTION_V4)
        tempo = [c for c in calls if "-af" in c][0]
        factor = float(tempo[tempo.index("-af") + 1].split("=")[1])
        self.assertLessEqual(factor, 1.12)
        self.assertGreater(factor, 1.0)

    def test_new_direction_drops_slow_singing_cues(self):
        self.assertNotIn("tranquila", v3.VOICE_DIRECTION_V4)
        self.assertNotIn("alargá", v3.VOICE_DIRECTION_V4)


if __name__ == "__main__":
    unittest.main()


class JudicialPortraitTests(unittest.TestCase):
    def test_portrait_in_judicial_story_is_excluded_but_not_elsewhere(self):
        face = {"corresponde": "si", "tipo": "retrato", "persona_primer_plano": True, "nitidez": 5}
        judicial = v3.assess(v3.Asset("a", "image", "x", "", 1280, 853, sha="d" * 64, check=dict(face)), policial=True, sensitive=False, judicial=True)
        self.assertFalse(judicial.eligible)
        self.assertIn("historia judicial", judicial.reasons[-1])
        other = v3.assess(v3.Asset("a", "image", "x", "", 1280, 853, sha="e" * 64, check=dict(face)), policial=True, sensitive=False, judicial=False)
        self.assertTrue(other.eligible)


class MediaPrescreenTests(unittest.TestCase):
    """Decisión del 2026-10-31: ningún hecho sale en el Reel sin imagen propia."""

    def _run(self, cands, checks):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        seen = []

        def vision(images, *, title, excerpt, video, cache_dir=None):
            seen.append((title, video))
            return dict(checks[(title, video)])

        def video(url, dest, max_seconds=90):
            Path(dest).write_bytes(url.encode())
            return (1080, 1920)

        with mock.patch("utils.remotion_renderer.REMOTION_DIR", tmp), mock.patch.object(v3, "_load_library", return_value={}), \
             mock.patch.object(nn, "media_duration", return_value=20.0), mock.patch.dict(os.environ, {"NIGHTLY_NEWSCAST_REQUIRE_MEDIA": "true"}):
            kept, report = v3.prescreen_media(cands, providers={"vision": vision, "video": video, "no_library": True})
        return kept, report, seen

    def _photo(self, name):
        path = os.path.join(tempfile.mkdtemp(), f"{name}.jpg")
        Image.new("RGB", (1280, 853), (90, 60, 40)).save(path)
        return path

    def test_only_notes_with_own_eligible_media_reach_the_script(self):
        ok = _cand("a", "Incendio en Sanagasta")
        ok.photo_path = self._photo("a")
        bare = _cand("b", "Robo en el centro")
        judge = _cand("c", "Procesan a un hombre por robo")
        judge.photo_path = self._photo("c")
        rescued = _cand("d", "Choque en ruta 5")
        rescued.photo_path = self._photo("d")
        rescued.video_url = "https://x/d.mp4"
        good = {"corresponde": "si", "tipo": "registro_del_hecho", "nitidez": 4}
        checks = {
            ("Incendio en Sanagasta", False): good,
            ("Procesan a un hombre por robo", False): {"corresponde": "si", "tipo": "retrato", "persona_primer_plano": True, "nitidez": 5},
            ("Choque en ruta 5", False): {"corresponde": "no", "tipo": "registro_del_hecho", "nitidez": 4, "describe": "otro choque"},
            ("Choque en ruta 5", True): {**good, "cuadros_utiles": [1, 2, 3]},
        }
        kept, report, seen = self._run([ok, bare, judge, rescued], checks)
        self.assertEqual([c.id for c in kept], ["a", "d"])
        self.assertEqual({e["id"] for e in report["excluded"]}, {"b", "c"})
        self.assertIn("historia judicial", next(e["motivo"] for e in report["excluded"] if e["id"] == "c"))
        # El video sólo se revisa cuando la foto no sirve.
        self.assertNotIn(("Incendio en Sanagasta", True), seen)

    def test_flag_off_keeps_every_candidate(self):
        with mock.patch.dict(os.environ, {"NIGHTLY_NEWSCAST_REQUIRE_MEDIA": "false"}):
            kept, report = v3.prescreen_media([_cand("a", "x")])
        self.assertEqual(len(kept), 1)
        self.assertIn("skipped", report)

    def test_runner_reports_no_work_when_too_few_stories_have_images(self):
        from meta import run_nightly_newscast as run

        env = {"NIGHTLY_NEWSCAST_ENABLED": "true", "NIGHTLY_NEWSCAST_VISUAL": "v3", "NIGHTLY_NEWSCAST_PUBLISH": "false"}
        cands = [_cand(f"n{i}", "T") for i in range(5)]
        script = v3.ScriptV3(blocks=[_block(["n1"], [(["n1"], "Texto.")])])
        with mock.patch.dict(os.environ, env), mock.patch.object(nn, "load_state", return_value={}), mock.patch.object(nn, "note_attempt"), \
             mock.patch.object(nn, "mark_day") as mark, mock.patch.object(v3, "collect_candidates_v3", return_value=(cands, {})), \
             mock.patch.object(v3, "prescreen_media", return_value=(cands, {})), mock.patch.object(v3, "write_script_v3", return_value=(script, [])), \
             mock.patch.object(v3, "build_edition_v3", side_effect=v3.NotEnoughMaterial("quedan 2")), mock.patch.object(nn, "publish") as publish:
            result = run.main([])
        self.assertEqual(result.status.value, "no_work")
        self.assertEqual(mark.call_args.kwargs["reason"], "pocos_hechos_con_imagen")
        self.assertFalse(publish.called)


class HookOpeningTests(unittest.TestCase):
    """Correcciones del 2026-10-31: la apertura abre con video, dura ≤ 7 s y
    el título corto no pierde preposiciones."""

    def _mk(self, i, interes, corto, titulo=None):
        return {**_block([i], [([i], "Texto del hecho.")], titulo=titulo or f"Titular {i}"), "titulo_corto": corto,
                "relevancia": {"interes": interes, "novedad": 3, "impacto_local": 3, "utilidad": 3, "seguimiento": 3}}

    def test_short_title_gets_back_its_missing_preposition(self):
        self.assertEqual(v3.repair_short_title("Juicio por tentativa femicidio", "Juicio por tentativa de femicidio en Chepes"),
                         "Juicio por tentativa de femicidio")
        self.assertEqual(v3.repair_short_title("Incendio en Sanagasta", "Incendio destruyó un comercio en Sanagasta"), "Incendio en Sanagasta")

    def test_video_event_opens_even_with_lower_score(self):
        blocks = [self._mk("a", 5, "Detenida por estafas"), self._mk("b", 5, "Juicio en Chepes"), self._mk("c", 3, "Incendio en Sanagasta")]
        assets = {"a": [_asset("a")], "b": [_asset("b")], "c": [_asset("c", "video", 1080, 1920, duration_ms=30000)]}
        hook = v3.derive_hook(blocks, assets)
        self.assertEqual(hook[0]["texto"], "Incendio en Sanagasta.")
        self.assertTrue(hook[0]["video"])
        self.assertEqual(len(hook), 3)

    def test_hook_respects_word_budget(self):
        blocks = [self._mk("a", 5, "Detuvieron a una mujer acusada de estafas"), self._mk("b", 4, "Juicio en Chepes"),
                  self._mk("c", 4, "Incendio voraz destruyó un comercio")]
        assets = {k: [_asset(k)] for k in "abc"}
        hook = v3.derive_hook(blocks, assets)
        self.assertLessEqual(sum(len(h["texto"].split()) for h in hook), v3.HOOK_MAX_WORDS)


class FactualDriftTests(unittest.TestCase):
    """Correcciones del 2026-11-01 sobre la edición del 31/10: el título corto
    no cambia la situación procesal y no entran hechos de otro día."""

    def test_short_title_cannot_turn_held_into_detained(self):
        src = [_cand("n7", "Demoraron a un menor tras intentar robar una moto",
                     "Un adolescente de 16 años fue demorado este sábado en Chilecito.")]
        self.assertEqual(v3.status_drift("Detenido por intento de robo", src), ["detenido"])
        self.assertEqual(v3.status_drift("Demoran a menor por intento de robo", src), [])
        self.assertEqual(v3.status_drift("Robo de moto en Chilecito", src), [])

    def test_weekday_two_or_more_days_back_is_stale(self):
        saturday = time.mktime((2026, 10, 31, 20, 15, 0, 0, 0, -1))
        self.assertEqual(v3.stale_weekday("Dos jóvenes resultaron heridas este miércoles por la tarde.", saturday), "este miercoles")
        self.assertEqual(v3.stale_weekday("Dos mujeres sufrieron fracturas este sábado.", saturday), "")
        self.assertEqual(v3.stale_weekday("El hecho ocurrió en la noche del viernes.", saturday), "")
        self.assertEqual(v3.stale_weekday("La audiencia será el próximo miércoles.", saturday), "")

    def test_stale_note_is_left_out_of_the_candidates(self):
        now = time.mktime((2026, 10, 31, 20, 15, 0, 0, 0, -1))
        entries = [{"title": t, "body": b, "web_url": f"https://lavozriojana.com/noticias/{k}", "published_at": now - 3600, "key": k}
                   for k, t, b in (("a", "Heridas tras caer de una moto", "Dos jóvenes cayeron este miércoles en el centro."),
                                   ("b", "Fracturas tras chocar", "Dos mujeres chocaron este sábado en la avenida Illia."))]
        with mock.patch.object(lib, "entries", return_value=entries):
            out, report = v3.collect_candidates_v3(now=now, refresh=lambda **_: {})
        self.assertEqual([c.title for c in out], ["Fracturas tras chocar"])
        self.assertEqual(report["stale"][0]["titulo"], "Heridas tras caer de una moto")
