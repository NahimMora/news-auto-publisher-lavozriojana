from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class QueueCutoverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.env = {
            "LVR_DATA_DIR": str(self.data),
            "LVR_LOGS_DIR": str(self.root / "logs"),
            "LVR_BACKUP_DIR": str(self.root / "backups"),
            "LVR_QUARANTINE_DIR": str(self.root / "quarantine"),
            "LVR_QUEUE_EVENTS_PATH": str(self.data / "events.json"),
            "LVR_QUEUE_CUTOVER_ARCHIVE_PATH": str(self.data / "cutover_archive.json"),
            "WEB_QUEUE_PATH": str(self.data / "web.json"),
            "META_QUEUE_PATH": str(self.data / "meta.json"),
            "SOCIAL_QUEUE_PATH": str(self.data / "social.json"),
            "JSON_BACKUP_ENABLED": "false",
        }
        self.patch = mock.patch.dict(os.environ, self.env, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        from utils import queue_cutover

        self.queue_cutover = queue_cutover
        self.addCleanup(self._close_logger)

    def _close_logger(self):
        for handler in list(self.queue_cutover.logger.handlers):
            handler.close()
            self.queue_cutover.logger.removeHandler(handler)

    def _seed(self):
        from utils.file_manager import save_json

        old = {"fecha": "2026-07-26", "canonical_url": "https://example.com/old"}
        today = {"fecha": "2026-07-27", "canonical_url": "https://example.com/today"}
        save_json(
            self.env["WEB_QUEUE_PATH"],
            [
                {**old, "web_queue_key": "web-old"},
                {**today, "web_queue_key": "web-today"},
            ],
        )
        save_json(
            self.env["META_QUEUE_PATH"],
            [
                {**old, "meta_queue_key": "meta-old"},
                {**today, "meta_queue_key": "meta-today"},
            ],
        )
        save_json(
            self.env["SOCIAL_QUEUE_PATH"],
            [
                {
                    **old,
                    "dedup_key": "social-old",
                    "facebook_state": "pending",
                    "instagram_state": "pending",
                },
                {
                    **today,
                    "dedup_key": "social-today",
                    "facebook_state": "pending",
                    "instagram_state": "pending",
                },
            ],
        )

    def test_report_only_does_not_modify_queues(self):
        self._seed()
        before = {
            name: Path(path).read_bytes()
            for name, path in (
                ("web", self.env["WEB_QUEUE_PATH"]),
                ("meta", self.env["META_QUEUE_PATH"]),
                ("social", self.env["SOCIAL_QUEUE_PATH"]),
            )
        }

        report = self.queue_cutover.build_cutover_report("2026-07-27", self.env)

        self.assertEqual(1, report["queues"]["web"]["before_cutoff"])
        self.assertEqual(1, report["queues"]["meta"]["before_cutoff"])
        self.assertEqual(1, report["queues"]["social"]["before_cutoff"])
        for name, path in (
            ("web", self.env["WEB_QUEUE_PATH"]),
            ("meta", self.env["META_QUEUE_PATH"]),
            ("social", self.env["SOCIAL_QUEUE_PATH"]),
        ):
            self.assertEqual(before[name], Path(path).read_bytes())

    def test_apply_archives_outputs_and_expires_social_states(self):
        from utils.file_manager import load_json
        self._seed()
        result = self.queue_cutover.apply_cutover(
            "2026-07-27", self.env, now=2_000_000
        )
        web = load_json(self.env["WEB_QUEUE_PATH"], [], expected_type=list)
        meta = load_json(self.env["META_QUEUE_PATH"], [], expected_type=list)
        social = load_json(self.env["SOCIAL_QUEUE_PATH"], [], expected_type=list)
        archive = load_json(
            self.env["LVR_QUEUE_CUTOVER_ARCHIVE_PATH"], [], expected_type=list
        )

        self.assertEqual(["web-today"], [item["web_queue_key"] for item in web])
        self.assertEqual(["meta-today"], [item["meta_queue_key"] for item in meta])
        self.assertEqual("expired", social[0]["facebook_state"])
        self.assertEqual("expired", social[0]["instagram_state"])
        self.assertEqual("pending", social[1]["facebook_state"])
        self.assertEqual(2, len(archive))
        self.assertEqual(2, result["social_states_expired"])
        self.assertTrue(Path(self.env["LVR_QUEUE_EVENTS_PATH"]).is_file())

    def test_unknown_date_blocks_apply(self):
        from utils.file_manager import save_json
        save_json(
            self.env["WEB_QUEUE_PATH"],
            [{"web_queue_key": "unknown", "fecha": ""}],
        )
        save_json(self.env["META_QUEUE_PATH"], [])
        save_json(self.env["SOCIAL_QUEUE_PATH"], [])

        with self.assertRaises(ValueError):
            self.queue_cutover.apply_cutover("2026-07-27", self.env)


if __name__ == "__main__":
    unittest.main()
