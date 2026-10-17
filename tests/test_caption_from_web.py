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
        self.assertIn("📲 Nota completa en lavozriojana.com", caption)
        self.assertNotIn("CAPTION VIEJO", caption)
        self.assertTrue(caption.rstrip().endswith("#Noticias"))

    def test_chip_key_points_are_not_listed_as_bullets(self):
        # Caso real 03/10: la web guarda chips ("Policiales", "La Rioja") y
        # frases cortadas por clean_text; no son puntos clave para el caption.
        noticia = _noticia()
        noticia["web_editorial"]["key_points"] = [
            "Policiales",
            "La Rioja",
            "Teresita Madera",
            "Convenio de cooperación ambient...",
        ]
        self.assertNotIn("▪️", self._build(noticia))

    def test_point_repeating_the_lead_is_dropped(self):
        # Caso real Chepes: "272 aniversario de Chepes." solo, repitiendo el lead.
        noticia = _noticia()
        noticia["web_editorial"]["lead"] = "Quintela visitó Chepes por su 272 aniversario."
        noticia["web_editorial"]["key_points"] = ["272 aniversario de Chepes.", "La obra demandó tres meses."]
        self.assertNotIn("▪️", self._build(noticia))

    def test_truncated_lead_is_cut_to_whole_sentences(self):
        noticia = _noticia()
        noticia["web_editorial"]["lead"] = (
            "Un total de 272 efectivos se sumaron este viernes. El acto marcó la "
            "incorporación de personal bajo un esquema que prioriza la presencia te..."
        )
        caption = self._build(noticia)
        self.assertIn("Un total de 272 efectivos se sumaron este viernes.\n", caption)
        self.assertNotIn("presencia", caption)

    def test_long_lead_without_period_cuts_on_whole_word(self):
        noticia = _noticia()
        noticia["web_editorial"]["lead"] = "palabra " * 200
        self.assertIn("palabra…", self._build(noticia))

    def test_source_fallback_uses_previous_caption(self):
        # Caso China Suárez: el fallback web publicó el primer párrafo crudo,
        # ajeno al título. Redes vuelven al caption propio.
        noticia = _noticia()
        noticia["web_editorial"]["source_fallback"] = True
        self.assertTrue(self._build(noticia).startswith("📢🗞️ CAPTION VIEJO"))

    def test_question_gets_opening_mark(self):
        caption = self._build(_noticia(cta="Qué medidas tomás en tu casa?"))
        self.assertIn("💬 ¿Qué medidas tomás en tu casa?", caption)

    def test_hashtags_are_not_repeated(self):
        caption = self._build(_noticia(hashtag_localidad="#LaRioja"))
        tags = caption.rsplit("\n\n", 1)[1].split()
        self.assertEqual(len(tags), len({tag.casefold() for tag in tags}))
        self.assertEqual("#LaRioja", tags[0])

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

    def test_snapshot_marks_source_fallback_only(self):
        from pipeline.node_webapp.publisher import _web_editorial_snapshot

        base = dict(title="T", lead="L", key_points=[])
        source = SimpleNamespace(**base, fallback_used=True, final_attempt_used=False)
        final = SimpleNamespace(**base, fallback_used=True, final_attempt_used=True)
        self.assertTrue(_web_editorial_snapshot(source)["source_fallback"])
        self.assertNotIn("source_fallback", _web_editorial_snapshot(final))

    def test_meta_normalization_preserves_web_editorial(self):
        from openIA import rewrite_news

        item = rewrite_news.build_meta_item(
            {"titulo": "x", "url": "https://x", "web_editorial": {"title": "T", "lead": "L"}}
        )
        self.assertEqual({"title": "T", "lead": "L"}, item["web_editorial"])


if __name__ == "__main__":
    unittest.main()
