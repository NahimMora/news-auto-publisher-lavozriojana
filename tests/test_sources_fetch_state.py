import tempfile
import unittest
from pathlib import Path

from sources import fetch_state


class FetchStateTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "fetch_state_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_never_fetched_source_is_always_due(self):
        self.assertTrue(fetch_state.is_due("nunca_sincronizada", poll_ttl=3600, path=self.db_path))
        self.assertIsNone(fetch_state.seconds_since_last_fetch("nunca_sincronizada", path=self.db_path))

    def test_recently_fetched_source_is_not_due(self):
        fetch_state.set_fetch_state("x", etag="abc", path=self.db_path)
        self.assertFalse(fetch_state.is_due("x", poll_ttl=3600, path=self.db_path))

    def test_get_state_roundtrip(self):
        fetch_state.set_fetch_state("x", etag="abc", last_modified="Mon, 01 Sep 2026", path=self.db_path)
        state = fetch_state.get_fetch_state("x", path=self.db_path)
        self.assertEqual(state["etag"], "abc")
        self.assertEqual(state["last_modified"], "Mon, 01 Sep 2026")

    def test_zero_poll_ttl_source_is_always_due_after_any_elapsed_time(self):
        fetch_state.set_fetch_state("x", path=self.db_path)
        self.assertTrue(fetch_state.is_due("x", poll_ttl=0, path=self.db_path))


if __name__ == "__main__":
    unittest.main()
