import tempfile
import unittest
from pathlib import Path

from editorial_context import archive_index as ai
from editorial_context import story_engine


class AssignStoryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "story_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_no_candidates_returns_none(self):
        result = story_engine.assign_story(
            article_id="new1", title="Noticia sin antecedentes", category="sociedad", path=self.db_path
        )
        self.assertIsNone(result)

    def test_creates_new_story_for_police_case_with_shared_entity_and_term(self):
        ai.upsert_article(
            ai.ArchiveArticle(
                article_id="prev1",
                title="Juan Perez fue detenido por la causa de contrabando de autopartes",
                category="policiales",
                published_at="2026-08-01T10:00:00Z",
            ),
            path=self.db_path,
        )
        result = story_engine.assign_story(
            article_id="new1",
            title="Juan Perez fue condenado en la causa de contrabando de autopartes",
            category="policiales",
            published_at="2026-08-10T10:00:00Z",
            path=self.db_path,
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.created_new)
        prev = ai.get_by_article_id("prev1", path=self.db_path)
        self.assertEqual(prev.story_key, result.story_key)

    def test_does_not_group_same_person_unrelated_events(self):
        ai.upsert_article(
            ai.ArchiveArticle(
                article_id="prev1",
                title="Juan Perez asumio como nuevo secretario de gobierno",
                category="politica",
                published_at="2026-08-01T10:00:00Z",
            ),
            path=self.db_path,
        )
        result = story_engine.assign_story(
            article_id="new1",
            title="Juan Perez participo de un festival de musica en la plaza",
            category="espectaculos",
            published_at="2026-08-10T10:00:00Z",
            path=self.db_path,
        )
        self.assertIsNone(result)

    def test_reuses_existing_story_key_of_qualifying_candidate(self):
        ai.upsert_article(
            ai.ArchiveArticle(
                article_id="prev1",
                title="Comenzo la obra de repavimentacion de la Ruta 38 en Chilecito",
                category="interior",
                published_at="2026-07-01T10:00:00Z",
                story_key="story:existing123",
            ),
            path=self.db_path,
        )
        result = story_engine.assign_story(
            article_id="new1",
            title="Avanza la segunda etapa de la obra de repavimentacion de la Ruta 38",
            category="interior",
            localities=["chilecito"],
            published_at="2026-08-10T10:00:00Z",
            path=self.db_path,
        )
        self.assertIsNotNone(result)
        self.assertFalse(result.created_new)
        self.assertEqual(result.story_key, "story:existing123")

    def test_does_not_group_by_category_alone(self):
        ai.upsert_article(
            ai.ArchiveArticle(
                article_id="prev1",
                title="Se registro un choque en la avenida principal",
                category="policiales",
                published_at="2026-08-01T10:00:00Z",
            ),
            path=self.db_path,
        )
        result = story_engine.assign_story(
            article_id="new1",
            title="Un hombre fue demorado tras una denuncia por robo",
            category="policiales",
            published_at="2026-08-10T10:00:00Z",
            path=self.db_path,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
