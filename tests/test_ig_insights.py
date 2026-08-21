from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meta import ig_insights
from utils.stage_result import StageStatus


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _insights_payload(reach, interactions):
    return {
        "data": [
            {"name": "reach", "values": [{"value": reach}]},
            {"name": "total_interactions", "values": [{"value": interactions}]},
        ]
    }


class IgInsightsStageTests(unittest.TestCase):
    def test_disabled_by_default_is_no_work(self):
        with patch.dict(os.environ, {"IG_STATS_ENABLED": "false"}, clear=False):
            result = ig_insights.main()
        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertTrue(result.details.get("disabled"))

    def test_missing_credentials_is_failed(self):
        with patch.dict(os.environ, {"IG_STATS_ENABLED": "true"}, clear=False), patch.object(
            ig_insights, "IG_ACCOUNT_ID", ""
        ):
            result = ig_insights.main()
        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("missing_configuration", result.error_type)

    def test_aggregates_engagement_rate_per_category_and_persists(self):
        posted = {
            "posted": {
                "link:a": {"external_id": "media-1", "seccion": "Politica", "posted_at": 300},
                "link:b": {"external_id": "media-2", "seccion": "Politica", "posted_at": 200},
                "link:c": {"external_id": "media-3", "seccion": "Deportes", "posted_at": 100},
            }
        }
        insights_by_media = {
            "media-1": _insights_payload(100, 10),
            "media-2": _insights_payload(100, 20),
            "media-3": _insights_payload(200, 4),
        }

        def fake_get(url, params=None, timeout=None):
            media_id = url.rsplit("/", 2)[-2]
            return FakeResponse(200, insights_by_media[media_id])

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "ig_posted.json"
            state_path.write_text(json.dumps(posted), encoding="utf-8")
            perf_path = Path(tmp) / "perf.json"

            with patch.dict(
                os.environ, {"IG_STATS_ENABLED": "true"}, clear=False
            ), patch.object(ig_insights, "IG_ACCOUNT_ID", "acc"), patch.object(
                ig_insights, "IG_ACCESS_TOKEN", "token"
            ), patch.object(
                ig_insights, "IG_STATE_PATH", str(state_path)
            ), patch.object(
                ig_insights, "PERFORMANCE_PATH", str(perf_path)
            ), patch.object(
                ig_insights.requests, "get", side_effect=fake_get
            ):
                result = ig_insights.main()

            self.assertEqual(StageStatus.SUCCESS, result.status)
            self.assertEqual(3, result.succeeded)

            snapshot = json.loads(perf_path.read_text(encoding="utf-8"))
            politica = snapshot["categories"]["politica"]
            self.assertEqual(2, politica["sample_size"])
            self.assertAlmostEqual(200.0, politica["reach_sum"])
            self.assertAlmostEqual(30.0, politica["interactions_sum"])
            self.assertAlmostEqual(0.15, politica["engagement_rate"])

            deportes = snapshot["categories"]["deportes"]
            self.assertAlmostEqual(0.02, deportes["engagement_rate"])

            overall = snapshot["overall"]
            self.assertEqual(3, overall["sample_size"])
            self.assertAlmostEqual(400.0, overall["reach_sum"])
            self.assertAlmostEqual(34.0, overall["interactions_sum"])

    def test_partial_failures_are_degraded_not_failed(self):
        posted = {
            "posted": {
                "link:a": {"external_id": "media-1", "seccion": "Politica", "posted_at": 200},
                "link:b": {"external_id": "media-2", "seccion": "Politica", "posted_at": 100},
            }
        }

        def fake_get(url, params=None, timeout=None):
            if "media-1" in url:
                return FakeResponse(200, _insights_payload(100, 10))
            return FakeResponse(400, {})

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "ig_posted.json"
            state_path.write_text(json.dumps(posted), encoding="utf-8")
            perf_path = Path(tmp) / "perf.json"

            with patch.dict(
                os.environ, {"IG_STATS_ENABLED": "true"}, clear=False
            ), patch.object(ig_insights, "IG_ACCOUNT_ID", "acc"), patch.object(
                ig_insights, "IG_ACCESS_TOKEN", "token"
            ), patch.object(
                ig_insights, "IG_STATE_PATH", str(state_path)
            ), patch.object(
                ig_insights, "PERFORMANCE_PATH", str(perf_path)
            ), patch.object(
                ig_insights.requests, "get", side_effect=fake_get
            ):
                result = ig_insights.main()

        self.assertEqual(StageStatus.DEGRADED, result.status)
        self.assertEqual(1, result.succeeded)
        self.assertEqual(1, result.failed)

    def test_no_posted_items_is_no_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "ig_posted.json"
            state_path.write_text(json.dumps({"posted": {}}), encoding="utf-8")
            with patch.dict(
                os.environ, {"IG_STATS_ENABLED": "true"}, clear=False
            ), patch.object(ig_insights, "IG_ACCOUNT_ID", "acc"), patch.object(
                ig_insights, "IG_ACCESS_TOKEN", "token"
            ), patch.object(ig_insights, "IG_STATE_PATH", str(state_path)):
                result = ig_insights.main()
        self.assertEqual(StageStatus.NO_WORK, result.status)


if __name__ == "__main__":
    unittest.main()
