"""Compuertas de los reels automáticos: plantilla Remotion obligatoria y puntaje editorial."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.file_manager import load_json, save_json
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


def _video_note(**extra):
    base = {
        "titulo": "Nota con video",
        "parrafos": ["Texto de la nota con video."],
        "dedup_key": "link:pap-gate",
        "canonical_url": "https://www.paparazzi.com.ar/teve/nota/",
        "seccion": "espectaculos",
        "titulo_instagram": "TITULO",
        "texto_instagram": "Caption",
        "video_url": "https://cdn.jwplayer.com/videos/x.mp4",
    }
    base.update(extra)
    return base


class ReelEditorialScoreTests(unittest.TestCase):
    def setUp(self):
        from utils import reel_editorial_score

        self.score = reel_editorial_score
        env = mock.patch.dict(
            os.environ,
            {
                "REEL_EDITORIAL_SCORE_ENABLED": "true",
                "REEL_EDITORIAL_MIN_SCORE": "60",
                "GEMINI_API_KEY": "test",
                "GEMINI_RETRY_COUNT": "2",
                "GEMINI_RETRY_SLEEP": "0",
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def _decide(self, *responses):
        with mock.patch("utils.ai_client.chat_completion", side_effect=list(responses)) as chat:
            decision = self.score.score_reel_candidate(_video_note(), origin="paparazzi")
        return decision, chat

    def test_disabled_approves_everything_without_ai(self):
        with mock.patch.dict(os.environ, {"REEL_EDITORIAL_SCORE_ENABLED": "false"}), mock.patch(
            "utils.ai_client.chat_completion"
        ) as chat:
            decision = self.score.score_reel_candidate(_video_note(), origin="x_video")
        chat.assert_not_called()
        self.assertEqual((True, "disabled"), (decision.allowed, decision.status))

    def test_score_at_or_above_threshold_is_approved(self):
        decision, _ = self._decide(json.dumps({"score": 60, "motivo": "Hecho actual"}))
        self.assertEqual((True, "approved", 60), (decision.allowed, decision.status, decision.score))

    def test_score_below_threshold_is_rejected(self):
        decision, _ = self._decide(json.dumps({"score": 59, "motivo": "Trivial"}))
        self.assertEqual((False, "rejected", 59), (decision.allowed, decision.status, decision.score))
        self.assertEqual("Trivial", decision.reason)

    def test_threshold_is_configurable(self):
        with mock.patch.dict(os.environ, {"REEL_EDITORIAL_MIN_SCORE": "80"}):
            decision, _ = self._decide(json.dumps({"score": 75, "motivo": "ok"}))
        self.assertFalse(decision.allowed)

    def test_invalid_answers_retry_and_end_unavailable(self):
        decision, chat = self._decide("no es json", json.dumps({"score": 140}))
        self.assertEqual(2, chat.call_count)
        self.assertEqual((False, "unavailable"), (decision.allowed, decision.status))

    def test_retry_recovers_after_invalid_answer(self):
        decision, chat = self._decide(json.dumps({"score": "alto"}), json.dumps({"score": 90}))
        self.assertEqual(2, chat.call_count)
        self.assertTrue(decision.allowed)

    def test_missing_credential_is_unavailable_not_approved(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "PENDIENTE"}):
            decision = self.score.score_reel_candidate(_video_note(), origin="x_video")
        self.assertEqual((False, "unavailable"), (decision.allowed, decision.status))

    def test_prompt_forbids_inventing_data(self):
        self.assertIn("No inventes datos, cifras, armas, personas", self.score._SCORE_PROMPT)


class RenderVideoTemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from utils import video_renderer

        self.vr = video_renderer
        self.source = Path(self.tmp.name) / "source.mp4"
        self.source.write_bytes(b"video")
        for name, value in (
            ("RENDERS_DIR", self.tmp.name),
            ("check_ffmpeg", lambda: True),
            ("get_source_video", lambda item: (str(self.source), OperationResult(StageStatus.SUCCESS))),
            ("get_video_duration", lambda path: 12.0),
            ("reel_cinematic_visual_style_enabled", lambda: True),
        ):
            patcher = mock.patch.object(video_renderer, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _main_output(self):
        path = Path(self.tmp.name) / "_main.mp4"
        path.write_bytes(b"render")
        return str(path)

    def test_without_fallback_remotion_failure_raises_and_skips_ffmpeg(self):
        with mock.patch.object(self.vr, "_render_remotion_main", return_value=None), mock.patch.object(
            self.vr, "render_overlay"
        ) as overlay, mock.patch.dict(os.environ, {"REMOTION_REEL_ATTEMPTS": "2"}):
            with self.assertRaises(self.vr.ReelTemplateUnavailable):
                self.vr.render_video({"titulo": "T"}, allow_ffmpeg_fallback=False)
        overlay.assert_not_called()

    def test_remotion_is_retried_before_giving_up(self):
        output = self._main_output()
        with mock.patch.object(
            self.vr, "_render_remotion_main", side_effect=[None, output]
        ) as remotion, mock.patch.dict(os.environ, {"REMOTION_REEL_ATTEMPTS": "2"}):
            path, _id, _duration, info = self.vr.render_video({"titulo": "T"}, allow_ffmpeg_fallback=False)
        self.assertEqual(2, remotion.call_count)
        self.assertEqual(("remotion", 2), (info["engine"], info["remotion_attempts"]))
        self.assertTrue(os.path.isfile(path))

    def test_default_keeps_single_attempt_and_ffmpeg_fallback(self):
        with mock.patch.object(self.vr, "_render_remotion_main", return_value=None) as remotion, mock.patch.object(
            self.vr, "render_overlay", return_value=mock.Mock()
        ), mock.patch.object(self.vr, "_ffmpeg_compose_video") as compose, mock.patch.object(
            self.vr, "_append_outro", return_value=False
        ), mock.patch.object(self.vr.os.path, "getsize", return_value=1):
            _path, _id, _duration, info = self.vr.render_video({"titulo": "T"})
        self.assertEqual(1, remotion.call_count)
        compose.assert_called_once()
        self.assertEqual("ffmpeg_fallback", info["engine"])

    def test_normalized_source_is_used_only_with_flag(self):
        normalized = Path(self.tmp.name) / "_src_norm.mp4"
        normalized.write_bytes(b"norm")
        output = self._main_output()
        with mock.patch.object(
            self.vr, "_normalize_source_for_remotion", return_value=str(normalized)
        ) as normalize, mock.patch.object(
            self.vr, "_render_remotion_main", return_value=output
        ) as remotion, mock.patch.dict(os.environ, {"REEL_SOURCE_NORMALIZE_ENABLED": "true"}):
            _path, _id, _duration, info = self.vr.render_video({"titulo": "T"})
        normalize.assert_called_once()
        self.assertEqual(str(normalized), remotion.call_args.args[3])
        self.assertTrue(info["source_normalized"])
        self.assertFalse(normalized.exists())

        output = self._main_output()
        with mock.patch.object(self.vr, "_normalize_source_for_remotion") as normalize, mock.patch.object(
            self.vr, "_render_remotion_main", return_value=output
        ), mock.patch.dict(os.environ, {"REEL_SOURCE_NORMALIZE_ENABLED": "false"}):
            self.vr.render_video({"titulo": "T"})
        normalize.assert_not_called()

    def test_normalize_never_uses_shell_and_falls_back_on_error(self):
        failed = mock.Mock(returncode=1, stderr="codec roto")
        with mock.patch.object(self.vr.subprocess, "run", return_value=failed) as run:
            self.assertIsNone(self.vr._normalize_source_for_remotion(str(self.source), "vid"))
        args, kwargs = run.call_args
        self.assertIsInstance(args[0], list)
        self.assertNotIn("shell", kwargs)


class RenderReelItemTemplateTests(unittest.TestCase):
    def test_require_remotion_disables_fallback_and_returns_none(self):
        from utils import paparazzi_reels, video_renderer

        with mock.patch.dict(os.environ, {"REEL_REQUIRE_REMOTION": "true"}), mock.patch(
            "utils.video_renderer.render_video",
            side_effect=video_renderer.ReelTemplateUnavailable("sin Remotion"),
        ) as render:
            self.assertIsNone(paparazzi_reels.render_reel_item(_video_note()))
        self.assertFalse(render.call_args.kwargs["allow_ffmpeg_fallback"])

    def test_without_flag_fallback_stays_allowed(self):
        from utils import paparazzi_reels

        with mock.patch.dict(os.environ, {"REEL_REQUIRE_REMOTION": "false"}), mock.patch(
            "utils.video_renderer.render_video", side_effect=RuntimeError("x")
        ) as render:
            paparazzi_reels.render_reel_item(_video_note())
        self.assertTrue(render.call_args.kwargs["allow_ffmpeg_fallback"])


class PaparazziNotScoredTests(unittest.TestCase):
    """El puntaje editorial aplica sólo a videos de X: paparazzi publica siempre su reel."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from utils import paparazzi_reels

        self.reels = paparazzi_reels
        patcher = mock.patch.object(paparazzi_reels, "STATE_PATH", str(Path(self.tmp.name) / "reels.json"))
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(
            os.environ,
            {
                "PAPARAZZI_REEL_ENABLED": "true",
                "IG_PUBLISH_ENABLED": "true",
                "FB_PUBLISH_ENABLED": "true",
                "REEL_EDITORIAL_SCORE_ENABLED": "true",
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def test_instagram_reel_renders_without_scoring(self):
        with mock.patch("utils.reel_editorial_score.score_reel_candidate") as score, mock.patch.object(
            self.reels, "render_reel_item", return_value=None
        ) as render:
            self.assertIsNone(self.reels.publish_paparazzi_reel_as_instagram_post(_video_note()))
        render.assert_called_once()
        score.assert_not_called()

    def test_extra_reel_renders_without_scoring(self):
        with mock.patch("utils.reel_editorial_score.score_reel_candidate") as score, mock.patch.object(
            self.reels, "render_reel_item", return_value=None
        ) as render:
            self.reels.publish_paparazzi_reel(_video_note())
        render.assert_called_once()
        score.assert_not_called()


class XVideoScoreGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from meta import run_x_videos
        from utils import x_video_reels

        self.stage = run_x_videos
        self.xv = x_video_reels
        self.state = Path(self.tmp.name) / "x_state.json"
        patcher = mock.patch.object(x_video_reels, "STATE_PATH", str(self.state))
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(
            os.environ,
            {
                "X_VIDEO_REELS_ENABLED": "true",
                "PIPELINE_DEPLOYMENT_MODE": "all",
                "IG_PUBLISH_ENABLED": "true",
                "FB_PUBLISH_ENABLED": "true",
                "WEB_PUBLISH_TARGET": "node_webapp",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        save_json(
            str(self.state),
            {"jobs": {"j1": {"status": "pending", "url": "https://x.com/a/status/1", "url_key": "x:1", "attempts": 0}}},
        )
        for target, name, value in (
            (x_video_reels, "read_feed", ([], "feed_missing")),
            (x_video_reels, "fetch_x_metadata", {"text": "Texto"}),
            (x_video_reels, "build_news_item", {"titulo": "T", "parrafos": ["Texto"]}),
            (run_x_videos, "rate_limit_until", 0),
        ):
            patcher = mock.patch.object(target, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _job(self):
        return load_json(str(self.state), {}, expected_type=dict)["jobs"]["j1"]

    def test_rejected_job_is_skipped_terminally_and_stage_has_no_work(self):
        from utils.reel_editorial_score import ReelScoreDecision

        with mock.patch.object(
            self.stage, "score_reel_candidate", return_value=ReelScoreDecision(False, "rejected", 35, "Saludo")
        ), mock.patch.object(self.stage, "render_reel_item") as render:
            result = self.stage.main()
        render.assert_not_called()
        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertEqual(1, result.details["editorial_skipped"])
        job = self._job()
        self.assertEqual(
            ("skipped", "editorial_score_below_threshold", 35, "Saludo"),
            (job["status"], job["reason"], job["editorial_score"], job["editorial_reason"]),
        )

    def test_unavailable_score_retries_instead_of_publishing(self):
        from utils.reel_editorial_score import ReelScoreDecision

        with mock.patch.object(
            self.stage, "score_reel_candidate", return_value=ReelScoreDecision(False, "unavailable", reason="ai_failed")
        ), mock.patch.object(self.stage, "render_reel_item") as render:
            self.stage.main()
        render.assert_not_called()
        job = self._job()
        self.assertEqual(("pending", "editorial_score_unavailable", 1), (job["status"], job["reason"], job["attempts"]))

    def test_editorially_skipped_url_is_not_ingested_again(self):
        save_json(
            str(self.state),
            {
                "jobs": {
                    "j1": {
                        "status": "skipped",
                        "reason": "editorial_score_below_threshold",
                        "url_key": self.xv._url_key("https://x.com/a/status/1"),
                    }
                }
            },
        )
        feed = [{"job_id": "j2", "url": "https://twitter.com/a/status/1", "created_at": "2026-10-02T00:00:00+00:00"}]
        counts = self.xv.ingest(feed, now=1_790_900_000)
        self.assertEqual(1, counts["skipped_duplicate_url"])


if __name__ == "__main__":
    unittest.main()
