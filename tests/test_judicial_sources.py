"""Fuentes judiciales oficiales: scraping, puntaje, mismo caso y reglas de redacción."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

from scraping import base_judiciales as bj
from tests.test_scraper_fixtures import FIXTURES, FakeResponse, fixture
from utils.stage_result import StageStatus

MPF_URL = "https://www.mpflarioja.gob.ar/2026/10/15/condenaron-a-prision-perpetua-por-femicidio/"
JUS_URL = (
    "https://www.justicialarioja.gob.ar/index.php/typography/"
    "noticias-e-informacion-general/3920-la-justicia-condeno-a-un-hombre"
)


def _feed(name: str) -> FakeResponse:
    return FakeResponse(content=(FIXTURES / name).read_bytes())


class JudicialScraperTests(unittest.TestCase):
    def test_mpf_links_use_link_and_ignore_other_hosts(self):
        with mock.patch.object(bj.requests, "get", return_value=_feed("judicial_mpf_feed.xml")):
            result = bj.scrap_links_result("mpf")
        self.assertEqual(StageStatus.SUCCESS, result.status)
        self.assertEqual([MPF_URL.rstrip("/")], result.links)

    def test_justicia_links_use_guid_not_the_category_link(self):
        with mock.patch.object(bj.requests, "get", return_value=_feed("judicial_justicia_feed.xml")):
            result = bj.scrap_links_result("justicia")
        self.assertEqual(2, len(result.links))
        self.assertEqual(JUS_URL, result.links[0])
        self.assertTrue(all("/392" not in url.rsplit("/", 1)[-1][:4] for url in result.links))

    def test_feed_errors(self):
        with mock.patch.object(bj.requests, "get", side_effect=requests.Timeout("timeout")):
            timeout = bj.scrap_links_result("mpf")
        with mock.patch.object(bj.requests, "get", return_value=FakeResponse(content=b"<html>no rss")):
            broken = bj.scrap_links_result("mpf")
        self.assertEqual(("failed", "timeout"), (timeout.status.value, timeout.error_type))
        self.assertEqual(("failed", "parse_error"), (broken.status.value, broken.error_type))

    def test_mpf_article(self):
        with mock.patch.object(bj.requests, "get", return_value=FakeResponse(fixture("judicial_mpf_article.html"))), mock.patch.object(
            bj, "_download_image", return_value=("raw.jpg", "opt.jpg")
        ):
            article = bj.scrap_noticia_result(MPF_URL, "mpf").article
        self.assertEqual("Condenaron a prisión perpetua a un hombre por femicidio", article["titulo"])
        self.assertEqual("judicial_mpf", article["source"])
        self.assertEqual("policiales", article["seccion"])
        self.assertEqual("2026-10-15", article["fecha"])
        self.assertEqual(2, len(article["parrafos"]))
        # Salta los logos y resuelve la ruta relativa.
        self.assertEqual("https://www.mpflarioja.gob.ar/wp-content/uploads/2026/10/1-4-1024x682.jpeg", article["imagen_url"])

    def test_justicia_article_takes_title_from_article_and_date_from_feed(self):
        with mock.patch.object(bj.requests, "get", return_value=_feed("judicial_justicia_feed.xml")):
            bj.scrap_links_result("justicia")
        with mock.patch.object(bj.requests, "get", return_value=FakeResponse(fixture("judicial_justicia_article.html"))), mock.patch.object(
            bj, "_download_image", return_value=("raw.jpg", "opt.jpg")
        ):
            article = bj.scrap_noticia_result(JUS_URL, "justicia").article
        self.assertEqual("La justicia condenó a un hombre por violencia contra su expareja", article["titulo"])
        self.assertEqual("2026-10-20", article["fecha"])
        self.assertEqual(
            "https://www.justicialarioja.gob.ar/images/Condena_violencia_20-10-26.jpeg", article["imagen_url"]
        )

    def test_article_without_body_fails(self):
        with mock.patch.object(bj.requests, "get", return_value=FakeResponse(fixture("empty_page.html"))):
            result = bj.scrap_noticia_result(MPF_URL, "mpf")
        self.assertEqual(("failed", "selector_mismatch"), (result.status.value, result.error_type))

    def test_disabled_by_default(self):
        import main_judiciales

        with mock.patch.dict(os.environ, {"SCRAPER_JUDICIALES_ENABLED": "0"}):
            result = main_judiciales.main()
        self.assertEqual(StageStatus.NO_WORK, result.status)


class JudicialAssessmentTests(unittest.TestCase):
    def _assess(self, raw, recent=("Detuvieron a un hombre en Chilecito",)):
        from utils import judicial_sources

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test", "GEMINI_RETRY_COUNT": "1"}), mock.patch(
            "utils.ai_client.chat_completion", return_value=raw
        ):
            return judicial_sources.assess_judicial("Título", ["Texto"], list(recent))

    def test_score_and_same_case(self):
        self.assertEqual((9, None), (self._assess('{"puntaje": 9, "mismo_caso": null}').score, None))
        same = self._assess('{"puntaje": 8, "mismo_caso": 1}')
        self.assertEqual((8, "Detuvieron a un hombre en Chilecito"), (same.score, same.duplicate_of))

    def test_invalid_answers(self):
        self.assertIsNone(self._assess("no sé").score)
        self.assertIsNone(self._assess('{"puntaje": true}').score)
        out_of_range = self._assess('{"puntaje": 15, "mismo_caso": 7}')
        self.assertEqual((10, None), (out_of_range.score, out_of_range.duplicate_of))

    def test_without_credentials(self):
        from utils import judicial_sources

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            result = judicial_sources.assess_judicial("Título", ["Texto"], [])
        self.assertEqual((None, "credential_missing"), (result.score, result.error_type))


class JudicialRewriteGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        import openIA.rewrite_news as rn

        self.rn = rn
        self.meta = Path(self.tmp.name) / "meta.json"
        now = int(time.time())
        self.meta.write_text(
            json.dumps(
                [
                    {"titulo_original": "Condenan a un hombre por violencia", "source": "tiempopopular_policiales", "seccion": "policiales", "queued_at": now},
                    {"titulo": "Ganó Andino", "source": "nuevarioja_deportes", "seccion": "deportes", "queued_at": now},
                    {"titulo": "Escándalo en la TV", "source": "paparazzi", "seccion": "espectaculos", "queued_at": now},
                    {"titulo": "Nota vieja", "source": "tiempopopular_locales", "seccion": "policiales", "queued_at": now - 5 * 86400},
                ]
            ),
            encoding="utf-8",
        )
        patcher = mock.patch.object(rn, "META_OUTPUT", str(self.meta))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_recent_titles_only_local_recent_and_judicial_categories(self):
        self.assertEqual(["Condenan a un hombre por violencia"], self.rn._recent_local_titles())

    def test_gate_decisions(self):
        from utils.judicial_sources import JudicialAssessment

        cases = {
            "pass": (JudicialAssessment(8), ("pass", "")),
            "dup": (JudicialAssessment(9, "Condenan a un hombre"), ("drop", "duplicate_judicial_case:Condenan a un hombre")),
            "low": (JudicialAssessment(5), ("drop", "judicial_low_score:5")),
            "retry": (JudicialAssessment(None, error_type="gemini_failed"), ("retry", "judicial_score_unavailable:gemini_failed")),
        }
        for name, (assessment, expected) in cases.items():
            with self.subTest(name=name), mock.patch.object(self.rn, "assess_judicial", return_value=assessment), mock.patch.dict(
                os.environ, {"JUDICIAL_MIN_SCORE": "7"}
            ):
                noticia = {"titulo": "t", "parrafos": ["p"], "source": "judicial_mpf"}
                self.assertEqual(expected, self.rn._judicial_gate(noticia))
                if assessment.score is not None:
                    self.assertEqual(assessment.score, noticia["judicial_relevance_score"])


class JudicialPromptRulesTests(unittest.TestCase):
    def test_title_prompt_includes_rules_only_for_judicial(self):
        import openIA.rewrite_news as rn
        from utils.judicial_sources import JUDICIAL_RULES

        with mock.patch.object(rn, "chat_completion", return_value="TITULO: t\nHASHTAG: NINGUNO") as call:
            rn._call_gemini("Título", ["p"], JUDICIAL_RULES)
            rn._call_gemini("Título", ["p"])
        self.assertIn(JUDICIAL_RULES, call.call_args_list[0].kwargs["messages"][0]["content"])
        self.assertNotIn("Fuente oficial judicial", call.call_args_list[1].kwargs["messages"][0]["content"])

    def test_caption_system_prompt_includes_rules(self):
        from openIA import caption_generator
        from utils.judicial_sources import JUDICIAL_RULES

        payload = json.dumps({"titulo_instagram": "T", "texto_instagram": "Texto", "cta": "¿Qué opinás?"})
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test"}), mock.patch(
            "utils.ai_client.chat_completion", return_value=payload
        ) as call:
            caption_generator.generate_caption(
                {"titulo": "T", "seccion": "policiales", "parrafos": ["Texto"], "source": "judicial_justicia"}
            )
        self.assertIn(JUDICIAL_RULES, call.call_args.kwargs["messages"][0]["content"])

    def test_web_editorial_payload_includes_source_rules(self):
        from pipeline.node_webapp import editorial
        from utils.judicial_sources import JUDICIAL_RULES

        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test"}), mock.patch(
            "utils.ai_client.chat_completion", return_value="{}"
        ) as call:
            editorial._call_ai_enricher(
                {"titulo": "T", "seccion": "policiales", "parrafos": ["Texto"], "source": "judicial_mpf"}
            )
        payload = json.loads(call.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(JUDICIAL_RULES, payload["source_rules"])


if __name__ == "__main__":
    unittest.main()
