import unittest

from sources import selector


class SelectSourcesTests(unittest.TestCase):
    def test_police_category_selects_mpf_and_justicia(self):
        sources = selector.select_sources(category="policiales", localities=["chilecito"])
        ids = {s.source_id for s in sources}
        self.assertIn("mpf_larioja", ids)
        self.assertIn("justicia_larioja", ids)

    def test_gendarmeria_excluded_without_riojan_locality(self):
        sources = selector.select_sources(category="policiales", localities=[])
        ids = {s.source_id for s in sources}
        self.assertNotIn("gendarmeria", ids)

    def test_gendarmeria_included_with_riojan_locality(self):
        sources = selector.select_sources(category="policiales", localities=["chilecito"])
        ids = {s.source_id for s in sources}
        self.assertIn("gendarmeria", ids)

    def test_anses_keyword_matches_rule_but_stays_filtered_while_disabled(self):
        # anses esta deshabilitada en el registry real (pendiente de confirmar
        # con fetch real, ver config/official_sources.json); el selector debe
        # seguir respetando enabled=False aunque la keyword matchee.
        self.assertIn("anses", selector.KEYWORD_SOURCE_IDS["anses"])
        sources = selector.select_sources(category="economia", keywords_text="Anses confirmo un nuevo bono")
        ids = {s.source_id for s in sources}
        self.assertNotIn("anses", ids)

    def test_sports_and_entertainment_categories_have_no_official_sources(self):
        self.assertEqual(selector.select_sources(category="deportes"), [])
        self.assertEqual(selector.select_sources(category="espectaculos"), [])

    def test_disabled_sources_are_never_selected(self):
        sources = selector.select_sources(category="policiales", localities=["chilecito"])
        ids = {s.source_id for s in sources}
        self.assertNotIn("policia_larioja", ids)

    def test_unknown_category_returns_empty(self):
        self.assertEqual(selector.select_sources(category="inexistente"), [])

    def test_mpf_selected_for_police_category_always(self):
        sources = selector.select_sources(category="policiales")
        self.assertIn("mpf_larioja", {s.source_id for s in sources})

    def test_mpf_not_selected_for_unrelated_category(self):
        sources = selector.select_sources(category="deportes")
        self.assertNotIn("mpf_larioja", {s.source_id for s in sources})

    def test_bcra_selected_for_economy_category(self):
        sources = selector.select_sources(category="economia")
        self.assertIn("bcra", {s.source_id for s in sources})

    def test_bcra_keyword_adds_bcra_even_outside_economy_category(self):
        sources = selector.select_sources(category="sociedad", keywords_text="el BCRA subio la tasa de referencia")
        self.assertIn("bcra", {s.source_id for s in sources})

    def test_climate_keyword_adds_smn(self):
        sources = selector.select_sources(category="sociedad", keywords_text="alerta por temporal en la zona")
        ids = {s.source_id for s in sources}
        self.assertIn("smn_news", ids)


if __name__ == "__main__":
    unittest.main()
