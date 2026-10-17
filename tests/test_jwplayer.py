"""Versión alternativa de MP4 de JWPlayer (KNOWN_ISSUES 97)."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from utils.operation_result import OperationResult
from utils.stage_result import StageStatus

BROKEN = "https://cdn.jwplayer.com/videos/mJ9Udz1k-a9NdgpIU.mp4"
GOOD_540 = "https://cdn.jwplayer.com/videos/mJ9Udz1k-HeIT2Id1.mp4"
_MEDIA = {
    "playlist": [
        {
            "sources": [
                {"type": "application/vnd.apple.mpegurl", "file": "https://cdn.jwplayer.com/manifests/mJ9Udz1k.m3u8"},
                {"type": "video/mp4", "label": "1080p", "file": "https://cdn.jwplayer.com/videos/mJ9Udz1k-rhnl7eMv.mp4"},
                {"type": "audio/mp4", "label": "AAC Audio", "file": "https://cdn.jwplayer.com/videos/mJ9Udz1k-OVWAiJCt.m4a"},
                {"type": "video/mp4", "label": "540p", "file": GOOD_540},
                {"type": "video/mp4", "label": "360p", "file": "https://cdn.jwplayer.com/videos/mJ9Udz1k-2KgaOY5Z.mp4"},
            ]
        }
    ]
}


def _response(payload):
    response = mock.Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class AlternativeMp4Tests(unittest.TestCase):
    def test_media_id_only_for_jwplayer_videos(self):
        from utils import jwplayer

        self.assertEqual("mJ9Udz1k", jwplayer.media_id(BROKEN))
        self.assertIsNone(jwplayer.media_id("https://example.com/video.mp4"))
        self.assertIsNone(jwplayer.media_id("https://cdn.jwplayer.com/manifests/mJ9Udz1k.m3u8"))

    def test_picks_priority_mp4_from_the_api(self):
        from utils import jwplayer

        with mock.patch.object(jwplayer, "safe_get", return_value=_response(_MEDIA)) as get:
            self.assertEqual(GOOD_540, jwplayer.alternative_mp4(BROKEN))
        self.assertEqual("https://cdn.jwplayer.com/v2/media/mJ9Udz1k", get.call_args.args[0])

    def test_never_returns_the_same_url(self):
        from utils import jwplayer

        with mock.patch.object(jwplayer, "safe_get", return_value=_response(_MEDIA)):
            self.assertEqual(
                "https://cdn.jwplayer.com/videos/mJ9Udz1k-2KgaOY5Z.mp4", jwplayer.alternative_mp4(GOOD_540)
            )

    def test_api_failure_or_non_jwplayer_returns_none(self):
        from utils import jwplayer

        with mock.patch.object(jwplayer, "safe_get", side_effect=RuntimeError("caída")):
            self.assertIsNone(jwplayer.alternative_mp4(BROKEN))
        with mock.patch.object(jwplayer, "safe_get") as get:
            self.assertIsNone(jwplayer.alternative_mp4("https://example.com/x.mp4"))
        get.assert_not_called()
        with mock.patch.object(jwplayer, "safe_get", return_value=_response({"playlist": []})):
            self.assertIsNone(jwplayer.alternative_mp4(BROKEN))


class RendererFallbackTests(unittest.TestCase):
    def test_reel_download_retries_with_alternative_version(self):
        from utils import video_renderer

        failed = OperationResult(StageStatus.DEGRADED, error_type="network_error", retryable=True)
        ok = OperationResult(StageStatus.SUCCESS, details={"path": "x"})
        with mock.patch.object(video_renderer, "_download_direct_video", side_effect=[failed, ok]) as download, \
                mock.patch.object(video_renderer, "alternative_mp4", return_value=GOOD_540):
            path, result = video_renderer.get_source_video({"video_url": BROKEN})
        self.assertTrue(result.ok)
        self.assertIsNotNone(path)
        self.assertEqual([BROKEN, GOOD_540], [call.args[0] for call in download.call_args_list])


class WebMediaFallbackTests(unittest.TestCase):
    def test_web_video_download_retries_with_alternative_version(self):
        from pipeline.node_webapp import media

        calls = []

        def fake_get(url, **_kwargs):
            calls.append(url)
            if url == BROKEN:
                raise RuntimeError("404 Client Error")
            response = mock.Mock()
            response.headers = {"Content-Type": "video/mp4"}
            response.raise_for_status.return_value = None
            response.iter_content.return_value = [b"mp4"]
            return response

        with mock.patch.object(media, "safe_get", side_effect=fake_get), mock.patch.object(
            media, "alternative_mp4", return_value=GOOD_540
        ) as alternative:
            path = media._download_remote_video(BROKEN)
        self.assertEqual([BROKEN, GOOD_540], calls)
        alternative.assert_called_once_with(BROKEN)
        self.assertTrue(Path(path).read_bytes() == b"mp4")
        Path(path).unlink()


if __name__ == "__main__":
    unittest.main()
