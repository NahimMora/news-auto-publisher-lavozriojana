from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


class CanaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / "canary.json"
        self.fixture.write_text(
            json.dumps(
                {
                    "canary_id": "canary-test-001",
                    "titulo": "Actividad cultural de prueba operativa",
                    "categoria": "cultura",
                    "web_url": "https://example.com/canary",
                    "imagen_url": "https://example.com/canary.jpg",
                }
            ),
            encoding="utf-8",
        )
        self.env = {
            "LVR_DATA_DIR": str(self.root / "data"),
            "LVR_LOGS_DIR": str(self.root / "logs"),
            "LVR_BACKUP_DIR": str(self.root / "backups"),
            "LVR_QUARANTINE_DIR": str(self.root / "quarantine"),
            "LVR_CANARY_STATE_PATH": str(self.root / "data" / "canary_runs.json"),
            "JSON_BACKUP_ENABLED": "false",
        }
        self.patch = mock.patch.dict(os.environ, self.env, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    @staticmethod
    def success(channel):
        return OperationResult(
            StageStatus.SUCCESS,
            external_id=f"{channel}-external",
            public_url=f"https://example.com/{channel}-external",
        )

    def test_dry_run_never_calls_publishers_and_allows_disabled_canary(self):
        from utils.canary import run_canary

        publisher = mock.Mock()
        result = run_canary(
            str(self.fixture),
            ["web", "facebook", "instagram"],
            dry_run=True,
            confirm_external_publication=False,
            values={**self.env, "CANARY_ENABLED": "false"},
            publishers={channel: publisher for channel in ("web", "facebook", "instagram")},
        )

        self.assertEqual(StageStatus.SUCCESS, result.status)
        self.assertFalse(result.details["production_calls"])
        publisher.assert_not_called()

    def test_disabled_and_missing_confirmation_are_blocked(self):
        from utils.canary import run_canary

        disabled = run_canary(
            str(self.fixture),
            ["web"],
            dry_run=False,
            confirm_external_publication=True,
            values={**self.env, "CANARY_ENABLED": "false"},
            publishers={"web": mock.Mock()},
        )
        unconfirmed = run_canary(
            str(self.fixture),
            ["web"],
            dry_run=False,
            confirm_external_publication=False,
            values={**self.env, "CANARY_ENABLED": "true"},
            publishers={"web": mock.Mock()},
        )

        self.assertEqual(StageStatus.BLOCKED, disabled.status)
        self.assertEqual("canary_disabled", disabled.error_type)
        self.assertEqual(StageStatus.BLOCKED, unconfirmed.status)
        self.assertEqual("external_confirmation_required", unconfirmed.error_type)

    def test_each_channel_and_all_channels_publish_at_most_once(self):
        from utils.canary import run_canary

        for channels in (
            ["web"],
            ["facebook"],
            ["instagram"],
            ["web", "facebook", "instagram"],
        ):
            with self.subTest(channels=channels):
                fixture = self.root / f"{'-'.join(channels)}.json"
                payload = json.loads(self.fixture.read_text(encoding="utf-8"))
                payload["canary_id"] = f"canary-{'-'.join(channels)}"
                fixture.write_text(json.dumps(payload), encoding="utf-8")
                handlers = {
                    channel: mock.Mock(return_value=self.success(channel))
                    for channel in channels
                }
                result = run_canary(
                    str(fixture),
                    channels,
                    dry_run=False,
                    confirm_external_publication=True,
                    values={**self.env, "CANARY_ENABLED": "true"},
                    publishers=handlers,
                )
                self.assertEqual(StageStatus.SUCCESS, result.status, result.to_dict())
                self.assertEqual(len(channels), result.processed)
                for handler in handlers.values():
                    handler.assert_called_once()

    def test_repeated_command_is_idempotent(self):
        from utils.canary import run_canary

        publisher = mock.Mock(return_value=self.success("web"))
        kwargs = dict(
            input_path=str(self.fixture),
            channels=["web"],
            dry_run=False,
            confirm_external_publication=True,
            values={**self.env, "CANARY_ENABLED": "true"},
            publishers={"web": publisher},
        )
        first = run_canary(**kwargs)
        second = run_canary(**kwargs)

        self.assertEqual(StageStatus.SUCCESS, first.status)
        self.assertEqual(StageStatus.SUCCESS, second.status)
        self.assertTrue(second.details["channels"]["web"]["deduplicated"])
        publisher.assert_called_once()

    def test_instagram_permalink_uses_instagram_media_field(self):
        from utils import canary

        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "id": "ig-media-1",
            "permalink": "https://www.instagram.com/p/canary/",
        }
        operation = OperationResult(
            StageStatus.SUCCESS,
            external_id="ig-media-1",
        )
        with mock.patch.object(canary.requests, "get", return_value=response) as get:
            result = canary._operation_with_permalink("instagram", operation)

        self.assertEqual(
            "https://www.instagram.com/p/canary/",
            result.public_url,
        )
        self.assertEqual("id,permalink", get.call_args.kwargs["params"]["fields"])

    def test_partial_401_429_and_ambiguous_timeout_remain_visible(self):
        from utils.canary import run_canary

        cases = {
            "401": OperationResult(
                StageStatus.FAILED,
                error_type="invalid_credential",
                error_code=401,
            ),
            "429": OperationResult(
                StageStatus.DEGRADED,
                error_type="rate_limit",
                error_code=429,
                retryable=True,
            ),
            "timeout": OperationResult(
                StageStatus.DEGRADED,
                error_type="network_error",
                retryable=False,
                details={"publication_outcome": "unknown"},
            ),
        }
        for name, operation in cases.items():
            with self.subTest(case=name):
                fixture = self.root / f"{name}.json"
                payload = json.loads(self.fixture.read_text(encoding="utf-8"))
                payload["canary_id"] = f"canary-{name}"
                fixture.write_text(json.dumps(payload), encoding="utf-8")
                result = run_canary(
                    str(fixture),
                    ["web", "facebook"],
                    dry_run=False,
                    confirm_external_publication=True,
                    values={**self.env, "CANARY_ENABLED": "true"},
                    publishers={
                        "web": lambda item: self.success("web"),
                        "facebook": lambda item, current=operation: current,
                    },
                )
                self.assertEqual(StageStatus.DEGRADED, result.status)
                if name == "timeout":
                    self.assertEqual(
                        "ambiguous_external_outcome",
                        result.error_type,
                    )
                    self.assertEqual(
                        "ambiguous",
                        result.details["channels"]["facebook"]["status"],
                    )

    def test_cleanup_success_and_failure_are_reported(self):
        from utils.canary import run_canary

        publish = run_canary(
            str(self.fixture),
            ["web", "facebook"],
            dry_run=False,
            confirm_external_publication=True,
            values={**self.env, "CANARY_ENABLED": "true"},
            publishers={
                "web": lambda item: self.success("web"),
                "facebook": lambda item: self.success("facebook"),
            },
        )
        cleanup = run_canary(
            str(self.fixture),
            ["web", "facebook"],
            dry_run=False,
            confirm_external_publication=True,
            cleanup=True,
            values={**self.env, "CANARY_ENABLED": "true"},
            cleanupers={
                "web": lambda evidence: OperationResult(
                    StageStatus.SUCCESS,
                    external_id=evidence["external_id"],
                ),
                "facebook": lambda evidence: OperationResult(
                    StageStatus.FAILED,
                    error_type="cleanup_rejected",
                    external_id=evidence["external_id"],
                ),
            },
        )

        self.assertEqual(StageStatus.SUCCESS, publish.status)
        self.assertEqual(StageStatus.DEGRADED, cleanup.status)
        self.assertEqual("cleanup_completed", cleanup.details["channels"]["web"]["status"])
        self.assertEqual("failed", cleanup.details["channels"]["facebook"]["status"])

    def test_sensitive_breaking_or_invalid_channel_is_rejected(self):
        from utils.canary import run_canary

        sensitive = self.root / "sensitive.json"
        sensitive.write_text(
            json.dumps(
                {
                    "titulo": "Noticia judicial",
                    "categoria": "judiciales",
                    "breaking": True,
                }
            ),
            encoding="utf-8",
        )
        invalid_fixture = run_canary(
            str(sensitive),
            ["web"],
            dry_run=True,
            confirm_external_publication=False,
        )
        invalid_channel = run_canary(
            str(self.fixture),
            ["tiktok"],
            dry_run=True,
            confirm_external_publication=False,
        )

        self.assertEqual(StageStatus.FAILED, invalid_fixture.status)
        self.assertEqual("invalid_fixture", invalid_fixture.error_type)
        self.assertEqual("invalid_channels", invalid_channel.error_type)


if __name__ == "__main__":
    unittest.main()
