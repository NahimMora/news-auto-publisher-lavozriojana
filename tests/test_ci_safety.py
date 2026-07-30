from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class CiSafetyTests(unittest.TestCase):
    def test_dry_run_gate_requires_success_and_production_calls_false(self):
        from scripts.verify_ci_safety import verify_dry_run

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "dry-run.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "success",
                        "details": {"production_calls": False},
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual([], verify_dry_run(path))
            path.write_text(
                json.dumps(
                    {
                        "status": "success",
                        "details": {"production_calls": True},
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(verify_dry_run(path))

    def test_dry_run_gate_accepts_windows_powershell_utf8_bom(self):
        from scripts.verify_ci_safety import verify_dry_run

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "dry-run-bom.json"
            payload = json.dumps(
                {
                    "status": "success",
                    "details": {"production_calls": False},
                }
            )
            path.write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))

            self.assertEqual([], verify_dry_run(path))

    def test_workflow_contains_required_windows_gates(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "reliability.yml"
        ).read_text(encoding="utf-8")

        for required in (
            "windows-latest",
            "pip check",
            "error::DeprecationWarning",
            "compileall -q .",
            "doctor --scope core --json",
            "run-once --dry-run --json",
            "git diff --check",
            "PIPELINE_DEPLOYMENT_MODE: observe",
            "GITHUB_ENV",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)
        job_env = workflow.split("    steps:", 1)[0]
        self.assertNotIn(
            "${{ runner.temp }}",
            job_env,
            "runner.temp no está disponible al evaluar jobs.<job>.env",
        )

    def test_repository_has_no_tracked_operational_state(self):
        from scripts.verify_ci_safety import verify_tracked_paths

        self.assertEqual([], verify_tracked_paths())

    def test_requirements_support_explicit_dotenv_isolation(self):
        requirements = (
            Path(__file__).resolve().parents[1] / "requirements.txt"
        ).read_text(encoding="utf-8")

        self.assertIn("python-dotenv>=1.2.2", requirements)


if __name__ == "__main__":
    unittest.main()
