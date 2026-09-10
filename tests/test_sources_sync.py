import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sources import cache as source_cache
from sources import fetch_state
from sources import http_client
from sources import sync
from sources.registry import SourceDefinition


def _rss_source(**overrides):
    defaults = dict(
        source_id="mpf_larioja",
        name="MPF",
        scheme="https",
        host="www.mpflarioja.gob.ar",
        path="/feed/",
        mode="BOTH",
        enabled=True,
        discovery_strategy="RSS",
        fetch_strategy="rss",
        allowed_hosts=("www.mpflarioja.gob.ar",),
        max_items_per_cycle=10,
        categories=("policiales",),
    )
    defaults.update(overrides)
    return SourceDefinition(**defaults)


_SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>El MPF confirmo la apertura de una causa</title>
<link>https://www.mpflarioja.gob.ar/n/1</link>
<pubDate>Mon, 01 Sep 2026 10:00:00 -0300</pubDate></item>
</channel></rss>"""


def _fake_fetch_result(text=_SAMPLE_RSS, status_code=200, not_modified=False, headers=None):
    return http_client.FetchResult(
        url="https://www.mpflarioja.gob.ar/feed/",
        status_code=304 if not_modified else status_code,
        text="" if not_modified else text,
        headers=headers or {},
        latency_ms=12.3,
        not_modified=not_modified,
    )


class SyncSourceTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "sync_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_disabled_source_is_never_fetched(self):
        source = _rss_source(enabled=False)
        with patch("sources.sync.http_client.fetch") as fake_fetch:
            report = sync.sync_source(source, path=self.db_path)
        fake_fetch.assert_not_called()
        self.assertEqual(report.parse_status, "disabled")

    def test_successful_rss_sync_caches_items_and_records_metrics(self):
        source = _rss_source()
        with patch("sources.sync.http_client.fetch", return_value=_fake_fetch_result()):
            report = sync.sync_source(source, path=self.db_path)

        self.assertTrue(report.reachable)
        self.assertEqual(report.items_found, 1)
        self.assertEqual(report.items_new, 1)
        cached = source_cache.get_cache_entry("https://www.mpflarioja.gob.ar/n/1", path=self.db_path)
        self.assertIsNotNone(cached)

    def test_dry_run_never_writes_cache_or_metrics(self):
        source = _rss_source()
        with patch("sources.sync.http_client.fetch", return_value=_fake_fetch_result()):
            sync.sync_source(source, dry_run=True, path=self.db_path)
        self.assertIsNone(source_cache.get_cache_entry("https://www.mpflarioja.gob.ar/n/1", path=self.db_path))
        state = fetch_state.get_fetch_state(source.source_id, path=self.db_path)
        self.assertEqual(state["etag"], "")

    def test_not_modified_response_skips_parsing(self):
        source = _rss_source()
        with patch("sources.sync.http_client.fetch", return_value=_fake_fetch_result(not_modified=True)):
            report = sync.sync_source(source, path=self.db_path)
        self.assertEqual(report.parse_status, "not_modified")
        self.assertEqual(report.items_found, 0)

    def test_fetch_error_is_handled_gracefully(self):
        source = _rss_source()
        with patch("sources.sync.http_client.fetch", side_effect=http_client.SourceFetchError("timeout de red")):
            report = sync.sync_source(source, path=self.db_path)
        self.assertFalse(report.reachable)
        self.assertEqual(report.parse_status, "fetch_error")

    def test_fetch_state_is_persisted_after_success(self):
        source = _rss_source()
        with patch(
            "sources.sync.http_client.fetch",
            return_value=_fake_fetch_result(headers={"ETag": '"abc"', "Last-Modified": "Mon, 01 Sep 2026 00:00:00 GMT"}),
        ):
            sync.sync_source(source, path=self.db_path)
        state = fetch_state.get_fetch_state(source.source_id, path=self.db_path)
        self.assertEqual(state["etag"], '"abc"')

    def test_second_sync_reuses_saved_etag_for_conditional_request(self):
        source = _rss_source()
        fetch_state.set_fetch_state(source.source_id, etag='"saved-etag"', path=self.db_path)
        captured = {}

        def fake_fetch(_source, *, etag, last_modified, resolver=None):
            captured["etag"] = etag
            return _fake_fetch_result(not_modified=True)

        with patch("sources.sync.http_client.fetch", side_effect=fake_fetch):
            sync.sync_source(source, path=self.db_path)
        self.assertEqual(captured["etag"], '"saved-etag"')

    def test_no_items_parsed_marks_parse_failure_status(self):
        source = _rss_source()
        with patch("sources.sync.http_client.fetch", return_value=_fake_fetch_result(text="<rss></rss>")):
            report = sync.sync_source(source, path=self.db_path)
        self.assertEqual(report.parse_status, "no_items_found")


if __name__ == "__main__":
    unittest.main()
