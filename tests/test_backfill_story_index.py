import importlib
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from editorial_context import archive_index as ai


def _load_script():
    import scripts.backfill_story_index as module

    importlib.reload(module)
    return module


class BuildReportTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.env = patch.dict(
            os.environ,
            {"LVR_DATA_DIR": self._tmpdir.name, "LVR_LOGS_DIR": os.path.join(self._tmpdir.name, "logs")},
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(logging.shutdown)
        self.module = _load_script()

    def test_report_only_never_calls_network(self):
        ai.upsert_article(
            ai.ArchiveArticle(article_id="a1", post_id="1", title="Nota sin historia todavia")
        )
        with patch.object(self.module.requests, "request") as fake_request:
            report = self.module.build_report()
        fake_request.assert_not_called()
        self.assertEqual(len(report), 1)
        self.assertIsNone(report[0]["candidate_story"])

    def test_finds_candidate_story_for_related_articles(self):
        ai.upsert_article(
            ai.ArchiveArticle(
                article_id="prev1",
                post_id="1",
                title="Juan Perez fue detenido por la causa de contrabando de autopartes",
                category="policiales",
                published_at="2026-08-01T10:00:00Z",
            )
        )
        ai.upsert_article(
            ai.ArchiveArticle(
                article_id="a2",
                post_id="2",
                title="Juan Perez fue condenado en la causa de contrabando de autopartes",
                category="policiales",
                published_at="2026-08-10T10:00:00Z",
            )
        )
        report = self.module.build_report()
        by_article = {row["article_id"]: row for row in report}
        self.assertIsNotNone(by_article["a2"]["candidate_story"])

    def test_apply_without_confirm_is_blocked(self):
        with patch.object(sys, "argv", ["backfill_story_index.py", "--apply"]):
            with patch("builtins.print") as fake_print:
                code = self.module.main()
        self.assertEqual(code, 1)
        printed = fake_print.call_args[0][0]
        self.assertIn("blocked", printed)

    def test_apply_report_without_credentials_reports_error(self):
        with patch.dict(os.environ, {"WEBAPP_BASE_URL": "", "PRIVATE_API_KEY": ""}, clear=False):
            results = self.module.apply_report(
                [{"post": "1", "article_id": "a1", "candidate_story": "story:x"}]
            )
        self.assertFalse(results[0]["applied"])
        self.assertEqual(results[0]["error"], "credenciales_no_configuradas")


if __name__ == "__main__":
    unittest.main()
