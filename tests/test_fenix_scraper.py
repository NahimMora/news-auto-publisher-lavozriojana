from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from scraping import base_fenix as fenix
from tests.test_scraper_fixtures import FakeResponse, fixture
from utils.stage_result import StageStatus


def _article(name: str, url: str = "https://www.fenix951.com.ar/noticia.php?id=900001"):
    with mock.patch.object(fenix.requests, "get", return_value=FakeResponse(fixture(name))), mock.patch.object(
        fenix, "_download_image", return_value=("raw.jpg", "opt.jpg")
    ):
        return fenix.scrap_noticia_result(url)


class FenixLinksTests(unittest.TestCase):
    def test_lists_only_section_rows_with_canonical_urls(self):
        with mock.patch.object(fenix.requests, "get", return_value=FakeResponse(fixture("fenix_section.html"))):
            result = fenix.scrap_links_result()

        self.assertEqual(StageStatus.SUCCESS, result.status)
        # Sin la nota del menú desplegable, sin duplicados y con host/parámetros normalizados.
        self.assertEqual(
            [
                "https://www.fenix951.com.ar/noticia.php?id=900001",
                "https://www.fenix951.com.ar/noticia.php?id=900002",
            ],
            result.links,
        )

    def test_empty_page_is_no_work_and_timeout_is_failed(self):
        with mock.patch.object(fenix.requests, "get", return_value=FakeResponse(fixture("empty_page.html"))):
            no_work = fenix.scrap_links_result()
        with mock.patch.object(fenix.requests, "get", side_effect=requests.Timeout("timeout")):
            failed = fenix.scrap_links_result()

        self.assertEqual(StageStatus.NO_WORK, no_work.status)
        self.assertEqual(StageStatus.FAILED, failed.status)
        self.assertEqual("timeout", failed.error_type)


class FenixArticleTests(unittest.TestCase):
    def test_article_fields(self):
        result = _article("fenix_article.html")

        self.assertEqual(StageStatus.SUCCESS, result.status)
        article = result.article
        self.assertEqual("Murió un vecino de Villa Castelli tras sufrir quemaduras graves", article["titulo"])
        self.assertEqual("2026-10-22", article["fecha"])
        self.assertEqual("locales", article["categoria_origen"])
        self.assertEqual("fenix_locales", article["source"])
        self.assertEqual("locales", article["seccion"])
        self.assertEqual("https://www.fenix951.com.ar/imagenes/900001_1792698696.jpg", article["imagen_url"])
        # Copete propio (no el del menú) + cuerpo, sin la línea de fecha ni vacíos.
        self.assertTrue(article["parrafos"][0].startswith("Había ingresado al hospital"))
        self.assertEqual(3, len(article["parrafos"]))
        self.assertFalse(any("Multiplataforma" in p for p in article["parrafos"]))
        self.assertFalse(any("gobernador" in p for p in article["parrafos"]))

    def test_article_in_progress_is_retried_later(self):
        result = _article("fenix_article_in_progress.html")

        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertEqual("article_in_progress", result.error_type)
        self.assertIsNone(result.article)

    def test_http_error_and_selector_mismatch_fail(self):
        with mock.patch.object(fenix.requests, "get", return_value=FakeResponse(status_code=503)):
            http_error = fenix.scrap_noticia_result("https://www.fenix951.com.ar/noticia.php?id=1")
        with mock.patch.object(fenix.requests, "get", return_value=FakeResponse(fixture("empty_page.html"))):
            mismatch = fenix.scrap_noticia_result("https://www.fenix951.com.ar/noticia.php?id=1")
        invalid = fenix.scrap_noticia_result("https://www.fenix951.com.ar/categoria.php?id=1")

        self.assertEqual(StageStatus.FAILED, http_error.status)
        self.assertEqual(StageStatus.FAILED, mismatch.status)
        self.assertEqual("selector_mismatch", mismatch.error_type)
        self.assertEqual("selector_mismatch", invalid.error_type)


class FenixRiojanFilterTests(unittest.TestCase):
    def test_dateline_and_menu_do_not_count_as_riojan_link(self):
        import main_fenix

        local = _article("fenix_article.html").article
        national = _article("fenix_article_national.html", "https://www.fenix951.com.ar/noticia.php?id=900002").article

        self.assertEqual((False, ""), main_fenix._discard(local))
        self.assertEqual((True, "fenix_sin_vinculo_riojano"), main_fenix._discard(national))
        self.assertEqual(
            (True, "fenix_fuera_de_locales"),
            main_fenix._discard({**local, "categoria_origen": "nacionales"}),
        )

    def test_terms_need_word_boundaries(self):
        self.assertTrue(fenix.has_riojan_link({"titulo": "Choque en Sanagasta", "parrafos": []}))
        self.assertTrue(fenix.has_riojan_link({"titulo": "Obra en Chilecito", "parrafos": []}))
        self.assertFalse(fenix.has_riojan_link({"titulo": "Tamara habló de su carrera", "parrafos": []}))


class FenixRunnerTests(unittest.TestCase):
    def test_section_persists_local_and_records_national_as_filtered(self):
        import main_fenix
        from scraping.runner import run_section

        pages = {
            fenix.SECTION_URL: fixture("fenix_section.html"),
            "https://www.fenix951.com.ar/noticia.php?id=900001": fixture("fenix_article.html"),
            "https://www.fenix951.com.ar/noticia.php?id=900002": fixture("fenix_article_national.html"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "noticias_ejecutadas_fenix.json"
            output = Path(tmp) / "noticias_norewrite_fenix.json"
            with mock.patch.object(
                fenix.requests, "get", side_effect=lambda url, **_kw: FakeResponse(pages[url])
            ), mock.patch.object(fenix, "_download_image", return_value=("raw.jpg", "opt.jpg")), mock.patch(
                "scraping.runner.record_queue_event"
            ), mock.patch("scraping.runner.is_blocked", return_value=False):
                result = run_section(
                    stage="scrape_fenix",
                    enabled=True,
                    history_path=str(history),
                    output_path=str(output),
                    fetch_links=fenix.scrap_links_result,
                    fetch_article=fenix.scrap_noticia_result,
                    extra_discard=main_fenix._discard,
                )
            queued = json.loads(output.read_text(encoding="utf-8"))
            seen = json.loads(history.read_text(encoding="utf-8"))

        self.assertEqual(StageStatus.SUCCESS, result.status)
        self.assertEqual(["fenix_locales"], [item["source"] for item in queued])
        self.assertEqual(1, result.details["discarded"])
        self.assertEqual(2, len(seen))

    def test_article_in_progress_is_deferred_without_degrading(self):
        from scraping.runner import run_section
        from utils.scraper_contract import ArticleScrapeResult, LinkScrapeResult

        url = "https://www.fenix951.com.ar/noticia.php?id=900003"
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "history.json"
            with mock.patch("scraping.runner.record_queue_event"):
                result = run_section(
                    stage="scrape_fenix",
                    enabled=True,
                    history_path=str(history),
                    output_path=str(Path(tmp) / "out.json"),
                    fetch_links=lambda: LinkScrapeResult(status=StageStatus.SUCCESS, links=[url]),
                    fetch_article=lambda _url: ArticleScrapeResult(
                        status=StageStatus.NO_WORK, error_type="article_in_progress"
                    ),
                )
            self.assertFalse(history.exists())

        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertEqual(1, result.deferred)

    def test_disabled_by_default(self):
        import main_fenix

        with mock.patch.dict("os.environ", {"SCRAPER_FENIX_ENABLED": "0"}):
            result = main_fenix.main()
        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertTrue(result.details.get("disabled"))


if __name__ == "__main__":
    unittest.main()
