import json
import tempfile
import unittest
from pathlib import Path

from sources import registry


class RegistryDefaultFileTests(unittest.TestCase):
    def test_default_registry_file_loads_without_error(self):
        sources = registry.load_registry()
        self.assertGreater(len(sources), 20)

    def test_all_source_ids_unique(self):
        sources = registry.load_registry()
        ids = [s.source_id for s in sources]
        self.assertEqual(len(ids), len(set(ids)))

    def test_disabled_sources_have_a_documented_reason_in_notes(self):
        for source in registry.load_registry():
            if not source.enabled:
                self.assertTrue(source.notes, f"{source.source_id} deshabilitada sin notes")

    def test_policia_larioja_is_disabled_facebook_only(self):
        source = registry.get_source("policia_larioja")
        self.assertIsNotNone(source)
        self.assertFalse(source.enabled)
        self.assertEqual(source.host, "www.facebook.com")

    def test_url_property_reconstructs_full_address(self):
        source = registry.get_source("mpf_larioja")
        self.assertEqual(source.url, "https://www.mpflarioja.gob.ar/feed/")

    def test_enabled_sources_returns_only_enabled(self):
        for source in registry.enabled_sources():
            self.assertTrue(source.enabled)


class RegistryCustomFileTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "sources.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, items):
        self.path.write_text(json.dumps(items), encoding="utf-8")

    def test_duplicate_source_id_raises(self):
        self._write(
            [
                {"source_id": "a", "host": "x.gob.ar", "path": "/"},
                {"source_id": "a", "host": "y.gob.ar", "path": "/"},
            ]
        )
        with self.assertRaises(ValueError):
            registry.load_registry(self.path)

    def test_invalid_mode_raises(self):
        self._write([{"source_id": "a", "host": "x.gob.ar", "path": "/", "mode": "BOGUS"}])
        with self.assertRaises(ValueError):
            registry.load_registry(self.path)

    def test_defaults_applied_when_fields_missing(self):
        self._write([{"source_id": "a", "host": "x.gob.ar"}])
        sources = registry.load_registry(self.path)
        self.assertEqual(sources[0].path, "/")
        self.assertEqual(sources[0].mode, "BOTH")
        self.assertFalse(sources[0].enabled)
        self.assertEqual(sources[0].allowed_hosts, ("x.gob.ar",))


if __name__ == "__main__":
    unittest.main()
