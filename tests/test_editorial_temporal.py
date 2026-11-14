"""Referencias temporales de la nota web (caso Anguinán, 13/11/2026)."""
from __future__ import annotations

import unittest
from datetime import date

from pipeline.node_webapp import editorial as ed

BAJADA = ("Un siniestro vial fatal se registró durante la mañana de este viernes en el barrio El Plumerillo, "
          "perteneciente al distrito Anguinán, donde un motociclista de 22 años perdió la vida tras colisionar contra un poste.")
CUERPO = "De acuerdo con el parte policial, la víctima se desplazaba en una motocicleta por la calle 4 de Junio."
FRIDAY = date(2026, 11, 13)
SATURDAY = date(2026, 11, 14)


def noticia(*parrafos, fecha="2026-11-13"):
    return {"titulo": "Un joven murió tras impactar su moto contra un poste", "parrafos": list(parrafos),
            "fecha": fecha, "source": "nuevarioja_policiales", "seccion": "policiales"}


def result(lead):
    return ed.EditorialResult(title="Murió un motociclista en Anguinán", excerpt="", lead=lead,
                              source_paragraph="", sections=[], closing_paragraph="")


class TemporalWarningsTests(unittest.TestCase):
    def test_real_case_sunday_instead_of_friday_is_flagged(self):
        n = noticia(BAJADA, CUERPO)
        w = ed._temporal_warnings(result("Un joven perdió la vida este domingo tras chocar contra un poste."), n, today=FRIDAY)
        self.assertIn("invented_weekday:domingo", w)

    def test_weekday_from_source_is_accepted(self):
        n = noticia(BAJADA, CUERPO)
        self.assertEqual([], ed._temporal_warnings(result("El choque ocurrió este viernes en Anguinán."), n, today=SATURDAY))

    def test_weekday_without_source_reference_is_flagged(self):
        """Sin bajada (como antes del arreglo del scraper) cualquier día es inventado."""
        n = noticia(CUERPO)
        self.assertIn("invented_weekday:domingo", ed._temporal_warnings(result("Murió este domingo."), n, today=FRIDAY))

    def test_yesterday_converted_to_weekday_is_accepted(self):
        n = noticia("El hecho ocurrió ayer por la tarde en Chilecito, según informó la Policía.", fecha="2026-11-13")
        self.assertEqual([], ed._temporal_warnings(result("El hecho ocurrió el jueves por la tarde."), n, today=SATURDAY))

    def test_yesterday_kept_when_published_another_day_is_stale(self):
        n = noticia("El hecho ocurrió ayer por la tarde en Chilecito, según informó la Policía.", fecha="2026-11-13")
        self.assertIn("stale_relative_day:ayer", ed._temporal_warnings(result("El hecho ocurrió ayer."), n, today=SATURDAY))

    def test_yesterday_same_day_is_accepted(self):
        n = noticia("El hecho ocurrió ayer por la tarde en Chilecito, según informó la Policía.", fecha="2026-11-13")
        self.assertEqual([], ed._temporal_warnings(result("El hecho ocurrió ayer."), n, today=FRIDAY))

    def test_today_invented_is_flagged(self):
        n = noticia(CUERPO)
        self.assertIn("invented_relative_day:hoy", ed._temporal_warnings(result("Hoy murió un motociclista."), n, today=FRIDAY))

    def test_publication_days_after_event_with_absolute_date(self):
        n = noticia("El choque ocurrió el 10 de noviembre en la Ruta 40 y la víctima murió en el hospital.", fecha="2026-11-13")
        self.assertEqual([], ed._temporal_warnings(result("El choque fue el martes 10 de noviembre."), n, today=SATURDAY))
        self.assertIn("invented_weekday:viernes",
                      ed._temporal_warnings(result("El choque fue este viernes."), n, today=SATURDAY))

    def test_near_midnight_tonight_from_previous_day_is_stale(self):
        n = noticia("Esta noche se registró un incendio en el barrio Cochangasta, informaron los bomberos.", fecha="2026-11-13")
        self.assertIn("stale_relative_day:esta noche",
                      ed._temporal_warnings(result("Esta noche se registró un incendio."), n, today=SATURDAY))
        self.assertEqual([], ed._temporal_warnings(result("El viernes por la noche hubo un incendio."), n, today=SATURDAY))

    def test_unknown_source_date_only_allows_literal_references(self):
        n = noticia("El hecho ocurrió ayer en Chamical.", fecha="")
        self.assertEqual([], ed._temporal_warnings(result("El hecho ocurrió ayer."), n, today=SATURDAY))
        self.assertIn("invented_weekday:jueves", ed._temporal_warnings(result("Ocurrió el jueves."), n, today=SATURDAY))

    def test_contradictory_weekdays_in_source_allow_only_those_days(self):
        n = noticia("El viernes se denunció el robo, que según la familia ocurrió el miércoles.", fecha="2026-11-13")
        self.assertEqual([], ed._temporal_warnings(result("El robo ocurrió el miércoles y se denunció el viernes."), n, today=SATURDAY))
        self.assertIn("invented_weekday:martes", ed._temporal_warnings(result("El robo fue el martes."), n, today=SATURDAY))

    def test_temporal_warnings_are_hard(self):
        hard = ed._hard_editorial_warnings(["invented_weekday:domingo", "stale_relative_day:ayer",
                                            "invented_relative_day:hoy", "quality_score_below_threshold:0.5"])
        self.assertEqual(3, len(hard))

    def test_feedback_explains_temporal_fix(self):
        fb = ed._feedback_for_warnings(["invented_weekday:domingo"], min_score=0.86)
        self.assertIn("contexto_temporal", fb)

    def test_temporal_context_separates_source_and_writing_dates(self):
        ctx = ed.temporal_context(noticia(CUERPO), today=SATURDAY)
        self.assertEqual("viernes 13/11/2026", ctx["fecha_publicacion_fuente"])
        self.assertEqual("sábado 14/11/2026", ctx["fecha_redaccion"])
        self.assertIsNone(ed.temporal_context(noticia(CUERPO, fecha="")))

    def test_validate_includes_temporal_check(self):
        n = noticia(BAJADA, CUERPO)
        w = ed.validate_editorial_result(result("Un joven perdió la vida este domingo en Anguinán."), n, check_similarity=False)
        self.assertIn("invented_weekday:domingo", w)


if __name__ == "__main__":
    unittest.main()
