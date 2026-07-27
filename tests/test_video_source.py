"""Contrato de descarga de video fuente (yt-dlp/MP4 directo) y detección de plataforma."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from utils import manual_video_queue, video_renderer
from utils.stage_result import StageStatus


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class YtdlpClassificationTests(unittest.TestCase):
    def test_auth_required_detected(self):
        error_type, retryable = video_renderer._classify_ytdlp_failure(
            "ERROR: [Instagram] abc123: Requested content is not available, "
            "rate-limit reached or login required"
        )
        self.assertEqual(error_type, "auth_required")
        self.assertFalse(retryable)

    def test_unsupported_url_detected(self):
        error_type, retryable = video_renderer._classify_ytdlp_failure(
            "ERROR: Unsupported URL: https://example.com/plain-article"
        )
        self.assertEqual(error_type, "unsupported_url")
        self.assertFalse(retryable)

    def test_rate_limit_is_retryable(self):
        error_type, retryable = video_renderer._classify_ytdlp_failure(
            "ERROR: unable to download video data: HTTP Error 429: Too Many Requests"
        )
        self.assertEqual(error_type, "rate_limit")
        self.assertTrue(retryable)

    def test_generic_failure_is_extractor_error(self):
        error_type, retryable = video_renderer._classify_ytdlp_failure(
            "ERROR: Unable to extract shared data"
        )
        self.assertEqual(error_type, "extractor_error")
        self.assertFalse(retryable)


class DownloadYtdlpTests(unittest.TestCase):
    def test_not_installed_is_reported(self):
        with patch.object(video_renderer, "check_ytdlp", return_value=False):
            result = video_renderer._download_ytdlp("https://youtu.be/abc", "dest.mp4")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "not_installed")

    def test_success_writes_file_and_returns_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.mp4")

            def fake_run(cmd, **kwargs):
                Path(dest).write_bytes(b"fake-mp4-bytes")
                return FakeCompletedProcess(returncode=0)

            with patch.object(video_renderer, "check_ytdlp", return_value=True), patch.object(
                video_renderer.subprocess, "run", side_effect=fake_run
            ):
                result = video_renderer._download_ytdlp(
                    "https://www.instagram.com/p/Daj2ZQFsRik/", dest
                )
        self.assertTrue(result.ok)

    def test_auth_required_failure_is_not_retryable(self):
        with patch.object(video_renderer, "check_ytdlp", return_value=True), patch.object(
            video_renderer.subprocess,
            "run",
            return_value=FakeCompletedProcess(
                returncode=1, stderr="ERROR: [Instagram] login required"
            ),
        ):
            result = video_renderer._download_ytdlp("https://instagram.com/p/x/", "dest.mp4")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "auth_required")
        self.assertFalse(result.retryable)

    def test_timeout_is_retryable_network_error(self):
        with patch.object(video_renderer, "check_ytdlp", return_value=True), patch.object(
            video_renderer.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="yt-dlp", timeout=180),
        ):
            result = video_renderer._download_ytdlp("https://tiktok.com/@a/video/1", "dest.mp4")
        self.assertEqual(result.status, StageStatus.DEGRADED)
        self.assertEqual(result.error_type, "network_error")
        self.assertTrue(result.retryable)

    def test_cookies_file_is_passed_when_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookies = os.path.join(tmp, "cookies.txt")
            Path(cookies).write_text("# cookies", encoding="utf-8")
            captured = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                return FakeCompletedProcess(returncode=1, stderr="ERROR: boom")

            with patch.object(video_renderer, "check_ytdlp", return_value=True), patch.object(
                video_renderer.subprocess, "run", side_effect=fake_run
            ), patch.dict(os.environ, {"YTDLP_COOKIES_FILE": cookies}):
                video_renderer._download_ytdlp("https://tiktok.com/@a/video/1", "dest.mp4")
        self.assertIn("--cookies", captured["cmd"])
        self.assertIn(cookies, captured["cmd"])


class GetSourceVideoTests(unittest.TestCase):
    def test_no_candidates_returns_success_without_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(video_renderer, "RENDERS_DIR", tmp):
                path, result = video_renderer.get_source_video({"titulo": "sin video"})
        self.assertIsNone(path)
        self.assertTrue(result.ok)

    def test_download_failure_reason_is_propagated(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(video_renderer, "RENDERS_DIR", tmp), patch.object(
                video_renderer, "check_ytdlp", return_value=False
            ):
                path, result = video_renderer.get_source_video(
                    {"video_url": "https://www.instagram.com/reel/abc/"}
                )
        self.assertIsNone(path)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_type, "not_installed")

    def test_generic_host_still_attempts_ytdlp_via_source_url(self):
        # Confirma que un host no listado explícitamente igual dispara un intento de
        # yt-dlp en vez de saltearse en silencio (cobertura "y más" plataformas).
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(video_renderer, "RENDERS_DIR", tmp), patch.object(
                video_renderer, "check_ytdlp", return_value=True
            ), patch.object(
                video_renderer.subprocess,
                "run",
                return_value=FakeCompletedProcess(returncode=1, stderr="ERROR: Unsupported URL"),
            ):
                path, result = video_renderer.get_source_video(
                    {"source_url": "https://www.threads.net/@user/post/xyz"}
                )
        self.assertIsNone(path)
        self.assertEqual(result.error_type, "unsupported_url")


class DetectPlatformTests(unittest.TestCase):
    def test_tiktok_is_recognized(self):
        self.assertEqual(
            manual_video_queue.detect_platform("https://www.tiktok.com/@user/video/123"),
            "tiktok",
        )

    def test_instagram_and_youtube_still_recognized(self):
        self.assertEqual(
            manual_video_queue.detect_platform("https://www.instagram.com/p/Daj2ZQFsRik/"),
            "instagram",
        )
        self.assertEqual(
            manual_video_queue.detect_platform("https://youtu.be/abc123"), "youtube"
        )


if __name__ == "__main__":
    unittest.main()
