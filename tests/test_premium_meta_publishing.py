from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meta import fb_client, ig_client


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload


class InstagramCarouselClientTests(unittest.TestCase):
    def test_creates_children_then_parent_carousel_and_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "premium_ig.json"
            calls = []

            def fake_post(url, data=None, timeout=None):
                calls.append((url, dict(data or {})))
                if url.endswith("/media") and data.get("is_carousel_item") == "true":
                    return FakeResponse(200, {"id": f"child-{len(calls)}"})
                if url.endswith("/media") and data.get("media_type") == "CAROUSEL":
                    return FakeResponse(200, {"id": "parent-container"})
                if url.endswith("/media_publish"):
                    return FakeResponse(200, {"id": "ig-post-final"})
                return FakeResponse(400, {})

            with patch.object(ig_client, "IG_ACCOUNT_ID", "acc"), patch.object(
                ig_client, "IG_ACCESS_TOKEN", "token"
            ), patch.object(ig_client, "PREMIUM_IG_STATE_PATH", str(state)), patch.object(
                ig_client, "IG_RATE_LIMIT_PATH", str(Path(tmp) / "rl.json")
            ), patch.object(
                ig_client.requests, "post", side_effect=fake_post
            ), patch.object(
                ig_client.r2_storage, "upload_temp", side_effect=[(f"https://r2/{i}", f"key{i}") for i in range(3)]
            ), patch.object(
                ig_client.r2_storage, "delete"
            ):
                package = {"id": "pkg-1", "title": "T", "caption": "cap"}
                result = ig_client.post_premium_carousel_to_instagram(package, [b"a", b"b", b"c"])

            self.assertTrue(result.ok)
            self.assertEqual("ig-post-final", result.external_id)
            child_calls = [c for c in calls if c[1].get("is_carousel_item") == "true"]
            self.assertEqual(3, len(child_calls))
            parent_calls = [c for c in calls if c[1].get("media_type") == "CAROUSEL"]
            self.assertEqual(1, len(parent_calls))
            self.assertEqual("child-1,child-2,child-3", parent_calls[0][1]["children"])

    def test_dedup_avoids_double_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "premium_ig.json"
            state.write_text(
                json.dumps({"posted": {"premium:pkg-1": {"external_id": "already-there"}}}),
                encoding="utf-8",
            )
            with patch.object(ig_client, "IG_ACCOUNT_ID", "acc"), patch.object(
                ig_client, "IG_ACCESS_TOKEN", "token"
            ), patch.object(ig_client, "PREMIUM_IG_STATE_PATH", str(state)), patch.object(
                ig_client, "IG_RATE_LIMIT_PATH", str(Path(tmp) / "rl.json")
            ), patch.object(ig_client.requests, "post") as post:
                package = {"id": "pkg-1", "premium_dedup_key": "premium:pkg-1", "title": "T"}
                result = ig_client.post_premium_carousel_to_instagram(package, [b"a", b"b"])
            self.assertTrue(result.ok)
            self.assertTrue(result.deduplicated)
            post.assert_not_called()

    def test_rate_limit_is_degraded_and_keeps_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            rl_path = Path(tmp) / "rl.json"
            rl_path.write_text(json.dumps({"blocked_until": 99999999999}), encoding="utf-8")
            with patch.object(ig_client, "IG_ACCOUNT_ID", "acc"), patch.object(
                ig_client, "IG_ACCESS_TOKEN", "token"
            ), patch.object(ig_client, "IG_RATE_LIMIT_PATH", str(rl_path)), patch.object(
                ig_client.requests, "post"
            ) as post:
                package = {"id": "pkg-2", "title": "T"}
                result = ig_client.post_premium_carousel_to_instagram(package, [b"a", b"b"])
            self.assertEqual("rate_limit", result.error_type)
            self.assertEqual(99999999999, result.next_retry_at)
            post.assert_not_called()

    def test_invalid_slide_count_is_rejected_before_any_call(self):
        with patch.object(ig_client, "IG_ACCOUNT_ID", "acc"), patch.object(
            ig_client, "IG_ACCESS_TOKEN", "token"
        ), patch.object(ig_client.requests, "post") as post:
            result = ig_client.post_premium_carousel_to_instagram({"id": "x"}, [b"only-one"])
        self.assertEqual("invalid_slide_count", result.error_type)
        post.assert_not_called()


class FacebookDirectMediaClientTests(unittest.TestCase):
    def _package(self, **overrides):
        pkg = {
            "id": "pkg-1",
            "title": "T",
            "caption": "Caption sin URL",
            "workflow": "manual_premium",
            "publish_mode": "direct_media",
        }
        pkg.update(overrides)
        return pkg

    def test_single_photo_never_requires_web_url_and_never_adds_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            fb_state = Path(tmp) / "fb.json"
            premium_state = Path(tmp) / "premium_fb.json"
            calls = []

            def fake_post(url, data=None, files=None, timeout=None):
                calls.append((url, dict(data or {})))
                return FakeResponse(200, {"id": "fb-photo-1"})

            with patch.object(fb_client, "PAGE_ID", "page"), patch.object(
                fb_client, "DISABLED_PAGE_IDS", set()
            ), patch.object(fb_client, "FB_STATE_PATH", str(fb_state)), patch.object(
                fb_client, "PREMIUM_FB_STATE_PATH", str(premium_state)
            ), patch.object(
                fb_client, "get_page_token", return_value="token"
            ), patch.object(fb_client.requests, "post", side_effect=fake_post):
                result = fb_client.post_premium_direct_media_to_facebook(self._package(), [b"only-image"])

            self.assertTrue(result.ok)
            url, payload = calls[0]
            self.assertTrue(url.endswith("/photos"))
            self.assertNotIn("link", payload)
            self.assertNotIn("http", payload.get("caption", ""))

    def test_multi_photo_creates_unpublished_photos_then_one_feed_post_without_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            fb_state = Path(tmp) / "fb.json"
            premium_state = Path(tmp) / "premium_fb.json"
            calls = []

            def fake_post(url, data=None, files=None, timeout=None):
                calls.append((url, dict(data or {})))
                if url.endswith("/photos"):
                    return FakeResponse(200, {"id": f"unpub-{len(calls)}"})
                if url.endswith("/feed"):
                    return FakeResponse(200, {"id": "fb-post-final"})
                return FakeResponse(400, {})

            with patch.object(fb_client, "PAGE_ID", "page"), patch.object(
                fb_client, "DISABLED_PAGE_IDS", set()
            ), patch.object(fb_client, "FB_STATE_PATH", str(fb_state)), patch.object(
                fb_client, "PREMIUM_FB_STATE_PATH", str(premium_state)
            ), patch.object(
                fb_client, "get_page_token", return_value="token"
            ), patch.object(fb_client.requests, "post", side_effect=fake_post):
                result = fb_client.post_premium_direct_media_to_facebook(self._package(), [b"a", b"b", b"c"])

            self.assertTrue(result.ok)
            self.assertEqual("fb-post-final", result.external_id)
            photo_calls = [c for c in calls if c[0].endswith("/photos")]
            self.assertEqual(3, len(photo_calls))
            self.assertTrue(all(c[1].get("published") == "false" for c in photo_calls))
            feed_calls = [c for c in calls if c[0].endswith("/feed")]
            self.assertEqual(1, len(feed_calls))
            self.assertNotIn("link", feed_calls[0][1])
            attached = json.loads(feed_calls[0][1]["attached_media"])
            self.assertEqual(3, len(attached))

    def test_publish_mode_must_be_explicit_never_inferred(self):
        with patch.object(fb_client, "PAGE_ID", "page"), patch.object(fb_client.requests, "post") as post:
            result = fb_client.post_premium_direct_media_to_facebook(
                {"id": "x", "workflow": "manual_premium"},  # falta publish_mode
                [b"a"],
            )
        self.assertEqual("invalid_publish_mode", result.error_type)
        post.assert_not_called()

    def test_dedup_avoids_double_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            fb_state = Path(tmp) / "fb.json"
            premium_state = Path(tmp) / "premium_fb.json"
            premium_state.write_text(
                json.dumps({"posted": {"premium:pkg-1": {"external_id": "already"}}}),
                encoding="utf-8",
            )
            with patch.object(fb_client, "PAGE_ID", "page"), patch.object(
                fb_client, "DISABLED_PAGE_IDS", set()
            ), patch.object(fb_client, "FB_STATE_PATH", str(fb_state)), patch.object(
                fb_client, "PREMIUM_FB_STATE_PATH", str(premium_state)
            ), patch.object(fb_client.requests, "post") as post:
                result = fb_client.post_premium_direct_media_to_facebook(
                    self._package(premium_dedup_key="premium:pkg-1"), [b"a"]
                )
            self.assertTrue(result.ok)
            self.assertTrue(result.deduplicated)
            post.assert_not_called()

    def test_rate_limit_shares_the_same_backoff_as_automatic_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            fb_state = Path(tmp) / "fb.json"
            fb_state.write_text(
                json.dumps({"posted": {}, "page_backoff": {"page": 99999999999}}),
                encoding="utf-8",
            )
            with patch.object(fb_client, "PAGE_ID", "page"), patch.object(
                fb_client, "DISABLED_PAGE_IDS", set()
            ), patch.object(fb_client, "FB_STATE_PATH", str(fb_state)), patch.object(
                fb_client.requests, "post"
            ) as post:
                result = fb_client.post_premium_direct_media_to_facebook(self._package(), [b"a"])
            self.assertEqual("rate_limit", result.error_type)
            self.assertEqual(99999999999, result.next_retry_at)
            post.assert_not_called()


class PremiumPublisherOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        self.patch = patch.dict(
            os.environ,
            {
                "LVR_DATA_DIR": str(self.data),
                "LVR_LOGS_DIR": str(Path(self.temp.name) / "logs"),
                "JSON_BACKUP_ENABLED": "false",
                "PREMIUM_PUBLISH_DRY_RUN": "false",
                # Estos tests cubren orquestación (degraded/retry/dedup), no motor
                # de render: forzar Pillow los hace rápidos y deterministas sin
                # depender de si Node/Remotion está instalado en la máquina que
                # corre la suite (ver docs/DECISIONS.md política por workflow).
                "PREMIUM_STATIC_RENDER_ENGINE": "pillow",
            },
            clear=False,
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self._close_loggers)

    def _close_loggers(self):
        # publish_package/render_package_with_engine tocan varios módulos con
        # setup_logger propio; cerrar sus handlers evita que Windows bloquee
        # el borrado del tempdir (archivo de log todavía abierto).
        import logging

        for name in ("premium_publisher", "premium_renderer", "remotion_renderer"):
            logger = logging.getLogger(name)
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)

    def _draft(self):
        from utils.premium_post_queue import create_draft
        from utils.premium_contract import add_slide

        draft = create_draft(
            title="Un festival cultural en Chilecito",
            caption="Caption sin link",
            section="cultura",
            destination=("instagram", "facebook"),
        )
        add_slide(draft, "closing", text="a")
        add_slide(draft, "closing", text="b")
        from utils.premium_post_queue import save_package

        save_package(draft)
        return draft

    def test_never_touches_cms_or_web_publisher(self):
        from utils.premium_publisher import publish_package

        draft = self._draft()
        with patch("meta.ig_client.post_premium_carousel_to_instagram") as ig_mock, patch(
            "meta.fb_client.post_premium_direct_media_to_facebook"
        ) as fb_mock, patch(
            "pipeline.node_webapp.publisher.publish_one_detailed"
        ) as web_publish_mock:
            from utils.operation_result import OperationResult
            from utils.stage_result import StageStatus

            ig_mock.return_value = OperationResult(StageStatus.SUCCESS, external_id="ig-1")
            fb_mock.return_value = OperationResult(StageStatus.SUCCESS, external_id="fb-1")
            result = publish_package(draft["id"])
            web_publish_mock.assert_not_called()
        self.assertEqual("published", result["status"])
        self.assertNotIn("web_url", result)
        for channel_result in result["channel_results"].values():
            self.assertNotIn("web_url", channel_result)

    def test_partial_success_is_degraded_and_preserves_successful_channel(self):
        from utils.operation_result import OperationResult
        from utils.premium_publisher import publish_package
        from utils.stage_result import StageStatus

        draft = self._draft()
        with patch("meta.ig_client.post_premium_carousel_to_instagram") as ig_mock, patch(
            "meta.fb_client.post_premium_direct_media_to_facebook"
        ) as fb_mock:
            ig_mock.return_value = OperationResult(StageStatus.SUCCESS, external_id="ig-ok")
            fb_mock.return_value = OperationResult(StageStatus.FAILED, error_type="request_rejected")
            result = publish_package(draft["id"])

        self.assertEqual("degraded", result["status"])
        self.assertEqual("ig-ok", result["channel_results"]["instagram"]["external_id"])
        self.assertFalse(result["channel_results"]["facebook"]["ok"])

    def test_retry_only_calls_the_failed_channel(self):
        from utils.operation_result import OperationResult
        from utils.premium_publisher import publish_package, retry_channel
        from utils.stage_result import StageStatus

        draft = self._draft()
        with patch("meta.ig_client.post_premium_carousel_to_instagram") as ig_mock, patch(
            "meta.fb_client.post_premium_direct_media_to_facebook"
        ) as fb_mock:
            ig_mock.return_value = OperationResult(StageStatus.SUCCESS, external_id="ig-ok")
            fb_mock.return_value = OperationResult(StageStatus.FAILED, error_type="request_rejected")
            publish_package(draft["id"])

            fb_mock.return_value = OperationResult(StageStatus.SUCCESS, external_id="fb-retry-ok")
            result = retry_channel(draft["id"], "facebook")

            ig_mock.assert_called_once()  # nunca se reintenta el canal ya exitoso
        self.assertEqual("published", result["status"])
        self.assertEqual("fb-retry-ok", result["channel_results"]["facebook"]["external_id"])

    def test_ambiguous_outcome_is_not_retried_without_force(self):
        from utils.operation_result import OperationResult
        from utils.premium_publisher import publish_package, retry_channel
        from utils.stage_result import StageStatus

        draft = self._draft()
        with patch("meta.ig_client.post_premium_carousel_to_instagram") as ig_mock, patch(
            "meta.fb_client.post_premium_direct_media_to_facebook"
        ) as fb_mock:
            ig_mock.return_value = OperationResult(StageStatus.SUCCESS, external_id="ig-ok")
            fb_mock.return_value = OperationResult(
                StageStatus.DEGRADED,
                error_type="network_error",
                retryable=True,
                details={"publication_outcome": "unknown"},
            )
            publish_package(draft["id"])

            result = retry_channel(draft["id"], "facebook")
            self.assertEqual("blocked", result["status"])
            fb_mock.assert_called_once()  # no se reintentó automáticamente

    def test_video_slides_block_publish_in_this_version(self):
        from utils.premium_publisher import publish_package
        from utils.premium_post_queue import save_package

        draft = self._draft()
        draft["slides"][0]["type"] = "video"
        save_package(draft)
        result = publish_package(draft["id"])
        self.assertEqual("failed", result["status"])
        self.assertTrue(any("video" in e for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
