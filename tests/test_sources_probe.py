import unittest
from unittest.mock import patch

from sources import http_client
from sources import probe
from sources import sync
from sources.registry import SourceDefinition


def _fake_fetch_result():
    return http_client.FetchResult(
        url="https://www.mpflarioja.gob.ar/feed/",
        status_code=200,
        text='<?xml version="1.0"?><rss version="2.0"><channel>'
        '<item><title>Titulo</title><link>https://x/1</link>'
        "<pubDate>Mon, 01 Sep 2026 10:00:00 -0300</pubDate></item>"
        "</channel></rss>",
        headers={},
        latency_ms=10.0,
    )


class ProbeSourceTests(unittest.TestCase):
    def test_unknown_source_id_raises_keyerror(self):
        with self.assertRaises(KeyError):
            probe.probe_source("no_existe_este_id")

    def test_probe_never_writes_to_cache_even_on_success(self):
        with patch("sources.sync.http_client.fetch", return_value=_fake_fetch_result()):
            result = probe.probe_source("mpf_larioja")
        self.assertEqual(result["source"], "mpf_larioja")
        self.assertTrue(result["reachable"])
        self.assertIn("items_found", result)

    def test_probe_forces_disabled_source_with_confirmed_strategy(self):
        source = SourceDefinition(
            source_id="candidate_x",
            name="Candidata",
            scheme="https",
            host="x.gob.ar",
            path="/feed/",
            enabled=False,
            fetch_strategy="rss",
            allowed_hosts=("x.gob.ar",),
        )
        with patch("sources.sync.http_client.fetch", return_value=_fake_fetch_result()):
            report = sync.sync_source(source, dry_run=True, force=True)
        self.assertTrue(report.reachable)

    def test_without_force_disabled_source_is_skipped(self):
        source = SourceDefinition(
            source_id="candidate_x",
            name="Candidata",
            scheme="https",
            host="x.gob.ar",
            path="/feed/",
            enabled=False,
            fetch_strategy="rss",
            allowed_hosts=("x.gob.ar",),
        )
        with patch("sources.sync.http_client.fetch") as fake_fetch:
            report = sync.sync_source(source, dry_run=True, force=False)
        fake_fetch.assert_not_called()
        self.assertEqual(report.parse_status, "disabled")


if __name__ == "__main__":
    unittest.main()
