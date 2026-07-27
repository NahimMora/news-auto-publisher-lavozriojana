from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


class FacebookReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.queue = self.data / "social.json"
        self.posted = self.data / "fb_posted.json"
        self.events = self.data / "events.json"
        self.now = 2_000_000
        self.env = {
            "LVR_DATA_DIR": str(self.data),
            "LVR_LOGS_DIR": str(self.root / "logs"),
            "LVR_BACKUP_DIR": str(self.root / "backups"),
            "LVR_QUARANTINE_DIR": str(self.root / "quarantine"),
            "LVR_QUEUE_EVENTS_PATH": str(self.events),
            "SOCIAL_QUEUE_PATH": str(self.queue),
            "FB_POSTED_PATH": str(self.posted),
            "SOCIAL_TTL_HOURS": "48",
            "JSON_BACKUP_ENABLED": "false",
        }
        self.patch = mock.patch.dict(os.environ, self.env, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def _write_queue(self):
        from utils.file_manager import save_json

        items = [
            {
                "dedup_key": "published",
                "titulo": "Publicada",
                "web_url": "https://example.com/publicada",
                "facebook_evidence": {"external_id": "fb-1"},
                "social_queued_at": self.now,
            },
            {
                "dedup_key": "published",
                "titulo": "Duplicada",
                "web_url": "https://example.com/duplicada",
                "social_queued_at": self.now,
            },
            {
                "dedup_key": "expired",
                "titulo": "Expirada",
                "web_url": "https://example.com/expirada",
                "social_queued_at": self.now - 49 * 3600,
            },
            {
                "dedup_key": "ambiguous",
                "titulo": "Ambigua",
                "web_url": "https://example.com/ambigua",
                "facebook_done": True,
                "facebook_state": "completed",
                "social_queued_at": self.now,
            },
            {"titulo": "Sin identidad", "web_url": "https://example.com/invalid"},
            {
                "dedup_key": "missing-web",
                "titulo": "Sin URL web",
                "social_queued_at": self.now,
            },
            {
                "dedup_key": "valid",
                "titulo": "Pendiente válida",
                "web_url": "https://example.com/valid",
                "social_queued_at": self.now,
            },
        ]
        save_json(str(self.queue), items)
        save_json(str(self.posted), {"posted": {}})
        return items

    def test_report_only_classifies_without_modifying_queue(self):
        from utils.facebook_reconcile import build_facebook_report

        self._write_queue()
        before = self.queue.read_bytes()
        report = build_facebook_report(self.env, now=self.now, verify_meta=False)
        after = self.queue.read_bytes()

        self.assertEqual(before, after)
        self.assertTrue(report["report_only"])
        self.assertFalse(report["modified_queue"])
        self.assertEqual(1, report["counts"]["already_published"])
        self.assertEqual(1, report["counts"]["duplicate"])
        self.assertEqual(1, report["counts"]["expired"])
        self.assertEqual(1, report["counts"]["ambiguous"])
        self.assertEqual(1, report["counts"]["invalid"])
        self.assertEqual(1, report["counts"]["blocked_missing_web_url"])
        self.assertEqual(1, report["counts"]["pending_valid"])

    def test_title_similarity_alone_does_not_mark_published(self):
        from utils.facebook_reconcile import build_facebook_report
        from utils.file_manager import save_json

        save_json(
            str(self.queue),
            [
                {
                    "dedup_key": "one",
                    "titulo": "El mismo título",
                    "web_url": "https://example.com/one",
                    "social_queued_at": self.now,
                },
                {
                    "dedup_key": "two",
                    "titulo": "El mismo título",
                    "web_url": "https://example.com/two",
                    "social_queued_at": self.now,
                },
            ],
        )
        save_json(str(self.posted), {"posted": {}})
        report = build_facebook_report(self.env, now=self.now, verify_meta=False)

        self.assertEqual(2, report["counts"]["pending_valid"])
        self.assertEqual(0, report["counts"]["already_published"])

    def test_explicit_expired_with_done_flag_is_not_ambiguous(self):
        from utils.facebook_reconcile import build_facebook_report
        from utils.file_manager import save_json

        save_json(
            str(self.queue),
            [
                {
                    "dedup_key": "expired-done",
                    "titulo": "Expirada por corte",
                    "fecha": "2026-07-26",
                    "facebook_state": "expired",
                    "facebook_done": True,
                    "facebook_reason": "operator_cutover_before_date",
                    "social_queued_at": self.now,
                }
            ],
        )
        save_json(str(self.posted), {"posted": {}})

        report = build_facebook_report(self.env, now=self.now, verify_meta=False)

        self.assertEqual(1, report["counts"]["expired"])
        self.assertEqual(0, report["counts"]["ambiguous"])

    def test_apply_requires_matching_report_and_only_explicit_decisions(self):
        from utils.facebook_reconcile import (
            apply_facebook_decisions,
            build_facebook_report,
        )
        from utils.file_manager import load_json

        original = self._write_queue()
        report = build_facebook_report(self.env, now=self.now, verify_meta=False)
        decision_file = self.root / "decisions.json"
        decision_file.write_text(
            json.dumps(
                {
                    "report_id": report["report_id"],
                    "decisions": [
                        {
                            "item_id": "valid",
                            "action": "mark_published",
                            "external_id": "fb-approved",
                            "public_url": "https://facebook.com/fb-approved",
                            "reason": "ID verificado por operador",
                        },
                        {
                            "item_id": "ambiguous",
                            "action": "keep_dead_letter",
                            "reason": "Resultado externo no verificable",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        applied = apply_facebook_decisions(decision_file, self.env, now=self.now)
        queue = load_json(str(self.queue), [], expected_type=list)

        self.assertEqual(2, applied["applied"])
        by_key = {item.get("dedup_key"): item for item in queue}
        self.assertEqual("completed", by_key["valid"]["facebook_state"])
        self.assertEqual(
            "fb-approved",
            by_key["valid"]["facebook_evidence"]["external_id"],
        )
        self.assertEqual("dead_letter", by_key["ambiguous"]["facebook_state"])
        self.assertEqual(original[2], queue[2], "La entrada sin decisión debe quedar intacta")
        self.assertTrue(self.events.is_file())

    def test_apply_rejects_stale_report_unknown_item_and_published_without_id(self):
        from utils.facebook_reconcile import (
            apply_facebook_decisions,
            build_facebook_report,
        )

        self._write_queue()
        report = build_facebook_report(self.env, now=self.now, verify_meta=False)
        cases = [
            {"report_id": "stale", "decisions": []},
            {
                "report_id": report["report_id"],
                "decisions": [{"item_id": "outside", "action": "keep_pending"}],
            },
            {
                "report_id": report["report_id"],
                "decisions": [{"item_id": "valid", "action": "mark_published"}],
            },
        ]
        for index, payload in enumerate(cases):
            with self.subTest(index=index):
                path = self.root / f"invalid-{index}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    apply_facebook_decisions(path, self.env, now=self.now)

    def test_meta_401_leaves_external_evidence_classified_without_false_success(self):
        from utils.facebook_reconcile import build_facebook_report

        self._write_queue()
        env = {**self.env, "FB_PAGE_ACCESS_TOKEN": "test"}
        response = mock.Mock(status_code=401)
        report = build_facebook_report(
            env,
            now=self.now,
            verify_meta=True,
            http_get=mock.Mock(return_value=response),
        )
        published = report["items"][0]

        self.assertEqual("already_published", published["classification"])
        self.assertEqual("blocked", published["evidence"]["meta_verification"])
        self.assertEqual(1, report["meta_verification"]["blocked"])


if __name__ == "__main__":
    unittest.main()
