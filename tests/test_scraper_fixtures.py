from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import requests


FIXTURES = Path(__file__).parent / "fixtures" / "scrapers"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, text="", status_code=200, headers=None, content=b"image"):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html"}
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


class TiempoPopularFixtureTests(unittest.TestCase):
    def test_each_section_has_a_representative_fixture(self):
        from scraping import base_tiempopopular as scraper
        from utils.stage_result import StageStatus

        for section in ("locales", "policiales", "interior", "deportes"):
            with self.subTest(section=section):
                response = FakeResponse(fixture(f"tiempopopular_{section}_section.html"))
                with mock.patch.object(scraper.requests, "get", return_value=response):
                    result = scraper.scrap_links_result(
                        f"https://www.tiempopopular.com.ar/{section}/",
                        section,
                    )
                self.assertEqual(result.status, StageStatus.SUCCESS)
                self.assertEqual(len(result.links), 1)
                self.assertIn(f"{section}-fixture", result.links[0])

    def test_section_and_article_contract(self):
        from scraping import base_tiempopopular as scraper
        from utils.stage_result import StageStatus

        section_html = (FIXTURES / "tiempopopular_section.html").read_text(encoding="utf-8")
        article_html = (FIXTURES / "tiempopopular_article.html").read_text(encoding="utf-8")
        with mock.patch.object(scraper.requests, "get", return_value=FakeResponse(section_html)):
            links = scraper.scrap_links_result(
                "https://www.tiempopopular.com.ar/locales/",
                "locales",
            )
        with mock.patch.object(scraper.requests, "get", return_value=FakeResponse(article_html)), mock.patch.object(
            scraper, "_download_image", return_value=("raw.jpg", "opt.jpg")
        ):
            article = scraper.scrap_noticia_result(links.links[0], "locales")

        self.assertEqual(StageStatus.SUCCESS, links.status)
        self.assertEqual(2, len(links.links))
        self.assertEqual(StageStatus.SUCCESS, article.status)
        self.assertEqual("Vialidad trabaja en una ruta de Aimogasta", article.article["titulo"])
        self.assertEqual("2026-07-23", article.article["fecha"])
        self.assertEqual("https://cdn.example.com/obra.jpg", article.article["imagen_url"])
        self.assertEqual("tiempopopular_locales", article.article["source"])

    def test_empty_page_is_no_work_but_timeout_is_failed(self):
        from scraping import base_tiempopopular as scraper
        from utils.stage_result import StageStatus

        empty = (FIXTURES / "empty_page.html").read_text(encoding="utf-8")
        with mock.patch.object(scraper.requests, "get", return_value=FakeResponse(empty)):
            no_work = scraper.scrap_links_result(
                "https://www.tiempopopular.com.ar/locales/",
                "locales",
            )
        with mock.patch.object(scraper.requests, "get", side_effect=requests.Timeout("timeout")):
            failed = scraper.scrap_links_result(
                "https://www.tiempopopular.com.ar/locales/",
                "locales",
            )

        self.assertEqual(StageStatus.NO_WORK, no_work.status)
        self.assertEqual(StageStatus.FAILED, failed.status)
        self.assertEqual("timeout", failed.error_type)

    def test_unexpected_article_is_failed_selector_contract(self):
        from scraping import base_tiempopopular as scraper
        from utils.stage_result import StageStatus

        html = (FIXTURES / "unexpected_article.html").read_text(encoding="utf-8")
        with mock.patch.object(scraper.requests, "get", return_value=FakeResponse(html)):
            result = scraper.scrap_noticia_result(
                "https://www.tiempopopular.com.ar/2026/07/23/nota-invalida/",
                "locales",
            )

        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("selector_mismatch", result.error_type)


class NuevaRiojaFixtureTests(unittest.TestCase):
    def test_each_section_has_a_representative_fixture(self):
        from scraping import base_nuevarioja as scraper
        from utils.stage_result import StageStatus

        sections = (
            "politica",
            "sociedad",
            "policiales",
            "deportes",
            "interior",
            "internacionales",
        )
        for section in sections:
            with self.subTest(section=section):
                response = FakeResponse(fixture(f"nuevarioja_{section}_section.html"))
                with mock.patch.object(scraper.requests, "get", return_value=response):
                    result = scraper.scrap_links_result(
                        f"https://nuevarioja.com.ar/{section}",
                        section,
                    )
                self.assertEqual(result.status, StageStatus.SUCCESS)
                self.assertEqual(len(result.links), 1)
                self.assertIn(f"{section}-fixture", result.links[0])

    def test_relative_links_and_article_fields(self):
        from scraping import base_nuevarioja as scraper
        from utils.stage_result import StageStatus

        section_html = (FIXTURES / "nuevarioja_section.html").read_text(encoding="utf-8")
        article_html = (FIXTURES / "nuevarioja_article.html").read_text(encoding="utf-8")
        with mock.patch.object(scraper.requests, "get", return_value=FakeResponse(section_html)):
            links = scraper.scrap_links_result(
                "https://nuevarioja.com.ar/politica",
                "politica",
            )
        with mock.patch.object(scraper.requests, "get", return_value=FakeResponse(article_html)), mock.patch.object(
            scraper, "_download_image", return_value=("raw.jpg", "opt.jpg")
        ):
            article = scraper.scrap_noticia_result(links.links[0], "politica")

        self.assertEqual(StageStatus.SUCCESS, links.status)
        self.assertEqual(
            "https://nuevarioja.com.ar/politica/el-gobierno-presento-el-nuevo-programa-provincial.htm",
            links.links[0],
        )
        self.assertEqual(StageStatus.SUCCESS, article.status)
        self.assertEqual("Presentaron un programa provincial", article.article["titulo"])
        self.assertEqual("nuevarioja_politica", article.article["source"])

    def test_http_error_is_failed(self):
        from scraping import base_nuevarioja as scraper
        from utils.stage_result import StageStatus

        with mock.patch.object(scraper.requests, "get", return_value=FakeResponse(status_code=500)):
            result = scraper.scrap_links_result(
                "https://nuevarioja.com.ar/politica",
                "politica",
            )

        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("http_error", result.error_type)
        self.assertEqual(500, result.http_status)


if __name__ == "__main__":
    unittest.main()
