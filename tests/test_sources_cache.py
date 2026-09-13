import tempfile
import unittest
from pathlib import Path

from sources import cache
from sources.contract import OfficialSourceItem


def _item(source_id, url, title, **kwargs):
    defaults = dict(source_id=source_id, url=url, title=title)
    defaults.update(kwargs)
    return OfficialSourceItem(**defaults)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "cache_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_upsert_new_item_is_marked_new(self):
        result = cache.upsert_cache_item(
            _item("mpf_larioja", "https://x.gob.ar/a", "El MPF confirmo la apertura de la causa"),
            path=self.db_path,
        )
        self.assertTrue(result["is_new"])
        self.assertIsNone(result["duplicate_of_url"])

    def test_upsert_same_url_twice_is_idempotent_and_not_new_second_time(self):
        item = _item("mpf_larioja", "https://x.gob.ar/a", "Titulo")
        cache.upsert_cache_item(item, path=self.db_path)
        second = cache.upsert_cache_item(item, path=self.db_path)
        self.assertFalse(second["is_new"])
        entry = cache.get_cache_entry("https://x.gob.ar/a", path=self.db_path)
        self.assertEqual(entry["title"], "Titulo")

    def test_cross_source_similar_title_marked_as_duplicate(self):
        cache.upsert_cache_item(
            _item("gobierno_larioja", "https://gobierno.gob.ar/a", "El gobierno anuncio un nuevo programa de asistencia social"),
            path=self.db_path,
        )
        result = cache.upsert_cache_item(
            _item("hacienda_larioja", "https://hacienda.gob.ar/b", "El gobierno anuncio un nuevo programa de asistencia social"),
            path=self.db_path,
        )
        self.assertEqual(result["duplicate_of_url"], "https://gobierno.gob.ar/a")

    def test_unrelated_items_are_not_marked_duplicate(self):
        cache.upsert_cache_item(
            _item("mpf_larioja", "https://x.gob.ar/a", "El MPF confirmo la apertura de una causa de contrabando"),
            path=self.db_path,
        )
        result = cache.upsert_cache_item(
            _item("smn_news", "https://smn.gob.ar/b", "Se emitio una alerta meteorologica amarilla"),
            path=self.db_path,
        )
        self.assertIsNone(result["duplicate_of_url"])

    def test_recent_items_for_source_filters_by_source(self):
        cache.upsert_cache_item(_item("mpf_larioja", "https://x.gob.ar/a", "Titulo A"), path=self.db_path)
        cache.upsert_cache_item(_item("smn_news", "https://smn.gob.ar/b", "Titulo B"), path=self.db_path)
        items = cache.recent_items_for_source("mpf_larioja", path=self.db_path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://x.gob.ar/a")


if __name__ == "__main__":
    unittest.main()
