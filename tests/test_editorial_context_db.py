import os
import tempfile
import unittest
from pathlib import Path

from editorial_context import db as ec_db


class EditorialContextDbTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "editorial_context_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ensure_schema_creates_all_tables(self):
        with ec_db.connection(self.db_path) as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
        expected = {
            "archive_articles",
            "stories",
            "story_relations",
            "context_facts",
            "official_content_cache",
            "source_metrics",
            "ai_call_metrics",
            "schema_meta",
        }
        self.assertTrue(expected.issubset(tables))
        self.assertTrue("archive_fts" in tables or "archive_fts_fallback" in tables)

    def test_fts5_probe_is_memoized_and_boolean(self):
        with ec_db.connection(self.db_path) as conn:
            first = ec_db.fts5_supported(conn)
            second = ec_db.fts5_supported(conn)
        self.assertIsInstance(first, bool)
        self.assertEqual(first, second)

    def test_rebuild_database_recreates_empty_schema(self):
        with ec_db.connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO archive_articles "
                "(article_id, title, created_at_ts, updated_at_ts) VALUES (?, ?, ?, ?)",
                ("a1", "Titulo", 0, 0),
            )
        ec_db.rebuild_database(self.db_path)
        with ec_db.connection(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM archive_articles").fetchone()["c"]
        self.assertEqual(count, 0)

    def test_connection_rolls_back_on_exception(self):
        with self.assertRaises(ValueError):
            with ec_db.connection(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO archive_articles "
                    "(article_id, title, created_at_ts, updated_at_ts) VALUES (?, ?, ?, ?)",
                    ("a2", "Titulo", 0, 0),
                )
                raise ValueError("boom")
        with ec_db.connection(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM archive_articles").fetchone()["c"]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
