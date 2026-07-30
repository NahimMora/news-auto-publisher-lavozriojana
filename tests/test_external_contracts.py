from __future__ import annotations

import logging
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace
from unittest import mock

import requests


class FakeResponse:
    def __init__(self, status_code, payload=None, text="", headers=None, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._payload


class CmsContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = mock.patch.dict(
            os.environ,
            {
                "LVR_DATA_DIR": self.temp.name,
                "LVR_LOGS_DIR": os.path.join(self.temp.name, "logs"),
                "JSON_BACKUP_ENABLED": "false",
                "WEBAPP_BASE_URL": "https://cms.example.com",
                "PRIVATE_API_KEY": "test-key-not-production",
                "WEBAPP_REQUEST_RETRIES": "1",
                "WEBAPP_RETRY_SLEEP_SECONDS": "0",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(logging.shutdown)

    def _call(self, response):
        from pipeline.node_webapp import publisher

        with mock.patch.object(publisher.requests, "post", return_value=response):
            return publisher.post_payload_detailed({"title": "Nota"})

    def test_200_and_201_require_ok_true(self):
        for status in (200, 201):
            with self.subTest(status=status):
                result = self._call(
                    FakeResponse(
                        status,
                        {"ok": True, "data": {"id": "post-1", "slug": "nota"}},
                    )
                )
                self.assertTrue(result.ok)
                self.assertEqual("post-1", result.external_id)

        result = self._call(FakeResponse(200, {"ok": False, "error": "rejected"}))
        self.assertFalse(result.ok)
        self.assertEqual("application_rejected", result.error_type)

    def test_400_401_500_and_non_json_are_typed(self):
        cases = [
            (FakeResponse(400, {"error": "bad"}, text="bad"), "request_rejected"),
            (FakeResponse(401, {"error": "unauthorized"}), "invalid_credential"),
            (FakeResponse(500, {"error": "server"}, text="server"), "server_error"),
            (FakeResponse(200, text="<html>", json_error=True), "invalid_response"),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected):
                result = self._call(response)
                self.assertFalse(result.ok)
                self.assertEqual(expected, result.error_type)

    def test_409_is_idempotent_only_with_existing_publication_evidence(self):
        with_evidence = self._call(
            FakeResponse(
                409,
                {"ok": False, "data": {"id": "existing", "url": "https://cms.example.com/n/existing"}},
            )
        )
        without_evidence = self._call(FakeResponse(409, {"ok": False, "error": "conflict"}))

        self.assertTrue(with_evidence.ok)
        self.assertTrue(with_evidence.deduplicated)
        self.assertFalse(without_evidence.ok)
        self.assertEqual("conflict_without_evidence", without_evidence.error_type)

    def test_concurrent_retries_share_external_id_and_create_once(self):
        from pipeline.node_webapp import publisher

        created: dict[str, str] = {}
        guard = Lock()

        def fake_cms(_endpoint, *, json, headers, timeout):
            del headers, timeout
            external_id = json["metadata"]["externalId"]
            with guard:
                if external_id in created:
                    post_id = created[external_id]
                    return FakeResponse(
                        409,
                        {
                            "ok": False,
                            "data": {
                                "id": post_id,
                                "url": f"https://cms.example.com/noticias/{post_id}",
                            },
                        },
                    )
                post_id = f"post-{len(created) + 1}"
                created[external_id] = post_id
                return FakeResponse(
                    201,
                    {
                        "ok": True,
                        "data": {
                            "id": post_id,
                            "url": f"https://cms.example.com/noticias/{post_id}",
                        },
                    },
                )

        payload = {"title": "Nota", "metadata": {"externalId": "stable-news-id"}}
        with mock.patch.object(publisher.requests, "post", side_effect=fake_cms):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(
                    executor.map(
                        publisher.post_payload_detailed,
                        [payload, dict(payload)],
                    )
                )

        self.assertEqual(1, len(created))
        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(1, sum(result.deduplicated for result in results))
        self.assertEqual({"post-1"}, {result.external_id for result in results})

    def test_429_exposes_retry_time(self):
        result = self._call(
            FakeResponse(
                429,
                {"error": "rate"},
                headers={"Retry-After": "120"},
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual("rate_limit", result.error_type)
        self.assertTrue(result.retryable)
        self.assertIsNotNone(result.next_retry_at)

    def test_network_error_is_retryable_and_typed(self):
        from pipeline.node_webapp import publisher

        with mock.patch.object(
            publisher.requests,
            "post",
            side_effect=requests.Timeout("timeout"),
        ):
            result = publisher.post_payload_detailed({"title": "Nota"})

        self.assertFalse(result.ok)
        self.assertTrue(result.retryable)
        self.assertEqual("network_error", result.error_type)

    def test_publish_is_not_completed_without_external_id_or_public_url(self):
        from pipeline.node_webapp import publisher
        from utils.operation_result import OperationResult
        from utils.stage_result import StageStatus

        editorial = SimpleNamespace(
            title="Nota",
            quality_score=0.95,
            fallback_used=False,
            tags=[],
        )
        media = SimpleNamespace(ok=True, warnings=[])
        with mock.patch.object(publisher, "prepare_editorial", return_value=editorial), mock.patch.object(
            publisher, "prepare_media", return_value=media
        ), mock.patch.object(publisher, "build_post_payload", return_value={"title": "Nota"}), mock.patch.object(
            publisher,
            "post_payload_detailed",
            return_value=OperationResult(
                StageStatus.SUCCESS,
                response={"ok": True},
            ),
        ):
            result = publisher.publish_one_detailed(
                {
                    "titulo": "Nota con contenido válido",
                    "seccion": "sociedad",
                    "parrafos": ["Contenido verificable de la noticia."],
                }
            )

        self.assertFalse(result["published"])
        self.assertEqual("missing_publication_evidence", result["error"])

    def test_public_url_without_post_id_is_degraded_when_flags_need_tracking(self):
        from pipeline.node_webapp import publisher
        from pipeline.node_webapp import editorial_flags
        from utils.operation_result import OperationResult
        from utils.stage_result import StageStatus

        editorial = SimpleNamespace(
            title="Nota",
            quality_score=0.95,
            fallback_used=False,
            tags=[],
        )
        media = SimpleNamespace(ok=True, warnings=[])
        public_url = "https://lavozriojana.example/nota"
        with mock.patch.object(
            publisher,
            "prepare_editorial",
            return_value=editorial,
        ), mock.patch.object(
            publisher,
            "prepare_media",
            return_value=media,
        ), mock.patch.object(
            publisher,
            "build_post_payload",
            return_value={"title": "Nota"},
        ), mock.patch.object(
            publisher,
            "post_payload_detailed",
            return_value=OperationResult(
                StageStatus.SUCCESS,
                public_url=public_url,
                response={"ok": True, "url": public_url},
            ),
        ), mock.patch.object(
            editorial_flags,
            "detect_breaking",
            return_value=False,
        ), mock.patch.object(
            editorial_flags,
            "detect_featured",
            return_value=True,
        ), mock.patch.object(
            publisher,
            "sync_meta_web_link",
            return_value=public_url,
        ), mock.patch.object(
            publisher,
            "_record_published_history",
        ), mock.patch.object(
            publisher,
            "record_queue_event",
        ):
            result = publisher.publish_one_detailed(
                {
                    "titulo": "Nota con contenido válido",
                    "seccion": "sociedad",
                    "parrafos": ["Contenido verificable de la noticia."],
                }
            )

        self.assertTrue(result["published"])
        self.assertTrue(result["degraded"])
        self.assertEqual(
            "editorial_flag_reconciliation_required",
            result["degraded_reason"],
        )

class EditorialFlagContractTests(unittest.TestCase):
    def test_failed_clear_is_persisted_for_reconciliation(self):
        import json
        import tempfile
        from pathlib import Path
        from pipeline.node_webapp import editorial_flags

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "flags.json"
            path.write_text(
                json.dumps(
                    {
                        "breaking": {"post_id": "old"},
                        "featured": None,
                        "reconciliation_required": [],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(editorial_flags, "FLAGS_PATH", str(path)), mock.patch.object(
                editorial_flags, "_patch_post", return_value=False
            ):
                errors = editorial_flags.reconcile_after_publish(
                    post_id="new",
                    is_breaking=True,
                    is_featured=False,
                )
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["breaking"]["post_id"], "new")
        self.assertEqual(len(saved["reconciliation_required"]), 1)
        self.assertIn("old", errors[0])


if __name__ == "__main__":
    unittest.main()
