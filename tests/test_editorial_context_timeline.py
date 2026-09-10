import tempfile
import unittest
from pathlib import Path

from editorial_context import archive_index as ai
from editorial_context import timeline as tl


class BuildTimelineTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "timeline_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _seed_story(self, story_key, n, *, confidence="high"):
        for i in range(n):
            article_id = f"a{i}"
            ai.upsert_article(
                ai.ArchiveArticle(
                    article_id=article_id,
                    title=f"Nota {i} de la historia",
                    category="interior",
                    published_at=f"2026-08-0{i+1}T10:00:00Z",
                    story_key=story_key,
                ),
                path=self.db_path,
            )
            ai.add_story_relation(
                article_id,
                story_key,
                relation_score=0.7,
                relation_reason="same_entity:x",
                matched_entities=["x"],
                matched_terms=["y"],
                time_distance_days=1.0,
                confidence=confidence,
                path=self.db_path,
            )

    def test_empty_story_key_returns_empty(self):
        self.assertEqual(tl.build_timeline("", path=self.db_path), [])

    def test_fewer_than_minimum_prior_items_returns_empty(self):
        self._seed_story("story:1", 1)
        self.assertEqual(tl.build_timeline("story:1", path=self.db_path), [])

    def test_low_confidence_story_does_not_show_timeline(self):
        self._seed_story("story:1", 3, confidence="medium")
        self.assertEqual(tl.build_timeline("story:1", path=self.db_path), [])

    def test_qualifying_story_returns_chronological_items(self):
        self._seed_story("story:1", 3, confidence="high")
        items = tl.build_timeline("story:1", path=self.db_path)
        self.assertEqual(len(items), 3)
        dates = [item.published_at for item in items]
        self.assertEqual(dates, sorted(dates))

    def test_excludes_current_article_and_caps_at_max(self):
        self._seed_story("story:1", 7, confidence="high")
        items = tl.build_timeline("story:1", exclude_article_id="a0", path=self.db_path)
        self.assertLessEqual(len(items), tl.MAX_TIMELINE_ITEMS)
        self.assertNotIn("a0", [item.article_id for item in items])


if __name__ == "__main__":
    unittest.main()
