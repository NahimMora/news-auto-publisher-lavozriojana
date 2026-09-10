import tempfile
import unittest
from pathlib import Path

from editorial_context import archive_index as ai


class GetAllWithoutStoryKeyTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "backfill_query_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_returns_only_articles_without_story_key(self):
        ai.upsert_article(ai.ArchiveArticle(article_id="a1", title="Con historia", story_key="story:x"), path=self.db_path)
        ai.upsert_article(ai.ArchiveArticle(article_id="a2", title="Sin historia"), path=self.db_path)
        results = ai.get_all_without_story_key(path=self.db_path)
        self.assertEqual([a.article_id for a in results], ["a2"])

    def test_respects_limit(self):
        for i in range(5):
            ai.upsert_article(ai.ArchiveArticle(article_id=f"a{i}", title=f"Nota {i}"), path=self.db_path)
        results = ai.get_all_without_story_key(limit=2, path=self.db_path)
        self.assertEqual(len(results), 2)

    def test_empty_index_returns_empty_list(self):
        self.assertEqual(ai.get_all_without_story_key(path=self.db_path), [])


if __name__ == "__main__":
    unittest.main()
