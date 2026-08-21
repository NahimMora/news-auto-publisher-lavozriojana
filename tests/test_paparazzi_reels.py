from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import paparazzi_reels
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


def _noticia(**overrides):
    base = {
        "titulo": "Nota de espectáculos",
        "dedup_key": "link:abc123",
        "canonical_url": "https://www.paparazzi.com.ar/teve/nota/",
        "titulo_instagram": "TÍTULO DEL REEL",
        "texto_instagram": "Caption de la nota.",
        "seccion": "espectaculos",
        "imagen_url": "https://www.paparazzi.com.ar/foto.jpg",
        "video_url": "https://cdn.jwplayer.com/videos/long-interview.mp4",
    }
    base.update(overrides)
    return base


class PaparazziReelPublishingTests(unittest.TestCase):
    def _env(self, tmp, **extra):
        state = Path(tmp) / "paparazzi_reels_posted.json"
        env = {
            "PAPARAZZI_REEL_ENABLED": "true",
            "IG_PUBLISH_ENABLED": "true",
            "FB_PUBLISH_ENABLED": "true",
        }
        env.update(extra)
        return state, env

    def test_flag_disabled_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, env = self._env(tmp, PAPARAZZI_REEL_ENABLED="false")
            with patch.object(paparazzi_reels, "STATE_PATH", str(state)), patch.dict(
                "os.environ", env, clear=False
            ), patch("utils.video_renderer.render_video") as render:
                paparazzi_reels.publish_paparazzi_reel(_noticia())
            render.assert_not_called()
            self.assertFalse(state.exists())

    def test_without_video_url_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, env = self._env(tmp)
            noticia = _noticia(video_url="")
            with patch.object(paparazzi_reels, "STATE_PATH", str(state)), patch.dict(
                "os.environ", env, clear=False
            ), patch("utils.video_renderer.render_video") as render:
                paparazzi_reels.publish_paparazzi_reel(noticia)
            render.assert_not_called()

    def test_already_posted_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, env = self._env(tmp)
            noticia = _noticia()
            dedup_key = paparazzi_reels.reel_dedup_key(noticia)
            state.write_text(
                json.dumps({"posted": {dedup_key: {"instagram_id": "already-there"}}}),
                encoding="utf-8",
            )
            with patch.object(paparazzi_reels, "STATE_PATH", str(state)), patch.dict(
                "os.environ", env, clear=False
            ), patch("utils.video_renderer.render_video") as render:
                paparazzi_reels.publish_paparazzi_reel(noticia)
            render.assert_not_called()

    def test_success_renders_uploads_and_publishes_both_platforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, env = self._env(tmp)
            noticia = _noticia()
            with patch.object(paparazzi_reels, "STATE_PATH", str(state)), patch.dict(
                "os.environ", env, clear=False
            ), patch(
                "utils.video_renderer.render_video",
                return_value=("/tmp/reel.mp4", "vid123", 45, {"source_used": "video"}),
            ), patch(
                "utils.r2_storage.is_configured", return_value=True
            ), patch(
                "utils.r2_storage.upload_temp",
                return_value=("https://r2/reel.mp4", "tmp/reel/key.mp4"),
            ), patch(
                "meta.ig_client.post_reel_video_to_instagram",
                return_value=OperationResult(StageStatus.SUCCESS, external_id="ig-reel-1"),
            ) as ig_call, patch(
                "meta.fb_client.post_reel_video_to_facebook",
                return_value=OperationResult(StageStatus.SUCCESS, external_id="fb-reel-1"),
            ) as fb_call:
                paparazzi_reels.publish_paparazzi_reel(noticia)

            ig_call.assert_called_once()
            fb_call.assert_called_once()
            ig_item = ig_call.call_args[0][0]
            self.assertEqual("https://r2/reel.mp4", ig_item["video_url"])
            self.assertEqual("TÍTULO DEL REEL", ig_item["titulo_reel"])

            saved_state = json.loads(state.read_text(encoding="utf-8"))
            key = paparazzi_reels.reel_dedup_key(noticia)
            self.assertEqual("ig-reel-1", saved_state["posted"][key]["instagram_id"])
            self.assertEqual("fb-reel-1", saved_state["posted"][key]["facebook_id"])

    def test_facebook_disabled_skips_only_facebook_leg(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, env = self._env(tmp, FB_PUBLISH_ENABLED="false")
            noticia = _noticia()
            with patch.object(paparazzi_reels, "STATE_PATH", str(state)), patch.dict(
                "os.environ", env, clear=False
            ), patch(
                "utils.video_renderer.render_video",
                return_value=("/tmp/reel.mp4", "vid123", 45, {"source_used": "video"}),
            ), patch(
                "utils.r2_storage.is_configured", return_value=True
            ), patch(
                "utils.r2_storage.upload_temp",
                return_value=("https://r2/reel.mp4", "tmp/reel/key.mp4"),
            ), patch(
                "meta.ig_client.post_reel_video_to_instagram",
                return_value=OperationResult(StageStatus.SUCCESS, external_id="ig-reel-1"),
            ) as ig_call, patch(
                "meta.fb_client.post_reel_video_to_facebook"
            ) as fb_call:
                paparazzi_reels.publish_paparazzi_reel(noticia)

            ig_call.assert_called_once()
            fb_call.assert_not_called()
            saved_state = json.loads(state.read_text(encoding="utf-8"))
            key = paparazzi_reels.reel_dedup_key(noticia)
            self.assertEqual("", saved_state["posted"][key]["facebook_id"])

    def test_fallback_to_image_is_not_published_as_reel(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, env = self._env(tmp)
            noticia = _noticia()
            with patch.object(paparazzi_reels, "STATE_PATH", str(state)), patch.dict(
                "os.environ", env, clear=False
            ), patch(
                "utils.video_renderer.render_video",
                return_value=(
                    "/tmp/reel.mp4",
                    "vid123",
                    20,
                    {"source_used": "image_fallback", "fallback_reason": {"error_type": "network_error"}},
                ),
            ), patch(
                "meta.ig_client.post_reel_video_to_instagram"
            ) as ig_call, patch(
                "meta.fb_client.post_reel_video_to_facebook"
            ) as fb_call:
                paparazzi_reels.publish_paparazzi_reel(noticia)

            ig_call.assert_not_called()
            fb_call.assert_not_called()
            self.assertFalse(state.exists())

    def test_all_platforms_failed_cleans_up_r2(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, env = self._env(tmp)
            noticia = _noticia()
            with patch.object(paparazzi_reels, "STATE_PATH", str(state)), patch.dict(
                "os.environ", env, clear=False
            ), patch(
                "utils.video_renderer.render_video",
                return_value=("/tmp/reel.mp4", "vid123", 45, {"source_used": "video"}),
            ), patch(
                "utils.r2_storage.is_configured", return_value=True
            ), patch(
                "utils.r2_storage.upload_temp",
                return_value=("https://r2/reel.mp4", "tmp/reel/key.mp4"),
            ), patch(
                "meta.ig_client.post_reel_video_to_instagram",
                return_value=OperationResult(StageStatus.FAILED, error_type="invalid_video_url"),
            ), patch(
                "meta.fb_client.post_reel_video_to_facebook",
                return_value=OperationResult(StageStatus.FAILED, error_type="invalid_video_url"),
            ), patch("utils.r2_storage.delete") as r2_delete:
                paparazzi_reels.publish_paparazzi_reel(noticia)

            r2_delete.assert_called_once_with("tmp/reel/key.mp4")
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
