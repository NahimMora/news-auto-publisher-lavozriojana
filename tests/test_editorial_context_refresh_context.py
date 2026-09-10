import unittest
from unittest.mock import patch

from editorial_context import refresh_context
from sources.registry import SourceDefinition
from sources.sync import SyncReport
from utils.stage_result import StageStatus


def _source(source_id, poll_ttl=3600):
    return SourceDefinition(
        source_id=source_id,
        name=source_id,
        scheme="https",
        host=f"{source_id}.gob.ar",
        path="/",
        enabled=True,
        fetch_strategy="rss",
        poll_ttl=poll_ttl,
        request_delay=0.0,
        allowed_hosts=(f"{source_id}.gob.ar",),
    )


class RefreshContextRunTests(unittest.TestCase):
    def test_no_enabled_sources_returns_no_work(self):
        with patch("editorial_context.refresh_context.enabled_sources", return_value=[]):
            result = refresh_context.run()
        self.assertEqual(result.status, StageStatus.NO_WORK)

    def test_sources_not_due_are_skipped(self):
        with patch("editorial_context.refresh_context.enabled_sources", return_value=[_source("a")]), patch(
            "editorial_context.refresh_context.is_due", return_value=False
        ), patch("editorial_context.refresh_context.sync_source") as fake_sync:
            result = refresh_context.run()
        fake_sync.assert_not_called()
        self.assertEqual(result.status, StageStatus.NO_WORK)

    def test_due_source_is_synced_and_counted_as_success(self):
        with patch("editorial_context.refresh_context.enabled_sources", return_value=[_source("a")]), patch(
            "editorial_context.refresh_context.is_due", return_value=True
        ), patch(
            "editorial_context.refresh_context.sync_source",
            return_value=SyncReport(source_id="a", reachable=True, strategy="RSS", items_found=2, items_new=1),
        ):
            result = refresh_context.run()
        self.assertEqual(result.succeeded, 1)
        self.assertEqual(result.status, StageStatus.SUCCESS)

    def test_unreachable_source_counts_as_failed_but_does_not_raise(self):
        with patch("editorial_context.refresh_context.enabled_sources", return_value=[_source("a")]), patch(
            "editorial_context.refresh_context.is_due", return_value=True
        ), patch(
            "editorial_context.refresh_context.sync_source",
            return_value=SyncReport(source_id="a", reachable=False, strategy="RSS", parse_status="fetch_error"),
        ):
            result = refresh_context.run()
        self.assertEqual(result.failed, 1)

    def test_unexpected_exception_in_one_source_does_not_break_the_cycle(self):
        sources = [_source("a"), _source("b")]
        with patch("editorial_context.refresh_context.enabled_sources", return_value=sources), patch(
            "editorial_context.refresh_context.is_due", return_value=True
        ), patch(
            "editorial_context.refresh_context.sync_source",
            side_effect=[RuntimeError("boom"), SyncReport(source_id="b", reachable=True, strategy="RSS")],
        ):
            result = refresh_context.run()
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.succeeded, 1)


if __name__ == "__main__":
    unittest.main()
