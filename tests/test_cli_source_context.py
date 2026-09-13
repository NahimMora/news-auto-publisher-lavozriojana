from __future__ import annotations

import json
import os
import tempfile
import unittest
from io import StringIO
from unittest import mock


class CliSourceProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = mock.patch.dict(
            os.environ,
            {"LVR_DATA_DIR": self.temp.name, "LVR_LOGS_DIR": os.path.join(self.temp.name, "logs")},
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_unknown_source_returns_error_exit_code(self):
        import cli

        with mock.patch("sys.stdout", new=StringIO()):
            exit_code = cli.main(["source-probe", "--source", "no_existe", "--json"])
        self.assertEqual(exit_code, 1)

    def test_known_source_probe_reports_json(self):
        import cli
        from sources.sync import SyncReport

        fake_report = SyncReport(
            source_id="mpf_larioja", reachable=True, strategy="RSS", http_status=200, items_found=3
        )
        buffer = StringIO()
        with mock.patch("sources.probe.sync_source", return_value=fake_report), mock.patch(
            "sys.stdout", new=buffer
        ):
            exit_code = cli.main(["source-probe", "--source", "mpf_larioja", "--json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["source"], "mpf_larioja")
        self.assertEqual(payload["items_found"], 3)


class CliArchiveIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = mock.patch.dict(
            os.environ,
            {"LVR_DATA_DIR": self.temp.name, "LVR_LOGS_DIR": os.path.join(self.temp.name, "logs")},
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_rebuild_creates_empty_derived_database(self):
        import cli

        buffer = StringIO()
        with mock.patch("sys.stdout", new=buffer):
            exit_code = cli.main(["archive-index", "rebuild"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "success")

    def test_stats_reports_empty_summary_on_fresh_index(self):
        import cli

        buffer = StringIO()
        with mock.patch("sys.stdout", new=buffer):
            exit_code = cli.main(["archive-index", "stats"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["editorial"]["articles_evaluated"], 0)
        self.assertEqual(payload["sources"], [])

    def test_backfill_cms_without_webapp_base_url_reports_error_exit_code(self):
        import cli

        with mock.patch.dict(os.environ, {"WEBAPP_BASE_URL": ""}, clear=False):
            buffer = StringIO()
            with mock.patch("sys.stdout", new=buffer):
                exit_code = cli.main(["archive-index", "backfill-cms"])
        self.assertEqual(exit_code, 2)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["errors"])


if __name__ == "__main__":
    unittest.main()
