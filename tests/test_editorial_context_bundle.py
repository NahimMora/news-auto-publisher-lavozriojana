import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from editorial_context import archive_index as ai
from editorial_context import bundle as eb
from editorial_context import metrics as ec_metrics
from sources import cache as source_cache
from sources.contract import OfficialSourceItem


class BuildContextBundleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "bundle_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_no_archive_no_official_gives_none_depth_and_empty_fragment(self):
        result = eb.build_context_bundle(
            article_id="new1",
            title="Una noticia completamente nueva sin antecedentes",
            category="sociedad",
            path=self.db_path,
        )
        self.assertEqual(result.context_depth, "NONE")
        self.assertEqual(result.to_prompt_fragment(), {})

    def test_strong_archive_match_produces_light_or_higher_with_snippet(self):
        ai.upsert_article(
            ai.ArchiveArticle(
                article_id="prev1",
                title="Juan Perez fue detenido por la causa de contrabando de autopartes",
                excerpt="La fiscalia confirmo la detencion en un operativo conjunto",
                category="policiales",
                published_at="2026-08-01T10:00:00Z",
                canonical_url="https://lavozriojana.com/prev1",
            ),
            path=self.db_path,
        )
        result = eb.build_context_bundle(
            article_id="new1",
            title="Juan Perez fue condenado en la causa de contrabando de autopartes",
            category="policiales",
            published_at="2026-08-10T10:00:00Z",
            path=self.db_path,
        )
        self.assertNotEqual(result.context_depth, "NONE")
        fragment = result.to_prompt_fragment()
        self.assertIn("archive_context", fragment)
        self.assertIn("context_depth", fragment)

    def test_official_snippet_alone_without_archive_gives_light(self):
        result = eb.build_context_bundle(
            article_id="new1",
            title="ANSES confirmo un nuevo bono para jubilados",
            category="economia",
            official_snippets=[
                eb.ContextSnippet(text="El bono sera de $50.000", source_type="official_source", source_id="anses", source_url="https://anses.gob.ar/x")
            ],
            path=self.db_path,
        )
        self.assertEqual(result.context_depth, "LIGHT")
        self.assertIn("official_context", result.to_prompt_fragment())

    def test_factual_basis_text_includes_snippet_content_for_validator_allowlist(self):
        result = eb.build_context_bundle(
            article_id="new1",
            title="ANSES confirmo un nuevo bono para jubilados",
            category="economia",
            official_snippets=[
                eb.ContextSnippet(text="El bono sera de $50.000 segun ANSES", source_type="official_source", source_id="anses")
            ],
            path=self.db_path,
        )
        self.assertIn("$50.000", result.factual_basis_text)

    def test_never_raises_even_if_internals_fail(self):
        with patch("editorial_context.bundle._build_context_bundle", side_effect=RuntimeError("boom")):
            result = eb.build_context_bundle(article_id="x", title="titulo", path=self.db_path)
        self.assertEqual(result.context_depth, "NONE")

    def test_auto_gathers_relevant_official_snippet_from_cache_via_selector(self):
        source_cache.upsert_cache_item(
            OfficialSourceItem(
                source_id="mpf_larioja",
                title="El MPF confirmo la apertura de una causa de contrabando de autopartes",
                url="https://www.mpflarioja.gob.ar/n/1",
                excerpt="La fiscalia detallo el operativo realizado en Chilecito",
                published_at="2026-08-09T10:00:00Z",
            ),
            path=self.db_path,
        )
        result = eb.build_context_bundle(
            article_id="new1",
            title="Se realizo un nuevo allanamiento en la causa de contrabando de autopartes",
            category="policiales",
            path=self.db_path,
        )
        self.assertTrue(any(s.source_id == "mpf_larioja" for s in result.official_snippets))
        self.assertIn("official_context", result.to_prompt_fragment())

    def test_auto_gather_ignores_unrelated_cached_items(self):
        source_cache.upsert_cache_item(
            OfficialSourceItem(
                source_id="mpf_larioja",
                title="Se realizo una capacitacion interna sobre gestion documental",
                url="https://www.mpflarioja.gob.ar/n/2",
                excerpt="Actividad administrativa sin vinculo con causas judiciales",
            ),
            path=self.db_path,
        )
        result = eb.build_context_bundle(
            article_id="new1",
            title="Juan Perez fue condenado en la causa de contrabando de autopartes",
            category="policiales",
            path=self.db_path,
        )
        self.assertEqual(result.official_snippets, [])

    def test_records_bundle_event_metrics(self):
        eb.build_context_bundle(article_id="new1", title="Una nota cualquiera", category="sociedad", path=self.db_path)
        summary = ec_metrics.editorial_metrics_summary(path=self.db_path)
        self.assertEqual(summary["articles_evaluated"], 1)
        self.assertEqual(summary["context_depth_none"], 1)


class ArchiveContextEntriesTests(unittest.TestCase):
    def test_empty_when_story_key_present(self):
        bundle = eb.EditorialContextBundle(
            story_key="story:x",
            archive_snippets=[eb.ContextSnippet(text="antecedente", source_type="own_archive")],
            related_articles=[{"article_id": "a1", "title": "T", "url": "https://x"}],
        )
        self.assertEqual(bundle.archive_context_entries(), [])

    def test_zips_snippets_with_related_articles_by_index(self):
        bundle = eb.EditorialContextBundle(
            story_key="",
            archive_snippets=[eb.ContextSnippet(text="En junio se habia anunciado la obra", source_type="own_archive")],
            related_articles=[{"article_id": "a1", "title": "Titulo previo", "url": "https://lavozriojana.com/a1"}],
        )
        entries = bundle.archive_context_entries()
        self.assertEqual(
            entries,
            [
                {
                    "postId": "a1",
                    "title": "Titulo previo",
                    "url": "https://lavozriojana.com/a1",
                    "snippet": "En junio se habia anunciado la obra",
                }
            ],
        )

    def test_empty_when_no_related_articles(self):
        bundle = eb.EditorialContextBundle(story_key="")
        self.assertEqual(bundle.archive_context_entries(), [])


if __name__ == "__main__":
    unittest.main()
