"""Limpieza automática de copias de trabajo (sin tocar el disco real)."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest import mock

from utils import disk_cleanup as dc

DAY = 86400


def touch(path: str, age_days: float, size: int = 10) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    old = time.time() - age_days * DAY
    os.utime(path, (old, old))
    return path


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def p(self, *parts):
        return os.path.join(self.root, *parts)

    def test_old_videos_go_recent_and_photos_stay(self):
        old_video = touch(self.p("web_media", "video_download_a.mp4"), 9, 1000)
        new_video = touch(self.p("web_media", "video_download_b.mp4"), 2)
        photo = touch(self.p("web_media", "abc.webp"), 9)
        rules = [dc.Rule("web_media_videos", self.p("web_media"), 7, (".mp4", ".part")),
                 dc.Rule("web_media_fotos", self.p("web_media"), 30, (".webp",))]
        report = dc.cleanup(rules)
        self.assertFalse(os.path.exists(old_video))
        self.assertTrue(os.path.exists(new_video) and os.path.exists(photo))
        self.assertEqual((report.deleted, report.freed_bytes), ({"web_media_videos": 1}, 1000))

    def test_folders_go_only_when_everything_inside_is_old(self):
        stale = self.p("tmp", "newscast3_x")
        touch(os.path.join(stale, "a.mp4"), 20)
        busy = self.p("tmp", "freel_ef_1")
        touch(os.path.join(busy, "old.jpg"), 20)
        touch(os.path.join(busy, "voz.wav"), 0)
        keep = self.p("tmp", "newscast_cache")
        touch(os.path.join(keep, "x.mp4"), 90)
        loose = touch(self.p("tmp", "abc.mp4"), 30)
        report = dc.cleanup([dc.Rule("remotion_tmp", self.p("tmp"), 7, dirs=True)])
        self.assertFalse(os.path.exists(stale) or os.path.exists(loose))
        self.assertTrue(os.path.exists(busy) and os.path.exists(keep))
        self.assertEqual(report.deleted, {"remotion_tmp": 2})

    def test_prefix_limits_what_is_touched_in_the_system_temp(self):
        bundle = self.p("temp", "remotion-webpack-bundle-abc")
        touch(os.path.join(bundle, "index.html"), 5)
        other = self.p("temp", "otra-app")
        touch(os.path.join(other, "x.txt"), 50)
        dc.cleanup([dc.Rule("bundles_temp", self.p("temp"), 2, prefix="remotion-webpack-bundle-", dirs=True)])
        self.assertFalse(os.path.exists(bundle))
        self.assertTrue(os.path.exists(other))

    def test_subfolders_are_not_removed_without_dirs_and_missing_roots_are_fine(self):
        nested = touch(self.p("renders", "sub", "a.mp4"), 60)
        report = dc.cleanup([dc.Rule("renders", self.p("renders"), 14), dc.Rule("nada", self.p("no-existe"), 1)])
        self.assertTrue(os.path.exists(nested))
        self.assertEqual(report.total, 0)

    def test_file_in_use_is_skipped(self):
        touch(self.p("renders", "a.mp4"), 60)
        with mock.patch.object(dc.os, "remove", side_effect=PermissionError):
            report = dc.cleanup([dc.Rule("renders", self.p("renders"), 14)])
        self.assertEqual((report.total, report.in_use), (0, 1))

    def test_default_rules_never_point_at_state_or_logs(self):
        for rule in dc.default_rules():
            parts = {p.lower() for p in os.path.normpath(rule.root).split(os.sep)}
            self.assertFalse(parts & {"data", "logs", "fotoslvr"}, rule.root)


class StageTests(unittest.TestCase):
    def test_disabled_by_default(self):
        from pipeline import run_disk_cleanup as stage

        with mock.patch.dict(os.environ, {"DISK_CLEANUP_ENABLED": "false"}), mock.patch.object(dc, "cleanup") as run:
            self.assertEqual(stage.main().status.value, "no_work")
        run.assert_not_called()

    def test_reports_what_was_freed(self):
        from pipeline import run_disk_cleanup as stage

        report = dc.Report(deleted={"renders": 3}, freed_bytes=3 * 1024 ** 3)
        with mock.patch.dict(os.environ, {"DISK_CLEANUP_ENABLED": "true"}), mock.patch.object(dc, "cleanup", return_value=report):
            result = stage.main()
        self.assertEqual(result.status.value, "success")
        self.assertEqual((result.succeeded, result.details["freed_gb"]), (3, 3.0))


if __name__ == "__main__":
    unittest.main()
