import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from editorial_context import archive_backfill as backfill
from editorial_context import archive_index as ai


def _resolver_for(*addresses):
    def resolver(host, port, type=socket.SOCK_STREAM):
        return [(socket.AF_INET, type, 6, "", (address, port)) for address in addresses]

    return resolver


_PUBLIC_RESOLVER = _resolver_for("93.184.216.34")


def _fake_response(status_code=200, payload=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload or {}
    return response


class BackfillFromCmsApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "backfill_test.sqlite3"
        self.env = patch.dict(
            "os.environ", {"WEBAPP_BASE_URL": "https://cms.example.com"}, clear=False
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_missing_base_url_reports_error_without_requests(self):
        with patch.dict("os.environ", {"WEBAPP_BASE_URL": ""}, clear=False):
            with patch("editorial_context.archive_backfill.safe_get") as fake_get:
                report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        fake_get.assert_not_called()
        self.assertIn("WEBAPP_BASE_URL no configurada", report.errors[0])

    def test_single_page_ingests_posts_and_stops_on_short_page(self):
        posts = [
            {
                "id": "1",
                "slug": "nota-1",
                "title": "Comenzo la obra en Chilecito",
                "excerpt": "Resumen",
                "url": "https://cms.example.com/noticias/nota-1",
                "categorySlug": "interior",
                "publishedAt": "2026-08-01T10:00:00Z",
                "tags": ["Interior"],
            }
        ]
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(200, {"data": posts}),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, page_size=50, resolver=_PUBLIC_RESOLVER)

        self.assertEqual(report.pages_fetched, 1)
        self.assertEqual(report.articles_upserted, 1)
        archived = ai.get_by_article_id("1", path=self.db_path)
        self.assertIsNotNone(archived)
        self.assertEqual(archived.title, "Comenzo la obra en Chilecito")

    def test_empty_page_stops_pagination(self):
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(200, {"data": []}),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        self.assertEqual(report.pages_fetched, 0)
        self.assertEqual(report.articles_upserted, 0)

    def test_non_200_status_stops_and_records_error(self):
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(500, {}),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        self.assertEqual(report.pages_fetched, 0)
        self.assertTrue(any("http_status=500" in err for err in report.errors))

    def test_malformed_post_is_skipped_but_others_continue(self):
        posts = [
            {"id": None, "title": None},  # provoca error al construir article_id vacio? sigue upsert igual
            {"id": "2", "title": "Nota valida", "url": "https://cms.example.com/n2"},
        ]
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(200, {"data": posts}),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        archived = ai.get_by_article_id("2", path=self.db_path)
        self.assertIsNotNone(archived)


if __name__ == "__main__":
    unittest.main()
