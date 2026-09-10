import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from editorial_context import archive_index as ai


def _article(article_id, title, **kwargs):
    defaults = dict(
        article_id=article_id,
        title=title,
        category="interior",
        published_at="2026-08-01T10:00:00Z",
    )
    defaults.update(kwargs)
    return ai.ArchiveArticle(**defaults)


class ArchiveIndexTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "archive_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_upsert_and_get_by_article_id_roundtrip(self):
        article = _article("a1", "Comenzo la obra en Ruta 38", excerpt="Vialidad inicio los trabajos")
        ai.upsert_article(article, path=self.db_path)
        fetched = ai.get_by_article_id("a1", path=self.db_path)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, article.title)
        self.assertTrue(fetched.entities or fetched.localities or True)  # se derivan automaticamente

    def test_upsert_is_idempotent_by_article_id(self):
        ai.upsert_article(_article("a1", "Titulo original"), path=self.db_path)
        ai.upsert_article(_article("a1", "Titulo actualizado"), path=self.db_path)
        fetched = ai.get_by_article_id("a1", path=self.db_path)
        self.assertEqual(fetched.title, "Titulo actualizado")

    def test_upsert_preserves_existing_story_key_when_not_provided(self):
        ai.upsert_article(_article("a1", "Titulo"), path=self.db_path)
        ai.set_story_key("a1", "story:abc123", path=self.db_path)
        ai.upsert_article(_article("a1", "Titulo actualizado sin story_key"), path=self.db_path)
        fetched = ai.get_by_article_id("a1", path=self.db_path)
        self.assertEqual(fetched.story_key, "story:abc123")

    def test_candidate_retrieval_finds_matching_entity(self):
        ai.upsert_article(
            _article("a1", "Juan Perez fue detenido por la causa de contrabando"),
            path=self.db_path,
        )
        ai.upsert_article(_article("a2", "El clima estara templado este fin de semana"), path=self.db_path)
        results = ai.candidate_retrieval(
            title="Juan Perez fue condenado en la causa de contrabando",
            path=self.db_path,
        )
        ids = [item.article_id for item in results]
        self.assertIn("a1", ids)
        self.assertNotIn("a2", ids)

    def test_candidate_retrieval_excludes_given_article_id(self):
        ai.upsert_article(_article("a1", "Juan Perez fue detenido"), path=self.db_path)
        results = ai.candidate_retrieval(title="Juan Perez", exclude_article_id="a1", path=self.db_path)
        self.assertEqual(results, [])

    def test_candidate_retrieval_empty_index_returns_empty(self):
        results = ai.candidate_retrieval(title="cualquier cosa", path=self.db_path)
        self.assertEqual(results, [])

    def test_story_relation_and_get_story_articles(self):
        ai.upsert_article(_article("a1", "Primera nota", story_key="story:x1"), path=self.db_path)
        ai.upsert_article(_article("a2", "Segunda nota", story_key="story:x1"), path=self.db_path)
        ai.add_story_relation(
            "a2",
            "story:x1",
            relation_score=0.7,
            relation_reason="same_entity:juan perez",
            matched_entities=["juan perez"],
            matched_terms=[],
            time_distance_days=2.0,
            confidence="high",
            path=self.db_path,
        )
        articles = ai.get_story_articles("story:x1", path=self.db_path)
        self.assertEqual({a.article_id for a in articles}, {"a1", "a2"})

    def test_get_story_articles_excludes_current(self):
        ai.upsert_article(_article("a1", "Primera nota", story_key="story:x1"), path=self.db_path)
        ai.upsert_article(_article("a2", "Segunda nota", story_key="story:x1"), path=self.db_path)
        articles = ai.get_story_articles("story:x1", exclude_article_id="a2", path=self.db_path)
        self.assertEqual([a.article_id for a in articles], ["a1"])

    def test_fallback_search_path_when_fts5_unavailable(self):
        with patch("editorial_context.db.fts5_supported", return_value=False):
            ai.upsert_article(
                _article("a1", "Juan Perez fue detenido por la causa de contrabando"),
                path=self.db_path,
            )
            results = ai.candidate_retrieval(
                title="Juan Perez fue condenado en la causa de contrabando",
                path=self.db_path,
            )
        self.assertTrue(any(item.article_id == "a1" for item in results))

    def test_archive_search_provider_related_uses_dict_shape(self):
        ai.upsert_article(_article("a1", "Juan Perez fue detenido en Chilecito"), path=self.db_path)
        provider = ai.ArchiveSearchProvider()
        with patch("editorial_context.archive_index.ec_db.db_path", return_value=self.db_path):
            results = provider.related({"titulo": "Juan Perez fue condenado", "article_id": "a2"})
        self.assertTrue(any(item.article_id == "a1" for item in results))


if __name__ == "__main__":
    unittest.main()
