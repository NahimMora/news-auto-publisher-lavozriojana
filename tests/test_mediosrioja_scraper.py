from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from scraping import base_mediosrioja as mr
from tests.test_scraper_fixtures import FakeResponse, fixture
from utils.stage_result import StageStatus

LOCAL_URL = "https://mediosrioja.com.ar/choque-entre-una-moto-y-un-utilitario-en-la-rioja-un-joven-sufrio-fractura-de-tibia-y-perone"


def _feed_response():
    text = fixture("mediosrioja_feed.xml")
    response = FakeResponse(text, headers={"Content-Type": "application/rss+xml"})
    response.content = text.encode("utf-8")
    return response


def _links():
    with mock.patch.object(mr.requests, "get", return_value=_feed_response()):
        return mr.scrap_links_result()


def _article(url: str = LOCAL_URL):
    with mock.patch.object(mr.requests, "get", return_value=FakeResponse(fixture("mediosrioja_article.html"))), mock.patch.object(
        mr, "_download_image", return_value=("raw.jpg", "opt.jpg")
    ):
        return mr.scrap_noticia_result(url)


class MediosRiojaLinksTests(unittest.TestCase):
    def setUp(self):
        mr._FEED_INFO.clear()

    def test_only_local_and_departmental_items(self):
        result = _links()

        self.assertEqual(StageStatus.SUCCESS, result.status)
        # Locales y Departamentales entran; Nacionales y Deportes no.
        self.assertEqual(2, len(result.links))
        self.assertTrue(all(link.startswith("https://mediosrioja.com.ar/") for link in result.links))
        self.assertTrue(any("choque-entre-una-moto" in link for link in result.links))
        self.assertTrue(any("chamical" in link for link in result.links))
        self.assertFalse(any("colapinto" in link or "libra" in link for link in result.links))

    def test_departmental_items_go_to_interior(self):
        result = _links()
        chamical = next(link for link in result.links if "chamical" in link)
        self.assertTrue(mr._FEED_INFO[chamical]["departamental"])
        self.assertFalse(mr._FEED_INFO[next(link for link in result.links if "choque" in link)]["departamental"])

    def test_broken_feed_and_timeout_fail(self):
        broken = FakeResponse("<rss><channel>")
        broken.content = b"<rss><channel>"
        with mock.patch.object(mr.requests, "get", return_value=broken):
            parse = mr.scrap_links_result()
        with mock.patch.object(mr.requests, "get", side_effect=requests.Timeout("timeout")):
            timeout = mr.scrap_links_result()

        self.assertEqual(("failed", "parse_error"), (parse.status.value, parse.error_type))
        self.assertEqual(("failed", "timeout"), (timeout.status.value, timeout.error_type))

    def test_feed_without_local_items_is_no_work(self):
        text = '<?xml version="1.0"?><rss><channel><item><title>x</title><link>https://mediosrioja.com.ar/una-nota-nacional-larga</link><category>Nacionales</category></item></channel></rss>'
        response = FakeResponse(text)
        response.content = text.encode("utf-8")
        with mock.patch.object(mr.requests, "get", return_value=response):
            result = mr.scrap_links_result()
        self.assertEqual(StageStatus.NO_WORK, result.status)


class MediosRiojaArticleTests(unittest.TestCase):
    def setUp(self):
        mr._FEED_INFO.clear()

    def test_article_fields(self):
        result = _article()

        self.assertEqual(StageStatus.SUCCESS, result.status)
        article = result.article
        self.assertTrue(article["titulo"].startswith("Choque entre una moto y un utilitario en La Rioja"))
        self.assertEqual("2026-10-24", article["fecha"])
        self.assertEqual("mediosrioja_locales", article["source"])
        self.assertEqual("locales", article["seccion"])
        self.assertEqual("https://mediosrioja.com.ar/wp-content/uploads/2026/10/ch.jpg", article["imagen_url"])
        # Sólo el cuerpo: ni el menú, ni "Compartir", ni "Te puede interesar".
        self.assertEqual(5, len(article["parrafos"]))
        self.assertFalse(any(p.lower().startswith(("compartir", "te puede", "menú")) for p in article["parrafos"]))

    def test_departmental_article_is_interior(self):
        _links()
        chamical = next(url for url, info in mr._FEED_INFO.items() if info["departamental"])
        result = _article(chamical)
        self.assertEqual(("interior", "mediosrioja_interior"), (result.article["seccion"], result.article["source"]))

    def test_http_error_selector_mismatch_and_foreign_url_fail(self):
        with mock.patch.object(mr.requests, "get", return_value=FakeResponse(status_code=503)):
            http_error = mr.scrap_noticia_result(LOCAL_URL)
        with mock.patch.object(mr.requests, "get", return_value=FakeResponse(fixture("empty_page.html"))):
            mismatch = mr.scrap_noticia_result(LOCAL_URL)
        foreign = mr.scrap_noticia_result("https://otro-sitio.com.ar/una-nota-cualquiera-larga")

        self.assertEqual(StageStatus.FAILED, http_error.status)
        self.assertEqual("selector_mismatch", mismatch.error_type)
        self.assertEqual("selector_mismatch", foreign.error_type)


class MediosRiojaRunnerTests(unittest.TestCase):
    def setUp(self):
        mr._FEED_INFO.clear()

    def test_section_persists_local_notes(self):
        from scraping.runner import run_section

        def get(url, **_kw):
            return _feed_response() if url == mr.FEED_URL else FakeResponse(fixture("mediosrioja_article.html"))

        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "noticias_ejecutadas_mediosrioja.json"
            output = Path(tmp) / "noticias_norewrite_mediosrioja.json"
            with mock.patch.object(mr.requests, "get", side_effect=get), mock.patch.object(
                mr, "_download_image", return_value=("raw.jpg", "opt.jpg")
            ), mock.patch("scraping.runner.record_queue_event"), mock.patch("scraping.runner.is_blocked", return_value=False):
                result = run_section(
                    stage="scrape_mediosrioja",
                    enabled=True,
                    history_path=str(history),
                    output_path=str(output),
                    fetch_links=mr.scrap_links_result,
                    fetch_article=mr.scrap_noticia_result,
                )
            queued = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(StageStatus.SUCCESS, result.status)
        self.assertEqual(2, len(queued))
        self.assertTrue(all(item["source"].startswith("mediosrioja_") for item in queued))

    def test_disabled_by_default(self):
        import main_mediosrioja

        with mock.patch.dict("os.environ", {"SCRAPER_MEDIOSRIOJA_ENABLED": "0"}):
            result = main_mediosrioja.main()
        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertTrue(result.details.get("disabled"))


if __name__ == "__main__":
    unittest.main()
