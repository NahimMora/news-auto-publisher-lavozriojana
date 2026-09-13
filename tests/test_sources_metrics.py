import tempfile
import unittest
from pathlib import Path

from sources import metrics as source_metrics
from editorial_context import metrics as ec_metrics


class RecordFetchTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "source_metrics_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_accumulates_multiple_calls_same_day(self):
        source_metrics.record_fetch("mpf_larioja", requests=1, items_discovered=5, items_new=2, latency_ms=100.0, path=self.db_path)
        source_metrics.record_fetch("mpf_larioja", requests=1, items_discovered=5, items_new=1, latency_ms=200.0, path=self.db_path)

        summary = ec_metrics.source_metrics_summary(path=self.db_path)
        entry = next(s for s in summary if s["source_id"] == "mpf_larioja")
        self.assertEqual(entry["requests"], 2)
        self.assertEqual(entry["items_new"], 3)
        self.assertEqual(entry["avg_latency_ms"], 150.0)

    def test_not_modified_and_failures_are_tracked_separately(self):
        source_metrics.record_fetch("x", not_modified=True, path=self.db_path)
        source_metrics.record_fetch("x", parse_failure=True, path=self.db_path)
        source_metrics.record_fetch("x", timeout=True, success=False, path=self.db_path)

        summary = ec_metrics.source_metrics_summary(path=self.db_path)
        entry = next(s for s in summary if s["source_id"] == "x")
        self.assertEqual(entry["not_modified_304"], 1)
        self.assertEqual(entry["parse_failures"], 1)
        self.assertEqual(entry["timeouts"], 1)

    def test_last_item_date_only_updates_when_provided(self):
        source_metrics.record_fetch("y", last_item_date="2026-09-01", path=self.db_path)
        source_metrics.record_fetch("y", path=self.db_path)
        summary = ec_metrics.source_metrics_summary(path=self.db_path)
        entry = next(s for s in summary if s["source_id"] == "y")
        self.assertEqual(entry["last_item_date"], "2026-09-01")


if __name__ == "__main__":
    unittest.main()
