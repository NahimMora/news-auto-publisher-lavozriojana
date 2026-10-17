import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openIA.caption_generator import generate_caption, generate_locality_and_deck
from utils.classifier import clasificar_con_resultado
from utils.editorial_priority import priority_interleave
from utils.news_dedup import duplicate_reason
from utils.url_normalization import canonical_url, url_hash


def _gemini_chat_mock(content: str):
    return Mock(return_value=content)


class UrlNormalizationTests(unittest.TestCase):
    def test_scheme_host_query_order_fragment_and_trailing_slash(self):
        left = "HTTPS://Example.COM/nota/?b=2&a=1#comentarios"
        right = "https://example.com/nota?a=1&b=2"
        self.assertEqual(canonical_url(left), canonical_url(right))
        self.assertEqual(url_hash(left), url_hash(right))


class DedupTests(unittest.TestCase):
    def test_shared_boilerplate_excerpt_does_not_merge_distinct_titles(self):
        boilerplate = "Leé todas las noticias de La Rioja en nuestro portal."
        a = {"titulo": "Municipio inaugura una obra vial", "excerpt": boilerplate}
        b = {"titulo": "Club local ganó el campeonato de fútbol", "excerpt": boilerplate}
        self.assertIsNone(duplicate_reason(a, [b], threshold=0.5))

    def test_similar_titles_are_detected(self):
        a = {"titulo": "Vialidad mejora rutas en Aimogasta"}
        b = {"titulo": "Vialidad mejoró las rutas de Aimogasta"}
        self.assertIsNotNone(duplicate_reason(a, [b], threshold=0.5))


class EditorialFallbackUnitTests(unittest.TestCase):
    def test_classifier_fallback_is_explicit(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "PENDIENTE"}, clear=False):
            result = clasificar_con_resultado("Nota", ["Contenido"])
        self.assertEqual(result.category, "Sociedad")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.error_type, "credential_missing")

    def test_caption_fallback_is_explicit_and_bounded(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "PENDIENTE"}, clear=False):
            result = generate_caption(
                {"titulo": "Título original", "parrafos": ["Texto original"]}
            )
        self.assertTrue(result["caption_fallback_used"])
        self.assertEqual(result["caption_fallback_reason"], "credential_missing")
        self.assertLessEqual(len(result["titulo_instagram"]), 80)
        self.assertLessEqual(len(result["texto_instagram"]), 2200)

    def test_locality_deck_fallback_is_explicit_and_empty(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "PENDIENTE"}, clear=False):
            result = generate_locality_and_deck(
                {"titulo": "Título original", "parrafos": ["Texto original"]}
            )
        self.assertTrue(result["locality_deck_fallback_used"])
        self.assertEqual(result["locality_deck_fallback_reason"], "credential_missing")
        self.assertEqual(result["locality"], "")
        self.assertEqual(result["deck"], "")
        self.assertNotIn("highlight_phrase", result)

    def test_manual_publication_fallback_selects_phrase_from_title(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "PENDIENTE"}, clear=False):
            result = generate_locality_and_deck(
                {"titulo": "El Gobierno anunció un plan integral de obras", "parrafos": ["Texto"]},
                include_highlight=True,
            )
        self.assertEqual(result["highlight_phrase"], "anunció un plan integral")

    def test_locality_deck_success_parses_json_and_bounds_length(self):
        payload = {
            "locality": "Chilecito",
            "deck": "Un anuncio clave para la ciudad " * 5,
            "highlight_phrase": "anuncia obras",
        }
        mock_chat = _gemini_chat_mock(json.dumps(payload))
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-only", "GEMINI_MODEL": "test-model", "GEMINI_RETRY_COUNT": "1"},
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            result = generate_locality_and_deck(
                {"titulo": "La Municipalidad anuncia obras", "parrafos": ["Texto de la nota en Chilecito"]},
                include_highlight=True,
            )
        self.assertFalse(result["locality_deck_fallback_used"])
        self.assertEqual(result["locality"], "Chilecito")
        self.assertLessEqual(len(result["deck"]), 90)
        self.assertEqual(result["highlight_phrase"], "anuncia obras")
        self.assertEqual("test-model", mock_chat.call_args.kwargs["model"])
        self.assertTrue(mock_chat.call_args.kwargs["json_mode"])
        prompt = mock_chat.call_args.kwargs["messages"][0]["content"]
        self.assertIn("núcleo de la noticia", prompt)
        self.assertIn("No elijas las últimas palabras", prompt)

    def test_highlight_phrase_is_always_copied_from_the_title(self):
        payload = {
            "locality": "",
            "deck": "",
            "highlight_phrase": "obras inventadas afuera",
        }
        mock_chat = _gemini_chat_mock(json.dumps(payload))
        title = "El Gobierno anunció un plan integral de obras públicas"
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-only", "GEMINI_RETRY_COUNT": "1"},
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            result = generate_locality_and_deck(
                {"titulo": title, "parrafos": ["Texto sin datos adicionales"]},
                include_highlight=True,
            )
        phrase = result["highlight_phrase"]
        self.assertGreaterEqual(len(phrase.split()), 2)
        self.assertLessEqual(len(phrase.split()), 4)
        self.assertIn(phrase, title)

    def test_highlight_rejects_a_generic_title_ending(self):
        payload = {
            "locality": "",
            "deck": "",
            "highlight_phrase": "puntos de la ciudad",
        }
        mock_chat = _gemini_chat_mock(json.dumps(payload))
        title = "El Gobierno anunció un plan de obras en distintos puntos de la ciudad"
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-only", "GEMINI_RETRY_COUNT": "1"},
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            result = generate_locality_and_deck(
                {"titulo": title, "parrafos": ["Texto"]},
                include_highlight=True,
            )
        self.assertNotEqual(result["highlight_phrase"], "puntos de la ciudad")
        self.assertIn(result["highlight_phrase"], title)

    def test_highlight_allows_a_final_phrase_only_when_it_contains_the_event(self):
        payload = {
            "locality": "",
            "deck": "",
            "highlight_phrase": "anunció nuevas obras",
        }
        mock_chat = _gemini_chat_mock(json.dumps(payload))
        title = "Tras meses de espera el Gobierno anunció nuevas obras"
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-only", "GEMINI_RETRY_COUNT": "1"},
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            result = generate_locality_and_deck(
                {"titulo": title, "parrafos": ["Texto"]},
                include_highlight=True,
            )
        self.assertEqual(result["highlight_phrase"], "anunció nuevas obras")

    def test_locality_deck_never_invents_when_text_has_no_place(self):
        payload = {"locality": "", "deck": "Un anuncio sin lugar concreto"}
        mock_chat = _gemini_chat_mock(json.dumps(payload))
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-only", "GEMINI_RETRY_COUNT": "1"},
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            result = generate_locality_and_deck(
                {"titulo": "Anuncio general", "parrafos": ["Texto sin localidad concreta"]}
            )
        self.assertEqual(result["locality"], "")

    def test_locality_deck_falls_back_when_gemini_keeps_failing(self):
        mock_chat = Mock(side_effect=RuntimeError("boom"))
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-only", "GEMINI_RETRY_COUNT": "1", "GEMINI_RETRY_SLEEP": "0"},
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            result = generate_locality_and_deck({"titulo": "Nota", "parrafos": ["Texto"]})
        self.assertTrue(result["locality_deck_fallback_used"])
        self.assertEqual(result["locality_deck_fallback_reason"], "gemini_failed")
        self.assertEqual(result["locality"], "")
        self.assertEqual(result["deck"], "")
        self.assertNotIn("highlight_phrase", result)

    def test_priority_interleave_prevents_deportes_monopoly(self):
        items = [
            {"titulo": "dep1", "seccion": "deportes"},
            {"titulo": "dep2", "seccion": "deportes"},
            {"titulo": "pol", "seccion": "policiales"},
            {"titulo": "int", "seccion": "interior"},
        ]
        ordered = priority_interleave(items)
        self.assertEqual([item["titulo"] for item in ordered[:2]], ["pol", "int"])


class AutomaticVisualStyleFlagTests(unittest.TestCase):
    def test_flag_defaults_off_and_manual_publication_is_always_enabled(self):
        from utils.visual_style import (
            automatic_manual_visual_style_enabled,
            uses_manual_publication_visual_style,
        )

        self.assertFalse(automatic_manual_visual_style_enabled({}))
        self.assertFalse(uses_manual_publication_visual_style({"source": "fixture"}, {}))
        self.assertTrue(
            uses_manual_publication_visual_style({"source": "fixture"}, {"AUTOMATIC_MANUAL_VISUAL_STYLE_ENABLED": "true"})
        )
        self.assertTrue(uses_manual_publication_visual_style({"source": "manual_custom_post"}, {}))

    def test_automatic_rewrite_generates_and_persists_highlight_when_enabled(self):
        from openIA import rewrite_news

        article = {
            "titulo": "El Gobierno anunció un plan integral de obras",
            "parrafos": ["El anuncio fue confirmado por autoridades."],
            "seccion": "politica",
            "url": "https://example.com/plan-obras",
            "source": "fixture",
        }
        visual_context = {
            "locality": "",
            "deck": "",
            "highlight_phrase": "plan integral de obras",
            "locality_deck_fallback_used": False,
        }
        with patch.dict(
            os.environ,
            # El .env del host puede diferir localidad/bajada; este test cubre
            # la generación durante la reescritura.
            {"AUTOMATIC_MANUAL_VISUAL_STYLE_ENABLED": "true", "LOCALITY_DECK_LAZY_ENABLED": "false"},
            clear=False,
        ), patch.object(
            rewrite_news,
            "_call_gemini",
            return_value=(article["titulo"], ""),
        ), patch.object(
            rewrite_news,
            "clasificar_con_resultado",
            return_value=SimpleNamespace(category="politica", fallback_used=False),
        ), patch.object(
            rewrite_news,
            "generate_caption",
            return_value={"caption_fallback_used": False},
        ), patch.object(
            rewrite_news,
            "generate_locality_and_deck",
            return_value=visual_context,
        ) as visual_context_mock:
            rewritten = rewrite_news.rewrite_noticia(dict(article))

        self.assertTrue(visual_context_mock.call_args.kwargs["include_highlight"])
        self.assertEqual(rewritten["highlight_terms"], ["plan integral de obras"])
        self.assertEqual(
            rewrite_news.build_meta_item(rewritten)["highlight_terms"],
            ["plan integral de obras"],
        )


class LazyLocalityDeckTests(unittest.TestCase):
    _ARTICLE = {
        "titulo": "El Gobierno anunció un plan integral de obras",
        "parrafos": ["El anuncio fue confirmado por autoridades."],
        "seccion": "politica",
        "url": "https://example.com/plan-obras",
        "source": "fixture",
    }

    def _rewrite(self, env: dict):
        from openIA import rewrite_news

        with patch.dict(os.environ, env, clear=False), patch.object(
            rewrite_news, "_call_gemini", return_value=(self._ARTICLE["titulo"], "")
        ), patch.object(
            rewrite_news,
            "clasificar_con_resultado",
            return_value=SimpleNamespace(category="politica", fallback_used=False),
        ), patch.object(
            rewrite_news, "generate_caption", return_value={"caption_fallback_used": False}
        ), patch.object(rewrite_news, "generate_locality_and_deck") as locality_mock:
            rewritten = rewrite_news.rewrite_noticia(
                {**self._ARTICLE, "highlight_terms": ["viejo"], "deck": "vieja"}
            )
        return rewrite_news, rewritten, locality_mock

    def test_flag_off_keeps_generating_during_rewrite(self):
        _, rewritten, locality_mock = self._rewrite({"LOCALITY_DECK_LAZY_ENABLED": "false"})
        self.assertEqual(locality_mock.call_count, 1)
        self.assertNotIn("locality_deck_deferred", rewritten)

    def test_flag_on_defers_without_calling_gemini_and_survives_meta_queue(self):
        rewrite_news, rewritten, locality_mock = self._rewrite({"LOCALITY_DECK_LAZY_ENABLED": "true"})
        locality_mock.assert_not_called()
        self.assertTrue(rewritten["locality_deck_deferred"])
        self.assertNotIn("deck", rewritten)
        self.assertNotIn("highlight_terms", rewritten)
        self.assertNotIn("locality_deck", rewritten["fallbacks_used"])
        self.assertTrue(rewrite_news.build_meta_item(rewritten)["locality_deck_deferred"])

    def test_ensure_completes_deferred_item_from_excerpt_and_caption(self):
        from openIA.caption_generator import ensure_locality_and_deck

        payload = {"locality": "Chilecito", "deck": "Obras para el oeste", "highlight_phrase": "plan integral"}
        mock_chat = _gemini_chat_mock(json.dumps(payload))
        item = {
            "titulo": self._ARTICLE["titulo"],
            "excerpt": "Primer párrafo en Chilecito.",
            "texto_instagram": "Caption de la nota.",
            "locality_deck_deferred": True,
        }
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-only", "GEMINI_RETRY_COUNT": "1", "AUTOMATIC_MANUAL_VISUAL_STYLE_ENABLED": "true"},
            clear=False,
        ), patch("utils.ai_client.chat_completion", mock_chat):
            self.assertTrue(ensure_locality_and_deck(item))
            # Segunda vez no vuelve a llamar a Gemini.
            self.assertFalse(ensure_locality_and_deck(item))

        self.assertEqual(mock_chat.call_count, 1)
        user_prompt = mock_chat.call_args.kwargs["messages"][1]["content"]
        self.assertIn("Primer párrafo en Chilecito.", user_prompt)
        self.assertIn("Caption de la nota.", user_prompt)
        self.assertEqual(item["locality"], "Chilecito")
        self.assertEqual(item["deck"], "Obras para el oeste")
        self.assertEqual(item["highlight_terms"], ["plan integral"])
        self.assertNotIn("locality_deck_deferred", item)

    def test_ensure_is_noop_for_items_generated_during_rewrite(self):
        from openIA.caption_generator import ensure_locality_and_deck

        mock_chat = Mock()
        item = {"titulo": "Nota", "locality": "", "deck": "Ya generada"}
        with patch("utils.ai_client.chat_completion", mock_chat):
            self.assertFalse(ensure_locality_and_deck(item))
        mock_chat.assert_not_called()
        self.assertEqual(item["deck"], "Ya generada")

    def test_ensure_failure_leaves_card_without_deck(self):
        from openIA.caption_generator import ensure_locality_and_deck

        item = {"titulo": "Nota", "excerpt": "Texto", "locality_deck_deferred": True}
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-only", "GEMINI_RETRY_COUNT": "1", "GEMINI_RETRY_SLEEP": "0"},
            clear=False,
        ), patch("utils.ai_client.chat_completion", Mock(side_effect=RuntimeError("boom"))):
            self.assertTrue(ensure_locality_and_deck(item))
        self.assertEqual(item["deck"], "")
        self.assertEqual(item["locality"], "")

    def test_ig_render_requests_deferred_fields_before_rendering(self):
        from meta import ig_client

        item = {"titulo": "Nota", "excerpt": "Texto", "locality_deck_deferred": True}
        seen: dict = {}

        def fake_render(noticia, **_kwargs):
            seen["deck"] = noticia.get("deck")
            raise RuntimeError("render cortado por el test")

        def fake_ensure(noticia):
            noticia["deck"] = "Bajada diferida"
            noticia.pop("locality_deck_deferred", None)
            return True

        with patch.object(ig_client.r2_storage, "is_configured", return_value=True), patch(
            "layout.image_generator.generate_instagram_with_engine", side_effect=fake_render
        ), patch("openIA.caption_generator.ensure_locality_and_deck", side_effect=fake_ensure), patch.dict(
            os.environ, {"IG_ALLOW_ORIGINAL_IMAGE_FALLBACK": "false"}, clear=False
        ):
            result, _url, _key = ig_client._prepare_image(item)

        self.assertFalse(result.ok)
        self.assertEqual(seen["deck"], "Bajada diferida")


class CustomPostVisualMetadataTests(unittest.TestCase):
    def test_custom_post_enforces_the_web_title_limit(self):
        from pipeline.custom_post import CUSTOM_TITLE_MAX_CHARS, build_custom_noticia

        base = {"cuerpo": "Cuerpo de prueba", "seccion": "sociedad"}
        with self.assertRaisesRegex(ValueError, str(CUSTOM_TITLE_MAX_CHARS)):
            build_custom_noticia(
                {**base, "titulo": "A" * (CUSTOM_TITLE_MAX_CHARS + 1)},
                require_image=False,
            )

    def test_custom_post_passes_one_relevant_title_phrase_to_the_renderer(self):
        from pipeline.custom_post import build_custom_noticia

        visual_context = {
            "locality": "",
            "deck": "",
            "highlight_phrase": "plan integral de obras",
            "locality_deck_fallback_used": False,
        }
        with patch(
            "openIA.caption_generator.generate_locality_and_deck",
            return_value=visual_context,
        ) as generate_visual_context:
            item = build_custom_noticia(
                {
                    "titulo": "El Gobierno anunció un plan integral de obras",
                    "cuerpo": "El anuncio fue realizado durante la jornada.",
                    "seccion": "politica",
                },
                require_image=False,
            )

        self.assertEqual(item["highlight_terms"], ["plan integral de obras"])
        self.assertTrue(generate_visual_context.call_args.kwargs["include_highlight"])


if __name__ == "__main__":
    unittest.main()
