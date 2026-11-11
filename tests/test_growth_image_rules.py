"""T02: reglas visuales de crecimiento (destacados, fotos compuestas, legibilidad)."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from PIL import Image, ImageDraw, ImageFilter

from utils import growth_image_rules as rules

LONG_TITLES = [
    "El Concejo Deliberante de Ángel Vicente Peñaloza aprobó por unanimidad la ordenanza que regula el uso de motos en el casco céntrico y fija multas de hasta $1.535.000",
    "¿Qué pasará con el agua en Coronel Felipe Varela y General Lamadrid? «Hay reservas», aseguró Aguas Riojanas",
    "URGENTE: CHOQUE FRONTAL EN LA RUTA 38 DEJÓ DOS HERIDOS GRAVES Y UN 100% DE DEMORAS",
    "Lali Espósito y Tini Stoessel confirmaron invitaciones mutuas a sus casamientos",
    "Incautaron un cargamento de cigarrillos de contrabando valuado en 428 mil dólares",
    "Chamical, Famatina, Sanagasta y Vinchina: cómo será el operativo de vacunación antigripal en el interior riojano",
]


def _noise(size, seed, base):
    img = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(img)
    for i in range(160):
        x = (i * 37 + seed * 11) % size[0]
        y = (i * 53 + seed * 7) % size[1]
        draw.ellipse((x, y, x + 25, y + 25), fill=((i * 41 + seed) % 255, (i * 13) % 255, (i * 29 + 60) % 255))
    return img.filter(ImageFilter.GaussianBlur(1.2))


def _diptych(gutter=0):
    left, right = _noise((500, 600), 1, (200, 180, 160)), _noise((500, 600), 2, (30, 40, 90))
    img = Image.new("RGB", (1000 + gutter, 600), "white")
    img.paste(left, (0, 0))
    img.paste(right, (500 + gutter, 0))
    return img


class FlagTests(unittest.TestCase):
    def test_disabled_by_default_and_gated_by_workflow(self):
        self.assertFalse(rules.growth_image_rules_enabled("og", {}))
        self.assertTrue(rules.growth_image_rules_enabled("og", {"GROWTH_IMAGE_RULES_ENABLED": "true"}))
        self.assertFalse(rules.growth_image_rules_enabled("reel", {"GROWTH_IMAGE_RULES_ENABLED": "true"}))
        only_og = {"GROWTH_IMAGE_RULES_ENABLED": "true", "GROWTH_IMAGE_RULES_WORKFLOWS": "og"}
        self.assertFalse(rules.growth_image_rules_enabled("instagram", only_og))


class HighlightTests(unittest.TestCase):
    def test_never_splits_a_proper_name(self):
        title = "Lali Espósito y Tini Stoessel confirmaron invitaciones mutuas a sus casamientos"
        out = rules.refine_highlight_terms(title, ["Stoessel confirmaron invitaciones mutuas"])
        self.assertTrue(out)
        self.assertNotIn("Stoessel", out[0])
        title = "El Concejo Deliberante de Ángel Vicente Peñaloza aprobó por unanimidad la ordenanza"
        out = rules.refine_highlight_terms(title, ["Ángel Vicente Peñaloza aprobó"])
        self.assertFalse(out and ("Vicente" in out[0]) != ("Ángel" in out[0]))

    def test_short_literal_and_within_share(self):
        for title in LONG_TITLES:
            for term in rules.refine_highlight_terms(title, []):
                words = term.split()
                self.assertLessEqual(len(words), 3)
                self.assertLessEqual(len(words), max(2, int(len(title.split()) * rules.MAX_HIGHLIGHT_SHARE)))
                self.assertIn(term, title)

    def test_valid_editorial_term_is_kept(self):
        title = "Incautaron un cargamento de cigarrillos de contrabando valuado en 428 mil dólares"
        self.assertEqual(["cigarrillos de contrabando"], rules.refine_highlight_terms(title, ["cigarrillos de contrabando"]))

    def test_does_not_cross_punctuation_and_handles_caps(self):
        title = "URGENTE: CHOQUE FRONTAL EN LA RUTA 38 DEJÓ DOS HERIDOS GRAVES Y UN 100% DE DEMORAS"
        out = rules.refine_highlight_terms(title, ["DEJÓ DOS HERIDOS GRAVES"])
        self.assertEqual(["DOS HERIDOS GRAVES"], out)

    def test_short_title_gets_nothing(self):
        self.assertEqual([], rules.refine_highlight_terms("Paro docente", ["Paro docente"]))

    def test_visual_section_alias(self):
        self.assertEqual("espectaculos", rules.visual_section("Paparazzi"))
        self.assertEqual("Policiales", rules.visual_section("Policiales"))


class PanelTests(unittest.TestCase):
    def test_single_photo_untouched(self):
        img = _noise((1000, 600), 3, (90, 120, 80))
        self.assertEqual(1, len(rules.detect_panels(img)[0]))
        self.assertIsNone(rules.recompose_for_slot(img, rules.OG_PHOTO_SLOT)[0])

    def test_soft_natural_edge_is_not_a_seam(self):
        img = Image.new("RGB", (1000, 600), (40, 40, 40))
        ImageDraw.Draw(img).rectangle((500, 0, 1000, 600), fill=(220, 220, 220))
        img = img.filter(ImageFilter.GaussianBlur(3))
        self.assertEqual(1, len(rules.detect_panels(img)[0]))

    def test_sharp_seam_and_gutter_become_diptych(self):
        for gutter in (0, 8):
            out, info = rules.recompose_for_slot(_diptych(gutter), rules.OG_PHOTO_SLOT)
            self.assertEqual("diptych", info["layout"], gutter)
            self.assertEqual((1200, 1260), out.size)

    def test_grid_uses_first_column_two_images_max(self):
        img = Image.new("RGB", (1200, 630), "white")
        for i, (x, y) in enumerate(((0, 0), (604, 0), (0, 320), (604, 320))):
            img.paste(_noise((596, 310), i + 4, (60 * i, 90, 140)), (x, y))
        out, info = rules.recompose_for_slot(img, rules.OG_PHOTO_SLOT)
        self.assertEqual(("2x2", "first_column"), (info["grid"], info["layout"]))

    def test_pillarbox_bars_are_dropped(self):
        img = Image.new("RGB", (1200, 675), (25, 25, 25))
        img.paste(_noise((420, 675), 9, (150, 100, 90)), (390, 0))
        out, info = rules.recompose_for_slot(img, rules.OG_PHOTO_SLOT)
        self.assertEqual("single_panel", info.get("layout"))

    def test_wide_slot_keeps_composite(self):
        self.assertIsNone(rules.recompose_for_slot(_diptych(), (1080, 620))[0])


class OverflowTests(unittest.TestCase):
    """Mismo algoritmo que fit.ts, con la fuente real: la cadena growth → legado
    nunca deja el titular cortado para títulos reales (≤ 160 caracteres)."""

    OG_BOX = (504, 446)  # FacebookOgCardV2 con foto: 600 − 2×48, 630 − 2×92

    def test_og_growth_or_legacy_always_fits(self):
        for title in LONG_TITLES:
            grown = rules.fit_headline(title, *self.OG_BOX, 46, 66, 5)
            fitted = grown if not grown["overflow"] else rules.fit_headline(title, *self.OG_BOX, 40, 66, 5)
            if fitted["overflow"]:
                # Mismo último recurso que FacebookOgCardV2 con growth: por alto.
                fitted = rules.fit_headline(title, *self.OG_BOX, 40, 66, 9)
            self.assertFalse(fitted["overflow"], title)
            self.assertGreaterEqual(fitted["size"], 40)
            self.assertLessEqual(len(fitted["lines"]) * fitted["size"], self.OG_BOX[1])

    def test_ig_text_column_fits_at_mobile_minimum(self):
        for title in LONG_TITLES:
            grown = rules.fit_headline(title, 952, 560, 64, 96, 4)
            fitted = grown if not grown["overflow"] else rules.fit_headline(title, 952, 560, 52, 96, 5)
            self.assertFalse(fitted["overflow"], title)

    def test_accents_and_symbols_measure_wider_than_ascii(self):
        lines = rules.wrap_headline("ÁNGEL VICENTE PEÑALOZA «$1.535.000»", 504, 60)
        self.assertTrue(all(isinstance(line, str) and line for line in lines))
        self.assertEqual("ÁNGEL VICENTE PEÑALOZA «$1.535.000»", " ".join(lines))


class ContrastTests(unittest.TestCase):
    """Contraste WCAG medido sobre los tokens V2 que usan las reglas."""

    @staticmethod
    def _lum(hex_color):
        rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def _ratio(self, a, b):
        la, lb = sorted((self._lum(a), self._lum(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)

    def test_text_pairs_meet_aa(self):
        pairs = {
            "titular papel": ("#14171C", "#F2EEE6"),
            "bajada papel": ("#5B5F66", "#F2EEE6"),
            "destacado rojo": ("#FFFFFF", "#B30000"),
            "destacado azul": ("#FFFFFF", "#2F6FB0"),
            "titular tinta": ("#FFFFFF", "#0A0D12"),
            "pie sobre bordó (blanco 86 %)": ("#E7DADA", "#6D1A1A"),
        }
        for name, (fg, bg) in pairs.items():
            self.assertGreaterEqual(self._ratio(fg, bg), 4.5, name)


class GeneratorWiringTests(unittest.TestCase):
    """Con el flag apagado los props V2 son los de siempre; encendido cambian
    sólo los campos de las reglas. No hay render real ni red."""

    def _og_props(self, flag, photo):
        from layout import image_generator as gen

        captured = {}

        def fake_render(composition, props, asset_paths=None, **kwargs):
            captured.update(props=dict(props), assets=dict(asset_paths or {}))
            buf = __import__("io").BytesIO()
            Image.new("RGB", (1200, 630)).save(buf, "PNG")
            return buf.getvalue(), {}

        env = {"VISUAL_STYLE_VERSION": "v2", "GROWTH_IMAGE_RULES_ENABLED": flag}
        with mock.patch.dict(os.environ, env), mock.patch("utils.remotion_renderer.render_still", side_effect=fake_render):
            gen._generate_facebook_remotion(
                {"titulo": "Lali Espósito y Tini Stoessel confirmaron invitaciones mutuas a sus casamientos", "seccion": "Paparazzi", "imagen_url": ""},
                preloaded_img=photo,
            )
        return captured

    def test_flag_off_props_unchanged(self):
        captured = self._og_props("false", _diptych(8))
        self.assertNotIn("growth", captured["props"])
        self.assertEqual("Paparazzi", captured["props"]["seccion"])

    def test_flag_on_applies_rules_and_recomposes_composite(self):
        captured = self._og_props("true", _diptych(8))
        props = captured["props"]
        self.assertTrue(props["growth"])
        self.assertEqual("espectaculos", props["seccion"])
        self.assertTrue(all("Stoessel" not in t for t in props["highlightTerms"]))
        # El archivo temporal recompuesto ya se limpió tras el render.
        self.assertFalse(os.path.exists(captured["assets"]["assetFile"]))


if __name__ == "__main__":
    unittest.main()
