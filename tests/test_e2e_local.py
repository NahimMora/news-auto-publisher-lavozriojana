import unittest

from tests.e2e_harness import LocalPipelineHarness, LocalScenario, fixture_news
from utils.stage_result import StageStatus


class EndToEndLocalTests(unittest.TestCase):
    def setUp(self):
        self.harness = LocalPipelineHarness()

    def tearDown(self):
        self.harness.close()

    def _run(self, **kwargs):
        scenario = LocalScenario(
            name=kwargs.pop("name"),
            news=kwargs.pop("news", [fixture_news()]),
            **kwargs,
        )
        evidence = self.harness.run(scenario)
        self.assertIn(evidence.result.exit_code, {0, 1, 2})
        if evidence.state:
            ids = [
                item["id"]
                for bucket in ("pending", "processing", "completed", "expired", "dead_letter")
                for item in evidence.state.get(bucket, [])
            ]
            self.assertEqual(len(ids), len(set(ids)), "No puede haber IDs activos duplicados")
        return evidence

    def test_01_success_all_channels(self):
        evidence = self._run(name="success")
        self.assertEqual(evidence.result.status, StageStatus.SUCCESS)
        self.assertEqual(len(evidence.state["completed"]), 1)
        channels = evidence.state["completed"][0]["result"]["channels"]
        self.assertTrue(channels["web"]["id"])
        self.assertTrue(channels["web"]["url"])
        self.assertEqual(evidence.social_pending, [])

    def test_02_no_new_articles(self):
        evidence = self._run(name="no_work", news=[])
        self.assertEqual(evidence.result.status, StageStatus.NO_WORK)
        self.assertEqual(evidence.result.exit_code, 0)

    def test_03_openai_down_with_allowed_fallback(self):
        evidence = self._run(name="fallback_allowed", openai="down", allow_fallback=True)
        self.assertEqual(evidence.result.status, StageStatus.DEGRADED)
        self.assertTrue(evidence.state["completed"][0]["result"]["fallback_used"])
        self.assertTrue(any(event["reason"] == "openai_fallback_used" for event in evidence.events))

    def test_04_openai_down_with_blocking_policy(self):
        evidence = self._run(name="fallback_blocked", openai="down", allow_fallback=False)
        self.assertEqual(evidence.result.status, StageStatus.FAILED)
        self.assertEqual(len(evidence.state["dead_letter"]), 1)

    def test_05_missing_image(self):
        evidence = self._run(name="missing_image", image="missing")
        self.assertEqual(evidence.result.status, StageStatus.FAILED)
        self.assertEqual(evidence.state["dead_letter"][0]["last_error"], "missing_image")

    def test_06_r2_down(self):
        evidence = self._run(name="r2_down", r2="down")
        self.assertEqual(evidence.result.status, StageStatus.DEGRADED)
        self.assertEqual(len(evidence.state["pending"]), 1)
        self.assertTrue(any(event["reason"] == "r2_unavailable" for event in evidence.events))

    def test_07_cms_401(self):
        evidence = self._run(name="cms_401", cms=401)
        self.assertEqual(evidence.result.status, StageStatus.FAILED)
        self.assertEqual(len(evidence.state["dead_letter"]), 1)
        self.assertTrue(any(event["reason"] == "cms_invalid_credential" for event in evidence.events))

    def test_08_cms_429(self):
        evidence = self._run(name="cms_429", cms=429)
        self.assertEqual(evidence.result.status, StageStatus.DEGRADED)
        self.assertEqual(len(evidence.state["pending"]), 1)
        self.assertTrue(any(event["reason"] == "cms_rate_limit" for event in evidence.events))

    def test_09_facebook_fails_instagram_succeeds(self):
        evidence = self._run(name="partial_meta", facebook="failed", instagram="ok")
        self.assertEqual(evidence.result.status, StageStatus.DEGRADED)
        self.assertEqual(evidence.social_pending[0]["platform"], "facebook")
        self.assertEqual(len(evidence.state["completed"]), 1)

    def test_10_instagram_rate_limit(self):
        evidence = self._run(name="ig_rate", instagram="rate_limit")
        self.assertEqual(evidence.result.status, StageStatus.DEGRADED)
        self.assertEqual(evidence.social_pending[0]["platform"], "instagram")
        self.assertTrue(any(event["reason"] == "instagram_rate_limit" for event in evidence.events))

    def test_11_interruption_and_resume(self):
        evidence = self._run(name="resume", interrupt_after_claim=True)
        self.assertEqual(evidence.result.status, StageStatus.SUCCESS)
        self.assertEqual(len(evidence.state["completed"]), 1)
        self.assertEqual(evidence.state["processing"], [])
        self.assertTrue(any(event["reason"] == "simulated_interruption" for event in evidence.events))

    def test_12_cross_source_duplicate(self):
        original = fixture_news(suffix="same", source="source-a")
        duplicate = dict(original, source="source-b", url="https://other.example/same")
        evidence = self._run(name="duplicate", news=[original, duplicate])
        self.assertEqual(evidence.result.status, StageStatus.SUCCESS)
        self.assertEqual(len(evidence.state["completed"]), 1)
        self.assertEqual(evidence.result.details["duplicates"], 1)

    def test_13_corrupt_json(self):
        evidence = self._run(name="corrupt", corrupt_state=True)
        self.assertEqual(evidence.result.status, StageStatus.FAILED)
        self.assertEqual(evidence.result.error_type, "state_corrupt")
        self.assertTrue(any(event["reason"] == "json_corrupt" for event in evidence.events))

    def test_14_two_concurrent_publishers(self):
        evidence = self._run(name="concurrent", concurrent_publishers=True)
        self.assertEqual(evidence.result.status, StageStatus.SUCCESS)
        self.assertEqual(len(evidence.state["completed"]), 1)
        self.assertEqual(evidence.external_calls["cms"], 1)

    def test_15_expired_article(self):
        evidence = self._run(name="expired", expire=True)
        self.assertEqual(evidence.result.expired, 1)
        self.assertEqual(len(evidence.state["expired"]), 1)
        self.assertTrue(any(event["status"] == "expired" for event in evidence.events))

    def test_16_breaking_article(self):
        evidence = self._run(name="breaking", breaking=True)
        self.assertEqual(evidence.result.status, StageStatus.SUCCESS)
        editorial = evidence.state["completed"][0]["result"]["channels"]["editorial"]
        self.assertEqual(editorial, {"breaking": True, "strict": True})

    def test_17_manual_publication_dry_run(self):
        evidence = self._run(name="manual_dry_run", news=[], manual_dry_run=True)
        self.assertEqual(evidence.result.status, StageStatus.SUCCESS)
        self.assertTrue(evidence.result.details["dry_run"])
        self.assertTrue(all(value == 0 for value in evidence.external_calls.values()))


if __name__ == "__main__":
    unittest.main()
