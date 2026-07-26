from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


class ProcessResultTests(unittest.TestCase):
    def test_exit_zero_without_structured_result_is_failure(self):
        from utils.process_runner import run_stage_process
        from utils.stage_result import StageStatus

        completed = SimpleNamespace(returncode=0, stdout="publicadas 4/10", stderr="")
        with mock.patch("utils.process_runner.subprocess.run", return_value=completed):
            result = run_stage_process("fake.py", base_dir=".", timeout=1)

        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("missing_stage_result", result.error_type)

    def test_structured_no_work_is_not_failure(self):
        from utils.process_runner import run_stage_process
        from utils.stage_result import StageResult, StageStatus

        def fake_run(args, **kwargs):
            result_path = Path(kwargs["env"]["LVR_STAGE_RESULT_PATH"])
            result_path.write_text(
                json.dumps(StageResult("fake", StageStatus.NO_WORK).to_dict()),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch("utils.process_runner.subprocess.run", side_effect=fake_run):
            result = run_stage_process("fake.py", base_dir=".", timeout=1)

        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertEqual(0, result.exit_code)

    def test_timeout_is_failure(self):
        import subprocess
        from utils.process_runner import run_stage_process
        from utils.stage_result import StageStatus

        with mock.patch(
            "utils.process_runner.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["python", "fake.py"], 1),
        ):
            result = run_stage_process("fake.py", base_dir=".", timeout=1)

        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("timeout", result.error_type)


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = mock.patch.dict(
            os.environ,
            {
                "LVR_DATA_DIR": self.temp.name,
                "LVR_LOGS_DIR": str(Path(self.temp.name) / "logs"),
                "PIPELINE_24X7_STALE_SECONDS": "60",
                "JSON_BACKUP_ENABLED": "false",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_fresh_and_stale_heartbeat(self):
        from utils.heartbeat import heartbeat_snapshot, write_heartbeat

        write_heartbeat(
            cycle_number=7,
            supervisor_status="running",
            heartbeat_at=1_000,
            cycle_started_at=990,
            cycle_finished_at=None,
            stage_results=[],
        )

        fresh = heartbeat_snapshot(now=1_030)
        stale = heartbeat_snapshot(now=1_061)

        self.assertFalse(fresh["stale"])
        self.assertTrue(stale["stale"])
        self.assertEqual(61, stale["age_seconds"])

    def test_queue_sizes_and_corruption_are_explicit(self):
        from utils.file_manager import save_json
        from utils.heartbeat import collect_queue_metrics

        root = Path(self.temp.name)
        save_json(str(root / "noticias_sociales_pendientes.json"), [
            {"facebook_done": False, "instagram_done": True},
            {"facebook_done": True, "instagram_done": False},
        ])
        save_json(str(root / "noticias_meta.json"), [{"id": 1}])
        (root / "noticias_web_pending.json").write_text("[", encoding="utf-8")

        metrics = collect_queue_metrics()

        self.assertEqual(1, metrics["social"]["facebook_pending"])
        self.assertEqual(1, metrics["social"]["instagram_pending"])
        self.assertEqual("corrupt", metrics["web"]["status"])


class CliStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = mock.patch.dict(
            os.environ,
            {
                "LVR_DATA_DIR": self.temp.name,
                "LVR_LOGS_DIR": str(self.root / "logs"),
                "PIPELINE_24X7_STALE_SECONDS": "60",
                "JSON_BACKUP_ENABLED": "false",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_status_is_read_only_and_reports_stale(self):
        import cli
        from utils.heartbeat import write_heartbeat

        pid_path = self.root / ".supervisor.pid"
        pid_path.write_text("4242", encoding="utf-8")
        write_heartbeat(
            cycle_number=2,
            supervisor_status="running",
            heartbeat_at=100,
            cycle_started_at=90,
            cycle_finished_at=None,
            stage_results=[],
        )

        with mock.patch.object(cli, "_is_running", return_value=False):
            snapshot = cli.build_status_snapshot(now=200)

        self.assertTrue(pid_path.exists(), "status no debe borrar el PID stale")
        self.assertEqual("stale", snapshot["supervisor"]["status"])
        self.assertEqual(100, snapshot["heartbeat"]["age_seconds"])

    def test_status_json_contains_structured_queue_counts(self):
        import cli
        from utils.file_manager import save_json

        save_json(str(self.root / "noticias_sociales_pendientes.json"), [
            {"facebook_done": False, "instagram_done": True},
        ])
        args = SimpleNamespace(json=True)
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            code = cli.cmd_status(args)

        payload = json.loads(output.getvalue())
        self.assertIn("queues", payload)
        self.assertEqual(1, payload["queues"]["social"]["facebook_pending"])
        self.assertNotEqual(0, code)

    def test_missing_log_is_reported_without_exception(self):
        import cli

        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            code = cli.cmd_logs(SimpleNamespace(modulo="supervisor", follow=False))
        self.assertEqual(code, 0)
        self.assertIn("no existe", output.getvalue())

    def test_run_once_dry_run_executes_only_local_e2e_suite(self):
        import cli

        completed = SimpleNamespace(returncode=0, stdout="", stderr="Ran 17 tests\nOK")
        with mock.patch.object(cli.subprocess, "run", return_value=completed) as run, mock.patch(
            "sys.stdout", io.StringIO()
        ):
            code = cli.cmd_run_once(SimpleNamespace(dry_run=True, json=True))
        self.assertEqual(code, 0)
        command = run.call_args.args[0]
        self.assertEqual(command[-1], "tests.test_e2e_local")
        self.assertNotIn("run_24x7.py", command)
        child_env = run.call_args.kwargs["env"]
        self.assertEqual("off", child_env["WEB_PUBLISH_TARGET"])
        self.assertEqual("false", child_env["FB_PUBLISH_ENABLED"])
        self.assertEqual("observe", child_env["PIPELINE_DEPLOYMENT_MODE"])
        self.assertEqual("false", child_env["CANARY_ENABLED"])
        self.assertEqual("false", child_env["ALERTS_ENABLED"])
        self.assertNotEqual(str(self.root), child_env["LVR_DATA_DIR"])
        self.assertNotEqual(str(self.root), child_env["LVR_BACKUP_DIR"])


class SupervisorSignalTests(unittest.TestCase):
    def test_shutdown_signal_changes_running_flag(self):
        import run_24x7

        original = run_24x7._running
        try:
            run_24x7._running = True
            run_24x7._handle_sigterm(None, None)
            self.assertFalse(run_24x7._running)
        finally:
            run_24x7._running = original


if __name__ == "__main__":
    unittest.main()
