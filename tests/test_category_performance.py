from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import category_performance as cp


class LoadCategoryPerformanceTests(unittest.TestCase):
    def test_returns_empty_dict_when_promotion_disabled(self):
        with patch.dict(os.environ, {"IG_STATS_PROMOTION_ENABLED": "false"}, clear=False):
            self.assertEqual({}, cp.load_category_performance())

    def test_loads_snapshot_when_enabled_and_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "perf.json"
            snapshot = {"overall": {"engagement_rate": 0.03}, "categories": {}}
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            with patch.dict(os.environ, {"IG_STATS_PROMOTION_ENABLED": "true"}, clear=False), patch.object(
                cp, "PERFORMANCE_PATH", str(path)
            ):
                self.assertEqual(snapshot, cp.load_category_performance())

    def test_missing_file_returns_empty_dict_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "does_not_exist.json"
            with patch.dict(os.environ, {"IG_STATS_PROMOTION_ENABLED": "true"}, clear=False), patch.object(
                cp, "PERFORMANCE_PATH", str(path)
            ):
                self.assertEqual({}, cp.load_category_performance())


class IsStrongPerformingCategoryTests(unittest.TestCase):
    def test_empty_performance_is_never_strong(self):
        self.assertFalse(cp.is_strong_performing_category("politica", {}))

    def test_meets_threshold_with_enough_sample(self):
        performance = {
            "overall": {"engagement_rate": 0.02},
            "categories": {"politica": {"engagement_rate": 0.03, "sample_size": 10}},
        }
        with patch.object(cp, "MIN_SAMPLE_SIZE", 5), patch.object(cp, "PROMOTION_THRESHOLD_RATIO", 1.0):
            self.assertTrue(cp.is_strong_performing_category("politica", performance))

    def test_below_threshold_is_not_strong(self):
        performance = {
            "overall": {"engagement_rate": 0.05},
            "categories": {"politica": {"engagement_rate": 0.01, "sample_size": 10}},
        }
        self.assertFalse(cp.is_strong_performing_category("politica", performance))

    def test_below_min_sample_size_is_not_strong_even_if_rate_is_high(self):
        performance = {
            "overall": {"engagement_rate": 0.02},
            "categories": {"politica": {"engagement_rate": 0.9, "sample_size": 1}},
        }
        with patch.object(cp, "MIN_SAMPLE_SIZE", 5):
            self.assertFalse(cp.is_strong_performing_category("politica", performance))

    def test_unknown_category_is_not_strong(self):
        performance = {
            "overall": {"engagement_rate": 0.02},
            "categories": {"deportes": {"engagement_rate": 0.05, "sample_size": 10}},
        }
        self.assertFalse(cp.is_strong_performing_category("politica", performance))

    def test_zero_overall_rate_avoids_division_by_zero(self):
        performance = {
            "overall": {"engagement_rate": 0},
            "categories": {"politica": {"engagement_rate": 0.05, "sample_size": 10}},
        }
        self.assertFalse(cp.is_strong_performing_category("politica", performance))


if __name__ == "__main__":
    unittest.main()
