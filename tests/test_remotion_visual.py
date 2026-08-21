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

    def test_editorial_reel_is_additive_and_keeps_the_legacy_composition(self):
        root = _read("Root.tsx")
        reel = _read("EditorialReel.tsx")
        self.assertIn('id="Main"', root)
        self.assertIn('id="EditorialReel"', root)
        self.assertIn("EDITORIAL_OUTRO_FRAMES", root)
        self.assertIn("useFontsReady", reel)
        self.assertIn("AnimatedHeadline", reel)
        self.assertIn("modeFromSection", reel)
        self.assertIn("highlightTerms", reel)

    def test_editorial_reel_animations_are_frame_driven(self):
        source = _read("EditorialReel.tsx")
        self.assertIn("useCurrentFrame", source)
        self.assertIn("interpolate", source)
        self.assertIn("spring", source)
        self.assertNotIn("transition:", source)
        self.assertNotIn("animation:", source)

    def test_editorial_reel_reserves_large_readable_chrome(self):
        source = _read("EditorialReel.tsx")
        for contract in (
            "REEL_HEADER_H = 164",
            "REEL_SECTION_H = 78",
            "REEL_FOOTER_H = 104",
            "width: 74, height: 74",
            "fontSize: 35",
            "width: 42, height: 42",
            "fontSize: 31",
            "width: 38",
            "fontSize: 33",
        ):
            self.assertIn(contract, source)

    def test_compact_layout_groups_section_headline_and_footer(self):
        source = _read("EditorialReel.tsx")
        self.assertIn("fitCompactHeadline", source)
        self.assertGreaterEqual(source.count("maxWidth: 800"), 2)
        self.assertIn("compactPanelTop", source)
        self.assertIn("fittedHeadlineHeight(compactHeadlineFit)", source)
        self.assertIn("Math.max(375, panelHeight - 174)", source)
        self.assertIn('whiteSpace: "nowrap"', source)
        self.assertNotIn("HEADLINE_COMPACT_SCALE", source)


class PremiumSlideSchemaTests(unittest.TestCase):
    def test_schema_covers_all_supported_slide_types(self):
        source = _read("PremiumSlide.tsx")
        for slide_type in ("cover", "image_text", "full_image", "key_points", "quote", "number", "closing", "context", "impact"):
            self.assertIn(f'"{slide_type}"', source)

    def test_schema_has_highlight_terms_and_template(self):
        source = _read("PremiumSlide.tsx")
        self.assertIn("highlightTerms:", source)
        self.assertIn("lvr_cronica", source)
        self.assertIn("lvr_datos", source)
        self.assertIn("lvr_visual", source)

    def test_premium_and_automatic_share_the_same_mobile_readability_scale(self):
        # Piezas de una sola imagen (manuales o automáticas, ver
        # pipeline/custom_post.py y layout/image_generator.py) comparten
        # exactamente el mismo masthead/footer/tipografía que el carrusel
        # premium — decisión revertida el 2026-07-31 (antes AutomaticInstagramCard
        # no activaba esta escala). Nunca deben mostrar señal de deslizamiento:
        # son una sola pieza, no un carrusel.
        premium = _read("PremiumSlide.tsx")
        automatic = _read("AutomaticInstagramCard.tsx")

        self.assertIn("export const PREMIUM_HEADLINE_SCALE = 1.06", premium)
        self.assertIn("PREMIUM_BODY_SCALE = 1.14", premium)
        self.assertIn("export const PREMIUM_MASTHEAD_H = 108", premium)
        self.assertIn("export const PREMIUM_FOOTER_H = 96", premium)
        self.assertIn("export const PREMIUM_CHROME_SCALE = 1.18", premium)
        self.assertIn("fontScale={PREMIUM_HEADLINE_SCALE}", premium)
        self.assertIn("mastheadHeight={PREMIUM_MASTHEAD_H}", premium)
        self.assertIn("footerHeight={PREMIUM_FOOTER_H}", premium)
        self.assertIn("chromeScale={PREMIUM_CHROME_SCALE}", premium)

        self.assertIn('from "./PremiumSlide"', automatic)
        self.assertIn("fontScale={PREMIUM_HEADLINE_SCALE}", automatic)
        self.assertIn("mastheadHeight={PREMIUM_MASTHEAD_H}", automatic)
        self.assertIn("footerHeight={PREMIUM_FOOTER_H}", automatic)
        self.assertIn("chromeScale={PREMIUM_CHROME_SCALE}", automatic)
        self.assertNotIn("showSwipeCue=", automatic)
        self.assertNotIn("total=", automatic)

    def test_automatic_card_has_full_width_title_locality_deck_and_social_footer(self):
        # Feedback puntual sobre AutomaticInstagramCard (piezas de una sola
        # imagen): título angosto/alineado a la derecha en modo Editorial
        # (sin motivo, Premium no lo hace), título pegado contra la foto
        # (maxHeight no restaba el padding real), sin chip de lugar/bajada
        # y sin firma social en el footer.
        automatic = _read("AutomaticInstagramCard.tsx")

        # Ancho/alineación: ya no debe reducir el ancho a 80% ni alinear a
        # la derecha el título de la card automática.
        self.assertNotIn("width * 0.8", automatic)
        self.assertNotIn('align="right"', automatic)
        self.assertNotIn("align: \"right\"", automatic)

        # Posición: maxHeight debe restar el mismo padding vertical que se
        # aplica al panel, no un valor fijo que desincronice el presupuesto.
        self.assertIn("panelH - panelPadY * 2", automatic)
        self.assertNotIn("panelH - 60", automatic)

        # Localidad (chip) + bajada (deck), completados por IA.
        self.assertIn("locality: z.string().default(\"\")", automatic)
        self.assertIn("deck: z.string().default(\"\")", automatic)
        self.assertIn("ContextChip", automatic)
        self.assertIn("deck={deck}", automatic)

        # Footer con firma social en vez de crédito de fuente.
        self.assertIn("showSocialFooter", automatic)

    def test_automatic_card_reserves_chip_height_before_overflowing_footer(self):
        # Feedback: "el título no se sobreponga al footer" — cuando hay chip
        # de localidad, su alto (+ el gap) tiene que restarse del
        # presupuesto del título en las tres composiciones (sin imagen,
        # crónica con imagen, editorial con imagen); si no, el conjunto
        # chip+título puede terminar más alto que el panel disponible.
        automatic = _read("AutomaticInstagramCard.tsx")
        self.assertIn("CHIP_H", automatic)
        self.assertIn("chipReserve", automatic)
        self.assertIn("overflow: \"hidden\"", automatic)

    def test_manual_panel_vertical_air_tracks_gradient_height(self):
        automatic = _read("AutomaticInstagramCard.tsx")
        self.assertIn("targetTitle.lines.length * targetTitle.lineHeightPx", automatic)
        self.assertIn("MANUAL_PANEL_MIN_H", automatic)
        self.assertIn("MANUAL_PANEL_MAX_H", automatic)
        self.assertIn("Math.round(panelH * 0.075)", automatic)
        self.assertIn("Math.max(36, Math.min(48", automatic)
        self.assertIn(": pad;", automatic)
        self.assertIn('manualPublication ? "center" : "flex-end"', automatic)

    def test_manual_publication_auto_fits_full_title_and_boxes_the_section(self):
        automatic = _read("AutomaticInstagramCard.tsx")
        headline = _read("shared/editorial/HeadlineBlock.tsx")
        masthead = _read("shared/editorial/EditorialMasthead.tsx")

        # La UI limita a 120 caracteres. El estilo manual reserva un panel
        # más alto, permite cinco líneas y baja el tamaño antes de recurrir
        # a la elipsis; el default automático conserva su geometría previa.
        self.assertIn('publicationStyle: z.enum(["automatic", "manual_publication"]).default("automatic")', automatic)
        self.assertIn("const MANUAL_PHOTO_MIN_H = 700", automatic)
        self.assertIn("const MANUAL_PANEL_MIN_H = 260", automatic)
        self.assertIn("MANUAL_TITLE_MIN_FONT_SIZE = 32", automatic)
        self.assertIn("manualPublication ? 5 : 3", automatic)
        self.assertIn("manualPublication ? 5 : 4", automatic)
        self.assertIn("manualPublication ? MANUAL_TITLE_MIN_FONT_SIZE : undefined", automatic)
        self.assertIn("minFontSize?: number", headline)

        # La sección manual usa la bandera/recuadro Premium, con el accent
        # del modo (rojo Crónica o azul Editorial).
        self.assertIn("boxedSection={manualPublication}", automatic)
        self.assertIn('mode.grid === "diagonal" || boxedSection', masthead)
        self.assertIn('SECTION_BLUE_DARK = "#0B2F4F"', _read("shared/designSystem.ts"))
        self.assertIn('mode.grid === "column" ? SECTION_BLUE_DARK : mode.accent', masthead)
        self.assertIn("backgroundColor: sectionBackground", masthead)

        # La frase relevante usa exactamente el mismo color de acento.
        self.assertIn("highlightColor={mode.accent}", headline)

    def test_og_card_headline_fits_its_own_short_panel(self):
        # El lienzo 1200x630 es mucho más bajo: reusar el padding/escala de
        # marca (pensados para 1080x1350) hacía que el título desbordara el
        # panel y se superpusiera al footer. FacebookOgCard usa su propia
        # escala tipográfica (OG_HEADLINE_SCALE) y comprime el padding.
        og = _read("FacebookOgCard.tsx")
        self.assertIn("OG_HEADLINE_SCALE", og)
        self.assertIn("mode.pad * 0.75", og)
        self.assertIn("overflow: \"hidden\"", og)
        self.assertNotIn("width * 0.8", og)
        self.assertNotIn('align="right"', og)
        # Chrome más grande (feedback: "la sección que se vea como las de
        # estudio premium" — antes 0.82 se veía chico).
        self.assertIn("OG_CHROME_SCALE = 1.05", og)
        self.assertIn("OG_MASTHEAD_H = 92", og)
        self.assertIn("OG_FOOTER_H = 78", og)
        self.assertIn('publicationStyle: z.enum(["automatic", "manual_publication"]).default("automatic")', og)
        self.assertIn('boxedSection={publicationStyle === "manual_publication"}', og)

    def test_still_layout_supports_optional_social_footer_without_affecting_premium(self):
        still_layout = _read("shared/StillLayout.tsx")
        premium = _read("PremiumSlide.tsx")
        self.assertIn("showSocialFooter", still_layout)
        self.assertIn("SocialFooter", still_layout)
        # PremiumSlide nunca activa el footer social — su footer sigue
        # siendo crédito de fuente + deslizamiento + numeración.
        self.assertNotIn("showSocialFooter", premium)


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

    def test_og_uses_auto_by_default_and_prefers_remotion_when_available(self):
        from utils.remotion_renderer import resolve_engine

        # Corrección 2026-07-31 (segunda ronda, ver docs/DECISIONS.md): "og"
        # sigue el mismo camino que "automatic" — intenta Remotion primero
        # (tarjeta FacebookOgCard) y nunca bloquea la publicación web real si
        # Remotion no está disponible.
        with self._clear_all_engine_vars(), patch("utils.remotion_renderer.remotion_available", return_value=True):
            self.assertEqual("remotion", resolve_engine("og"))

    def test_og_falls_back_to_pillow_when_remotion_unavailable(self):
        from utils.remotion_renderer import resolve_engine

        with self._clear_all_engine_vars(), patch("utils.remotion_renderer.remotion_available", return_value=False):
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

    def test_render_still_forwards_validated_scale_to_persistent_server(self):
        from utils.remotion_renderer import render_still

        with patch(
            "utils.remotion_renderer._render_still_via_server",
            return_value=(b"png", {"engine": "remotion"}),
        ) as server, patch("utils.remotion_renderer._render_still_via_subprocess") as subprocess_render:
            render_still("AutomaticInstagramCard", {}, scale=2)

        self.assertEqual(server.call_args.kwargs["scale"], 2.0)
        subprocess_render.assert_not_called()

    def test_render_still_rejects_unsafe_scale(self):
        from utils.remotion_renderer import render_still

        for invalid_scale in (0, 4.1, "no-es-numero", float("nan")):
            with self.subTest(scale=invalid_scale), self.assertRaises(ValueError):
                render_still("AutomaticInstagramCard", {}, scale=invalid_scale)

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
        add_slide(package, "context", title="Contexto", text="b")

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
        add_slide(package, "context", title="Contexto", text="b")

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
        add_slide(package, "context", title="Contexto")

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
                "slideType": "impact",
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
