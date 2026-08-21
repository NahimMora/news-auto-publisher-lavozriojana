from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from scraping import base_infobae as ib
from scraping import runner as scraping_runner
from utils.stage_result import StageStatus

HOME_HTML = """
<html><body><main>
<a href="/sociedad/policiales/2026/08/14/un-adolescente-mato-a-un-peluquero/">Nota 1</a>
<a href="/sociedad/policiales/2026/08/14/estafada-en-la-rioja/">Nota 2</a>
<a href="/sociedad/2026/08/14/nota-fuera-de-policiales/">Sociedad</a>
<a href="/deportes/2026/08/14/nota-de-deportes/">Deportes</a>
<a href="/sociedad/policiales/">Portada</a>
</main></body></html>
"""

ARTICLE_LD_JSON = {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    "headline": "Un adolescente mató a un peluquero en una barbería",
    "image": {"@type": "ImageObject", "url": "https://www.infobae.com/resizer/v2/foto.jpg"},
    "datePublished": "2026-08-14T18:48:45.465Z",
}

VIDEO_LD_JSON = {
    "@context": "https://schema.org",
    "@type": "VideoObject",
    "name": "Video de la nota",
    "contentUrl": "https://cdn.jwplayer.com/videos/cHYVdhpU-HeIT2Id1.mp4",
    "duration": "PT7M39S",
}


def _ld_script(data: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


def _article_html(*, with_video: bool) -> str:
    scripts = _ld_script(ARTICLE_LD_JSON)
    if with_video:
        scripts += _ld_script(VIDEO_LD_JSON)
    return f"""
<html><head>{scripts}</head><body>
<h1>Un adolescente mató a un peluquero en una barbería</h1>
<article>
<p class="paragraph" data-paragraph-number="1">Una discusión que comenzó por un turno para cortarse el pelo terminó con un crimen en Dock Sud.</p>
<p class="paragraph" data-paragraph-number="2">El agresor tiene 15 años y quedó a disposición de la Justicia tras el ataque.</p>
</article>
</body></html>
"""


class LinksScraperTests(unittest.TestCase):
    def test_filters_out_non_policiales_and_category_root(self):
        response = Mock(status_code=200, text=HOME_HTML)
        response.raise_for_status = Mock()
        with patch.object(ib.requests, "get", return_value=response):
            result = ib.scrap_links_result()

        self.assertEqual(StageStatus.SUCCESS, result.status)
        self.assertEqual(
            [
                "https://www.infobae.com/sociedad/policiales/2026/08/14/un-adolescente-mato-a-un-peluquero",
                "https://www.infobae.com/sociedad/policiales/2026/08/14/estafada-en-la-rioja",
            ],
            result.links,
        )

    def test_source_access_error_is_failed_not_empty(self):
        with patch.object(ib.requests, "get", side_effect=ib.requests.Timeout("boom")):
            result = ib.scrap_links_result()
        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("timeout", result.error_type)


class ArticleScraperTests(unittest.TestCase):
    def test_extracts_title_paragraphs_image_date_without_video(self):
        response = Mock(status_code=200, text=_article_html(with_video=False))
        response.raise_for_status = Mock()
        with patch.object(ib.requests, "get", return_value=response), patch.object(
            ib, "_download_image", return_value=("raw.jpg", "opt.jpg")
        ), patch.object(ib.time, "sleep"):
            result = ib.scrap_noticia_result(
                "https://www.infobae.com/sociedad/policiales/2026/08/14/x/"
            )

        self.assertEqual(StageStatus.SUCCESS, result.status)
        article = result.article
        self.assertEqual("Un adolescente mató a un peluquero en una barbería", article["titulo"])
        self.assertEqual(2, len(article["parrafos"]))
        self.assertEqual("infobae_policiales", article["source"])
        self.assertEqual("policiales", article["seccion"])
        self.assertEqual("2026-08-14", article["fecha"])
        self.assertNotIn("video_url", article)

    def test_extracts_direct_mp4_from_video_object_json_ld(self):
        response = Mock(status_code=200, text=_article_html(with_video=True))
        response.raise_for_status = Mock()
        with patch.object(ib.requests, "get", return_value=response), patch.object(
            ib, "_download_image", return_value=(None, None)
        ), patch.object(ib.time, "sleep"):
            result = ib.scrap_noticia_result(
                "https://www.infobae.com/sociedad/policiales/2026/08/14/x/"
            )

        article = result.article
        self.assertEqual(
            "https://cdn.jwplayer.com/videos/cHYVdhpU-HeIT2Id1.mp4", article["video_url"]
        )
        self.assertEqual(459, article["video_duration_seconds"])

    def test_missing_title_and_body_is_selector_mismatch(self):
        response = Mock(status_code=200, text="<html><body><p>sin titulo ni contenido real</p></body></html>")
        response.raise_for_status = Mock()
        with patch.object(ib.requests, "get", return_value=response), patch.object(ib.time, "sleep"):
            result = ib.scrap_noticia_result(
                "https://www.infobae.com/sociedad/policiales/2026/08/14/x/"
            )
        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("selector_mismatch", result.error_type)


class IsoDurationTests(unittest.TestCase):
    def test_parses_hours_minutes_seconds(self):
        self.assertEqual(459, ib._parse_iso_duration("PT7M39S"))
        self.assertEqual(3661, ib._parse_iso_duration("PT1H1M1S"))
        self.assertIsNone(ib._parse_iso_duration("garbage"))
        self.assertIsNone(ib._parse_iso_duration(""))


class IsArticleUrlTests(unittest.TestCase):
    def test_rejects_other_hosts(self):
        self.assertFalse(
            ib._is_article_url("https://evil.example.com/sociedad/policiales/2026/08/14/x/")
        )

    def test_accepts_relative_article_path(self):
        self.assertTrue(ib._is_article_url("/sociedad/policiales/2026/08/14/un-caso-largo/"))

    def test_rejects_section_root(self):
        self.assertFalse(ib._is_article_url("/sociedad/policiales/"))


class ExtraDiscardRunnerTests(unittest.TestCase):
    """La política 'sólo video o vínculo riojano' se aplica genéricamente en
    scraping.runner vía extra_discard — no debe afectar a fuentes que no lo
    pasan (paparazzi, policiales locales, etc. quedan con extra_discard=None)."""

    def test_extra_discard_none_keeps_default_behavior(self):
        from utils.scraper_contract import ArticleScrapeResult, LinkScrapeResult

        article = {"titulo": "x", "url": "https://example.com/a", "canonical_url": "https://example.com/a"}
        with patch("scraping.runner.load_json", return_value=[]), patch(
            "scraping.runner.append_json_items"
        ) as append_mock, patch("scraping.runner.record_queue_event"):
            result = scraping_runner.run_section(
                stage="test_stage",
                enabled=True,
                history_path="hist.json",
                output_path="out.json",
                fetch_links=lambda: LinkScrapeResult(status=StageStatus.SUCCESS, links=[article["url"]]),
                fetch_article=lambda url: ArticleScrapeResult(status=StageStatus.SUCCESS, article=article),
            )
        self.assertEqual(1, result.succeeded)
        self.assertEqual(2, append_mock.call_count)  # output + history

    def test_extra_discard_true_writes_only_to_history(self):
        from utils.scraper_contract import ArticleScrapeResult, LinkScrapeResult

        article = {"titulo": "x", "url": "https://example.com/a", "canonical_url": "https://example.com/a"}
        with patch("scraping.runner.load_json", return_value=[]), patch(
            "scraping.runner.append_json_items"
        ) as append_mock, patch("scraping.runner.record_queue_event") as event_mock:
            result = scraping_runner.run_section(
                stage="test_stage",
                enabled=True,
                history_path="hist.json",
                output_path="out.json",
                fetch_links=lambda: LinkScrapeResult(status=StageStatus.SUCCESS, links=[article["url"]]),
                fetch_article=lambda url: ArticleScrapeResult(status=StageStatus.SUCCESS, article=article),
                extra_discard=lambda a: (True, "no_video_no_riojan_link"),
            )
        self.assertEqual(1, result.succeeded)
        self.assertEqual(1, append_mock.call_count)  # history only, never output
        self.assertEqual("hist.json", append_mock.call_args[0][0])
        event_mock.assert_called_once()
        self.assertEqual("no_video_no_riojan_link", event_mock.call_args.kwargs["reason"])


class InfobaeDiscardPolicyTests(unittest.TestCase):
    def test_keeps_article_with_video(self):
        import main_infobae_policiales as entry

        keep, reason = entry._keep_if_video_or_riojan({"video_url": "https://x/v.mp4", "titulo": "x"})
        self.assertFalse(keep)  # keep == "should discard"; False = not discarded
        self.assertEqual("", reason)

    def test_keeps_article_with_riojan_link(self):
        import main_infobae_policiales as entry

        discard, reason = entry._keep_if_video_or_riojan(
            {"titulo": "Estafa en La Rioja", "parrafos": ["Una mujer fue estafada en La Rioja."]}
        )
        self.assertFalse(discard)
        self.assertEqual("", reason)

    def test_discards_article_without_video_or_riojan_link(self):
        import main_infobae_policiales as entry

        discard, reason = entry._keep_if_video_or_riojan(
            {"titulo": "Robo en Rosario", "parrafos": ["Un robo ocurrió en Rosario."]}
        )
        self.assertTrue(discard)
        self.assertEqual("infobae_sin_video_ni_vinculo_riojano", reason)


if __name__ == "__main__":
    unittest.main()
