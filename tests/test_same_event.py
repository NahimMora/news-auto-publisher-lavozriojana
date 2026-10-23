"""Mismo hecho entre fuentes, actualizaciones, alertas sólo del SMN y lugar en la placa."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest import mock

NOW = 1_792_760_000.0


def _meta(title: str, *, key: str, url: str, hours_ago: float = 2, **extra) -> dict:
    return {"titulo": title, "titulo_instagram": title, "meta_queue_key": key, "canonical_url": url, "source": "nuevarioja_policiales",
            "queued_at": int(NOW - hours_ago * 3600), **extra}


QUEUE = [
    _meta("Confirmaron muerte cerebral para el joven accidentado en Sanagasta", key="k1", url="https://nr/1", web_url="https://lvr/1"),
    _meta("Inauguraron la plaza de Vargas", key="k2", url="https://nr/2"),
    _meta("Murió una mujer en un choque en Aimogasta", key="k3", url="https://nr/3", hours_ago=60),
    {**_meta("Accidente en Sanagasta: video viral", key="k4", url="https://pp/4"), "source": "paparazzi_virales"},
]
NEW = {
    "titulo": "Murió el joven que sufrió un vuelco en la Ruta 75, en Sanagasta",
    "parrafos": ["El joven de 25 años que había volcado en la Ruta 75 falleció en el Hospital Vera Barros."],
    "canonical_url": "https://tp/9",
}


class _TempData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LVR_DATA_DIR": self.tmp.name, "SAME_EVENT_CHECK_ENABLED": "true"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name: str, value) -> None:
        with open(os.path.join(self.tmp.name, name), "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)


class CandidateTests(unittest.TestCase):
    def test_window_source_and_shared_words(self):
        from utils.same_event import recent_candidates

        found = recent_candidates(NEW, items=QUEUE, now=NOW)
        # Sólo la de Sanagasta: la plaza no comparte palabras, la de Aimogasta
        # está fuera de la ventana de 36 h y la de paparazzi no es local.
        self.assertEqual([c["meta_queue_key"] for c in found], ["k1"])
        self.assertEqual(found[0]["web_url"], "https://lvr/1")

    def test_same_url_is_not_a_candidate(self):
        from utils.same_event import recent_candidates

        self.assertEqual(recent_candidates({**NEW, "canonical_url": "https://nr/1"}, items=QUEUE, now=NOW), [])


class AssessTests(unittest.TestCase):
    def setUp(self):
        from utils.same_event import recent_candidates

        self.candidates = recent_candidates(NEW, items=QUEUE, now=NOW)

    def _assess(self, answer=None, *, error=None):
        from utils import same_event

        def completion(**_kwargs):
            if error:
                raise error
            return json.dumps(answer)

        with mock.patch.dict(os.environ, {"GEMINI_RETRY_SLEEP": "0", "GEMINI_RETRY_COUNT": "2"}):
            return same_event.assess_same_event(NEW, candidates=self.candidates, completion=completion)

    def test_update_with_new_fact(self):
        check = self._assess({"mismo_hecho": 1, "ancla": "Sanagasta", "dato_nuevo": True, "novedad": "El joven murió en el hospital."})
        self.assertEqual(check.relation, "update")
        self.assertEqual(check.update_payload(), {
            "of_title": "Confirmaron muerte cerebral para el joven accidentado en Sanagasta", "of_meta_key": "k1",
            "of_canonical_url": "https://nr/1", "of_web_url": "https://lvr/1", "novedad": "El joven murió en el hospital",
        })

    def test_duplicate_without_new_fact(self):
        self.assertEqual(self._assess({"mismo_hecho": 1, "ancla": "Sanagasta", "dato_nuevo": False, "novedad": ""}).relation, "duplicate")
        # "Dato nuevo" sin decir cuál no alcanza para publicar una actualización.
        self.assertEqual(self._assess({"mismo_hecho": 1, "ancla": "Sanagasta", "dato_nuevo": True, "novedad": ""}).relation, "duplicate")

    def test_other_event_or_bad_answer_is_new(self):
        self.assertEqual(self._assess({"mismo_hecho": None, "dato_nuevo": False}).relation, "new")
        self.assertEqual(self._assess({"mismo_hecho": 7, "dato_nuevo": True, "novedad": "x"}).relation, "new")
        self.assertEqual(self._assess({"mismo_hecho": True}).relation, "new")

    def test_same_event_needs_a_concrete_shared_anchor(self):
        # Sin ancla, con una palabra común o con un dato que una de las dos no dice: nota nueva.
        for anchor in ("", "joven", "vuelco", "Ruta 40"):
            answer = {"mismo_hecho": 1, "ancla": anchor, "dato_nuevo": True, "novedad": "Murió"}
            self.assertEqual(self._assess(answer).relation, "new", anchor)

    def test_non_local_sources_are_not_assessed(self):
        from utils import same_event

        completion = mock.Mock()
        check = same_event.assess_same_event({**NEW, "source": "paparazzi"}, candidates=self.candidates, completion=completion)
        self.assertEqual(check.relation, "new")
        completion.assert_not_called()

    def test_failure_keeps_the_note(self):
        check = self._assess(error=RuntimeError("timeout"))
        self.assertEqual((check.relation, check.error_type), ("new", "gemini_failed"))

    def test_no_candidates_no_call(self):
        from utils import same_event

        completion = mock.Mock()
        self.assertEqual(same_event.assess_same_event(NEW, candidates=[], completion=completion).relation, "new")
        completion.assert_not_called()


class SupersededTests(_TempData):
    def test_newer_update_replaces_older_pending_version(self):
        from utils import same_event

        update = {"titulo": "Murió el joven", "web_url": "https://lvr/9", "meta_queue_key": "k9",
                  "event_update": {"of_meta_key": "k1", "of_canonical_url": "https://nr/1"}}
        self.write("noticias_meta.json", [QUEUE[0], update])
        with mock.patch("utils.social_queue.mark_policy_excluded") as excluded:
            kept, dropped = same_event.drop_superseded([QUEUE[0], update, QUEUE[1]], "instagram")
        self.assertEqual([n["meta_queue_key"] for n in kept], ["k9", "k2"])
        self.assertEqual(dropped, 1)
        excluded.assert_called_once_with(QUEUE[0], "instagram", "policy_superseded_by_update")

    def test_update_without_web_url_does_not_replace_yet(self):
        from utils import same_event

        update = {"titulo": "Murió el joven", "meta_queue_key": "k9", "event_update": {"of_meta_key": "k1"}}
        self.write("noticias_meta.json", [QUEUE[0], update])
        kept, dropped = same_event.drop_superseded([QUEUE[0]], "instagram")
        self.assertEqual((len(kept), dropped), (1, 0))

    def test_disabled_does_nothing(self):
        from utils import same_event

        with mock.patch.dict(os.environ, {"SAME_EVENT_CHECK_ENABLED": "false"}):
            self.assertEqual(same_event.drop_superseded([QUEUE[0]], "instagram"), ([QUEUE[0]], 0))

    def test_original_published_per_platform(self):
        from utils.same_event import original_published

        self.write("ig_posted.json", {"posted": {"a": {"canonical_url": "https://nr/1", "external_id": "179"}}})
        self.write("fb_posted.json", {"posted": {}})
        noticia = {"event_update": {"of_canonical_url": "https://nr/1"}}
        self.assertTrue(original_published(noticia, "instagram"))
        self.assertFalse(original_published(noticia, "facebook"))
        self.assertFalse(original_published({}, "instagram"))


class UpdatePresentationTests(_TempData):
    def test_caption_says_update(self):
        from utils.social_caption import build_instagram_caption

        caption = build_instagram_caption({"texto_instagram": "MURIÓ EL JOVEN 👇", "show_update": True})
        self.assertTrue(caption.startswith("🔄 ACTUALIZACIÓN\n\nMURIÓ EL JOVEN"))
        self.assertFalse(build_instagram_caption({"texto_instagram": "X"}).startswith("🔄"))

    def test_card_props_flag(self):
        from utils.visual_v2_props import instagram_props_v2

        with mock.patch("utils.visual_v2_props.deck_for", return_value=""):
            self.assertTrue(instagram_props_v2({"titulo": "Murió el joven", "show_update": True}, asset_file="")["update"])
            self.assertFalse(instagram_props_v2({"titulo": "Murió el joven"}, asset_file="")["update"])

    def test_story_candidate_for_event_update(self):
        from utils import story_updates as su

        posted_at = time.time() - 3600
        self.write("ig_posted.json", {"posted": {"ig1": {"canonical_url": "https://nr/1", "external_id": "179", "posted_at": posted_at,
                                                         "titulo": "Confirmaron muerte cerebral para el joven accidentado en Sanagasta"}}})
        self.write("fb_posted.json", {"posted": {"fb1": {"canonical_url": "https://nr/1", "external_id": "55_66"}}})
        self.write("noticias_web_publicadas.json", [{
            "titulo": "Murió el joven que había volcado en la Ruta 75", "web_url": "https://lvr/9", "canonical_url": "https://tp/9",
            "published_at_ts": posted_at + 600, "event_update": {"of_canonical_url": "https://nr/1", "novedad": "Murió en el hospital"},
        }])
        [cand] = su.update_candidates(state={})
        self.assertEqual((cand["kind"], cand["ig_media_id"], cand["fb_post_id"]), ("event", "179", "55_66"))
        self.assertEqual(cand["before"], "Confirmaron muerte cerebral para el joven accidentado en Sanagasta")
        self.assertEqual(cand["new_title"], "Murió el joven que había volcado en la Ruta 75")


class RewriteGateTests(unittest.TestCase):
    def test_event_update_survives_meta_queue(self):
        from openIA.rewrite_news import build_meta_item

        item = build_meta_item({"titulo": "x", "url": "https://tp/9", "event_update": {"of_meta_key": "k1"}})
        self.assertEqual(item["event_update"], {"of_meta_key": "k1"})

    def test_update_rule_reaches_title_prompt(self):
        from openIA import rewrite_news

        noticia = {"titulo": "Murió el joven", "parrafos": ["texto"], "event_update": {"of_title": "Muerte cerebral", "novedad": "murió"}}
        with mock.patch.object(rewrite_news, "_call_gemini", side_effect=RuntimeError("corte")) as call, \
                mock.patch.object(rewrite_news, "GEMINI_RETRY_COUNT", 1):
            try:
                rewrite_news.rewrite_noticia(noticia)
            except Exception:
                pass
        rules = call.call_args.args[2]
        self.assertIn("ACTUALIZA una ya publicada", rules)
        self.assertIn("murió", rules)


class WeatherAlertNewsTests(unittest.TestCase):
    def test_only_with_flag(self):
        from openIA.rewrite_news import is_weather_alert_news as w

        alert = {"titulo_original": "Rige alerta por lluvias aisladas y vientos en la cordillera riojana"}
        with mock.patch.dict(os.environ, {"WEATHER_ALERT_NEWS_SMN_ONLY": "true"}):
            self.assertTrue(w(alert))
            self.assertTrue(w({"titulo_original": "Vientos de más de 100 km/h afectarán a distintos departamentos",
                               "parrafos": ["El SMN emitió una alerta amarilla por vientos para la provincia."]}))
            self.assertFalse(w({"titulo_original": "Alerta en salud: denuncian el recorte del programa Remediar"}))
            self.assertFalse(w({"titulo_original": "Jueves con lluvias aisladas y tormentas", "parrafos": ["No hay alertas vigentes."]}))
            self.assertFalse(w({"titulo_original": "Vialidad limpia alcantarillas ante el pronóstico de lluvias"}))
        with mock.patch.dict(os.environ, {"WEATHER_ALERT_NEWS_SMN_ONLY": "false"}):
            self.assertFalse(w(alert))


class PlaceTests(unittest.TestCase):
    def test_strip_places_without_dangling_connectors(self):
        from utils.visual_v2_props import strip_places as s

        self.assertEqual(s("Dos accidentes de moto dejaron tres mujeres heridas en Capital y Chilecito", "Capital · Chilecito"),
                         "Dos accidentes de moto dejaron tres mujeres heridas")
        self.assertEqual(s("Murió el joven que volcó en la Ruta 75 en Sanagasta", "Sanagasta"), "Murió el joven que volcó en la Ruta 75")
        self.assertEqual(s("Chilecito: abren la inscripción para los talleres de verano", "Chilecito"),
                         "Abren la inscripción para los talleres de verano")
        self.assertEqual(s("Choque en la ruta 38 en el departamento de Arauco: dos heridos", "Arauco"), "Choque en la ruta 38: dos heridos")
        self.assertEqual(s("Inauguraron la obra de agua del departamento Castro Barros", "Castro Barros"), "Inauguraron la obra de agua")

    def test_strip_places_leaves_what_it_cannot_cut_cleanly(self):
        from utils.visual_v2_props import strip_places as s

        for title, place in (
            ("La Universidad Nacional de Chilecito abrió la inscripción", "Chilecito"),
            ("Chilecito celebra su aniversario con un gran desfile", "Chilecito"),
            ("Corte de luz en Famatina", "Famatina"),
            ("Obras en Capital, Sanagasta y Chilecito para el verano", "Capital · Sanagasta"),
        ):
            self.assertEqual(s(title, place), title)
        self.assertEqual(s("Sin lugar en la pestaña", ""), "Sin lugar en la pestaña")

    def test_two_places_at_most_and_verified(self):
        from openIA.caption_generator import _verified_locality as v
        from utils.visual_v2_props import locality_for

        self.assertEqual(locality_for({"locality": "Capital, Chilecito, Famatina"}), "Capital · Chilecito")
        self.assertEqual(v("Capital y Chilecito", "Dos accidentes en Capital y Chilecito"), "Capital · Chilecito")
        self.assertEqual(v("Famatina", "Choque en Chilecito"), "")

    def test_sanagasta_is_riojan(self):
        from utils.editorial_router import detect_riojan_link

        self.assertEqual(detect_riojan_link({"titulo": "Confirmaron muerte cerebral para el joven accidentado en Sanagasta"}),
                         (True, "keyword:sanagasta"))


if __name__ == "__main__":
    unittest.main()
