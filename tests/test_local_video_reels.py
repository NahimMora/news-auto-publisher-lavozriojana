"""Reels de notas locales con YouTube incrustado (LOCAL_VIDEO_REEL_ENABLED)."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from bs4 import BeautifulSoup

YOUTUBE = "https://www.youtube.com/watch?v=EvpKwfKIHxA"
ENABLED = {
    "LOCAL_VIDEO_REEL_ENABLED": "true",
    "LOCAL_VIDEO_REEL_CATEGORIES": "policiales,interior",
    "PAPARAZZI_VIDEO_MAX_AGE_HOURS": "24",
    "SOCIAL_BOOTSTRAP_NOT_BEFORE_TS": "",
}


def _local(key="a", *, seccion="policiales", source="tiempopopular_policiales", video=True, **extra):
    item = {
        "titulo": f"Murió el joven del vuelco número {key}",
        "canonical_url": f"https://www.tiempopopular.com.ar/2026/10/22/nota-{key}",
        "seccion": seccion,
        "source": source,
        "selected_for_publish": True,
        "texto_instagram": "🚨 Murió el joven que volcó en Sanagasta.",
        "queued_at": int(time.time()) - 60,
    }
    if video:
        item["video_embed_url"] = YOUTUBE
        item["video_embed_author"] = "Medios Provincia"
    item.update(extra)
    return item


class FakeOembed:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {}
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class YoutubeEmbedTests(unittest.TestCase):
    def test_first_youtube_iframe_with_channel(self):
        from scraping import video_embeds

        body = BeautifulSoup(
            '<div class="entry-content"><p>Texto</p>'
            '<iframe src="https://www.facebook.com/plugins/video.php?href=x"></iframe>'
            '<iframe src="https://www.youtube.com/embed/EvpKwfKIHxA?feature=oembed"></iframe></div>',
            "html.parser",
        )
        with mock.patch.object(
            video_embeds.requests, "get", return_value=FakeOembed({"author_name": "Medios Provincia"})
        ):
            embed = video_embeds.youtube_embed(body)
        self.assertEqual({"video_embed_url": YOUTUBE, "video_embed_author": "Medios Provincia"}, embed)

    def test_without_video_or_channel(self):
        import requests
        from scraping import video_embeds

        empty = BeautifulSoup("<div><p>Sin video</p></div>", "html.parser")
        nocookie = BeautifulSoup(
            '<div><iframe src="https://www.youtube-nocookie.com/embed/EvpKwfKIHxA"></iframe></div>', "html.parser"
        )
        self.assertEqual({}, video_embeds.youtube_embed(empty))
        self.assertEqual({}, video_embeds.youtube_embed(None))
        with mock.patch.object(video_embeds.requests, "get", return_value=FakeOembed(error=requests.HTTPError("401"))):
            self.assertEqual({"video_embed_url": YOUTUBE}, video_embeds.youtube_embed(nocookie))

    def test_rewrite_keeps_embed_fields_in_meta_queue(self):
        from openIA.rewrite_news import build_meta_item

        item = build_meta_item({**_local(), "url": "u", "parrafos": ["p"]})
        self.assertEqual(YOUTUBE, item["video_embed_url"])
        self.assertEqual("Medios Provincia", item["video_embed_author"])


class LocalVideoReelSelectionTests(unittest.TestCase):
    def test_only_selected_local_policiales_or_interior_with_video(self):
        from utils.publish_selection import is_local_video_reel_item, video_reels_enabled

        with mock.patch.dict(os.environ, ENABLED):
            self.assertTrue(video_reels_enabled())
            self.assertTrue(is_local_video_reel_item(_local()))
            self.assertTrue(is_local_video_reel_item(_local(seccion="interior", source="nuevarioja_interior")))
            self.assertFalse(is_local_video_reel_item(_local(video=False)))
            self.assertFalse(is_local_video_reel_item(_local(seccion="economia")))
            self.assertFalse(is_local_video_reel_item(_local(selected_for_publish=False)))
            self.assertFalse(is_local_video_reel_item(_local(social_skip_reason="policy_x")))
            self.assertFalse(is_local_video_reel_item(_local(source="nuevarioja_internacionales")))
            self.assertFalse(is_local_video_reel_item(_local(source="infobae_policiales")))
        with mock.patch.dict(os.environ, {"LOCAL_VIDEO_REEL_ENABLED": "false"}):
            self.assertFalse(is_local_video_reel_item(_local()))


class LocalVideoReelJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from utils import paparazzi_video_jobs

        self.jobs = paparazzi_video_jobs
        root = Path(self.tmp.name)
        self.meta = root / "meta.json"
        self.state = root / "jobs.json"
        for name, value in (
            ("STATE_PATH", str(self.state)),
            ("META_INPUT", str(self.meta)),
            ("REELS_POSTED_PATH", str(root / "reels_posted.json")),
        ):
            patcher = mock.patch.object(paparazzi_video_jobs, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, ENABLED)
        env.start()
        self.addCleanup(env.stop)

    def test_ingest_builds_instagram_only_job_with_youtube_source_and_credit(self):
        note = _local()
        self.meta.write_text(json.dumps([note, _local("b", video=False)]), encoding="utf-8")

        self.assertEqual({"new": 1}, self.jobs.ingest())
        (_job_id, job), = self.jobs.pending_jobs(0)
        noticia = job["noticia"]
        self.assertEqual(YOUTUBE, noticia["video_url"])
        self.assertEqual(["instagram"], noticia["reel_channels"])
        self.assertEqual("Medios Provincia", noticia["video_credit"])
        self.assertTrue(noticia["texto_instagram"].endswith("🎥 Video: Medios Provincia"))

    def test_expected_until_the_reel_gives_up(self):
        from utils.paparazzi_reels import reel_dedup_key

        note = _local()
        stale = _local("old", queued_at=int(time.time()) - 3 * 86400)
        self.assertTrue(self.jobs.local_reel_expected()(note))
        self.assertFalse(self.jobs.local_reel_expected()(stale))
        self.assertFalse(self.jobs.local_reel_expected()(_local(video=False)))

        self.meta.write_text(json.dumps([note]), encoding="utf-8")
        self.jobs.ingest()
        self.assertTrue(self.jobs.local_reel_expected()(note))
        self.jobs.transition(reel_dedup_key(note), status="dead_letter", reason="reel_render_unavailable")
        self.assertFalse(self.jobs.local_reel_expected()(note))

    def test_disabled_flag_does_not_read_state(self):
        with mock.patch.dict(os.environ, {"LOCAL_VIDEO_REEL_ENABLED": "false"}), mock.patch.object(
            self.jobs, "load_json"
        ) as load:
            expected = self.jobs.local_reel_expected()
        load.assert_not_called()
        self.assertFalse(expected(_local()))


class LocalVideoReelInstagramTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from meta import run_ig
        from utils import paparazzi_video_jobs, social_queue

        self.run_ig = run_ig
        self.jobs = paparazzi_video_jobs
        root = Path(self.tmp.name)
        self.meta = root / "meta.json"
        self.queue = root / "social.json"
        self.state = root / "jobs.json"
        for target, name, value in (
            (run_ig, "META_INPUT", str(self.meta)),
            (social_queue, "QUEUE_PATH", str(self.queue)),
            (paparazzi_video_jobs, "STATE_PATH", str(self.state)),
            (paparazzi_video_jobs, "META_INPUT", str(self.meta)),
            (paparazzi_video_jobs, "REELS_POSTED_PATH", str(root / "reels_posted.json")),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("utils.social_queue.record_queue_event", "utils.social_queue.record_queue_events"):
            patcher = mock.patch(name)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {**ENABLED, "IG_LOCAL_CATEGORIES": ""})
        env.start()
        self.addCleanup(env.stop)

    def _queued_titles(self):
        if not self.queue.exists():
            return []
        return [item["titulo"] for item in json.loads(self.queue.read_text(encoding="utf-8"))]

    def test_image_waits_for_the_reel_and_returns_if_it_fails(self):
        from utils.paparazzi_reels import reel_dedup_key

        note = _local(web_url="https://lavozriojana.com/nota-a", fecha=time.strftime("%Y-%m-%d"))
        self.meta.write_text(json.dumps([note]), encoding="utf-8")

        self.run_ig._bootstrap_queue()
        self.assertEqual([], self._queued_titles())

        self.jobs.ingest()
        self.jobs.transition(reel_dedup_key(note), status="dead_letter", reason="reel_render_unavailable")
        self.run_ig._bootstrap_queue()
        self.assertEqual([note["titulo"]], self._queued_titles())


class LocalVideoReelStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from meta import run_paparazzi_videos
        from utils import paparazzi_video_jobs

        self.stage = run_paparazzi_videos
        self.jobs_path = Path(self.tmp.name) / "jobs.json"
        patcher = mock.patch.object(paparazzi_video_jobs, "STATE_PATH", str(self.jobs_path))
        patcher.start()
        self.addCleanup(patcher.stop)
        noticia = {**_local(), "video_url": YOUTUBE, "reel_channels": ["instagram"]}
        self.job = {"noticia": noticia, "status": "pending", "attempts": 0, "queued_at": 1}
        self.jobs_path.write_text(json.dumps({"jobs": {"reel:1": self.job}}), encoding="utf-8")

    def test_local_reel_goes_only_to_instagram(self):
        from utils.operation_result import OperationResult
        from utils.stage_result import StageStatus

        ok = OperationResult(StageStatus.SUCCESS, external_id="ig-1")
        with mock.patch.object(self.stage, "render_reel_item", return_value=({"video_url": "u"}, "k")), mock.patch.object(
            self.stage, "post_reel_video_to_instagram", return_value=ok
        ), mock.patch.object(self.stage, "publish_facebook_reel") as facebook, mock.patch.object(
            self.stage, "_record_evidence"
        ):
            outcome = self.stage._process("reel:1", self.job, instagram=True, facebook=True)
        self.assertEqual("completed", outcome)
        facebook.assert_not_called()

    def test_skipped_without_instagram(self):
        with mock.patch.object(self.stage, "render_reel_item") as render:
            outcome = self.stage._process("reel:1", self.job, instagram=False, facebook=True)
        self.assertEqual("skipped", outcome)
        render.assert_not_called()
        job = json.loads(self.jobs_path.read_text(encoding="utf-8"))["jobs"]["reel:1"]
        self.assertEqual("pending", job["status"])


class LocalVideoReelCreditTests(unittest.TestCase):
    def test_on_screen_credit_uses_the_channel(self):
        from utils import paparazzi_reels

        captured = {}

        def fake_render(item, **_kw):
            captured.update(item)
            raise RuntimeError("stop")

        noticia = {**_local(), "video_url": YOUTUBE, "video_credit": "Medios Provincia"}
        with mock.patch("utils.video_renderer.render_video", side_effect=fake_render):
            self.assertIsNone(paparazzi_reels.render_reel_item(noticia))
        self.assertEqual("Video: Medios Provincia", captured["reel_credit"])


class YtDlpFormatTests(unittest.TestCase):
    def test_merges_tracks_when_no_progressive_mp4(self):
        from utils import video_renderer

        completed = mock.Mock(returncode=0, stderr="", stdout="")
        with mock.patch.object(video_renderer, "check_ytdlp", return_value=True), mock.patch.object(
            video_renderer.subprocess, "run", return_value=completed
        ) as run, mock.patch.object(video_renderer.os.path, "exists", return_value=True), mock.patch.object(
            video_renderer.os.path, "getsize", return_value=1024
        ):
            video_renderer._download_ytdlp(YOUTUBE, "out.mp4")
        cmd = run.call_args.args[0]
        self.assertIn("bv*[ext=mp4][height<=1080]+ba[ext=m4a]", cmd[cmd.index("-f") + 1])
        self.assertEqual("mp4", cmd[cmd.index("--merge-output-format") + 1])


if __name__ == "__main__":
    unittest.main()
