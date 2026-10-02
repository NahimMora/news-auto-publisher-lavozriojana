"""Regresión del bucle de reactivación de la cola social (2026-09/10).

En producción, ``enqueue`` reactivaba ítems ``expired``; el TTL los volvía a
vencer y el bootstrap los reactivaba en cada corrida. Como además cada
``enqueue`` reescribía la cola completa, el bootstrap de Facebook/Instagram
superaba el timeout de la etapa y nunca llegaba a publicar.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from utils import social_queue
from utils.file_manager import load_json, save_json


class _QueueTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue_path = str(self.root / "social.json")
        self.events_path = str(self.root / "events.json")
        patches = [
            mock.patch.object(social_queue, "QUEUE_PATH", self.queue_path),
            mock.patch.dict(
                os.environ,
                {
                    "LVR_QUEUE_EVENTS_PATH": self.events_path,
                    "JSON_BACKUP_ENABLED": "false",
                    "SOCIAL_BOOTSTRAP_NOT_BEFORE_TS": "",
                },
                clear=False,
            ),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _queue(self) -> list[dict]:
        return load_json(self.queue_path, [], expected_type=list)


class EnqueueReactivationTests(_QueueTestCase):
    def test_expired_item_is_not_reactivated(self):
        save_json(
            self.queue_path,
            [
                {
                    "dedup_key": "link:viejo",
                    "titulo": "Nota vieja",
                    "instagram_state": "expired",
                    "instagram_done": True,
                    "instagram_done_at": 100,
                }
            ],
        )

        social_queue.enqueue({"dedup_key": "link:viejo", "titulo": "Nota vieja"}, platform="instagram")

        self.assertEqual("expired", self._queue()[0]["instagram_state"])

    def test_ttl_then_bootstrap_does_not_loop(self):
        old = int(time.time()) - (social_queue.SOCIAL_TTL_HOURS + 1) * 3600
        noticia = {"dedup_key": "link:loop", "titulo": "Nota en bucle"}
        social_queue.enqueue(noticia, platform="instagram")
        queue = self._queue()
        queue[0]["social_queued_at"] = old
        save_json(self.queue_path, queue)

        self.assertEqual([], social_queue.get_pending("instagram"))
        social_queue.enqueue(noticia, platform="instagram")

        self.assertEqual("expired", self._queue()[0]["instagram_state"])
        self.assertEqual([], social_queue.get_pending("instagram"))

    def test_pending_item_is_left_untouched(self):
        save_json(
            self.queue_path,
            [
                {
                    "dedup_key": "link:p",
                    "titulo": "Pendiente",
                    "facebook_state": "pending",
                    "facebook_updated_at": 123,
                }
            ],
        )

        counts = social_queue.enqueue_many(
            [{"dedup_key": "link:p", "titulo": "Pendiente"}], platform="facebook"
        )

        self.assertEqual(1, counts["unchanged"])
        self.assertEqual(123, self._queue()[0]["facebook_updated_at"])

    def test_editorial_exclusion_is_reactivated_but_operator_cutover_is_not(self):
        save_json(
            self.queue_path,
            [
                {
                    "dedup_key": "link:editorial",
                    "titulo": "Excluida por el editor",
                    "instagram_state": "excluded",
                    "instagram_reason": "editorial_override_to_candidate:manual",
                },
                {
                    "dedup_key": "link:operador",
                    "titulo": "Excluida por el corte",
                    "instagram_state": "excluded",
                    "instagram_reason": "operator_social_reset",
                },
            ],
        )

        counts = social_queue.enqueue_many(
            [
                {"dedup_key": "link:editorial", "titulo": "Excluida por el editor"},
                {"dedup_key": "link:operador", "titulo": "Excluida por el corte"},
            ],
            platform="instagram",
        )

        states = {item["dedup_key"]: item["instagram_state"] for item in self._queue()}
        self.assertEqual("pending", states["link:editorial"])
        self.assertEqual("excluded", states["link:operador"])
        self.assertEqual(1, counts["reactivated"])
        self.assertEqual(1, counts["unchanged"])

    def test_batch_uses_a_single_queue_write(self):
        noticias = [
            {"dedup_key": f"link:{index}", "titulo": f"Titular distinto número {index} {'x' * index}"}
            for index in range(40)
        ]
        with mock.patch.object(
            social_queue, "update_json", wraps=social_queue.update_json
        ) as update:
            counts = social_queue.enqueue_many(noticias, platform="facebook")

        self.assertEqual(1, update.call_count)
        self.assertEqual(40, counts["enqueued"] + counts["duplicate"])
        self.assertEqual(counts["enqueued"], len(self._queue()))

    def test_empty_batch_does_not_touch_the_queue(self):
        with mock.patch.object(social_queue, "update_json") as update:
            social_queue.enqueue_many([], platform="facebook")
        update.assert_not_called()


class BootstrapAgeGateTests(_QueueTestCase):
    def test_too_old_by_ttl(self):
        now = 1_000_000
        old = now - (social_queue.SOCIAL_TTL_HOURS + 1) * 3600
        self.assertTrue(social_queue.is_too_old_for_bootstrap({"queued_at": old}, now=now))
        self.assertFalse(social_queue.is_too_old_for_bootstrap({"queued_at": now - 60}, now=now))

    def test_unknown_timestamp_is_not_treated_as_old(self):
        self.assertFalse(social_queue.is_too_old_for_bootstrap({}))
        self.assertFalse(social_queue.is_too_old_for_bootstrap({"queued_at": "x"}))

    def test_operator_cutoff(self):
        now = int(time.time())
        with mock.patch.dict(os.environ, {"SOCIAL_BOOTSTRAP_NOT_BEFORE_TS": str(now - 10)}):
            self.assertTrue(social_queue.is_too_old_for_bootstrap({"queued_at": now - 60}))
            self.assertFalse(social_queue.is_too_old_for_bootstrap({"queued_at": now - 5}))

    def test_invalid_cutoff_is_ignored(self):
        with mock.patch.dict(os.environ, {"SOCIAL_BOOTSTRAP_NOT_BEFORE_TS": "ayer"}):
            self.assertEqual(0, social_queue.bootstrap_not_before())


class FacebookBootstrapTests(unittest.TestCase):
    def test_skips_old_news_and_enqueues_once(self):
        from meta import run_fb

        now = int(time.time())
        fresh = {
            "dedup_key": "link:fresh",
            "web_url": "https://lavozriojana.com/fresh",
            "selected_for_publish": True,
            "queued_at": now - 60,
        }
        old = {
            "dedup_key": "link:old",
            "web_url": "https://lavozriojana.com/old",
            "selected_for_publish": True,
            "queued_at": now - 30 * 24 * 3600,
        }
        with mock.patch.object(run_fb, "load_json", return_value=[fresh, old]), mock.patch.object(
            run_fb, "enqueue_many"
        ) as enqueue_many, mock.patch.dict(
            os.environ, {"SOCIAL_BOOTSTRAP_NOT_BEFORE_TS": ""}, clear=False
        ):
            included = run_fb._bootstrap_queue()

        self.assertEqual(1, included)
        enqueue_many.assert_called_once_with([fresh], platform="facebook")


class InstagramManualPromotionCutoffTests(unittest.TestCase):
    def _candidate(self, identity: str, promoted_ts: int) -> dict:
        return {
            "identity": identity,
            "noticia": {"dedup_key": identity, "titulo": identity, "web_url": "https://x"},
            "manual_override_history": [
                {"from": "candidate", "to": "automatic", "ts": promoted_ts}
            ],
        }

    def test_promotions_before_cutoff_are_not_drained(self):
        from meta import run_ig

        cutoff = int(time.time()) - 100
        candidates = [
            self._candidate("link:antes", cutoff - 1),
            self._candidate("link:despues", cutoff + 1),
        ]
        with mock.patch.dict(
            os.environ,
            {"SOCIAL_BOOTSTRAP_NOT_BEFORE_TS": str(cutoff), "IG_MANUAL_OVERRIDE_MAX_PER_RUN": "3"},
            clear=False,
        ), mock.patch.object(run_ig, "load_json", return_value=[]), mock.patch.object(
            run_ig, "manual_automatic_candidates", return_value=candidates
        ), mock.patch.object(run_ig, "enqueue_many") as enqueue_many:
            included, *_rest = run_ig._bootstrap_queue()

        self.assertEqual(1, included)
        batch = enqueue_many.call_args.args[0]
        self.assertEqual(["link:despues"], [item["dedup_key"] for item in batch])

    def test_without_cutoff_manual_promotions_keep_working(self):
        from meta import run_ig

        candidates = [self._candidate("link:vieja", 1)]
        with mock.patch.dict(
            os.environ, {"SOCIAL_BOOTSTRAP_NOT_BEFORE_TS": ""}, clear=False
        ), mock.patch.object(run_ig, "load_json", return_value=[]), mock.patch.object(
            run_ig, "manual_automatic_candidates", return_value=candidates
        ), mock.patch.object(run_ig, "enqueue_many") as enqueue_many:
            included, *_rest = run_ig._bootstrap_queue()

        self.assertEqual(1, included)
        enqueue_many.assert_called_once()


class SocialResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {
            "LVR_QUEUE_EVENTS_PATH": str(self.root / "events.json"),
            "SOCIAL_QUEUE_PATH": str(self.root / "social.json"),
            "WEB_QUEUE_PATH": str(self.root / "web.json"),
            "META_QUEUE_PATH": str(self.root / "meta.json"),
            "LVR_QUEUE_CUTOVER_ARCHIVE_PATH": str(self.root / "archive.json"),
            "JSON_BACKUP_ENABLED": "false",
        }
        patcher = mock.patch.dict(os.environ, self.env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        from utils import queue_cutover

        self.queue_cutover = queue_cutover
        save_json(
            self.env["SOCIAL_QUEUE_PATH"],
            [
                {"dedup_key": "link:pend", "facebook_state": "pending", "instagram_state": "pending"},
                {
                    "dedup_key": "link:proc",
                    "facebook_state": "processing",
                    "instagram_state": "completed",
                    "instagram_done": True,
                    "instagram_done_at": 5,
                    "instagram_evidence": {"external_id": "ig-1"},
                },
                {
                    "dedup_key": "link:edit",
                    "facebook_state": "expired",
                    "instagram_state": "excluded",
                    "instagram_reason": "editorial_override_to_candidate:x",
                },
            ],
        )
        save_json(self.env["WEB_QUEUE_PATH"], [{"web_queue_key": "w1"}])

    def test_report_only_does_not_modify(self):
        before = load_json(self.env["SOCIAL_QUEUE_PATH"], [], expected_type=list)
        report = self.queue_cutover.build_social_reset_report()
        after = load_json(self.env["SOCIAL_QUEUE_PATH"], [], expected_type=list)

        self.assertEqual(before, after)
        self.assertFalse(report["modified_queues"])
        self.assertEqual(1, report["transitions"]["facebook"]["to_excluded"])
        self.assertEqual(1, report["transitions"]["facebook"]["to_dead_letter"])
        self.assertEqual(2, report["transitions"]["instagram"]["to_excluded"])

    def test_apply_leaves_no_pending_and_keeps_evidence(self):
        result = self.queue_cutover.apply_social_reset(now=1_800_000_000)

        self.assertEqual(1_800_000_000, result["cutoff_ts"])
        items = {
            item["dedup_key"]: item
            for item in load_json(self.env["SOCIAL_QUEUE_PATH"], [], expected_type=list)
        }
        self.assertEqual("excluded", items["link:pend"]["facebook_state"])
        self.assertEqual("operator_social_reset", items["link:pend"]["facebook_reason"])
        self.assertEqual("dead_letter", items["link:proc"]["facebook_state"])
        self.assertEqual("completed", items["link:proc"]["instagram_state"])
        self.assertEqual({"external_id": "ig-1"}, items["link:proc"]["instagram_evidence"])
        self.assertEqual("expired", items["link:edit"]["facebook_state"])
        self.assertEqual("operator_social_reset", items["link:edit"]["instagram_reason"])
        # Web no se toca.
        self.assertEqual([{"web_queue_key": "w1"}], load_json(self.env["WEB_QUEUE_PATH"], []))

        events = load_json(self.env["LVR_QUEUE_EVENTS_PATH"], [], expected_type=list)
        self.assertEqual(4, sum(event["metadata"]["count"] for event in events))

        with mock.patch.object(social_queue, "QUEUE_PATH", self.env["SOCIAL_QUEUE_PATH"]):
            for platform in ("facebook", "instagram"):
                social_queue.enqueue_many(
                    [{"dedup_key": "link:pend"}, {"dedup_key": "link:edit"}],
                    platform=platform,
                )
                self.assertEqual([], social_queue.get_pending(platform))

    def test_apply_is_idempotent(self):
        self.queue_cutover.apply_social_reset(now=1)
        second = self.queue_cutover.apply_social_reset(now=2)
        self.assertEqual(0, second["social_states_excluded"])
        self.assertEqual(0, second["social_processing_dead_letter"])


if __name__ == "__main__":
    unittest.main()
