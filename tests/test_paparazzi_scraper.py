from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from scraping import base_paparazzi as ppz
from utils.stage_result import StageStatus


HOME_HTML = """
<html><body><main>
<a href="/tag/wanda-nara/">Wanda Nara</a>
<a href="/teve/un-escandalo-de-famosos-muy-largo-de-verdad/">Escándalo</a>
<a href="/deportes/el-pase-del-jugador-mas-comentado-del-ano/">Pase</a>
<a href="/horoscopo/el-horoscopo-de-hoy-miercoles/">Horóscopo</a>
<a href="/branded-content/publicidad-pago-de-una-marca/">Publi</a>
<a href="/teve/">Teve</a>
</main></body></html>
"""

ARTICLE_HTML_NO_VIDEO = """
<html><head>
<meta property="og:title" content="Titulo OG"/>
<meta property="og:image" content="https://www.paparazzi.com.ar/wp-content/uploads/foto.jpg"/>
<meta property="article:published_time" content="2026-08-05T10:00:00+00:00"/>
</head><body>
<h1 class="entry-title">Un escándalo de famosos muy largo de verdad</h1>
<div class="entry-content">
<p>Este es un párrafo lo suficientemente largo como para pasar el filtro de longitud minima.</p>
<p>Otro párrafo también largo, con suficiente texto para no ser descartado por el scraper.</p>
</div>
</body></html>
"""

ARTICLE_HTML_WITH_VIDEO = ARTICLE_HTML_NO_VIDEO.replace(
    '<h1 class="entry-title">Un escándalo de famosos muy largo de verdad</h1>',
    '<h1 class="entry-title">Un escándalo de famosos muy largo de verdad</h1>'
    '<div class="contenedor_video_intro">'
    '<script src="https://cdn.jwplayer.com/players/AbCdEfGh-gPzfiBLp.js"></script></div>',
)

JWPLAYER_RESPONSE = {
    "playlist": [
        {
            "duration": 142,
            "sources": [
                {"type": "video/mp4", "label": "180p", "file": "https://cdn.jwplayer.com/v/180.mp4"},
                {"type": "video/mp4", "label": "540p", "file": "https://cdn.jwplayer.com/v/540.mp4"},
                {"type": "application/vnd.apple.mpegurl", "file": "https://cdn.jwplayer.com/m.m3u8"},
            ],
        }
    ]
}


class LinksScraperTests(unittest.TestCase):
    def test_filters_out_tag_horoscopo_branded_and_category_root(self):
        response = Mock(status_code=200, text=HOME_HTML)
        response.raise_for_status = Mock()
        with patch.object(ppz.requests, "get", return_value=response):
            result = ppz.scrap_links_result()

        self.assertEqual(StageStatus.SUCCESS, result.status)
        self.assertEqual(
            [
                "https://www.paparazzi.com.ar/teve/un-escandalo-de-famosos-muy-largo-de-verdad",
                "https://www.paparazzi.com.ar/deportes/el-pase-del-jugador-mas-comentado-del-ano",
            ],
            result.links,
        )

    def test_source_access_error_is_failed_not_empty(self):
        with patch.object(ppz.requests, "get", side_effect=ppz.requests.Timeout("boom")):
            result = ppz.scrap_links_result()
        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("timeout", result.error_type)


class ArticleScraperTests(unittest.TestCase):
    def test_extracts_title_paragraphs_image_date_without_video(self):
        response = Mock(status_code=200, text=ARTICLE_HTML_NO_VIDEO)
        response.raise_for_status = Mock()
        with patch.object(ppz.requests, "get", return_value=response), patch.object(
            ppz, "_download_image", return_value=("raw.jpg", "opt.jpg")
        ), patch.object(ppz.time, "sleep"):
            result = ppz.scrap_noticia_result("https://www.paparazzi.com.ar/teve/x/")

        self.assertEqual(StageStatus.SUCCESS, result.status)
        article = result.article
        self.assertEqual("Un escándalo de famosos muy largo de verdad", article["titulo"])
        self.assertEqual(2, len(article["parrafos"]))
        self.assertEqual("paparazzi", article["source"])
        self.assertEqual("2026-08-05", article["fecha"])
        self.assertNotIn("video_url", article)

    def test_resolves_jwplayer_video_and_picks_preferred_mp4_label(self):
        article_response = Mock(status_code=200, text=ARTICLE_HTML_WITH_VIDEO)
        article_response.raise_for_status = Mock()
        jw_response = Mock(status_code=200)
        jw_response.raise_for_status = Mock()
        jw_response.json = Mock(return_value=JWPLAYER_RESPONSE)

        with patch.object(
            ppz.requests, "get", side_effect=[article_response, jw_response]
        ), patch.object(ppz, "_download_image", return_value=(None, None)), patch.object(
            ppz.time, "sleep"
        ):
            result = ppz.scrap_noticia_result("https://www.paparazzi.com.ar/teve/x/")

        article = result.article
        self.assertEqual("https://cdn.jwplayer.com/v/540.mp4", article["video_url"])
        self.assertEqual(142, article["video_duration_seconds"])

    def test_jwplayer_api_failure_degrades_to_no_video_without_failing_article(self):
        article_response = Mock(status_code=200, text=ARTICLE_HTML_WITH_VIDEO)
        article_response.raise_for_status = Mock()
        with patch.object(
            ppz.requests, "get", side_effect=[article_response, ppz.requests.Timeout("jw down")]
        ), patch.object(ppz, "_download_image", return_value=("raw.jpg", "opt.jpg")), patch.object(
            ppz.time, "sleep"
        ):
            result = ppz.scrap_noticia_result("https://www.paparazzi.com.ar/teve/x/")

        self.assertEqual(StageStatus.SUCCESS, result.status)
        self.assertNotIn("video_url", result.article)

    def test_missing_title_is_selector_mismatch(self):
        response = Mock(status_code=200, text="<html><body><p>sin titulo ni contenido real</p></body></html>")
        response.raise_for_status = Mock()
        with patch.object(ppz.requests, "get", return_value=response), patch.object(ppz.time, "sleep"):
            result = ppz.scrap_noticia_result("https://www.paparazzi.com.ar/teve/x/")
        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("selector_mismatch", result.error_type)


class IsArticleUrlTests(unittest.TestCase):
    def test_rejects_other_hosts(self):
        self.assertFalse(ppz._is_article_url("https://evil.example.com/teve/algo-largo-de-verdad/"))

    def test_accepts_relative_article_path(self):
        self.assertTrue(ppz._is_article_url("/teve/algo-largo-de-verdad/"))

    def test_rejects_short_slug(self):
        self.assertFalse(ppz._is_article_url("/teve/x/"))


if __name__ == "__main__":
    unittest.main()
