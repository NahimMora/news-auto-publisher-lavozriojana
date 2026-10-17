import json
import unittest
from pathlib import Path

from utils.visual_v2_props import highlight_terms_for, instagram_props_v2, og_props_v2, phrase_in_title, reel_props_v2
from utils.visual_version import composition_for, resolve_visual_version

ROOT = Path(__file__).resolve().parent.parent


class VisualVersionSelectorTests(unittest.TestCase):
    def test_default_is_v1_with_current_compositions(self):
        for workflow, expected in (("reel", "EditorialReel"), ("instagram", "AutomaticInstagramCard"), ("og", "FacebookOgCard")):
            decision = resolve_visual_version(workflow, values={})
            self.assertEqual(decision.version, "v1")
            self.assertEqual(decision.composition, expected)
            self.assertEqual(decision.source, "default")

    def test_reel_v1_respects_legacy_cinematic_flag(self):
        self.assertEqual(resolve_visual_version("reel", values={}, reel_cinematic=False).composition, "Main")

    def test_global_v2_applies_to_all_three_workflows(self):
        env = {"VISUAL_STYLE_VERSION": "v2"}
        comps = {w: resolve_visual_version(w, values=env).composition for w in ("reel", "instagram", "og")}
        self.assertEqual(comps, {"reel": "EditorialReelV2", "instagram": "AutomaticInstagramCardV2", "og": "FacebookOgCardV2"})

    def test_divergence_requires_explicit_workflow_variable(self):
        env = {"VISUAL_STYLE_VERSION": "v2", "OG_VISUAL_STYLE_VERSION": "v1"}
        self.assertEqual(resolve_visual_version("instagram", values=env).version, "v2")
        og = resolve_visual_version("og", values=env)
        self.assertEqual((og.version, og.source), ("v1", "OG_VISUAL_STYLE_VERSION"))

    def test_invalid_values_fall_back_to_v1(self):
        env = {"VISUAL_STYLE_VERSION": "v3", "REEL_VISUAL_STYLE_VERSION": "nueva"}
        self.assertEqual(resolve_visual_version("reel", values=env).version, "v1")

    def test_pinned_item_keeps_version_during_processing(self):
        item = {"visual_style_version": "v1"}
        decision = resolve_visual_version("instagram", item, values={"VISUAL_STYLE_VERSION": "v2"})
        self.assertEqual(decision.version, "v1")
        self.assertIn("fijada", decision.source)

    def test_explicit_rollback_wins_over_v2_pin(self):
        item = {"visual_style_version": "v2"}
        decision = resolve_visual_version("reel", item, values={"VISUAL_STYLE_VERSION": "v1"})
        self.assertEqual(decision.version, "v1")
        self.assertIn("rollback", decision.source)

    def test_v2_pin_survives_when_config_is_only_default(self):
        decision = resolve_visual_version("og", {"visual_style_version": "v2"}, values={})
        self.assertEqual(decision.version, "v2")

    def test_metadata_is_reproducible(self):
        meta = resolve_visual_version("instagram", values={"VISUAL_STYLE_VERSION": "v2"}).as_metadata()
        self.assertEqual(meta["visual_style_version"], "v2")
        self.assertEqual(meta["composition"], "AutomaticInstagramCardV2")

    def test_unknown_workflow_rejected(self):
        with self.assertRaises(ValueError):
            resolve_visual_version("tiktok", values={})
        with self.assertRaises(ValueError):
            composition_for("og", "v9")

    def test_v2_compositions_registered_without_touching_v1(self):
        root = (ROOT / "remotion" / "src" / "Root.tsx").read_text(encoding="utf-8")
        register = (ROOT / "remotion" / "src" / "v2" / "register.tsx").read_text(encoding="utf-8")
        for comp in ("EditorialReel", "AutomaticInstagramCard", "FacebookOgCard", "Main"):
            self.assertRegex(root, rf'id="{comp}"')
        for comp in ("EditorialReelV2", "AutomaticInstagramCardV2", "FacebookOgCardV2"):
            self.assertRegex(register, rf'id="{comp}"')
        self.assertIn("<V2Compositions />", root)


class VisualV2PropsTests(unittest.TestCase):
    def test_pipeline_highlight_only_if_present_in_title(self):
        item = {"highlight_terms": ["Detuvieron a un ladrón"]}
        title = "Se quedó dormido al volante y volcó en la Ruta 38"
        terms = highlight_terms_for(title, item)
        for term in terms:
            self.assertTrue(phrase_in_title(term, title))
        self.assertNotIn("Detuvieron a un ladrón", terms)

    def test_valid_pipeline_highlight_is_kept(self):
        self.assertEqual(highlight_terms_for("Se quedó dormido al volante", {"highlight_terms": ["quedó dormido"]}), ["quedó dormido"])

    def test_reel_props_superset_of_main_schema(self):
        props = reel_props_v2({"titulo": "Vélez ganó", "seccion": "Deportes"}, duration_frames=300, asset_type="video", asset_file="tmp/x.mp4", asset_size=(960, 540))
        for key in ("titulo", "seccion", "assetType", "assetFile", "kenBurnsVariant", "durationInFrames", "highlightTerms"):
            self.assertIn(key, props)
        self.assertEqual((props["assetWidth"], props["assetHeight"]), (960, 540))
        self.assertEqual(props["hookStyle"], "auto")
        self.assertNotIn("statement", props)

    def test_reel_without_asset_is_none(self):
        props = reel_props_v2({"titulo": "x"}, duration_frames=90, asset_type="video", asset_file="")
        self.assertEqual(props["assetType"], "none")

    def test_no_invented_fields(self):
        props = instagram_props_v2({"titulo": "Título", "seccion": "Salud"}, asset_file="")
        self.assertEqual(props["locality"], "")
        self.assertEqual(props["deck"], "")
        self.assertFalse(props["breaking"])
        og = og_props_v2({"titulo": "A", "titulo_instagram": "B"}, asset_file="")
        self.assertEqual(og["titulo"], "B")


class ReelV2HookTests(unittest.TestCase):
    def test_single_editorial_hook(self):
        source = (ROOT / "remotion" / "src" / "v2" / "EditorialReelV2.tsx").read_text(encoding="utf-8")
        self.assertNotIn("kinetic_breaking", source)
        self.assertNotIn("visual_statement", source)
        self.assertNotIn("AccentSweep", source)

    def test_gallery_has_no_reel_without_media(self):
        cases = json.loads((ROOT / "tests" / "fixtures" / "visual_v2" / "cases.json").read_text(encoding="utf-8"))
        for case in cases:
            if case.get("reel"):
                self.assertTrue(case.get("video") or case.get("photo"), case["id"])


if __name__ == "__main__":
    unittest.main()
