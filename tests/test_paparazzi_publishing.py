from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meta import ig_client
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload


def _noticia(**overrides):
    base = {
        "titulo": "Nota de espectáculos",
        "dedup_key": "link:abc123",
        "canonical_url": "https://www.paparazzi.com.ar/teve/nota/",
        "source": "paparazzi",
        "imagen_url": "https://www.paparazzi.com.ar/foto.jpg",
    }
    base.update(overrides)
    return base


class PaparazziCarouselPublishingTests(unittest.TestCase):
    def test_with_video_creates_image_and_video_children_then_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "ig_posted.json"
            calls = []
            status_calls = []

            def fake_post(url, data=None, timeout=None):
                calls.append((url, dict(data or {})))
                if url.endswith("/media") and data.get("is_carousel_item") == "true":
                    return FakeResponse(200, {"id": f"child-{len(calls)}"})
                if url.endswith("/media") and data.get("media_type") == "CAROUSEL":
                    return FakeResponse(200, {"id": "parent-container"})
                if url.endswith("/media_publish"):
                    return FakeResponse(200, {"id": "ig-post-final"})
                return FakeResponse(400, {})

            def fake_get(url, params=None, timeout=None):
                status_calls.append(url.rsplit("/", 1)[-1])
                return FakeResponse(200, {"status_code": "FINISHED"})

            noticia = _noticia(video_url="https://cdn.jwplayer.com/videos/long-interview.mp4")

            with patch.object(ig_client, "IG_ACCOUNT_ID", "acc"), patch.object(
                ig_client, "IG_ACCESS_TOKEN", "token"
            ), patch.object(ig_client, "IG_STATE_PATH", str(state)), patch.object(
                ig_client, "IG_RATE_LIMIT_PATH", str(Path(tmp) / "rl.json")
            ), patch.object(
                ig_client.requests, "post", side_effect=fake_post
            ), patch.object(
                ig_client.requests, "get", side_effect=fake_get
            ), patch(
                "utils.video_renderer.render_paparazzi_clips",
                return_value=(["/tmp/clip.mp4"], {"parts": 1, "segments_seconds": [20]}),
            ), patch.object(
                ig_client, "_prepare_image",
                return_value=(OperationResult(StageStatus.SUCCESS), "https://r2/cover.jpg", "key-img"),
            ), patch.object(
                ig_client.r2_storage, "upload_temp", return_value=("https://r2/clip.mp4", "key-vid")
            ), patch.object(
                ig_client.r2_storage, "delete"
            ):
                result = ig_client.post_paparazzi_carousel_to_instagram(noticia)

            self.assertTrue(result.ok, result.error_type)
            self.assertEqual("ig-post-final", result.external_id)

            child_calls = [c for c in calls if c[1].get("is_carousel_item") == "true"]
            self.assertEqual(2, len(child_calls))
            self.assertEqual("https://r2/cover.jpg", child_calls[0][1]["image_url"])
            self.assertEqual("https://r2/clip.mp4", child_calls[1][1]["video_url"])
            self.assertEqual("VIDEO", child_calls[1][1]["media_type"])

            parent_calls = [c for c in calls if c[1].get("media_type") == "CAROUSEL"]
            self.assertEqual(1, len(parent_calls))
            self.assertEqual("child-1,child-2", parent_calls[0][1]["children"])

            saved_state = json.loads(state.read_text(encoding="utf-8"))
            self.assertIn("link:abc123", saved_state["posted"])

    def test_long_video_splits_into_two_video_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "ig_posted.json"
            calls = []
            status_calls = []

            def fake_post(url, data=None, timeout=None):
                calls.append((url, dict(data or {})))
                if url.endswith("/media") and data.get("is_carousel_item") == "true":
                    return FakeResponse(200, {"id": f"child-{len(calls)}"})
                if url.endswith("/media") and data.get("media_type") == "CAROUSEL":
                    return FakeResponse(200, {"id": "parent-container"})
                if url.endswith("/media_publish"):
                    return FakeResponse(200, {"id": "ig-post-final"})
                return FakeResponse(400, {})

            def fake_get(url, params=None, timeout=None):
                status_calls.append(url.rsplit("/", 1)[-1])
                return FakeResponse(200, {"status_code": "FINISHED"})

            noticia = _noticia(video_url="https://cdn.jwplayer.com/videos/long-interview.mp4")

            with patch.object(ig_client, "IG_ACCOUNT_ID", "acc"), patch.object(
                ig_client, "IG_ACCESS_TOKEN", "token"
            ), patch.object(ig_client, "IG_STATE_PATH", str(state)), patch.object(
                ig_client, "IG_RATE_LIMIT_PATH", str(Path(tmp) / "rl.json")
            ), patch.object(
                ig_client.requests, "post", side_effect=fake_post
            ), patch.object(
                ig_client.requests, "get", side_effect=fake_get
            ), patch(
                "utils.video_renderer.render_paparazzi_clips",
                return_value=(
                    ["/tmp/clip_part1.mp4", "/tmp/clip_part2.mp4"],
                    {"parts": 2, "segments_seconds": [60, 40]},
                ),
            ), patch.object(
                ig_client, "_prepare_image",
                return_value=(OperationResult(StageStatus.SUCCESS), "https://r2/cover.jpg", "key-img"),
            ), patch.object(
                ig_client.r2_storage,
                "upload_temp",
                side_effect=[
                    ("https://r2/clip1.mp4", "key-vid-1"),
                    ("https://r2/clip2.mp4", "key-vid-2"),
                ],
            ), patch.object(
                ig_client.r2_storage, "delete"
            ) as r2_delete:
                result = ig_client.post_paparazzi_carousel_to_instagram(noticia)

            self.assertTrue(result.ok, result.error_type)
            child_calls = [c for c in calls if c[1].get("is_carousel_item") == "true"]
            self.assertEqual(3, len(child_calls))  # portada + 2 partes de video
            self.assertEqual("https://r2/cover.jpg", child_calls[0][1]["image_url"])
            self.assertEqual("https://r2/clip1.mp4", child_calls[1][1]["video_url"])
            self.assertEqual("https://r2/clip2.mp4", child_calls[2][1]["video_url"])

            parent_calls = [c for c in calls if c[1].get("media_type") == "CAROUSEL"]
            self.assertEqual("child-1,child-2,child-3", parent_calls[0][1]["children"])
            # limpia la portada + las 2 claves R2 de video
            self.assertEqual(3, r2_delete.call_count)

    def test_without_video_url_falls_back_to_single_image_post(self):
        noticia = _noticia()  # sin video_url
        with patch.object(ig_client, "IG_ACCOUNT_ID", "acc"), patch.object(
            ig_client, "IG_ACCESS_TOKEN", "token"
        ), patch.object(
            ig_client, "rate_limit_until", return_value=0
        ), patch.object(
            ig_client, "_load_state", return_value={"posted": {}}
        ), patch.object(
            ig_client, "_posted_duplicate_reason", return_value=None
        ), patch.object(
            ig_client, "post_to_instagram_detailed", return_value=OperationResult(StageStatus.SUCCESS, external_id="img-only")
        ) as fallback:
            result = ig_client.post_paparazzi_carousel_to_instagram(noticia)

        self.assertTrue(result.ok)
        self.assertEqual("img-only", result.external_id)
        fallback.assert_called_once()
        passed_noticia = fallback.call_args[0][0]
        self.assertNotIn("video_url", passed_noticia)

    def test_clip_render_failure_falls_back_to_single_image_without_raw_video_url(self):
        noticia = _noticia(video_url="https://cdn.jwplayer.com/videos/long-interview.mp4")
        with patch.object(ig_client, "IG_ACCOUNT_ID", "acc"), patch.object(
            ig_client, "IG_ACCESS_TOKEN", "token"
        ), patch.object(
            ig_client, "rate_limit_until", return_value=0
        ), patch.object(
            ig_client, "_load_state", return_value={"posted": {}}
        ), patch.object(
            ig_client, "_posted_duplicate_reason", return_value=None
        ), patch(
            "utils.video_renderer.render_paparazzi_clips",
            return_value=([], {"error_type": "ffmpeg_unavailable"}),
        ), patch.object(
            ig_client, "post_to_instagram_detailed",
            return_value=OperationResult(StageStatus.SUCCESS, external_id="img-only"),
        ) as fallback:
            result = ig_client.post_paparazzi_carousel_to_instagram(noticia)

        self.assertTrue(result.ok)
        fallback.assert_called_once()
        passed_noticia = fallback.call_args[0][0]
        self.assertNotIn("video_url", passed_noticia)
        # el noticia original (con video_url) no debe mutarse en el lugar
        self.assertIn("video_url", noticia)

    def test_dedup_avoids_double_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "ig_posted.json"
            state.write_text(
                json.dumps({"posted": {"link:abc123": {"external_id": "already-there"}}}),
                encoding="utf-8",
            )
            noticia = _noticia(video_url="https://cdn.jwplayer.com/videos/x.mp4")
            with patch.object(ig_client, "IG_ACCOUNT_ID", "acc"), patch.object(
                ig_client, "IG_ACCESS_TOKEN", "token"
            ), patch.object(ig_client, "IG_STATE_PATH", str(state)), patch.object(
                ig_client, "IG_RATE_LIMIT_PATH", str(Path(tmp) / "rl.json")
            ), patch.object(ig_client.requests, "post") as post:
                result = ig_client.post_paparazzi_carousel_to_instagram(noticia)
            self.assertTrue(result.ok)
            self.assertTrue(result.deduplicated)
            post.assert_not_called()

    def test_rate_limit_is_degraded_and_keeps_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            rl_path = Path(tmp) / "rl.json"
            rl_path.write_text(json.dumps({"blocked_until": 99999999999}), encoding="utf-8")
            noticia = _noticia(video_url="https://cdn.jwplayer.com/videos/x.mp4")
            with patch.object(ig_client, "IG_ACCOUNT_ID", "acc"), patch.object(
                ig_client, "IG_ACCESS_TOKEN", "token"
            ), patch.object(ig_client, "IG_RATE_LIMIT_PATH", str(rl_path)), patch.object(
                ig_client.requests, "post"
            ) as post:
                result = ig_client.post_paparazzi_carousel_to_instagram(noticia)
            self.assertEqual("rate_limit", result.error_type)
            self.assertEqual(99999999999, result.next_retry_at)
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
