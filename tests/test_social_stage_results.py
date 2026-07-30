import os
import unittest
from unittest.mock import patch

from meta import run_fb, run_ig
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


def news(key):
    return {"titulo": key, "dedup_key": f"link:{key}"}


class FacebookStageTests(unittest.TestCase):
    def test_bootstrap_only_enqueues_items_with_verified_web_url(self):
        items = [
            {"dedup_key": "without-web", "titulo": "Sin web"},
            {
                "dedup_key": "with-web",
                "titulo": "Con web",
                "web_url": "https://lavozriojana.com/noticias/con-web",
            },
        ]
        with patch.object(run_fb, "load_json", return_value=items), patch.object(
            run_fb, "enqueue"
        ) as enqueue:
            included = run_fb._bootstrap_queue()

        self.assertEqual(1, included)
        enqueue.assert_called_once_with(items[1], platform="facebook")

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
    def test_bootstrap_waits_for_verified_web_url(self):
        items = [
            {
                "dedup_key": "without-web",
                "titulo": "Sin web",
                "categoria": "sociedad",
            },
            {
                "dedup_key": "with-web",
                "titulo": "Con web",
                "categoria": "sociedad",
                "web_url": "https://lavozriojana.com/noticias/con-web",
            },
        ]
        with patch.object(run_ig, "load_json", return_value=items), patch.object(
            run_ig, "enqueue"
        ) as enqueue:
            included, omitted_by_policy, missing_web_url = run_ig._bootstrap_queue()

        self.assertEqual((1, 0, 1), (included, omitted_by_policy, missing_web_url))
        enqueue.assert_called_once_with(items[1], platform="instagram")

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

    def test_request_rejection_is_logged_and_dead_letter_keeps_safe_diagnostics(self):
        item = {
            **news("ig-rejected"),
            "categoria": "sociedad",
            "web_url": "https://lavozriojana.com/noticias/ig-rejected",
        }
        operation = OperationResult(
            StageStatus.FAILED,
            error_type="request_rejected",
            error_code=400,
            response={
                "error": {
                    "code": 100,
                    "error_subcode": 33,
                    "type": "OAuthException",
                    "message": "access_token=secreto-no-persistir",
                }
            },
            details={"publication_outcome": "not_published"},
        )
        with patch.object(run_ig, "IG_ACCOUNT_ID", "ig"), patch.object(
            run_ig, "IG_ACCESS_TOKEN", "token"
        ), patch.dict(
            os.environ,
            {
                "IG_PUBLISH_ENABLED": "true",
                "IG_MAX_PER_RUN": "1",
            },
            clear=False,
        ), patch.object(
            run_ig, "rate_limit_until", return_value=0
        ), patch.object(
            run_ig, "recover_ambiguous_processing", return_value=0
        ), patch.object(
            run_ig, "_bootstrap_queue", return_value=(1, 0, 0)
        ), patch.object(
            run_ig, "_sync_posted_state", return_value=0
        ), patch.object(
            run_ig, "get_pending", side_effect=[[item], [item]]
        ), patch.object(
            run_ig, "claim", return_value=True
        ), patch.object(
            run_ig, "post_to_instagram_detailed", return_value=operation
        ), patch.object(
            run_ig, "mark_done"
        ), patch.object(
            run_ig, "mark_pending"
        ), patch.object(
            run_ig, "mark_dead_letter"
        ) as mark_dead_letter, patch.object(
            run_ig, "compact_queue"
        ), patch.object(
            run_ig.logger, "error"
        ) as log_error:
            result = run_ig.main()

        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertTrue(log_error.called)
        metadata = mark_dead_letter.call_args.kwargs["metadata"]
        self.assertEqual(400, metadata["http_status"])
        self.assertEqual(100, metadata["provider_code"])
        self.assertEqual(33, metadata["provider_subcode"])
        self.assertEqual("OAuthException", metadata["provider_type"])
        self.assertNotIn("secreto-no-persistir", repr(metadata))


if __name__ == "__main__":
    unittest.main()
