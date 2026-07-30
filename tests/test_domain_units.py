import os
import unittest
from unittest.mock import patch

from openIA.caption_generator import generate_caption
from utils.classifier import clasificar_con_resultado
from utils.editorial_priority import priority_interleave
from utils.news_dedup import duplicate_reason
from utils.url_normalization import canonical_url, url_hash


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
        with patch.dict(os.environ, {"OPENAI_API_KEY": "PENDIENTE"}, clear=False):
            result = clasificar_con_resultado("Nota", ["Contenido"])
        self.assertEqual(result.category, "Sociedad")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.error_type, "credential_missing")

    def test_caption_fallback_is_explicit_and_bounded(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "PENDIENTE"}, clear=False):
            result = generate_caption(
                {"titulo": "Título original", "parrafos": ["Texto original"]}
            )
        self.assertTrue(result["caption_fallback_used"])
        self.assertEqual(result["caption_fallback_reason"], "credential_missing")
        self.assertLessEqual(len(result["titulo_instagram"]), 80)
        self.assertLessEqual(len(result["texto_instagram"]), 2200)

    def test_priority_interleave_prevents_deportes_monopoly(self):
        items = [
            {"titulo": "dep1", "seccion": "deportes"},
            {"titulo": "dep2", "seccion": "deportes"},
            {"titulo": "pol", "seccion": "policiales"},
            {"titulo": "int", "seccion": "interior"},
        ]
        ordered = priority_interleave(items)
        self.assertEqual([item["titulo"] for item in ordered[:2]], ["pol", "int"])


if __name__ == "__main__":
    unittest.main()
