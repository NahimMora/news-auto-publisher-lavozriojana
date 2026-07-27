from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class DeploymentModeTests(unittest.TestCase):
    def _env(self, mode: str, *, web=False, facebook=False, instagram=False):
        return {
            "PIPELINE_DEPLOYMENT_MODE": mode,
            "WEB_PUBLISH_TARGET": "node_webapp" if web else "off",
            "FB_PUBLISH_ENABLED": "true" if facebook else "false",
            "IG_PUBLISH_ENABLED": "true" if instagram else "false",
        }

    def test_each_mode_requires_exact_individual_kill_switches(self):
        from utils.deployment import deployment_plan

        cases = {
            "observe": (False, False, False, set()),
            "web_only": (True, False, False, {"web"}),
            "web_facebook": (True, True, False, {"web", "facebook"}),
            "web_instagram": (True, False, True, {"web", "instagram"}),
            "all": (True, True, True, {"web", "facebook", "instagram"}),
        }
        for mode, (web, facebook, instagram, expected) in cases.items():
            with self.subTest(mode=mode):
                plan = deployment_plan(
                    self._env(
                        mode,
                        web=web,
                        facebook=facebook,
                        instagram=instagram,
                    )
                )
                self.assertTrue(plan.ok, plan.to_dict())
                self.assertEqual(expected, set(plan.enabled_channels))

    def test_mode_never_overrides_kill_switch_and_contradiction_is_error(self):
        from utils.config import validate_config
        from utils.deployment import deployment_plan

        env = self._env("all", web=True, facebook=False, instagram=True)
        plan = deployment_plan(env)
        report = validate_config(env, scope="core")

        self.assertFalse(plan.channel_enabled("facebook"))
        self.assertFalse(plan.ok)
        self.assertIn(
            "deployment_kill_switch_off",
            {issue.code for issue in report.errors},
        )

    def test_observe_rejects_accidentally_enabled_channel(self):
        from utils.deployment import deployment_plan

        plan = deployment_plan(self._env("observe", facebook=True))

        self.assertFalse(plan.ok)
        self.assertEqual(set(), set(plan.enabled_channels))
        self.assertEqual(
            "deployment_unexpected_channel_enabled",
            plan.errors[0]["code"],
        )

    def test_operational_limits_are_unlimited_web_and_eight_per_meta_channel(self):
        from utils.deployment import deployment_plan, stage_environment

        plan = deployment_plan(self._env("all", web=True, facebook=True, instagram=True))

        self.assertEqual(
            {
                "WEB_PUBLISH_MAX_PER_RUN": "0",
                "WEB_MAX_DEPORTES_PER_RUN": "-1",
            },
            stage_environment("web", plan),
        )
        self.assertEqual({"PUBLISH_MAX_PER_RUN": "8"}, stage_environment("facebook", plan))
        self.assertEqual({"IG_MAX_PER_RUN": "8"}, stage_environment("instagram", plan))
        self.assertEqual(
            {
                "web_per_cycle": "unlimited",
                "facebook_per_cycle": 8,
                "instagram_per_cycle": 8,
            },
            plan.to_dict()["limits"],
        )

    def test_runners_are_disabled_when_switch_is_missing(self):
        import meta.run_fb as run_fb
        import meta.run_ig as run_ig
        from utils.stage_result import StageStatus

        with mock.patch.dict(
            os.environ,
            {"FB_PUBLISH_ENABLED": "", "IG_PUBLISH_ENABLED": ""},
            clear=False,
        ):
            self.assertEqual(StageStatus.NO_WORK, run_fb.main().status)
            self.assertEqual(StageStatus.NO_WORK, run_ig.main().status)

    def test_supervisor_observe_skips_every_external_stage(self):
        import run_24x7
        from utils.stage_result import StageResult, StageStatus

        with tempfile.TemporaryDirectory() as temp:
            env = {
                "LVR_DATA_DIR": temp,
                "LVR_LOGS_DIR": str(Path(temp) / "logs"),
                "JSON_BACKUP_ENABLED": "false",
                **self._env("observe"),
            }
            fake_core = StageResult("scraping_rewrite", StageStatus.NO_WORK)
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
                run_24x7,
                "run_step",
                return_value=fake_core,
            ) as run_step, mock.patch.object(
                run_24x7,
                "monitor_operational_state",
                return_value=StageResult("alerts", StageStatus.NO_WORK),
            ):
                result = run_24x7.run_cycle(1, heartbeat_interval=1)

        self.assertEqual(1, run_step.call_count)
        children = result.details["children"]
        self.assertEqual(
            ["scraping_rewrite", "web", "facebook", "instagram"],
            [item["stage"] for item in children],
        )
        self.assertTrue(all(item["status"] == "no_work" for item in children))


class BlockedStatusTests(unittest.TestCase):
    def test_blocked_has_nonzero_distinct_exit_code(self):
        from utils.stage_result import StageResult, StageStatus

        result = StageResult("preflight", StageStatus.BLOCKED)

        self.assertEqual(3, result.exit_code)
        self.assertFalse(result.acceptable)


if __name__ == "__main__":
    unittest.main()
