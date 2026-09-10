import os
import unittest

from sources.strategies.html_index import parse_html_index
from sources.strategies.rss import parse_rss

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "official_sources")


def _read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), "r", encoding="utf-8") as handle:
        return handle.read()


class ParseRssTests(unittest.TestCase):
    def test_parses_rss2_items_with_title_link_and_date(self):
        items = parse_rss(_read_fixture("sample_rss.xml"), source_id="mpf_larioja")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "El MPF confirmo la apertura de una nueva causa")
        self.assertEqual(items[0].url, "https://ejemplo.gob.ar/noticias/mpf-nueva-causa")
        self.assertIn("2026", items[0].published_at)
        self.assertNotIn("<p>", items[0].excerpt)

    def test_parses_atom_feed_when_no_rss_items(self):
        items = parse_rss(_read_fixture("sample_atom.xml"), source_id="ejemplo")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Se lanzo un nuevo programa de asistencia")
        self.assertEqual(items[0].url, "https://ejemplo.gob.ar/noticias/nuevo-programa")

    def test_invalid_xml_returns_empty_list_without_raising(self):
        items = parse_rss("<not-valid-xml", source_id="x")
        self.assertEqual(items, [])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(parse_rss("", source_id="x"), [])

    def test_respects_max_items(self):
        items = parse_rss(_read_fixture("sample_rss.xml"), source_id="mpf_larioja", max_items=1)
        self.assertEqual(len(items), 1)


class ParseHtmlIndexTests(unittest.TestCase):
    def test_extracts_articles_with_dates_and_excludes_nav_and_cross_domain(self):
        items = parse_html_index(
            _read_fixture("sample_html_index.html"),
            source_id="ejemplo",
            base_url="https://ejemplo.gob.ar/noticias/",
        )
        urls = [item.url for item in items]
        self.assertIn("https://ejemplo.gob.ar/noticias/2026/obra-vial-comenzo", urls)
        self.assertIn("https://ejemplo.gob.ar/noticias/2026/campana-vacunacion", urls)
        self.assertNotIn("https://otrositio.com/noticia", urls)
        self.assertFalse(any("Inicio" == item.title for item in items))
        self.assertFalse(any("Contacto" == item.title for item in items))

    def test_extracts_published_at_from_nearby_text(self):
        items = parse_html_index(
            _read_fixture("sample_html_index.html"),
            source_id="ejemplo",
            base_url="https://ejemplo.gob.ar/noticias/",
        )
        by_url = {item.url: item for item in items}
        obra = by_url["https://ejemplo.gob.ar/noticias/2026/obra-vial-comenzo"]
        self.assertIn("01/09/2026", obra.published_at)

    def test_invalid_html_returns_empty_list(self):
        self.assertEqual(parse_html_index("", source_id="x", base_url="https://x.gob.ar/"), [])

    def test_respects_max_items(self):
        items = parse_html_index(
            _read_fixture("sample_html_index.html"),
            source_id="ejemplo",
            base_url="https://ejemplo.gob.ar/noticias/",
            max_items=1,
        )
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
