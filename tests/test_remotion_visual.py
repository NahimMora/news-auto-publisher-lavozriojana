from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

REMOTION_SRC = Path(__file__).resolve().parents[1] / "remotion" / "src"


def _read(relative: str) -> str:
    return (REMOTION_SRC / relative).read_text(encoding="utf-8")


class NoGoldInTokensTests(unittest.TestCase):
    def test_constants_do_not_declare_gold(self):
        source = _read("constants.ts")
        self.assertNotIn("GOLD", source)
        self.assertNotIn("#F6C343", source)

    def test_main_does_not_import_or_use_gold(self):
        source = _read("Main.tsx")
        self.assertNotIn("GOLD", source)

    def test_official_palette_tokens_are_declared(self):
        source = _read("constants.ts")
        for token in ("ROJO", "BORDO", "AZUL", "NEGRO", "WHITE"):
            self.assertIn(f"export const {token}", source)

    def test_new_compositions_do_not_reference_gold(self):
        for filename in ("PremiumSlide.tsx", "AutomaticInstagramCard.tsx", "FacebookOgCard.tsx", "shared/sectionColors.ts"):
            with self.subTest(file=filename):
                self.assertNotIn("GOLD", _read(filename))
                self.assertNotIn("#F6C343", _read(filename))


class ReelBackwardCompatibilityTests(unittest.TestCase):
    def test_main_schema_keeps_original_fields(self):
        source = _read("Main.tsx")
        for field in ("titulo:", "seccion:", "assetType:", "assetFile:", "kenBurnsVariant:", "durationInFrames:"):
            self.assertIn(field, source)

    def test_highlight_terms_is_optional_with_default(self):
        source = _read("Main.tsx")
        self.assertIn("highlightTerms: z.array(z.string()).optional().default([])", source)

    def test_root_default_props_include_highlight_terms(self):
        source = _read("Root.tsx")
        self.assertIn("highlightTerms: []", source)


class PremiumSlideSchemaTests(unittest.TestCase):
    def test_schema_covers_all_seven_slide_types(self):
        source = _read("PremiumSlide.tsx")
        for slide_type in ("cover", "image_text", "full_image", "key_points", "quote", "number", "closing"):
            self.assertIn(f'"{slide_type}"', source)

    def test_schema_has_highlight_terms_and_template(self):
        source = _read("PremiumSlide.tsx")
        self.assertIn("highlightTerms:", source)
        self.assertIn("lvr_cronica", source)
        self.assertIn("lvr_datos", source)
        self.assertIn("lvr_visual", source)


class HighlightedTitleUnitTests(unittest.TestCase):
    """Pruebas de la lógica de resaltado en JS, ejercitadas vía Node si está
    disponible; si no, se documenta como no ejecutado (nunca se inventa)."""

    def test_component_file_exists_and_exports_expected_symbol(self):
        source = _read("shared/HighlightedTitle.tsx")
        self.assertIn("export const HighlightedTitle", source)
        self.assertIn("highlightTerms", source)


class RemotionEngineDispatchTests(unittest.TestCase):
    """Pruebas puras de utils/remotion_renderer.py y utils/premium_renderer.py:
    no requieren Node, todas mockeadas."""

    def setUp(self):
        from utils import remotion_renderer

        remotion_renderer._availability_cache.clear()
        self.addCleanup(remotion_renderer._availability_cache.clear)

    def _clear_all_engine_vars(self):
        return patch.dict(
            os.environ,
            {
                "AUTOMATIC_STATIC_RENDER_ENGINE": "",
                "PREMIUM_STATIC_RENDER_ENGINE": "",
                "OG_STATIC_RENDER_ENGINE": "",
                "STATIC_RENDER_ENGINE": "",
            },
            clear=False,
        )

    def test_automatic_uses_auto_by_default_and_prefers_remotion_when_available(self):
        from utils.remotion_renderer import resolve_engine

        # Corrección 2026-07-31 (ver docs/DECISIONS.md "Editorial Cinemática
        # Riojana"): con el servidor de render persistente, "automatic" pasó
        # de "pillow" a "auto" — intenta Remotion primero y nunca bloquea la
        # publicación real si Remotion no está disponible.
        with self._clear_all_engine_vars(), patch("utils.remotion_renderer.remotion_available", return_value=True):
            self.assertEqual("remotion", resolve_engine("automatic"))

    def test_automatic_falls_back_to_pillow_when_remotion_unavailable(self):
        from utils.remotion_renderer import resolve_engine

        with self._clear_all_engine_vars(), patch("utils.remotion_renderer.remotion_available", return_value=False):
            self.assertEqual("pillow", resolve_engine("automatic"))

    def test_og_uses_pillow_by_default_without_any_variable(self):
        from utils.remotion_renderer import resolve_engine

        with self._clear_all_engine_vars(), patch("utils.remotion_renderer.remotion_available", return_value=True):
            self.assertEqual("pillow", resolve_engine("og"))

    def test_premium_uses_remotion_by_default_without_any_variable(self):
        from utils.remotion_renderer import resolve_engine

        with self._clear_all_engine_vars(), patch("utils.remotion_renderer.remotion_available", return_value=True):
            self.assertEqual("remotion", resolve_engine("premium"))

    def test_premium_default_reports_unavailable_explicitly_when_remotion_missing(self):
        from utils.remotion_renderer import resolve_engine

        with self._clear_all_engine_vars(), patch("utils.remotion_renderer.remotion_available", return_value=False):
            # El default de premium es "remotion" (no "auto"): sin Remotion, reporta
            # fallo explícito en vez de caer en silencio a Pillow.
            self.assertEqual("remotion_unavailable", resolve_engine("premium"))

    def test_workflow_specific_override_takes_precedence_over_default(self):
        from utils.remotion_renderer import resolve_engine

        with patch.dict(os.environ, {"AUTOMATIC_STATIC_RENDER_ENGINE": "remotion"}, clear=False), patch(
            "utils.remotion_renderer.remotion_available", return_value=True
        ):
            self.assertEqual("remotion", resolve_engine("automatic"))

    def test_workflow_specific_pillow_override_forces_pillow_without_checking_availability(self):
        from utils.remotion_renderer import resolve_engine

        with patch.dict(os.environ, {"PREMIUM_STATIC_RENDER_ENGINE": "pillow"}, clear=False), patch(
            "utils.remotion_renderer.remotion_available"
        ) as available:
            self.assertEqual("pillow", resolve_engine("premium"))
        available.assert_not_called()

    def test_legacy_static_render_engine_overrides_default_when_no_specific_var(self):
        from utils.remotion_renderer import resolve_engine

        with patch.dict(
            os.environ,
            {"STATIC_RENDER_ENGINE": "pillow", "PREMIUM_STATIC_RENDER_ENGINE": ""},
            clear=False,
        ):
            # Sin PREMIUM_STATIC_RENDER_ENGINE explícito, el legacy manda sobre el
            # default de premium ("remotion").
            self.assertEqual("pillow", resolve_engine("premium"))

    def test_specific_var_takes_precedence_over_legacy(self):
        from utils.remotion_renderer import resolve_engine

        with patch.dict(
            os.environ,
            {"STATIC_RENDER_ENGINE": "remotion", "AUTOMATIC_STATIC_RENDER_ENGINE": "pillow"},
            clear=False,
        ), patch("utils.remotion_renderer.remotion_available", return_value=True):
            # La variable específica del workflow gana sobre el legacy.
            self.assertEqual("pillow", resolve_engine("automatic"))

    def test_auto_mode_falls_back_to_pillow_when_unavailable(self):
        from utils.remotion_renderer import resolve_engine

        with patch.dict(os.environ, {"PREMIUM_STATIC_RENDER_ENGINE": "auto"}, clear=False), patch(
            "utils.remotion_renderer.remotion_available", return_value=False
        ):
            self.assertEqual("pillow", resolve_engine("premium"))

    def test_auto_mode_uses_remotion_when_available(self):
        from utils.remotion_renderer import resolve_engine

        with patch.dict(os.environ, {"PREMIUM_STATIC_RENDER_ENGINE": "auto"}, clear=False), patch(
            "utils.remotion_renderer.remotion_available", return_value=True
        ):
            self.assertEqual("remotion", resolve_engine("premium"))

    def test_explicit_remotion_mode_reports_unavailable_instead_of_silent_fallback(self):
        from utils.remotion_renderer import resolve_engine

        with patch.dict(os.environ, {"AUTOMATIC_STATIC_RENDER_ENGINE": "remotion"}, clear=False), patch(
            "utils.remotion_renderer.remotion_available", return_value=False
        ):
            self.assertEqual("remotion_unavailable", resolve_engine("automatic"))

    def test_invalid_workflow_name_raises(self):
        from utils.remotion_renderer import resolve_engine

        with self.assertRaises(ValueError):
            resolve_engine("not_a_real_workflow")

    def test_resolution_logs_workflow_engine_requested_engine_used_and_fallback_reason(self):
        from utils.remotion_renderer import resolve_engine

        with patch.dict(os.environ, {"AUTOMATIC_STATIC_RENDER_ENGINE": "auto"}, clear=False), patch(
            "utils.remotion_renderer.remotion_available", return_value=False
        ), self.assertLogs("remotion_renderer", level="INFO") as captured:
            resolve_engine("automatic")

        joined = "\n".join(captured.output)
        self.assertIn("workflow=automatic", joined)
        self.assertIn("engine_requested=auto", joined)
        self.assertIn("engine_used=pillow", joined)
        self.assertIn("fallback_reason=auto_mode_fallback_remotion_unavailable", joined)

    def test_render_package_with_engine_falls_back_to_pillow_on_remotion_error(self):
        from utils.premium_contract import add_slide, new_package
        from utils.premium_renderer import render_package_with_engine
        from utils.remotion_renderer import RemotionRenderError

        package = new_package(title="Nota de prueba", section="interior")
        add_slide(package, "closing", text="a")
        add_slide(package, "closing", text="b")

        with patch.dict(os.environ, {"STATIC_RENDER_ENGINE": "auto"}, clear=False), patch(
            "utils.remotion_renderer.remotion_available", return_value=True
        ), patch(
            "utils.premium_renderer.render_package_remotion",
            side_effect=RemotionRenderError("boom"),
        ):
            images, warnings, engine = render_package_with_engine(package)
        self.assertEqual("pillow", engine)
        self.assertEqual(2, len(images))

    def test_render_package_with_engine_uses_remotion_when_available(self):
        from utils.premium_contract import add_slide, new_package
        from utils.premium_renderer import render_package_with_engine

        package = new_package(title="Nota de prueba", section="interior")
        add_slide(package, "closing", text="a")
        add_slide(package, "closing", text="b")

        with patch.dict(os.environ, {"STATIC_RENDER_ENGINE": "auto"}, clear=False), patch(
            "utils.remotion_renderer.remotion_available", return_value=True
        ), patch(
            "utils.premium_renderer.render_package_remotion",
            return_value=([b"fake-png-bytes"] * 2, []),
        ) as remotion_mock:
            images, warnings, engine = render_package_with_engine(package)
        remotion_mock.assert_called_once()
        self.assertEqual("remotion", engine)
        self.assertEqual([b"fake-png-bytes"] * 2, images)

    def test_explicit_remotion_mode_raises_when_unavailable(self):
        from utils.premium_contract import add_slide, new_package
        from utils.premium_renderer import render_package_with_engine
        from utils.remotion_renderer import RemotionRenderError

        package = new_package(title="Nota", section="interior")
        add_slide(package, "closing")
        add_slide(package, "closing")

        with patch.dict(os.environ, {"STATIC_RENDER_ENGINE": "remotion"}, clear=False), patch(
            "utils.remotion_renderer.remotion_available", return_value=False
        ):
            with self.assertRaises(RemotionRenderError):
                render_package_with_engine(package)


@unittest.skipUnless(
    str(os.getenv("REMOTION_LIVE_TESTS", "auto")).strip().lower() != "skip"
    and (REMOTION_SRC.parent / "node_modules").is_dir(),
    "remotion/node_modules no está instalado en este entorno; se omite el render real "
    "(set REMOTION_LIVE_TESTS=skip para omitir explícitamente aunque esté instalado)",
)
class RemotionLiveRenderTests(unittest.TestCase):
    """Renders reales contra el CLI de Remotion (Node). Se documentan como
    ejecutados sólo si esta clase efectivamente corrió — ver docs/METRICS.md
    y el benchmark de Fase 4 para tiempos medidos."""

    @classmethod
    def setUpClass(cls):
        from utils.remotion_renderer import remotion_available

        if not remotion_available(force_recheck=True):
            raise unittest.SkipTest("Remotion CLI no respondió (Node/npx no operativo en este entorno)")

    def test_premium_slide_renders_with_highlight_terms_and_long_title(self):
        from utils.remotion_renderer import render_still

        long_title = (
            "La Municipalidad de Chilecito anunció un plan integral de obras "
            "públicas que incluye pavimentación, alumbrado y desagües en varios "
            "barrios durante los próximos meses"
        )
        png_bytes, metadata = render_still(
            "PremiumSlide",
            {
                "slideType": "closing",
                "template": "lvr_datos",
                "title": long_title,
                "text": long_title,
                "items": [],
                "highlightTerms": ["Chilecito", "obras"],
                "assetFile": "",
                "section": "interior",
                "index": 1,
                "total": 1,
            },
        )
        self.assertTrue(png_bytes.startswith(b"\x89PNG"))
        self.assertEqual("remotion", metadata["engine"])
        self.assertGreater(metadata["duration_seconds"], 0)

    def test_automatic_instagram_card_renders(self):
        from utils.remotion_renderer import render_still

        png_bytes, _metadata = render_still(
            "AutomaticInstagramCard",
            {
                "titulo": "Un incendio afecta un comercio en Chilecito",
                "seccion": "interior",
                "assetFile": "",
                "highlightTerms": ["incendio", "Chilecito"],
            },
        )
        self.assertTrue(png_bytes.startswith(b"\x89PNG"))

    def test_facebook_og_card_renders(self):
        from utils.remotion_renderer import render_still

        png_bytes, _metadata = render_still(
            "FacebookOgCard",
            {
                "titulo": "Un incendio afecta un comercio en Chilecito",
                "seccion": "interior",
                "assetFile": "",
                "highlightTerms": [],
            },
        )
        self.assertTrue(png_bytes.startswith(b"\x89PNG"))

    def test_full_package_render_via_engine_dispatch_uses_remotion(self):
        from utils.premium_contract import add_slide, new_package
        from utils.premium_renderer import render_package_with_engine

        package = new_package(title="Nota de prueba en vivo", section="interior")
        package["highlight_terms"] = ["prueba"]
        add_slide(package, "closing", text="Gracias por leernos")
        add_slide(package, "key_points", title="Puntos", items=["Uno", "Dos"])

        with patch.dict(os.environ, {"STATIC_RENDER_ENGINE": "remotion"}, clear=False):
            images, warnings, engine = render_package_with_engine(package)
        self.assertEqual("remotion", engine)
        self.assertEqual(2, len(images))
        for image_bytes in images:
            self.assertTrue(image_bytes[:2] == b"\xff\xd8")  # JPEG magic (convertido desde PNG)


if __name__ == "__main__":
    unittest.main()
