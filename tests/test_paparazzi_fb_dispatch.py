from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from meta import run_fb
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


class FacebookPaparazziDispatchTests(unittest.TestCase):
    """meta/run_fb.py debe rutear notas de paparazzi a
    post_paparazzi_video_to_facebook (video editado) y todo lo demás a
    post_to_facebook_detailed (sin cambios) — ver docs/DECISIONS.md."""

    def test_paparazzi_item_uses_the_edited_video_publisher(self):
        items = [
            {"dedup_key": "link:g1", "titulo": "Local", "source": "nuevarioja"},
            {"dedup_key": "link:p1", "titulo": "Paparazzi", "source": "paparazzi"},
        ]

        with patch.object(run_fb, "PAGE_ID", "page"), patch.dict(
            os.environ, {"FB_PUBLISH_ENABLED": "true", "FB_PAGE_ACCESS_TOKEN": "configured"}, clear=False
        ), patch.object(
            run_fb, "recover_ambiguous_processing", return_value=0
        ), patch.object(
            run_fb, "_bootstrap_queue", return_value=len(items)
        ), patch.object(
            run_fb, "_sync_posted_state", return_value=0
        ), patch.object(
            run_fb, "get_pending", side_effect=[items, items]
        ), patch.object(
            run_fb, "claim", return_value=True
        ), patch.object(
            run_fb, "post_to_facebook_detailed",
            return_value=OperationResult(StageStatus.SUCCESS, external_id="standard-ok"),
        ) as standard_publish, patch.object(
            run_fb, "post_paparazzi_video_to_facebook",
            return_value=OperationResult(StageStatus.SUCCESS, external_id="paparazzi-ok"),
        ) as paparazzi_publish, patch.object(
            run_fb, "mark_done"
        ), patch.object(
            run_fb, "compact_queue"
        ):
            result = run_fb.main()

        self.assertEqual(2, result.succeeded)
        standard_publish.assert_called_once()
        self.assertEqual("Local", standard_publish.call_args[0][0]["titulo"])
        paparazzi_publish.assert_called_once()
        self.assertEqual("Paparazzi", paparazzi_publish.call_args[0][0]["titulo"])


if __name__ == "__main__":
    unittest.main()
