import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from editorial_context import archive_backfill as backfill
from editorial_context import archive_index as ai

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "cms_api")


def _load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES_DIR, name), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolver_for(*addresses):
    def resolver(host, port, type=socket.SOCK_STREAM):
        return [(socket.AF_INET, type, 6, "", (address, port)) for address in addresses]

    return resolver


_PUBLIC_RESOLVER = _resolver_for("93.184.216.34")


def _fake_response(status_code=200, payload=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
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

    # ── Contrato real: {"ok": true, "data": {"items": [...], "pagination": {...}}} ──

    def test_single_page_last_page_ingests_posts_with_real_contract_shape(self):
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(200, _load_fixture("public_posts_empty.json")),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        self.assertEqual(report.pages_fetched, 0)
        self.assertEqual(report.articles_upserted, 0)
        self.assertEqual(report.errors, [])

    def test_multi_page_pagination_stops_on_total_reached(self):
        page1 = _load_fixture("public_posts_page1.json")
        page2 = _load_fixture("public_posts_page2.json")
        responses = [_fake_response(200, page1), _fake_response(200, page2)]

        with patch("editorial_context.archive_backfill.safe_get", side_effect=responses):
            report = backfill.backfill_from_cms_api(path=self.db_path, page_size=2, resolver=_PUBLIC_RESOLVER)

        self.assertEqual(report.pages_fetched, 2)
        self.assertEqual(report.articles_seen, 3)
        self.assertEqual(report.articles_upserted, 3)
        for article_id in ("101", "102", "103"):
            self.assertIsNotNone(ai.get_by_article_id(article_id, path=self.db_path))

    def test_last_page_partial_is_detected_via_pagination_total(self):
        # page2 trae 1 item con perPage=2: 2*2 >= total(3) -> debe frenar sin
        # pedir una tercera pagina.
        page1 = _load_fixture("public_posts_page1.json")
        page2 = _load_fixture("public_posts_page2.json")
        fetch_calls = []

        def fake_get(url, **kwargs):
            fetch_calls.append(url)
            return _fake_response(200, page1 if "page=1" in url else page2)

        with patch("editorial_context.archive_backfill.safe_get", side_effect=fake_get):
            backfill.backfill_from_cms_api(path=self.db_path, page_size=2, resolver=_PUBLIC_RESOLVER)

        self.assertEqual(len(fetch_calls), 2)

    def test_empty_items_list_stops_pagination_without_error(self):
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(200, _load_fixture("public_posts_empty.json")),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        self.assertEqual(report.pages_fetched, 0)
        self.assertEqual(report.errors, [])

    def test_total_greater_than_page_size_requires_multiple_requests(self):
        # simula total=120 con perPage=50: page1 llena (50 items) no debe
        # frenar por "pagina corta", solo por total alcanzado.
        def make_page(page, count, total):
            # ids unicos y arrancando en 1 (Prisma autoincrement nunca genera id=0).
            offset = (page - 1) * 50
            return {
                "ok": True,
                "data": {
                    "items": [
                        {"id": offset + i, "slug": f"n-{offset + i}", "title": f"Nota {offset + i}"}
                        for i in range(1, count + 1)
                    ],
                    "pagination": {"page": page, "perPage": 50, "total": total},
                },
            }

        responses = [
            _fake_response(200, make_page(1, 50, 120)),
            _fake_response(200, make_page(2, 50, 120)),
            _fake_response(200, make_page(3, 20, 120)),
        ]
        with patch("editorial_context.archive_backfill.safe_get", side_effect=responses):
            report = backfill.backfill_from_cms_api(path=self.db_path, page_size=50, resolver=_PUBLIC_RESOLVER)

        self.assertEqual(report.pages_fetched, 3)
        self.assertEqual(report.articles_upserted, 120)

    def test_page_size_is_clamped_to_50_matching_lib_http_ts(self):
        captured = {}

        def fake_get(url, **kwargs):
            captured["url"] = url
            return _fake_response(200, _load_fixture("public_posts_empty.json"))

        with patch("editorial_context.archive_backfill.safe_get", side_effect=fake_get):
            backfill.backfill_from_cms_api(path=self.db_path, page_size=999, resolver=_PUBLIC_RESOLVER)

        self.assertIn("perPage=50", captured["url"])

    def test_query_string_uses_perpage_not_pagesize(self):
        captured = {}

        def fake_get(url, **kwargs):
            captured["url"] = url
            return _fake_response(200, _load_fixture("public_posts_empty.json"))

        with patch("editorial_context.archive_backfill.safe_get", side_effect=fake_get):
            backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)

        self.assertIn("perPage=", captured["url"])
        self.assertNotIn("pageSize=", captured["url"])

    # ── Rechazo estricto de contratos inesperados (sin heuristicas permisivas) ──

    def test_ok_false_is_rejected_explicitly(self):
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(200, {"ok": False, "error": {"message": "boom"}}),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        self.assertEqual(report.pages_fetched, 0)
        self.assertTrue(any("contrato inesperado" in err or "ok=true" in err for err in report.errors))

    def test_data_not_an_object_is_rejected_explicitly(self):
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(200, {"ok": True, "data": [1, 2, 3]}),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        self.assertEqual(report.pages_fetched, 0)
        self.assertTrue(any("data no es un objeto" in err for err in report.errors))

    def test_items_not_a_list_is_rejected_explicitly(self):
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(200, {"ok": True, "data": {"items": "nope"}}),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        self.assertEqual(report.pages_fetched, 0)
        self.assertTrue(any("data.items no es una lista" in err for err in report.errors))

    def test_legacy_flat_data_list_is_no_longer_silently_accepted(self):
        # forma vieja incorrecta: data como lista directa de posts. NO debe
        # colarse silenciosamente (esa era la forma del bug original).
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(200, {"ok": True, "data": [{"id": 1, "slug": "x"}]}),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        self.assertEqual(report.articles_upserted, 0)
        self.assertTrue(any("data no es un objeto" in err for err in report.errors))

    def test_non_200_status_stops_and_records_error(self):
        with patch(
            "editorial_context.archive_backfill.safe_get",
            return_value=_fake_response(500, {}),
        ):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        self.assertEqual(report.pages_fetched, 0)
        self.assertTrue(any("http_status=500" in err for err in report.errors))

    def test_malformed_post_without_id_or_slug_is_skipped_but_others_continue(self):
        payload = {
            "ok": True,
            "data": {
                "items": [
                    {"id": None, "slug": None, "title": None},
                    {"id": 2, "slug": "nota-valida", "title": "Nota valida"},
                ],
                "pagination": {"page": 1, "perPage": 50, "total": 2},
            },
        }
        with patch("editorial_context.archive_backfill.safe_get", return_value=_fake_response(200, payload)):
            report = backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        self.assertIsNotNone(ai.get_by_article_id("2", path=self.db_path))
        self.assertEqual(report.articles_upserted, 1)

    # ── Tags reales (PostTag anidado) ──

    def test_real_nested_tag_shape_is_extracted(self):
        page1 = _load_fixture("public_posts_page1.json")
        with patch("editorial_context.archive_backfill.safe_get", return_value=_fake_response(200, page1)):
            backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        archived = ai.get_by_article_id("101", path=self.db_path)
        self.assertIn("Vialidad Provincial", archived.tags)

    def test_post_without_tags_gets_empty_list_not_error(self):
        page1 = _load_fixture("public_posts_page1.json")
        with patch("editorial_context.archive_backfill.safe_get", return_value=_fake_response(200, page1)):
            backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        archived = ai.get_by_article_id("102", path=self.db_path)
        self.assertEqual(archived.tags, [])

    def test_legacy_flat_tag_shape_still_supported_as_fallback(self):
        payload = {
            "ok": True,
            "data": {
                "items": [{"id": 5, "slug": "n5", "title": "N5", "tags": [{"name": "Legacy"}, "PlanoString"]}],
                "pagination": {"page": 1, "perPage": 50, "total": 1},
            },
        }
        with patch("editorial_context.archive_backfill.safe_get", return_value=_fake_response(200, payload)):
            backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        archived = ai.get_by_article_id("5", path=self.db_path)
        self.assertEqual(set(archived.tags), {"Legacy", "PlanoString"})

    # ── URL canónica reconstruida desde slug (el Post público no tiene url propia) ──

    def test_canonical_url_is_built_from_slug_and_base_url(self):
        page1 = _load_fixture("public_posts_page1.json")
        with patch("editorial_context.archive_backfill.safe_get", return_value=_fake_response(200, page1)):
            backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        archived = ai.get_by_article_id("101", path=self.db_path)
        self.assertEqual(
            archived.canonical_url,
            "https://cms.example.com/noticias/comenzo-la-obra-de-repavimentacion-en-chilecito",
        )

    def test_no_url_invented_when_slug_missing(self):
        payload = {
            "ok": True,
            "data": {
                "items": [{"id": 9, "title": "Sin slug"}],
                "pagination": {"page": 1, "perPage": 50, "total": 1},
            },
        }
        with patch("editorial_context.archive_backfill.safe_get", return_value=_fake_response(200, payload)):
            backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        archived = ai.get_by_article_id("9", path=self.db_path)
        self.assertEqual(archived.canonical_url, "")

    def test_explicit_url_field_is_respected_if_present(self):
        payload = {
            "ok": True,
            "data": {
                "items": [{"id": 10, "slug": "n10", "title": "N10", "url": "https://otra.example.com/n10"}],
                "pagination": {"page": 1, "perPage": 50, "total": 1},
            },
        }
        with patch("editorial_context.archive_backfill.safe_get", return_value=_fake_response(200, payload)):
            backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        archived = ai.get_by_article_id("10", path=self.db_path)
        self.assertEqual(archived.canonical_url, "https://otra.example.com/n10")

    # ── category/author anidados reales ──

    def test_category_and_author_extracted_from_nested_objects(self):
        page1 = _load_fixture("public_posts_page1.json")
        with patch("editorial_context.archive_backfill.safe_get", return_value=_fake_response(200, page1)):
            backfill.backfill_from_cms_api(path=self.db_path, resolver=_PUBLIC_RESOLVER)
        archived = ai.get_by_article_id("101", path=self.db_path)
        self.assertEqual(archived.category, "interior")
        self.assertEqual(archived.author, "Fernando Nahim Mora")


if __name__ == "__main__":
    unittest.main()
