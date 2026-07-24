import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from botocore.exceptions import ClientError

from meta import fb_client, ig_client
from utils import r2_storage, social_queue
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FacebookContractTests(unittest.TestCase):
    def _news(self):
        return {
            "titulo": "Nota de prueba",
            "web_url": "https://lavozriojana.example/noticias/nota",
            "dedup_key": "link:fb-test",
        }

    def test_success_requires_external_id_and_persists_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "fb.json"
            with patch.object(fb_client, "PAGE_ID", "page"), patch.object(
                fb_client, "DISABLED_PAGE_IDS", set()
            ), patch.object(fb_client, "FB_STATE_PATH", str(state)), patch.object(
                fb_client, "get_page_token", return_value="token"
            ), patch.object(
                fb_client.requests,
                "post",
                return_value=FakeResponse(200, {"id": "page_123"}),
            ):
                result = fb_client.post_to_facebook_detailed(self._news())
            saved = json.loads(state.read_text(encoding="utf-8"))
        self.assertTrue(result.ok)
        self.assertEqual(result.external_id, "page_123")
        self.assertEqual(saved["posted"]["link:fb-test"]["external_id"], "page_123")

    def test_credential_rate_limit_server_and_network_are_typed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "fb.json"
            common = [
                patch.object(fb_client, "PAGE_ID", "page"),
                patch.object(fb_client, "DISABLED_PAGE_IDS", set()),
                patch.object(fb_client, "FB_STATE_PATH", str(state)),
                patch.object(fb_client, "get_page_token", return_value="token"),
            ]
            for manager in common:
                manager.start()
            try:
                with patch.object(
                    fb_client.requests,
                    "post",
                    return_value=FakeResponse(401, {"error": {"code": 190}}),
                ):
                    self.assertEqual(
                        fb_client.post_to_facebook_detailed(self._news()).error_type,
                        "invalid_credential",
                    )
                with patch.object(
                    fb_client.requests,
                    "post",
                    return_value=FakeResponse(429, {"error": {"code": 4}}),
                ):
                    limited = fb_client.post_to_facebook_detailed(self._news())
                self.assertEqual(limited.status, StageStatus.DEGRADED)
                self.assertGreater(limited.next_retry_at, time.time())

                state.write_text(
                    json.dumps({"posted": {}, "page_backoff": {}}),
                    encoding="utf-8",
                )
                with patch.object(
                    fb_client.requests,
                    "post",
                    return_value=FakeResponse(500, {"error": {"code": 2}}),
                ):
                    self.assertEqual(
                        fb_client.post_to_facebook_detailed(self._news()).error_type,
                        "server_error",
                    )
                with patch.object(
                    fb_client.requests,
                    "post",
                    side_effect=requests.Timeout("timeout"),
                ):
                    network = fb_client.post_to_facebook_detailed(self._news())
                self.assertEqual(network.error_type, "network_error")
                self.assertEqual(network.details["publication_outcome"], "unknown")
            finally:
                for manager in reversed(common):
                    manager.stop()


class InstagramContractTests(unittest.TestCase):
    def test_missing_r2_does_not_silently_use_original_image(self):
        from meta import ig_client

        with patch.object(ig_client.r2_storage, "is_configured", return_value=False):
            with patch.dict(
                os.environ,
                {"IG_ALLOW_ORIGINAL_IMAGE_FALLBACK": "false"},
                clear=False,
            ):
                result, public_url, key = ig_client._prepare_image(
                    {"imagen_url": "https://media.example.com/original.jpg"}
                )

        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("missing_r2_configuration", result.error_type)
        self.assertEqual("", public_url)
        self.assertIsNone(key)

    def _news(self):
        return {
            "titulo": "Nota de prueba",
            "imagen_url": "https://media.example/nota.jpg",
            "dedup_key": "link:ig-test",
        }

    def test_create_and_publish_require_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "ig.json"
            rate = Path(tmp) / "rate.json"
            with patch.object(ig_client, "IG_ACCOUNT_ID", "ig"), patch.object(
                ig_client, "IG_ACCESS_TOKEN", "token"
            ), patch.object(ig_client, "IG_STATE_PATH", str(state)), patch.object(
                ig_client, "IG_RATE_LIMIT_PATH", str(rate)
            ), patch.object(ig_client.r2_storage, "is_configured", return_value=False), patch.dict(
                os.environ,
                {
                    "IG_IMAGE_CONTAINER_WAIT_SECONDS": "0",
                    "IG_ALLOW_ORIGINAL_IMAGE_FALLBACK": "true",
                },
                clear=False,
            ), patch.object(
                ig_client.requests,
                "post",
                side_effect=[
                    FakeResponse(200, {"id": "container"}),
                    FakeResponse(200, {"id": "media"}),
                ],
            ):
                result = ig_client.post_to_instagram_detailed(self._news())
            saved = json.loads(state.read_text(encoding="utf-8"))
        self.assertTrue(result.ok)
        self.assertEqual(result.external_id, "media")
        self.assertEqual(saved["posted"]["link:ig-test"]["external_id"], "media")

    def test_rate_limit_and_ambiguous_publish_network_are_typed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "ig.json"
            rate = Path(tmp) / "rate.json"
            common = [
                patch.object(ig_client, "IG_ACCOUNT_ID", "ig"),
                patch.object(ig_client, "IG_ACCESS_TOKEN", "token"),
                patch.object(ig_client, "IG_STATE_PATH", str(state)),
                patch.object(ig_client, "IG_RATE_LIMIT_PATH", str(rate)),
                patch.object(ig_client.r2_storage, "is_configured", return_value=False),
                patch.dict(
                    os.environ,
                    {
                        "IG_IMAGE_CONTAINER_WAIT_SECONDS": "0",
                        "IG_ALLOW_ORIGINAL_IMAGE_FALLBACK": "true",
                    },
                    clear=False,
                ),
            ]
            for manager in common:
                manager.start()
            try:
                with patch.object(
                    ig_client.requests,
                    "post",
                    return_value=FakeResponse(429, {"error": {"code": 4}}),
                ):
                    limited = ig_client.post_to_instagram_detailed(self._news())
                self.assertEqual(limited.error_type, "rate_limit")
                self.assertGreater(limited.next_retry_at, time.time())

                rate.write_text("{}", encoding="utf-8")
                with patch.object(
                    ig_client.requests,
                    "post",
                    side_effect=[
                        FakeResponse(200, {"id": "container"}),
                        requests.Timeout("unknown"),
                    ],
                ):
                    network = ig_client.post_to_instagram_detailed(self._news())
                self.assertEqual(network.error_type, "network_error")
                self.assertEqual(network.details["publication_outcome"], "unknown")
            finally:
                for manager in reversed(common):
                    manager.stop()


class R2ContractTests(unittest.TestCase):
    def test_upload_retries_then_returns_public_evidence(self):
        client = Mock()
        client.upload_file.side_effect = [
            ClientError({"Error": {"Code": "SlowDown", "Message": "wait"}}, "PutObject"),
            None,
        ]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "image.jpg"
            source.write_bytes(b"jpeg")
            with patch.object(r2_storage, "_get_client", return_value=client), patch.dict(
                os.environ,
                {
                    "R2_BUCKET_NAME": "bucket",
                    "R2_PUBLIC_URL": "https://media.example",
                    "R2_RETRY_COUNT": "2",
                    "R2_RETRY_BACKOFF_SECONDS": "0",
                },
                clear=False,
            ):
                result = r2_storage.upload_file_detailed(
                    str(source),
                    "news/image.jpg",
                    "image/jpeg",
                )
        self.assertTrue(result.ok)
        self.assertEqual(result.public_url, "https://media.example/news/image.jpg")
        self.assertEqual(result.details["attempts"], 2)

    def test_invalid_key_and_exhausted_retries_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "image.jpg"
            source.write_bytes(b"jpeg")
            invalid = r2_storage.upload_file_detailed(
                str(source),
                "../secret",
                "image/jpeg",
            )
            client = Mock()
            client.upload_file.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied"}},
                "PutObject",
            )
            with patch.object(r2_storage, "_get_client", return_value=client), patch.dict(
                os.environ,
                {
                    "R2_BUCKET_NAME": "bucket",
                    "R2_PUBLIC_URL": "https://media.example",
                    "R2_RETRY_COUNT": "1",
                },
                clear=False,
            ):
                failed = r2_storage.upload_file_detailed(
                    str(source),
                    "news/image.jpg",
                    "image/jpeg",
                )
        self.assertEqual(invalid.error_type, "invalid_object_key")
        self.assertEqual(failed.status, StageStatus.DEGRADED)
        self.assertTrue(failed.retryable)

    def test_delete_failure_is_visible_and_retryable(self):
        client = Mock()
        client.delete_object.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "retry"}},
            "DeleteObject",
        )
        with patch.object(r2_storage, "_get_client", return_value=client), patch.object(
            r2_storage,
            "_configured_value",
            return_value="bucket",
        ):
            result = r2_storage.delete("tmp/reels/video.mp4")

        self.assertEqual(StageStatus.DEGRADED, result.status)
        self.assertEqual("r2_delete_error", result.error_type)
        self.assertTrue(result.retryable)


class SocialRecoveryTests(unittest.TestCase):
    def test_interrupted_processing_is_dead_letter_not_automatic_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "social.json"
            events = Path(tmp) / "events.json"
            item = {"titulo": "A", "dedup_key": "link:a"}
            with patch.object(social_queue, "QUEUE_PATH", str(queue)), patch.dict(
                os.environ,
                {"LVR_QUEUE_EVENTS_PATH": str(events)},
                clear=False,
            ):
                social_queue.enqueue(item, platform="facebook")
                self.assertTrue(social_queue.claim(item, "facebook"))
                self.assertEqual(
                    social_queue.recover_ambiguous_processing("facebook"),
                    1,
                )
                self.assertEqual(social_queue.get_pending("facebook"), [])
            saved = json.loads(queue.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["facebook_state"], "dead_letter")
        self.assertIn("reconciliation", saved[0]["facebook_reason"])

    def test_expiration_is_terminal_and_journaled(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "social.json"
            events = Path(tmp) / "events.json"
            item = {
                "titulo": "Vencida",
                "dedup_key": "link:expired",
                "social_queued_at": int(time.time()) - 7200,
                "facebook_done": False,
                "instagram_done": True,
            }
            queue.write_text(json.dumps([item]), encoding="utf-8")
            with patch.object(social_queue, "QUEUE_PATH", str(queue)), patch.object(
                social_queue, "SOCIAL_TTL_HOURS", 1
            ), patch.dict(
                os.environ,
                {"LVR_QUEUE_EVENTS_PATH": str(events)},
                clear=False,
            ):
                self.assertEqual(social_queue.get_pending("facebook"), [])
            saved = json.loads(queue.read_text(encoding="utf-8"))
            journal = json.loads(events.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["facebook_state"], "expired")
        self.assertEqual(journal[0]["reason"], "social_ttl_exceeded")


if __name__ == "__main__":
    unittest.main()
