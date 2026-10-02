"""LVR-IMPROVEMENT-0001: Instagram/Facebook reflejan la versión editorial web."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from utils import social_caption


def _noticia(**extra):
    base = {
        "titulo": "Titular scrapeado",
        "seccion": "interior",
        "texto_instagram": "📢🗞️ CAPTION VIEJO 👇",
        "cta": "¿Qué opinás de la obra?",
        "web_editorial": {
            "title": "Inauguraron un acueducto en El Alto",
            "social_title": "Agua potable para 30 familias de El Alto",
            "lead": "El nuevo acueducto abastece a más de 30 familias del barrio.",
            "key_points": [
                "La obra demandó tres meses.",
                "Beneficia a más de 30 familias.",
                "Es parte del plan provincial de agua.",
                "Cuarto punto que no entra.",
            ],
        },
    }
    base.update(extra)
    return base


class CaptionFromWebTests(unittest.TestCase):
    def _build(self, noticia, enabled="true"):
        with mock.patch.dict(os.environ, {"IG_CAPTION_FROM_WEB_ENABLED": enabled}):
            return social_caption.build_instagram_caption(noticia)

    def test_flag_off_keeps_previous_caption(self):
        caption = self._build(_noticia(), enabled="false")
        self.assertTrue(caption.startswith("📢🗞️ CAPTION VIEJO"))

    def test_flag_on_uses_web_version(self):
        caption = self._build(_noticia())
        self.assertTrue(caption.startswith("📍 Agua potable para 30 familias de El Alto"))
        self.assertIn("El nuevo acueducto abastece", caption)
        self.assertIn("▪️ La obra demandó tres meses.", caption)
        self.assertNotIn("Cuarto punto", caption)
        self.assertIn("💬 ¿Qué opinás de la obra?", caption)
        self.assertNotIn("CAPTION VIEJO", caption)
        self.assertTrue(caption.rstrip().endswith("#Noticias"))

    def test_without_web_version_falls_back(self):
        noticia = _noticia()
        noticia.pop("web_editorial")
        self.assertTrue(self._build(noticia).startswith("📢🗞️ CAPTION VIEJO"))

    def test_incomplete_web_version_falls_back(self):
        noticia = _noticia(web_editorial={"title": "Sólo título"})
        self.assertTrue(self._build(noticia).startswith("📢🗞️ CAPTION VIEJO"))

    def test_respects_instagram_limit(self):
        noticia = _noticia()
        noticia["web_editorial"]["lead"] = "x" * 5000
        self.assertLessEqual(len(self._build(noticia)), 2200)


class WebEditorialSnapshotTests(unittest.TestCase):
    def test_snapshot_keeps_only_reusable_fields(self):
        from pipeline.node_webapp.publisher import _web_editorial_snapshot

        editorial = SimpleNamespace(
            title="T",
            excerpt="E",
            lead="L",
            social_title="",
            social_description="SD",
            key_points=["a", " ", "b", "c", "d", "e"],
            content_html="<p>no va</p>",
        )
        snapshot = _web_editorial_snapshot(editorial)
        self.assertEqual(
            {"title": "T", "excerpt": "E", "lead": "L", "social_description": "SD", "key_points": ["a", "b", "c", "d"]},
            snapshot,
        )

    def test_meta_normalization_preserves_web_editorial(self):
        from openIA import rewrite_news

        item = rewrite_news.build_meta_item(
            {"titulo": "x", "url": "https://x", "web_editorial": {"title": "T", "lead": "L"}}
        )
        self.assertEqual({"title": "T", "lead": "L"}, item["web_editorial"])


if __name__ == "__main__":
    unittest.main()
