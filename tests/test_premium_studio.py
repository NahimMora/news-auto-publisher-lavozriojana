from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.premium_contract import (
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
    for _ in range(2):
        add_slide(pkg, "image_text", title="Slide", text="texto")
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

    def test_duplicate_and_remove_respect_slide_limits(self):
        pkg = _package()
        from utils.premium_contract import duplicate_slide, MIN_SLIDES

        slide_id = pkg["slides"][0]["id"]
        duplicate_slide(pkg, slide_id)
        self.assertEqual(3, len(pkg["slides"]))
        remove_slide(pkg, pkg["slides"][-1]["id"])
        self.assertEqual(MIN_SLIDES, len(pkg["slides"]))
        with self.assertRaises(Exception):
            remove_slide(pkg, pkg["slides"][-1]["id"])

    def test_change_slide_type_rejects_unknown_type(self):
        pkg = _package()
        with self.assertRaises(ValueError):
            change_slide_type(pkg, pkg["slides"][0]["id"], "not_a_type")


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


if __name__ == "__main__":
    unittest.main()
