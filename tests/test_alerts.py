from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests


class Response:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class AlertTests(unittest.TestCase):
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
            "LVR_QUEUE_EVENTS_PATH": str(self.data / "queue_events.json"),
            "LVR_ALERT_OUTBOX_PATH": str(self.data / "alert_outbox.json"),
            "LVR_ALERT_STATE_PATH": str(self.data / "alert_state.json"),
            "JSON_BACKUP_ENABLED": "false",
            "ALERTS_ENABLED": "true",
            "ALERT_RECOVERY_ENABLED": "true",
            "ALERT_DEDUP_SECONDS": "3600",
            "DISK_FREE_MIN_MB": "1",
        }
        self.patch = mock.patch.dict(os.environ, self.env, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    @staticmethod
    def snapshot(*, stale=False, stages=None, backlog=0):
        return {
            "heartbeat": {
                "stale": stale,
                "age_seconds": 100 if stale else 1,
            },
            "stages": stages or [],
            "queues": {
                "social": {
                    "facebook_pending": backlog,
                    "instagram_pending": 0,
                },
                "web": {"size": 0},
                "rewrite": {"pending": 0, "processing": 0},
            },
        }

    def _outbox(self):
        from utils.file_manager import load_json

        return load_json(
            self.env["LVR_ALERT_OUTBOX_PATH"],
            {"events": []},
            expected_type=dict,
        )["events"]

    def test_no_work_does_not_alert(self):
        from utils.alerts import process_snapshot
        from utils.stage_result import StageStatus

        result = process_snapshot(
            self.snapshot(stages=[{"stage": "scraper", "status": "no_work"}]),
            self.env,
            now=100,
        )

        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertEqual([], self._outbox())

    def test_stale_failed_invalid_credential_selector_and_rate_limit_are_detected(self):
        from utils.alerts import process_snapshot

        stages = [
            {
                "stage": "facebook",
                "status": "failed",
                "error_type": "invalid_credential",
            },
            {
                "stage": "scraper",
                "status": "failed",
                "error_type": "selector_mismatch",
            },
            {
                "stage": "instagram",
                "status": "degraded",
                "error_type": "rate_limit",
                "next_retry_at": 90,
            },
        ]
        result = process_snapshot(
            self.snapshot(stale=True, stages=stages),
            self.env,
            now=100,
        )
        types = {event["type"] for event in self._outbox()}

        self.assertGreaterEqual(result.succeeded, 6)
        self.assertIn("heartbeat_stale", types)
        self.assertIn("stage_failed", types)
        self.assertIn("invalid_credential", types)
        self.assertIn("selector_mismatch", types)
        self.assertIn("rate_limit_overdue", types)

    def test_three_degraded_cycles_alert_once_then_recover(self):
        from utils.alerts import process_snapshot

        degraded = self.snapshot(
            stages=[{"stage": "cms", "status": "degraded", "error_type": "server_error"}]
        )
        for moment in (100, 200, 300, 400):
            process_snapshot(degraded, self.env, now=moment)
        alerts = [
            event
            for event in self._outbox()
            if event["type"] == "stage_degraded_repeated" and event["event"] == "alert"
        ]
        process_snapshot(
            self.snapshot(stages=[{"stage": "cms", "status": "success"}]),
            self.env,
            now=500,
        )
        recoveries = [
            event
            for event in self._outbox()
            if event["type"] == "stage_degraded_repeated" and event["event"] == "recovery"
        ]

        self.assertEqual(1, len(alerts), "dedupe debe evitar una alerta por heartbeat")
        self.assertEqual(1, len(recoveries))

    def test_backlog_growing_dead_letter_and_quarantine_are_detected(self):
        from utils.alerts import process_snapshot
        from utils.file_manager import save_json

        save_json(
            self.env["LVR_QUEUE_EVENTS_PATH"],
            [
                {
                    "event_id": "dead-1",
                    "status": "dead_letter",
                    "stage": "facebook",
                }
            ],
        )
        quarantine = Path(self.env["LVR_QUARANTINE_DIR"])
        quarantine.mkdir(parents=True)
        (quarantine / "queue.json.abc.corrupt").write_text("[", encoding="utf-8")
        for moment, backlog in ((100, 1), (200, 2), (300, 3)):
            process_snapshot(self.snapshot(backlog=backlog), self.env, now=moment)
        types = {event["type"] for event in self._outbox()}

        self.assertIn("dead_letter_new", types)
        self.assertIn("json_quarantined", types)
        self.assertIn("backlog_growing", types)

    def test_disabled_alerts_do_not_persist_events(self):
        from utils.alerts import alert_test, process_snapshot
        from utils.stage_result import StageStatus

        env = {**self.env, "ALERTS_ENABLED": "false"}
        detected = process_snapshot(self.snapshot(stale=True), env, now=100)
        tested = alert_test(env, now=100)

        self.assertEqual(StageStatus.NO_WORK, detected.status)
        self.assertEqual(StageStatus.NO_WORK, tested.status)
        self.assertFalse(Path(self.env["LVR_ALERT_OUTBOX_PATH"]).exists())

    def test_webhook_200_400_429_and_timeout_are_visible(self):
        from utils.alerts import alert_test
        from utils.stage_result import StageStatus

        cases = (
            ("200", mock.Mock(return_value=Response(200)), StageStatus.SUCCESS, None),
            ("400", mock.Mock(return_value=Response(400)), StageStatus.DEGRADED, "webhook_rejected"),
            (
                "429",
                mock.Mock(return_value=Response(429, {"Retry-After": "30"})),
                StageStatus.DEGRADED,
                "rate_limit",
            ),
            (
                "timeout",
                mock.Mock(side_effect=requests.Timeout()),
                StageStatus.DEGRADED,
                "timeout",
            ),
        )
        for name, post, expected, error in cases:
            with self.subTest(case=name):
                temp = Path(self.temp.name) / name
                temp.mkdir()
                env = {
                    **self.env,
                    "LVR_ALERT_OUTBOX_PATH": str(temp / "outbox.json"),
                    "LVR_ALERT_STATE_PATH": str(temp / "state.json"),
                    "ALERT_WEBHOOK_URL": "https://alerts.example.com/hook",
                }
                result = alert_test(
                    env,
                    http_post=post,
                    resolver=lambda *args, **kwargs: [
                        (None, None, None, None, ("8.8.8.8", 443))
                    ],
                    now=100,
                )
                self.assertEqual(expected, result.status)
                self.assertEqual(error, result.error_type)

    def test_secret_redaction_is_recursive(self):
        from utils.alerts import sanitize_alert_value

        sanitized = sanitize_alert_value(
            {
                "access_token": "real-token",
                "message": "token=real-token authorization:Bearer-abc",
                "nested": [{"api_key": "real-key"}],
            }
        )
        rendered = json.dumps(sanitized)

        self.assertNotIn("real-token", rendered)
        self.assertNotIn("real-key", rendered)
        self.assertIn("REDACTADO", rendered)


if __name__ == "__main__":
    unittest.main()
