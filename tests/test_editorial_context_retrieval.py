import unittest

from editorial_context.archive_index import ArchiveArticle
from editorial_context import retrieval


def _candidate(title, excerpt="", category="policiales", published_at="2026-08-01T10:00:00Z"):
    return ArchiveArticle(
        article_id="cand1",
        title=title,
        excerpt=excerpt,
        category=category,
        published_at=published_at,
    )


class ScoreCandidateTests(unittest.TestCase):
    def test_same_person_and_same_case_term_scores_high_for_policial(self):
        candidate = _candidate(
            "Juan Perez fue detenido por la causa de contrabando de autopartes",
        )
        result = retrieval.score_candidate(
            probe_title="Juan Perez fue condenado en la causa de contrabando de autopartes",
            probe_category="policiales",
            probe_published_at="2026-08-10T10:00:00Z",
            candidate=candidate,
        )
        self.assertTrue(result.matched_entities)
        self.assertTrue(result.matched_terms)
        self.assertTrue(result.meets_category_bar("policiales"))

    def test_same_person_different_unrelated_topic_does_not_meet_strict_bar(self):
        candidate = _candidate("Juan Perez asumio como nuevo secretario de gobierno")
        result = retrieval.score_candidate(
            probe_title="Juan Perez participo de un festival de musica en la plaza",
            probe_category="espectaculos",
            candidate=candidate,
        )
        self.assertTrue(result.matched_entities)
        self.assertFalse(result.meets_category_bar("espectaculos"))

    def test_non_strict_category_accepts_entity_match_alone(self):
        candidate = _candidate(
            "Comenzo la obra de repavimentacion de la Ruta 38 en Chilecito",
            category="interior",
        )
        result = retrieval.score_candidate(
            probe_title="Avanza la segunda etapa de la obra de repavimentacion de la Ruta 38",
            probe_category="interior",
            probe_localities=["chilecito"],
            probe_published_at="2026-08-05T10:00:00Z",
            candidate=candidate,
        )
        self.assertTrue(result.meets_category_bar("interior"))

    def test_unrelated_articles_score_low(self):
        candidate = _candidate("El clima estara templado durante el fin de semana", category="sociedad")
        result = retrieval.score_candidate(
            probe_title="La seleccion argentina goleo en un amistoso",
            probe_category="deportes",
            candidate=candidate,
        )
        self.assertLess(result.score, 0.2)
        self.assertFalse(result.meets_category_bar("deportes"))

    def test_time_distance_reduces_recency_bonus_for_old_candidate(self):
        near = _candidate("Juan Perez brindo declaraciones sobre la causa", published_at="2026-08-09T10:00:00Z")
        far = _candidate("Juan Perez brindo declaraciones sobre la causa", published_at="2025-01-01T10:00:00Z")
        probe_kwargs = dict(
            probe_title="Juan Perez volvio a declarar sobre la causa",
            probe_category="policiales",
            probe_published_at="2026-08-10T10:00:00Z",
        )
        near_score = retrieval.score_candidate(candidate=near, **probe_kwargs)
        far_score = retrieval.score_candidate(candidate=far, **probe_kwargs)
        self.assertGreater(near_score.score, far_score.score)

    def test_confidence_bucket_high_for_strong_match(self):
        candidate = _candidate("Juan Perez fue detenido por la causa de contrabando de autopartes")
        result = retrieval.score_candidate(
            probe_title="Juan Perez fue condenado en la causa de contrabando de autopartes",
            probe_category="policiales",
            probe_published_at="2026-08-02T10:00:00Z",
            candidate=candidate,
        )
        self.assertEqual(result.confidence, "high")

    def test_rank_candidates_sorts_descending(self):
        strong = _candidate("Juan Perez fue detenido por la causa de contrabando")
        strong.article_id = "strong"
        weak = _candidate("El tiempo estara nublado", category="sociedad")
        weak.article_id = "weak"
        ranked = retrieval.rank_candidates(
            [weak, strong],
            probe_title="Juan Perez fue condenado en la causa de contrabando",
            probe_category="policiales",
        )
        self.assertEqual(ranked[0].candidate.article_id, "strong")


if __name__ == "__main__":
    unittest.main()
