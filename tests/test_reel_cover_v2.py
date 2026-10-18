"""Reel V2 (revisión 2026-10-18): props de bajada/crédito, portada propia
(ReelCoverV2) y su publicación como cover_url / miniatura de Facebook."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from PIL import Image

from utils.visual_v2_props import date_label, reel_credit, reel_deck_from_caption, reel_props_v2


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (54, 96), (20, 30, 40)).save(buffer, "PNG")
    return buffer.getvalue()


CAPTION = (
    "🎭⭐ EL MISTERIO EN LA MANSIÓN 👇\n\n"
    "📌 Charlotte Caniggia contó en PH una experiencia paranormal en la mansión familiar. Fue en Marbella.\n\n"
    "🔑 Otra cosa."
)


class ReelV2PropsTests(unittest.TestCase):
    def test_deck_is_first_sentence_of_pin_paragraph(self):
        self.assertEqual(
            reel_deck_from_caption(CAPTION),
            "Charlotte Caniggia contó en PH una experiencia paranormal en la mansión familiar.",
        )

    def test_deck_omitted_when_missing_or_too_long(self):
        self.assertEqual(reel_deck_from_caption("Sin estructura"), "")
        self.assertEqual(reel_deck_from_caption("📌 " + "palabra " * 40 + "."), "")

    def test_credit_is_derived_from_source_url(self):
        self.assertEqual(reel_credit("https://x.com/crave_indie/status/1"), "Video: X / @crave_indie")
        self.assertEqual(reel_credit("https://www.infobae.com/sociedad/x/"), "Video: Infobae")
        self.assertEqual(reel_credit("https://www.paparazzi.com.ar/teve/nota/"), "Video: Paparazzi")
        self.assertEqual(reel_credit("https://cdn.jwplayer.com/v.mp4"), "")

    def test_display_title_keeps_original_case(self):
        item = {"titulo_display": "El relato de Charlotte Caniggia", "titulo_reel": "EL RELATO DE CHARLOTTE CANIGGIA", "reel_deck": "Bajada.", "reel_credit": "Video: Paparazzi"}
        props = reel_props_v2(item, duration_frames=300, asset_type="video", asset_file="tmp/x.mp4")
        self.assertEqual(props["titulo"], "El relato de Charlotte Caniggia")
        self.assertEqual((props["deck"], props["credit"], props["still"]), ("Bajada.", "Video: Paparazzi", False))

    def test_date_label_uses_argentina_time(self):
        # 02:00 UTC del domingo 18 = sábado 17 a las 23:00 en Argentina.
        self.assertEqual(date_label(datetime(2026, 10, 18, 2, 0, tzinfo=timezone.utc)), "sábado 17 de octubre")


class ReelCoverRenderTests(unittest.TestCase):
    def test_cover_renders_still_from_video_frame(self):
        from utils import video_renderer

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(video_renderer, "RENDERS_DIR", tmp):
            frame = Path(tmp) / "frame.jpg"
            Image.new("RGB", (1280, 720)).save(frame)
            with mock.patch.object(video_renderer, "_extract_cover_frame", return_value=str(frame)), mock.patch(
                "utils.remotion_renderer.render_still", return_value=(_png(), {})
            ) as still, mock.patch.object(video_renderer, "get_media_size", return_value=(1280, 720)):
                cover = video_renderer.render_reel_cover({"titulo_display": "Título"}, "vid", 10, "src.mp4", "video")
            self.assertTrue(cover and os.path.isfile(cover))
            self.assertFalse(frame.exists(), "el cuadro temporal se limpia")
        composition, props = still.call_args.args[:2]
        self.assertEqual(composition, "ReelCoverV2")
        self.assertTrue(props["still"])
        self.assertEqual(props["assetType"], "image")
        self.assertEqual(props["assetWidth"], 1280)

    def test_cover_failure_is_best_effort(self):
        from utils import video_renderer
        from utils.remotion_renderer import RemotionRenderError

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(video_renderer, "RENDERS_DIR", tmp), mock.patch(
            "utils.remotion_renderer.render_still", side_effect=RemotionRenderError("x")
        ):
            self.assertIsNone(video_renderer.render_reel_cover({"titulo": "T"}, "vid", 5, None, "none"))


class ReelCoverPublishingTests(unittest.TestCase):
    def _render(self, cover_path: str):
        def fake_render(item, allow_ffmpeg_fallback=True):
            self.render_item = item
            video = Path(self.tmp.name) / "reel.mp4"
            video.write_bytes(b"mp4")
            return str(video), "vid", 10, {"source_used": "video", "cover_path": cover_path}

        return fake_render

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_cover_uploaded_and_set_as_cover_url(self):
        from utils import paparazzi_reels

        cover = Path(self.tmp.name) / "vid_cover.jpg"
        cover.write_bytes(b"jpg")
        uploads = iter([("https://r2/reel.mp4", "tmp/reel/a.mp4"), ("https://r2/cover.jpg", "tmp/reel/a.jpg")])
        noticia = {
            "titulo_instagram": "El relato de Charlotte Caniggia",
            "texto_instagram": CAPTION,
            "seccion": "espectaculos",
            "canonical_url": "https://www.paparazzi.com.ar/teve/nota/",
            "video_url": "https://cdn.jwplayer.com/videos/x.mp4",
        }
        with mock.patch("utils.video_renderer.render_video", side_effect=self._render(str(cover))), mock.patch(
            "utils.r2_storage.is_configured", return_value=True
        ), mock.patch("utils.r2_storage.upload_temp", side_effect=lambda *a, **k: next(uploads)), mock.patch(
            "utils.r2_storage.delete"
        ) as delete:
            reel_item, key = paparazzi_reels.render_reel_item(noticia)
            self.assertEqual(reel_item["cover_url"], "https://r2/cover.jpg")
            self.assertFalse(cover.exists(), "la portada local se limpia tras subirla")
            paparazzi_reels.delete_reel_upload(key)
        self.assertEqual({c.args[0] for c in delete.call_args_list}, {"tmp/reel/a.mp4", "tmp/reel/a.jpg"})
        self.assertEqual(self.render_item["titulo_display"], "El relato de Charlotte Caniggia")
        self.assertEqual(self.render_item["reel_credit"], "Video: Paparazzi")
        self.assertTrue(self.render_item["reel_deck"].startswith("Charlotte Caniggia contó"))

    def test_without_cover_keeps_thumb_offset(self):
        from utils import paparazzi_reels

        noticia = {"titulo_instagram": "T", "texto_instagram": "C", "video_url": "https://cdn.jwplayer.com/v.mp4"}
        with mock.patch("utils.video_renderer.render_video", side_effect=self._render("")), mock.patch(
            "utils.r2_storage.is_configured", return_value=True
        ), mock.patch("utils.r2_storage.upload_temp", return_value=("https://r2/reel.mp4", "tmp/reel/b.mp4")):
            reel_item, _key = paparazzi_reels.render_reel_item(noticia)
        self.assertNotIn("cover_url", reel_item)
        self.assertIn("thumb_offset_ms", reel_item)

    def test_facebook_thumbnail_only_after_successful_reel(self):
        from utils import paparazzi_reels
        from utils.operation_result import OperationResult
        from utils.stage_result import StageStatus

        item = {"cover_url": "https://r2/cover.jpg"}
        with mock.patch.dict(os.environ, {"REEL_COVER_FACEBOOK_ENABLED": "true"}), mock.patch(
            "meta.fb_client.post_reel_video_to_facebook", return_value=OperationResult(StageStatus.SUCCESS, external_id="v1")
        ), mock.patch("meta.fb_client.set_video_thumbnail") as thumb:
            self.assertEqual(paparazzi_reels.publish_facebook_reel(item), (True, "v1"))
        thumb.assert_called_once_with("v1", "https://r2/cover.jpg")

        with mock.patch.dict(os.environ, {"REEL_COVER_FACEBOOK_ENABLED": "true"}), mock.patch(
            "meta.fb_client.post_reel_video_to_facebook", return_value=OperationResult(StageStatus.FAILED, error_type="x")
        ), mock.patch("meta.fb_client.set_video_thumbnail") as thumb:
            paparazzi_reels.publish_facebook_reel(item)
        thumb.assert_not_called()


class FacebookThumbnailTests(unittest.TestCase):
    def _call(self, status: int, body: dict):
        from meta import fb_client

        image = mock.Mock(content=b"jpg", status_code=200)
        image.raise_for_status = mock.Mock()
        response = mock.Mock(status_code=status)
        response.json = mock.Mock(return_value=body)
        with mock.patch.object(fb_client, "get_page_token", return_value="tok"), mock.patch.object(
            fb_client, "safe_get", return_value=image
        ), mock.patch.object(fb_client.requests, "post", return_value=response) as post:
            result = fb_client.set_video_thumbnail("v1", "https://r2/cover.jpg")
        return result, post

    def test_success_response_without_id(self):
        result, post = self._call(200, {"success": True})
        self.assertTrue(result.ok)
        self.assertIn("/v1/thumbnails", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["data"]["is_preferred"], "true")

    def test_rejection_is_degraded_not_failure(self):
        result, _post = self._call(400, {"error": {"code": 100, "message": "x"}})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "thumbnail_rejected")


if __name__ == "__main__":
    unittest.main()
