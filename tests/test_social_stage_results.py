import os
import unittest
from unittest.mock import patch

from meta import run_fb, run_ig
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


def news(key):
    return {"titulo": key, "dedup_key": f"link:{key}"}


class FacebookStageTests(unittest.TestCase):
    def _patch_stage(self, pending, operations):
        return (
            patch.object(run_fb, "PAGE_ID", "page"),
            patch.dict(
                os.environ,
                {
                    "FB_PUBLISH_ENABLED": "true",
                    "FB_PAGE_ACCESS_TOKEN": "configured",
                    "PUBLISH_MAX_PER_RUN": "10",
                },
                clear=False,
            ),
            patch.object(run_fb, "recover_ambiguous_processing", return_value=0),
            patch.object(run_fb, "_bootstrap_queue", return_value=len(pending)),
            patch.object(run_fb, "_sync_posted_state", return_value=0),
            patch.object(run_fb, "get_pending", side_effect=[pending, pending]),
            patch.object(run_fb, "claim", return_value=True),
            patch.object(run_fb, "post_to_facebook_detailed", side_effect=operations),
            patch.object(run_fb, "mark_done"),
            patch.object(run_fb, "mark_pending"),
            patch.object(run_fb, "mark_dead_letter"),
            patch.object(run_fb, "compact_queue"),
        )

    def test_partial_batch_is_degraded(self):
        items = [news("a"), news("b")]
        patches = self._patch_stage(
            items,
            [
                OperationResult(StageStatus.SUCCESS, external_id="fb-a"),
                OperationResult(StageStatus.FAILED, error_type="request_rejected"),
            ],
        )
        for manager in patches:
            manager.start()
        try:
            result = run_fb.main()
        finally:
            for manager in reversed(patches):
                manager.stop()
        self.assertEqual(result.status, StageStatus.DEGRADED)
        self.assertEqual((result.succeeded, result.failed), (1, 1))

    def test_zero_of_nonzero_is_failed_and_invalid_credential_is_explicit(self):
        items = [news("a")]
        patches = self._patch_stage(
            items,
            [OperationResult(StageStatus.FAILED, error_type="invalid_credential")],
        )
        for manager in patches:
            manager.start()
        try:
            result = run_fb.main()
        finally:
            for manager in reversed(patches):
                manager.stop()
        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.error_type, "invalid_credential")
        self.assertEqual(result.exit_code, 1)

    def test_rate_limit_is_degraded_with_next_retry(self):
        items = [news("a"), news("b")]
        patches = self._patch_stage(
            items,
            [
                OperationResult(
                    StageStatus.DEGRADED,
                    error_type="rate_limit",
                    retryable=True,
                    next_retry_at=9999999999,
                )
            ],
        )
        for manager in patches:
            manager.start()
        try:
            result = run_fb.main()
        finally:
            for manager in reversed(patches):
                manager.stop()
        self.assertEqual(result.status, StageStatus.DEGRADED)
        self.assertEqual(result.next_retry_at, 9999999999)
        self.assertEqual(result.deferred, 1)


class InstagramStageTests(unittest.TestCase):
    def test_active_rate_limit_is_degraded_even_before_selection(self):
        with patch.object(run_ig, "IG_ACCOUNT_ID", "ig"), patch.object(
            run_ig, "IG_ACCESS_TOKEN", "token"
        ), patch.dict(
            os.environ, {"IG_PUBLISH_ENABLED": "true"}, clear=False
        ), patch.object(
            run_ig, "rate_limit_until", return_value=9999999999
        ):
            result = run_ig.main()
        self.assertEqual(result.status, StageStatus.DEGRADED)
        self.assertEqual(result.error_type, "rate_limit")
        self.assertEqual(result.exit_code, 2)


if __name__ == "__main__":
    unittest.main()
