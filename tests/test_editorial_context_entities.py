import unittest

from editorial_context import entities


class ExtractLocalitiesTests(unittest.TestCase):
    def test_detects_specific_locality(self):
        self.assertEqual(
            entities.extract_localities("Un accidente ocurrio en Chilecito esta manana"),
            ["chilecito"],
        )

    def test_specific_locality_sorts_before_province_wide_term(self):
        result = entities.extract_localities("La Rioja sigue de cerca la obra en Chamical")
        self.assertEqual(result[0], "chamical")
        self.assertIn("la rioja", result)

    def test_no_locality_found_returns_empty(self):
        self.assertEqual(entities.extract_localities("Un partido de futbol en Buenos Aires"), [])


class ExtractEntitiesTests(unittest.TestCase):
    def test_multiword_person_name_kept_even_at_sentence_start(self):
        result = entities.extract_entities("Juan Perez fue detenido en un operativo")
        self.assertIn("Juan Perez", result)

    def test_institution_with_connector_words_merged(self):
        result = entities.extract_entities("El Ministerio de Salud confirmo el aumento")
        self.assertIn("Ministerio de Salud", result)
        self.assertNotIn("El Ministerio de Salud", result)

    def test_generic_single_word_at_sentence_start_dropped(self):
        result = entities.extract_entities("Gobierno anuncio nuevas medidas economicas")
        self.assertEqual(result, [])

    def test_institution_spanning_article_and_locality_kept_whole(self):
        result = entities.extract_entities("El Gobierno de La Rioja lanzo un nuevo programa")
        self.assertIn("Gobierno de La Rioja", result)

    def test_acronym_kept_even_at_sentence_start(self):
        result = entities.extract_entities("MPF confirmo la apertura de la causa")
        self.assertIn("MPF", result)

    def test_acronym_after_leading_article_strips_article(self):
        result = entities.extract_entities("El MPF confirmo la apertura de la causa")
        self.assertIn("MPF", result)
        self.assertNotIn("El MPF", result)

    def test_dedup_and_order_preserved(self):
        result = entities.extract_entities("Juan Perez hablo. Despues, Juan Perez se retiro.")
        self.assertEqual(result.count("Juan Perez"), 1)

    def test_max_entities_respected(self):
        text = " ".join(f"Entidad{i} Numero{i}." for i in range(30))
        result = entities.extract_entities(text, max_entities=5)
        self.assertLessEqual(len(result), 5)

    def test_multiple_texts_are_joined(self):
        result = entities.extract_entities("Titulo generico", "Juan Perez declaro en Chilecito")
        self.assertIn("Juan Perez", result)


if __name__ == "__main__":
    unittest.main()
