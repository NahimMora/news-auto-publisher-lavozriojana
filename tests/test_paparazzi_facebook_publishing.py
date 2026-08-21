from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meta import fb_client
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _noticia(**overrides):
    base = {
        "titulo": "Nota de espectáculos",
        "dedup_key": "link:abc123",
        "canonical_url": "https://www.paparazzi.com.ar/teve/nota/",
        "source": "paparazzi",
        "web_url": "https://lavozriojana.com/noticias/nota",
    }
    base.update(overrides)
    return base


class PaparazziFacebookVideoTests(unittest.TestCase):
    def test_with_video_uploads_a_single_edited_clip_not_the_raw_source_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "fb_posted.json"
            calls = []

            def fake_post(url, data=None, timeout=None):
                calls.append((url, dict(data or {})))
                if url.endswith("/videos"):
                    return FakeResponse(200, {"id": "fb-video-1"})
                return FakeResponse(400, {})

            noticia = _noticia(video_url="https://cdn.jwplayer.com/videos/long-interview.mp4")

            with patch.object(fb_client, "PAGE_ID", "page"), patch.object(
                fb_client, "DISABLED_PAGE_IDS", set()
            ), patch.object(fb_client, "FB_STATE_PATH", str(state)), patch.object(
                fb_client, "get_page_token", return_value="token"
            ), patch.object(
                fb_client.requests, "post", side_effect=fake_post
            ), patch(
                "utils.video_renderer.render_paparazzi_clips",
                return_value=(["/tmp/edited_clip.mp4"], {"duration_seconds": 90}),
            ), patch.object(
                fb_client.r2_storage, "upload_temp", return_value=("https://r2/edited_clip.mp4", "key-vid")
            ), patch.object(
                fb_client.r2_storage, "delete"
            ):
                result = fb_client.post_paparazzi_video_to_facebook(noticia)

            self.assertTrue(result.ok, result.error_type)
            self.assertEqual("fb-video-1", result.external_id)
            video_calls = [c for c in calls if c[0].endswith("/videos")]
            self.assertEqual(1, len(video_calls))
            # el file_url debe ser el clip editado subido a R2, NUNCA la URL
            # cruda del scraper (video_url original, sin recortar ni marca).
            self.assertEqual("https://r2/edited_clip.mp4", video_calls[0][1]["file_url"])
            self.assertNotEqual(
                "https://cdn.jwplayer.com/videos/long-interview.mp4",
                video_calls[0][1]["file_url"],
            )

            saved_state = json.loads(state.read_text(encoding="utf-8"))
            self.assertIn("link:abc123", saved_state["posted"])

    def test_without_video_url_falls_back_to_standard_post(self):
        noticia = _noticia()  # sin video_url
        with patch.object(fb_client, "PAGE_ID", "page"), patch.object(
            fb_client, "DISABLED_PAGE_IDS", set()
        ), patch.object(
            fb_client, "_backoff_until", return_value=0
        ), patch.object(
            fb_client, "_load_state", return_value={"posted": {}, "page_backoff": {}}
        ), patch.object(
            fb_client, "post_to_facebook_detailed",
            return_value=OperationResult(StageStatus.SUCCESS, external_id="fb-standard"),
        ) as fallback:
            result = fb_client.post_paparazzi_video_to_facebook(noticia)

        self.assertTrue(result.ok)
        self.assertEqual("fb-standard", result.external_id)
        fallback.assert_called_once()
        passed_noticia = fallback.call_args[0][0]
        self.assertNotIn("video_url", passed_noticia)

    def test_clip_render_failure_falls_back_to_standard_post_without_raw_video_url(self):
        noticia = _noticia(video_url="https://cdn.jwplayer.com/videos/long-interview.mp4")
        with patch.object(fb_client, "PAGE_ID", "page"), patch.object(
            fb_client, "DISABLED_PAGE_IDS", set()
        ), patch.object(
            fb_client, "_backoff_until", return_value=0
        ), patch.object(
            fb_client, "_load_state", return_value={"posted": {}, "page_backoff": {}}
        ), patch(
            "utils.video_renderer.render_paparazzi_clips",
            return_value=([], {"error_type": "ffmpeg_unavailable"}),
        ), patch.object(
            fb_client, "post_to_facebook_detailed",
            return_value=OperationResult(StageStatus.SUCCESS, external_id="fb-standard"),
        ) as fallback:
            result = fb_client.post_paparazzi_video_to_facebook(noticia)

        self.assertTrue(result.ok)
        fallback.assert_called_once()
        passed_noticia = fallback.call_args[0][0]
        self.assertNotIn("video_url", passed_noticia)
        self.assertIn("video_url", noticia)  # el original no se muta

    def test_dedup_avoids_double_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "fb_posted.json"
            state.write_text(
                json.dumps({"posted": {"link:abc123": {"external_id": "already-there"}}, "page_backoff": {}}),
                encoding="utf-8",
            )
            noticia = _noticia(video_url="https://cdn.jwplayer.com/videos/x.mp4")
            with patch.object(fb_client, "PAGE_ID", "page"), patch.object(
                fb_client, "DISABLED_PAGE_IDS", set()
            ), patch.object(fb_client, "FB_STATE_PATH", str(state)), patch.object(
                fb_client.requests, "post"
            ) as post:
                result = fb_client.post_paparazzi_video_to_facebook(noticia)
            self.assertTrue(result.ok)
            self.assertTrue(result.deduplicated)
            post.assert_not_called()

    def test_rate_limit_is_degraded_and_keeps_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "fb_posted.json"
            state.write_text(
                json.dumps({"posted": {}, "page_backoff": {"page": 99999999999}}),
                encoding="utf-8",
            )
            noticia = _noticia(video_url="https://cdn.jwplayer.com/videos/x.mp4")
            with patch.object(fb_client, "PAGE_ID", "page"), patch.object(
                fb_client, "DISABLED_PAGE_IDS", set()
            ), patch.object(fb_client, "FB_STATE_PATH", str(state)), patch.object(
                fb_client.requests, "post"
            ) as post:
                result = fb_client.post_paparazzi_video_to_facebook(noticia)
            self.assertEqual("rate_limit", result.error_type)
            self.assertEqual(99999999999, result.next_retry_at)
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
