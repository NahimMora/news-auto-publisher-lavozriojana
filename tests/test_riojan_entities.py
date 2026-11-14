"""Vínculo riojano por referentes e instituciones (2026-11-13)."""
import unittest
from unittest.mock import patch

from utils import editorial_router
from utils.editorial_router import detect_riojan_link, compute_topic_key as topic_key


def nota(titulo, source="nuevarioja_politica", **extra):
    return {"titulo": titulo, "source": source, "seccion": "Politica", **extra}


class RiojanEntityTests(unittest.TestCase):
    def test_referentes_sin_localidad_cuentan_como_riojanos(self):
        casos = {
            "Quintela cruzó a Milei por la inflación de octubre": "entity:quintela",
            "Braida pidió por el empleo ante el Papa León": "entity:braida",
            "Luna Corzo evitó confirmar aumentos salariales": "entity:luna corzo",
            "Teresita Madera inauguró la iluminación del club": "entity:teresita madera",
            "Récord de atenciones en la guardia del Vera Barros": "entity:vera barros",
            "Cambio de autoridades en el gremio de la UNLaR": "entity:unlar",
        }
        for titulo, esperado in casos.items():
            with self.subTest(titulo=titulo):
                self.assertEqual((True, esperado), detect_riojan_link(nota(titulo)))

    def test_fuentes_judiciales_riojanas(self):
        for source in ("judicial_mpf", "judicial_justicia"):
            ok, reason = detect_riojan_link(nota("Elevan a juicio una causa por femicidio", source=source))
            self.assertTrue(ok)
            self.assertEqual(f"institution:{source}", reason)

    def test_palabra_completa_y_sin_homonimos(self):
        for titulo in (
            "Una mesa de madera tallada a mano",  # "madera" sola no cuenta
            "Temporal en Salta: más de 150 heridos en Embarcación",
            "Desembarcaron con ayuda humanitaria",
        ):
            with self.subTest(titulo=titulo):
                self.assertFalse(detect_riojan_link(nota(titulo))[0])

    def test_directorio_requiere_cargo(self):
        with patch("utils.gov_tags.person_aliases", return_value=("Juan Carlos Vergara",)):
            self.assertFalse(detect_riojan_link(nota("Juan Carlos Vergara ganó un torneo de ajedrez"))[0])
            self.assertEqual(
                (True, "entity:juan carlos vergara"),
                detect_riojan_link(nota("El ministro Juan Carlos Vergara anunció una campaña")),
            )

    def test_localidad_sigue_teniendo_prioridad(self):
        self.assertEqual(
            (True, "keyword:chilecito"),
            detect_riojan_link(nota("Quintela visitó Chilecito")),
        )

    def test_topic_key_no_cambia_por_referente(self):
        noticia = nota("Quintela cruzó a Milei por la inflación", fecha="2026-11-13")
        with patch.object(editorial_router, "RIOJAN_ENTITY_TERMS", set()):
            antes = topic_key(noticia)
        self.assertEqual(antes, topic_key(noticia))


if __name__ == "__main__":
    unittest.main()
