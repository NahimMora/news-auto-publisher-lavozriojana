"""Instagram publica sólo el Reel en notas con video, y videos de X como Reel."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from utils.file_manager import load_json, save_json
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


def _paparazzi(**extra):
    base = {
        "titulo": "Nota con video",
        "dedup_key": "link:pap1",
        "canonical_url": "https://www.paparazzi.com.ar/teve/nota/",
        "source": "paparazzi",
        "titulo_instagram": "TITULO",
        "texto_instagram": "Caption",
        "seccion": "espectaculos",
        "imagen_url": "https://www.paparazzi.com.ar/foto.jpg",
        "video_url": "https://cdn.jwplayer.com/videos/x.mp4",
    }
    base.update(extra)
    return base


class InstagramReelOnlyDispatchTests(unittest.TestCase):
    def test_video_note_publishes_only_the_reel(self):
        from meta import run_ig

        reel = OperationResult(StageStatus.SUCCESS, external_id="ig-reel")
        with mock.patch(
            "utils.paparazzi_reels.publish_paparazzi_reel_as_instagram_post", return_value=reel
        ) as reel_publish, mock.patch.object(run_ig, "post_paparazzi_carousel_to_instagram") as carousel:
            result = run_ig._publish_paparazzi(_paparazzi())

        self.assertIs(reel, result)
        reel_publish.assert_called_once()
        carousel.assert_not_called()

    def test_without_usable_reel_publishes_image_only(self):
        from meta import run_ig

        image = OperationResult(StageStatus.SUCCESS, external_id="ig-img")
        with mock.patch(
            "utils.paparazzi_reels.publish_paparazzi_reel_as_instagram_post", return_value=None
        ), mock.patch.object(run_ig, "post_paparazzi_carousel_to_instagram", return_value=image) as carousel:
            result = run_ig._publish_paparazzi(_paparazzi(video_duration_seconds=40, media_type="video"))

        self.assertIs(image, result)
        sent = carousel.call_args.args[0]
        self.assertNotIn("video_url", sent)
        self.assertNotIn("media_type", sent)

    def test_note_without_video_never_tries_reel(self):
        from meta import run_ig

        with mock.patch(
            "utils.paparazzi_reels.publish_paparazzi_reel_as_instagram_post"
        ) as reel_publish, mock.patch.object(
            run_ig, "post_paparazzi_carousel_to_instagram", return_value=OperationResult(StageStatus.SUCCESS)
        ):
            run_ig._publish_paparazzi(_paparazzi(video_url=""))
        reel_publish.assert_not_called()


class PaparazziPrimaryReelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from utils import paparazzi_reels
        from meta import ig_client

        self.reels = paparazzi_reels
        self.state = Path(self.tmp.name) / "reels.json"
        self.ig_state = Path(self.tmp.name) / "ig_posted.json"
        for target, name, value in (
            (paparazzi_reels, "STATE_PATH", str(self.state)),
            (ig_client, "IG_STATE_PATH", str(self.ig_state)),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"PAPARAZZI_REEL_ENABLED": "true", "FB_PUBLISH_ENABLED": "true"})
        env.start()
        self.addCleanup(env.stop)

    def test_success_records_evidence_and_keeps_facebook_reel(self):
        rendered = ({"video_url": "https://r2/reel.mp4", "titulo": "T"}, "temp/reel.mp4")
        with mock.patch.object(self.reels, "render_reel_item", return_value=rendered), mock.patch(
            "meta.ig_client.post_reel_video_to_instagram",
            return_value=OperationResult(StageStatus.SUCCESS, external_id="ig-1"),
        ), mock.patch.object(self.reels, "publish_facebook_reel", return_value=(True, "fb-1")) as fb:
            result = self.reels.publish_paparazzi_reel_as_instagram_post(_paparazzi())

        self.assertTrue(result.ok)
        fb.assert_called_once()
        posted = load_json(str(self.state), {}, expected_type=dict)["posted"]
        record = next(iter(posted.values()))
        self.assertEqual(("ig-1", "fb-1"), (record["instagram_id"], record["facebook_id"]))
        ig_posted = load_json(str(self.ig_state), {}, expected_type=dict)["posted"]
        self.assertEqual("ig-1", ig_posted["link:pap1"]["external_id"])

    def test_already_published_reel_is_deduplicated(self):
        save_json(str(self.state), {"posted": {self.reels.reel_dedup_key(_paparazzi()): {"instagram_id": "ig-0"}}})
        with mock.patch.object(self.reels, "render_reel_item") as render:
            result = self.reels.publish_paparazzi_reel_as_instagram_post(_paparazzi())
        render.assert_not_called()
        self.assertTrue(result.deduplicated)
        self.assertEqual("ig-0", result.external_id)

    def test_instagram_failure_cleans_upload_and_skips_facebook(self):
        rendered = ({"video_url": "https://r2/reel.mp4"}, "temp/reel.mp4")
        failure = OperationResult(StageStatus.FAILED, error_type="request_rejected")
        with mock.patch.object(self.reels, "render_reel_item", return_value=rendered), mock.patch(
            "meta.ig_client.post_reel_video_to_instagram", return_value=failure
        ), mock.patch.object(self.reels, "publish_facebook_reel") as fb, mock.patch.object(
            self.reels, "delete_reel_upload"
        ) as delete:
            result = self.reels.publish_paparazzi_reel_as_instagram_post(_paparazzi())
        self.assertIs(failure, result)
        fb.assert_not_called()
        delete.assert_called_once_with("temp/reel.mp4")
        self.assertFalse(self.state.exists())

    def test_unusable_video_returns_none(self):
        with mock.patch.object(self.reels, "render_reel_item", return_value=None):
            self.assertIsNone(self.reels.publish_paparazzi_reel_as_instagram_post(_paparazzi()))


class XVideoFeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from utils import x_video_reels

        self.xv = x_video_reels
        self.feed = Path(self.tmp.name) / "x_video_sources.json"
        self.state = Path(self.tmp.name) / "x_state.json"
        patcher = mock.patch.object(x_video_reels, "STATE_PATH", str(self.state))
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"X_VIDEO_FEED_PATH": str(self.feed), "X_VIDEO_MAX_AGE_HOURS": "24"})
        env.start()
        self.addCleanup(env.stop)

    def _write_feed(self, items):
        self.feed.write_text(json.dumps(items), encoding="utf-8")

    def test_missing_or_invalid_feed_is_not_an_error(self):
        self.assertEqual(([], "feed_missing"), self.xv.read_feed())
        self.feed.write_text("{roto", encoding="utf-8")
        self.assertEqual(([], "feed_invalid_json"), self.xv.read_feed())

    def test_read_feed_never_modifies_the_backend_file(self):
        self._write_feed([{"job_id": "j1", "url": "https://x.com/a/status/1", "created_at": "2026-10-01T15:20:00+00:00"}])
        before = self.feed.read_bytes()
        items, issue = self.xv.read_feed()
        self.assertIsNone(issue)
        self.assertEqual(1, len(items))
        self.assertEqual(before, self.feed.read_bytes())

    def test_non_x_urls_are_ignored(self):
        self._write_feed([{"job_id": "j1", "url": "https://evil.example/status/1", "created_at": ""}])
        self.assertEqual([], self.xv.read_feed()[0])

    def test_ingest_dedups_job_and_url_and_skips_old(self):
        now = 1_790_900_000
        recent = "2026-10-02T00:00:00+00:00"
        old = "2026-09-01T00:00:00+00:00"
        feed = [  # más nuevo primero, como el backend
            {"job_id": "j3", "url": "https://x.com/b/status/2", "created_at": old},
            {"job_id": "j2", "url": "https://twitter.com/a/status/1", "created_at": recent},
            {"job_id": "j1", "url": "https://x.com/a/status/1", "created_at": recent},
        ]
        counts = self.xv.ingest(feed, now=now)
        self.assertEqual({"new": 1, "skipped_old": 1, "skipped_duplicate_url": 1}, counts)
        jobs = load_json(str(self.state), {}, expected_type=dict)["jobs"]
        self.assertEqual("pending", jobs["j1"]["status"])
        self.assertEqual("duplicate_url", jobs["j2"]["reason"])
        self.assertEqual("older_than_max_age", jobs["j3"]["reason"])
        self.assertEqual({"new": 0, "skipped_old": 0, "skipped_duplicate_url": 0}, self.xv.ingest(feed, now=now))

    def test_interrupted_processing_goes_to_dead_letter(self):
        save_json(str(self.state), {"jobs": {"j1": {"status": "processing"}}})
        self.assertEqual(1, self.xv.recover_interrupted())
        job = load_json(str(self.state), {}, expected_type=dict)["jobs"]["j1"]
        self.assertEqual("dead_letter", job["status"])

    def test_news_item_requires_post_text_and_uses_one_caption_call(self):
        self.assertIsNone(self.xv.build_news_item({"url": "https://x.com/a/status/1"}, {}))
        with mock.patch(
            "openIA.caption_generator.generate_caption",
            return_value={"titulo_instagram": "Gancho", "texto_instagram": "Caption", "cta": "?"},
        ) as caption:
            item = self.xv.build_news_item(
                {"url": "https://x.com/a/status/1"}, {"text": "Un hecho ocurrido hoy en Salta"}
            )
        caption.assert_called_once()
        self.assertEqual("https://x.com/a/status/1", item["source_url"])
        self.assertEqual("Gancho", item["titulo_instagram"])
        self.assertNotIn("video_url", item)


class XVideoStageTests(unittest.TestCase):
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
        save_json(str(self.state), {"jobs": {"j1": {"status": "pending", "url": "https://x.com/a/status/1", "attempts": 0}}})
        for name, value in (
            ("read_feed", ([], "feed_missing")),
            ("fetch_x_metadata", {"text": "Texto"}),
            ("build_news_item", {"titulo_instagram": "T", "source_url": "https://x.com/a/status/1"}),
        ):
            patcher = mock.patch.object(x_video_reels, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(run_x_videos, "rate_limit_until", return_value=0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _job(self):
        return load_json(str(self.state), {}, expected_type=dict)["jobs"]["j1"]

    def test_disabled_is_noop(self):
        with mock.patch.dict(os.environ, {"X_VIDEO_REELS_ENABLED": "false"}):
            self.assertEqual(StageStatus.NO_WORK, self.stage.main().status)

    def test_publishes_reel_on_both_networks(self):
        with mock.patch.object(self.stage, "render_reel_item", return_value=({"video_url": "u"}, "k")), mock.patch.object(
            self.stage, "post_reel_video_to_instagram", return_value=OperationResult(StageStatus.SUCCESS, external_id="ig-9")
        ), mock.patch.object(self.stage, "publish_facebook_reel", return_value=(True, "fb-9")):
            result = self.stage.main()
        self.assertEqual(StageStatus.SUCCESS, result.status)
        job = self._job()
        self.assertEqual(("completed", "ig-9", "fb-9"), (job["status"], job["instagram_id"], job["facebook_id"]))

    def test_render_failure_retries_then_dead_letters(self):
        with mock.patch.object(self.stage, "render_reel_item", return_value=None):
            for _ in range(3):
                self.stage.main()
        job = self._job()
        self.assertEqual("dead_letter", job["status"])
        self.assertEqual(3, job["attempts"])

    def test_ambiguous_instagram_outcome_is_not_retried(self):
        unknown = OperationResult(
            StageStatus.FAILED, error_type="network_error", retryable=True, details={"publication_outcome": "unknown"}
        )
        with mock.patch.object(self.stage, "render_reel_item", return_value=({"video_url": "u"}, "k")), mock.patch.object(
            self.stage, "post_reel_video_to_instagram", return_value=unknown
        ), mock.patch.object(self.stage, "publish_facebook_reel") as fb, mock.patch.object(self.stage, "delete_reel_upload"):
            self.stage.main()
        fb.assert_not_called()
        self.assertEqual("ambiguous_publication_outcome", self._job()["reason"])

    def test_meta_rate_limit_defers_without_processing(self):
        with mock.patch.object(self.stage, "rate_limit_until", return_value=time.time() + 600), mock.patch.object(
            self.stage, "render_reel_item"
        ) as render:
            result = self.stage.main()
        render.assert_not_called()
        self.assertEqual(StageStatus.DEGRADED, result.status)
        self.assertEqual("pending", self._job()["status"])


if __name__ == "__main__":
    unittest.main()
