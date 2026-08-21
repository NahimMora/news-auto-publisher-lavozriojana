from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from utils.premium_contract import (
    DuplicateSlideTypeError,
    add_slide,
    change_slide_type,
    move_slide_down,
    move_slide_up,
    new_package,
    remove_slide,
    validate_highlight_terms,
    validate_package,
)
from utils.premium_importer import import_chatgpt_package


def _package(**overrides):
    pkg = new_package(title="Un festival cultural en Chilecito", caption="Caption sin link", section="cultura")
    add_slide(pkg, "image_text", title="Slide", text="texto")
    add_slide(pkg, "context", title="Contexto", text="texto")
    pkg.update(overrides)
    return pkg


class PremiumContractTests(unittest.TestCase):
    def test_valid_package_has_no_errors(self):
        pkg = _package()
        pkg["slides"][0]["asset_id"] = "asset-1"
        pkg["slides"][1]["asset_id"] = "asset-2"
        errors, _warnings = validate_package(pkg)
        self.assertEqual([], errors)

    def test_slide_count_out_of_range_is_an_error(self):
        pkg = new_package(title="X")
        add_slide(pkg, "image_text")  # sólo 1, mínimo es 2 -> forzamos con append directo
        pkg["slides"] = pkg["slides"][:1]
        errors, _warnings = validate_package(pkg)
        self.assertTrue(any("cantidad_de_slides_fuera_de_rango" in e for e in errors))

    def test_highlight_term_not_in_title_is_a_warning(self):
        warnings = validate_highlight_terms("Un incendio en Chilecito", ["inexistente"])
        self.assertTrue(any("highlight_term_inexistente_en_titulo" in w for w in warnings))

    def test_highlight_terms_within_title_produce_no_warning(self):
        warnings = validate_highlight_terms("Un incendio en Chilecito", ["incendio", "Chilecito"])
        self.assertEqual([], [w for w in warnings if "inexistente" in w])

    def test_reordering_moves_slide_up_and_down(self):
        pkg = _package()
        pkg["slides"][0]["text"] = "primero"
        pkg["slides"][1]["text"] = "segundo"
        first_id = pkg["slides"][0]["id"]
        move_slide_down(pkg, first_id)
        self.assertEqual("segundo", pkg["slides"][0]["text"])
        move_slide_up(pkg, first_id)
        self.assertEqual("primero", pkg["slides"][0]["text"])

    def test_duplicate_is_rejected_and_remove_respects_slide_limits(self):
        pkg = _package()
        from utils.premium_contract import duplicate_slide, MIN_SLIDES

        slide_id = pkg["slides"][0]["id"]
        with self.assertRaises(DuplicateSlideTypeError):
            duplicate_slide(pkg, slide_id)
        add_slide(pkg, "key_points")
        self.assertEqual(3, len(pkg["slides"]))
        remove_slide(pkg, pkg["slides"][-1]["id"])
        self.assertEqual(MIN_SLIDES, len(pkg["slides"]))
        with self.assertRaises(Exception):
            remove_slide(pkg, pkg["slides"][-1]["id"])

    def test_change_slide_type_rejects_unknown_type(self):
        pkg = _package()
        with self.assertRaises(ValueError):
            change_slide_type(pkg, pkg["slides"][0]["id"], "not_a_type")

    def test_repeated_slide_type_is_rejected_by_editing_and_validation(self):
        pkg = _package()
        first = pkg["slides"][0]

        with self.assertRaises(DuplicateSlideTypeError):
            change_slide_type(pkg, first["id"], "context")

        pkg["slides"].append(
            {
                **pkg["slides"][1],
                "id": "slide_tipo_repetido",
            }
        )
        errors, _warnings = validate_package(pkg)
        self.assertIn("slide_2_tipo_duplicado:context", errors)

    def test_change_to_text_only_slide_removes_stale_image(self):
        pkg = _package()
        slide = pkg["slides"][0]
        slide["asset_id"] = "asset-1"
        slide["asset_label"] = "Foto anterior"

        change_slide_type(pkg, slide["id"], "key_points")

        self.assertEqual("", slide["asset_id"])
        self.assertNotIn("asset_label", slide)


class PremiumImporterTests(unittest.TestCase):
    def test_valid_json_is_imported_with_slides(self):
        raw = json.dumps(
            {
                "title": "Un festival cultural en Chilecito",
                "caption": "Caption",
                "section": "cultura",
                "suggested_template": "lvr_visual",
                "slides": [
                    {"type": "cover", "text": "", "highlights": [], "asset_hint": "festival"},
                    {"type": "closing", "text": "Gracias por leernos"},
                ],
                "sources": ["https://fuente.example/nota"],
                "unknowns": [],
            }
        )
        package, errors, warnings = import_chatgpt_package(raw)
        self.assertIsNotNone(package)
        self.assertEqual([], errors)
        self.assertEqual(2, len(package["slides"]))
        self.assertEqual("lvr_visual", package["template"])

    def test_invalid_json_is_rejected_with_field_errors(self):
        package, errors, _warnings = import_chatgpt_package("{not valid json")
        self.assertIsNone(package)
        self.assertTrue(any("json_invalido" in e for e in errors))

    def test_missing_required_fields_are_reported(self):
        package, errors, _warnings = import_chatgpt_package(json.dumps({"caption": "sin titulo ni slides"}))
        self.assertIsNone(package)
        self.assertTrue(any("title" in e for e in errors))
        self.assertTrue(any("slides" in e for e in errors))

    def test_slide_count_out_of_range_is_flagged_but_draft_is_kept(self):
        raw = json.dumps(
            {
                "title": "Nota con una sola slide",
                "slides": [{"type": "cover", "text": ""}],
            }
        )
        package, errors, _warnings = import_chatgpt_package(raw)
        self.assertIsNotNone(package)  # no se pierde el contenido pegado
        self.assertTrue(any("cantidad_de_slides_fuera_de_rango" in e for e in errors))

    def test_repeated_slide_type_is_imported_only_as_invalid_draft(self):
        raw = json.dumps(
            {
                "title": "Nota con tipos repetidos",
                "slides": [
                    {"type": "cover", "text": "Portada"},
                    {"type": "context", "text": "Primer contexto"},
                    {"type": "context", "text": "Segundo contexto"},
                ],
            }
        )

        package, errors, _warnings = import_chatgpt_package(raw)

        self.assertIsNotNone(package)
        self.assertIn("slide_2_tipo_duplicado:context", errors)

    def test_unknown_slide_type_falls_back_to_image_text(self):
        raw = json.dumps(
            {
                "title": "Nota",
                "slides": [
                    {"type": "not_a_real_type", "text": "a"},
                    {"type": "closing", "text": "b"},
                ],
            }
        )
        package, _errors, warnings = import_chatgpt_package(raw)
        self.assertEqual("image_text", package["slides"][0]["type"])
        self.assertTrue(any("tipo_desconocido" in w for w in warnings))

    def test_text_only_slides_do_not_search_or_keep_image_suggestions(self):
        raw = json.dumps(
            {
                "title": "Nota",
                "slides": [
                    {"type": "cover", "asset_hint": "recinto legislativo"},
                    {"type": "closing", "asset_hint": "logo de cierre"},
                ],
            }
        )
        with patch(
            "utils.premium_importer._suggest_assets",
            return_value=[{"asset_id": "asset-1", "thumbnail": "/thumb.jpg"}],
        ) as suggest:
            package, _errors, warnings = import_chatgpt_package(raw)

        suggest.assert_called_once()
        self.assertEqual([{"asset_id": "asset-1", "thumbnail": "/thumb.jpg"}], package["slides"][0]["suggested_assets"])
        self.assertEqual([], package["slides"][1]["suggested_assets"])
        self.assertEqual("", package["slides"][1]["asset_hint"])
        self.assertFalse(any("slide_1_sin_sugerencia_de_imagen" in warning for warning in warnings))

    def test_impact_is_a_valid_text_only_slide(self):
        raw = json.dumps(
            {
                "title": "Nota",
                "slides": [
                    {"type": "cover", "asset_hint": "recinto legislativo"},
                    {"type": "impact", "title": "Impacto local", "text": "Desarrollo", "asset_hint": "no usar"},
                ],
            }
        )
        with patch("utils.premium_importer._suggest_assets", return_value=[]) as suggest:
            package, errors, _warnings = import_chatgpt_package(raw)

        self.assertEqual([], errors)
        self.assertEqual("impact", package["slides"][1]["type"])
        self.assertEqual("", package["slides"][1]["asset_hint"])
        self.assertEqual([], package["slides"][1]["suggested_assets"])
        suggest.assert_called_once()


class PremiumPostQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        self.patch = patch.dict(
            os.environ,
            {"LVR_DATA_DIR": str(self.data), "JSON_BACKUP_ENABLED": "false"},
            clear=False,
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_draft_survives_even_with_validation_errors(self):
        from utils.premium_post_queue import create_draft, get_package

        draft = create_draft(title="")  # inválido a propósito: sin título, sin slides
        recovered = get_package(draft["id"])
        self.assertIsNotNone(recovered)
        self.assertEqual(draft["id"], recovered["id"])

    def test_multiple_source_item_ids_round_trip(self):
        from utils.premium_post_queue import create_draft, get_package

        draft = create_draft(title="Nota", source_item_ids=["news:1", "news:2", "asset:3"])
        recovered = get_package(draft["id"])
        self.assertEqual(["news:1", "news:2", "asset:3"], recovered["source_item_ids"])

    def test_save_removes_images_from_text_only_slides(self):
        from utils.premium_contract import add_slide, new_package
        from utils.premium_post_queue import get_package, save_package

        package = new_package(title="Nota")
        add_slide(package, "cover", asset_id="asset-cover")
        add_slide(package, "closing", asset_id="asset-stale", asset_label="No corresponde")

        saved = save_package(package)
        recovered = get_package(saved["id"])

        self.assertEqual("asset-cover", recovered["slides"][0]["asset_id"])
        self.assertEqual("", recovered["slides"][1]["asset_id"])
        self.assertNotIn("asset_label", recovered["slides"][1])


class PremiumRendererAssetTests(unittest.TestCase):
    def test_text_only_slide_never_resolves_stale_asset(self):
        from utils.premium_renderer import render_slide

        resolver = Mock()
        package = new_package(title="Nota", section="sociedad")
        slide = {
            "id": "slide-texto",
            "type": "key_points",
            "title": "Puntos clave",
            "items": ["Primer punto"],
            "asset_id": "asset-stale",
        }

        _image, warnings = render_slide(slide, package, asset_resolver=resolver)

        resolver.assert_not_called()
        self.assertFalse(any("asset" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
