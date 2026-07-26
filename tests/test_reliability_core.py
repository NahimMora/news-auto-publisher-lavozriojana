from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


class StageResultContractTests(unittest.TestCase):
    def test_zero_of_nonzero_is_never_success(self):
        from utils.stage_result import StageStatus, result_from_counts

        result = result_from_counts(
            "facebook",
            received=10,
            selected=10,
            processed=10,
            succeeded=0,
            failed=10,
        )

        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertNotEqual(0, result.exit_code)

    def test_no_work_is_acceptable_and_exit_zero(self):
        from utils.stage_result import StageStatus, result_from_counts

        result = result_from_counts("scraper", received=0, selected=0)

        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertEqual(0, result.exit_code)

    def test_partial_batch_is_degraded(self):
        from utils.stage_result import StageStatus, result_from_counts

        result = result_from_counts(
            "instagram",
            received=5,
            selected=5,
            processed=5,
            succeeded=3,
            failed=2,
        )

        self.assertEqual(StageStatus.DEGRADED, result.status)
        self.assertEqual(2, result.exit_code)


class SafeJsonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "state.json"

    def test_truncated_json_is_quarantined_and_never_becomes_empty(self):
        from utils.file_manager import JsonCorruptionError, load_json

        self.path.write_text('[{"id": 1}', encoding="utf-8")

        with mock.patch.dict(
            os.environ,
            {"LVR_QUARANTINE_DIR": str(self.root / "quarantine")},
            clear=False,
        ):
            with self.assertRaises(JsonCorruptionError):
                load_json(str(self.path), [])

        self.assertEqual('[{"id": 1}', self.path.read_text(encoding="utf-8"))
        quarantined = list((self.root / "quarantine").glob("state.json.*.corrupt"))
        self.assertEqual(1, len(quarantined))
        self.assertEqual(self.path.read_bytes(), quarantined[0].read_bytes())

    def test_concurrent_updates_do_not_lose_data(self):
        from utils.file_manager import save_json, update_json

        save_json(str(self.path), [])

        def append_item(value):
            def updater(items):
                items.append(value)
                return items

            update_json(str(self.path), updater, [])

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(append_item, range(100)))

        values = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(list(range(100)), sorted(values))

    def test_failed_replace_preserves_previous_state(self):
        from utils.file_manager import JsonWriteError, save_json

        save_json(str(self.path), [{"id": "original"}])
        with mock.patch("utils.file_manager.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(JsonWriteError):
                save_json(str(self.path), [{"id": "new"}])

        self.assertEqual([{"id": "original"}], json.loads(self.path.read_text(encoding="utf-8")))

    def test_permission_error_is_explicit(self):
        from utils.file_manager import JsonReadError, load_json

        self.path.write_text("[]", encoding="utf-8")
        original_open = open

        def denied(path, *args, **kwargs):
            if os.fspath(path) == os.fspath(self.path):
                raise PermissionError("denied")
            return original_open(path, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=denied):
            with self.assertRaises(JsonReadError):
                load_json(str(self.path), [])

    def test_backup_can_be_restored(self):
        from utils.file_manager import backup_json, load_json, restore_json, save_json

        save_json(str(self.path), [{"version": 1}])
        backup = backup_json(str(self.path), str(self.root / "backups"))
        save_json(str(self.path), [{"version": 2}])

        restore_json(backup, str(self.path))

        self.assertEqual([{"version": 1}], load_json(str(self.path), []))

    def test_old_lock_owned_by_live_process_is_not_stolen(self):
        from utils.file_manager import FileLock, JsonLockTimeout

        lock_path = Path(f"{self.path}.lock")
        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "created_at": time.time()}),
            encoding="utf-8",
        )
        old = time.time() - 3600
        os.utime(lock_path, (old, old))

        with self.assertRaises(JsonLockTimeout):
            FileLock(
                str(self.path),
                timeout=0.05,
                poll_interval=0.01,
                stale_seconds=1,
            ).acquire()

        self.assertTrue(lock_path.exists())

    def test_old_lock_from_dead_process_is_recovered(self):
        from utils.file_manager import FileLock

        lock_path = Path(f"{self.path}.lock")
        lock_path.write_text(
            json.dumps({"pid": 2147483647, "created_at": 1}),
            encoding="utf-8",
        )
        old = time.time() - 3600
        os.utime(lock_path, (old, old))

        with FileLock(
            str(self.path),
            timeout=0.5,
            poll_interval=0.01,
            stale_seconds=1,
        ):
            self.assertTrue(lock_path.exists())

        self.assertFalse(lock_path.exists())

    def test_multifile_partial_acquire_releases_previous_locks(self):
        from utils.file_manager import JsonLockTimeout, MultiFileLock

        first = self.root / "a.json"
        second = self.root / "b.json"
        second_lock = Path(f"{second}.lock")
        second_lock.write_text(
            json.dumps({"pid": os.getpid(), "created_at": time.time()}),
            encoding="utf-8",
        )

        with self.assertRaises(JsonLockTimeout):
            with MultiFileLock((str(first), str(second)), timeout=0.05):
                pass

        self.assertFalse(Path(f"{first}.lock").exists())
        self.assertTrue(second_lock.exists())

    def test_lock_metadata_write_failure_does_not_leave_orphan(self):
        from utils.file_manager import FileLock, JsonWriteError

        with mock.patch(
            "utils.file_manager.os.write",
            side_effect=OSError("disk write failed"),
        ):
            with self.assertRaises(JsonWriteError):
                FileLock(str(self.path), timeout=0.05).acquire()

        self.assertFalse(Path(f"{self.path}.lock").exists())


class DurableQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "legacy.json"
        self.state = self.root / "rewrite_state.json"

    def _items(self):
        return [
            {
                "titulo": f"Noticia {number}",
                "url": f"https://example.com/noticia-{number}",
            }
            for number in range(10)
        ]

    def test_interruption_after_third_recovers_all_exactly_once(self):
        from utils.durable_queue import DurableQueue
        from utils.file_manager import save_json

        save_json(str(self.source), self._items())
        queue = DurableQueue(str(self.state), "rewrite", max_attempts=3)
        self.assertEqual(10, queue.transfer_from_legacy(str(self.source)))

        completed_ids = []
        for _ in range(3):
            job = queue.claim_one()
            completed_ids.append(job["id"])
            queue.complete(job["id"])

        # Simula corte con un cuarto elemento ya reclamado.
        interrupted = queue.claim_one()
        self.assertIsNotNone(interrupted)

        restarted = DurableQueue(str(self.state), "rewrite", max_attempts=3)
        self.assertEqual(1, restarted.recover_processing())
        while True:
            job = restarted.claim_one()
            if not job:
                break
            completed_ids.append(job["id"])
            restarted.complete(job["id"])

        snapshot = restarted.snapshot()
        final_ids = [item["id"] for item in snapshot["completed"]]
        self.assertEqual(10, len(final_ids))
        self.assertEqual(10, len(set(final_ids)))
        self.assertEqual(10, len(set(completed_ids)))
        self.assertEqual([], snapshot["pending"])
        self.assertEqual([], snapshot["processing"])

    def test_concurrent_claims_are_unique(self):
        from utils.durable_queue import DurableQueue
        from utils.file_manager import save_json

        save_json(str(self.source), self._items())
        queue = DurableQueue(str(self.state), "rewrite")
        queue.transfer_from_legacy(str(self.source))
        claimed = []
        guard = threading.Lock()

        def worker():
            job = queue.claim_one()
            if job:
                with guard:
                    claimed.append(job["id"])

        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(lambda _: worker(), range(10)))

        self.assertEqual(10, len(claimed))
        self.assertEqual(10, len(set(claimed)))

    def test_repeated_failures_end_in_dead_letter(self):
        from utils.durable_queue import DurableQueue
        from utils.file_manager import save_json

        save_json(str(self.source), self._items()[:1])
        queue = DurableQueue(str(self.state), "rewrite", max_attempts=2)
        queue.transfer_from_legacy(str(self.source))

        first = queue.claim_one()
        queue.fail(first["id"], "openai_timeout", retryable=True)
        second = queue.claim_one()
        queue.fail(second["id"], "openai_timeout", retryable=True)

        snapshot = queue.snapshot()
        self.assertEqual([], snapshot["pending"])
        self.assertEqual(1, len(snapshot["dead_letter"]))
        self.assertEqual("openai_timeout", snapshot["dead_letter"][0]["last_error"])


class BootstrapTests(unittest.TestCase):
    def test_init_data_creates_a_valid_durable_rewrite_queue(self):
        from utils.durable_queue import DurableQueue

        with tempfile.TemporaryDirectory() as temp:
            env = {
                **os.environ,
                "LVR_DATA_DIR": str(Path(temp) / "data"),
            }
            completed = subprocess.run(
                [sys.executable, "init_data.py"],
                cwd=str(Path(__file__).resolve().parents[1]),
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            queue = DurableQueue(
                str(Path(env["LVR_DATA_DIR"]) / "rewrite_queue_state.json"),
                "rewrite",
            )
            state = queue.snapshot()
            for bucket in queue.BUCKETS:
                self.assertIsInstance(state[bucket], list)


if __name__ == "__main__":
    unittest.main()
