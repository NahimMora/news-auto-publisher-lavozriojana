"""LVR-NOTE-0001: mediciones semanales de redes."""
from __future__ import annotations

import tempfile
import time
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from utils import kpis
from utils.file_manager import save_json


class KpiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name, value in (
            ("KPI_DAILY_PATH", str(root / "kpi_daily.json")),
            ("MEDIA_INSIGHTS_PATH", str(root / "ig_media_insights.json")),
        ):
            patcher = mock.patch.object(kpis, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(kpis, "data_dir", return_value=root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = root

    def test_followers_snapshot_once_per_day_and_never_invents_values(self):
        calls = []
        fetchers = {"instagram": lambda: calls.append("ig") or 1200, "facebook": lambda: None}
        self.assertEqual({"instagram": 1200}, kpis.record_followers_snapshot(fetchers, today="2026-10-05"))
        self.assertEqual({}, kpis.record_followers_snapshot(fetchers, today="2026-10-05"))
        self.assertEqual(["ig"], calls)

    def test_weekly_report(self):
        for day, value in (("2026-09-28", 1000), ("2026-10-01", 1040), ("2026-10-04", 1100)):
            kpis.record_followers_snapshot({"instagram": lambda v=value: v}, today=day)
        posted_ts = int(datetime(2026, 9, 30, 12).timestamp())
        kpis.record_media_insights(
            [
                {"media_id": "m1", "posted_at": posted_ts, "reach": 300, "interactions": 6},
                {"media_id": "m2", "posted_at": posted_ts, "reach": 100, "interactions": 2},
            ],
            now=posted_ts,
        )
        save_json(str(self.root / "ig_posted.json"), {"posted": {"a": {"posted_at": posted_ts, "external_id": "m1"}}})
        save_json(str(self.root / "fb_posted.json"), {"posted": {}})

        week = kpis.weekly_report(1, today=date(2026, 10, 2))[0]

        self.assertEqual("2026-09-28", week["week_start"])
        self.assertEqual({"start": 1000, "end": 1100, "delta": 100}, week["followers"]["instagram"])
        self.assertNotIn("facebook", week["followers"])
        self.assertEqual({"instagram": 1, "facebook": 0}, week["posts"])
        self.assertEqual(200.0, week["instagram"]["avg_reach"])
        self.assertEqual(0.02, week["instagram"]["engagement_rate"])

    def test_old_media_is_pruned(self):
        now = time.time()
        kpis.record_media_insights([{"media_id": "old", "posted_at": now - 200 * 86400, "reach": 1}], now=now)
        report = kpis.weekly_report(1)
        self.assertEqual(0, report[0]["instagram"]["measured_posts"])


if __name__ == "__main__":
    unittest.main()
