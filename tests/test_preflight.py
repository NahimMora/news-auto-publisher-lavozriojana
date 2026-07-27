from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests


class FakeResponse:
    def __init__(self, status=200, *, payload=None, text="", content_type="application/json", headers=None):
        self.status_code = status
        self._payload = payload
        self.text = text
        self.headers = {"Content-Type": content_type, **(headers or {})}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        if self._payload is None:
            raise ValueError("non-json")
        return self._payload


def public_resolver(*args, **kwargs):
    return [(None, None, None, None, ("8.8.8.8", 443))]


class SourcePreflightTests(unittest.TestCase):
    SECTION = "https://nuevarioja.com.ar/locales"
    ARTICLE = "https://nuevarioja.com.ar/locales/nota-canary-verificable-larga.htm"

    def test_accessible_empty_source_is_no_work(self):
        from utils.preflight import check_sources
        from utils.stage_result import StageStatus

        result = check_sources(
            http_get=lambda *args, **kwargs: FakeResponse(
                text="<html><body>Sin notas</body></html>",
                content_type="text/html",
            ),
            resolver=public_resolver,
            sections={"fixture": self.SECTION},
        )

        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertEqual(0, result.failed)

    def test_selector_mismatch_is_failed(self):
        from utils.preflight import check_sources
        from utils.stage_result import StageStatus

        section = f'<a href="{self.ARTICLE}">Nota</a>'

        def get(url, **kwargs):
            if url == self.SECTION:
                return FakeResponse(text=section, content_type="text/html")
            return FakeResponse(text="<html><h2>Sin contrato</h2></html>", content_type="text/html")

        result = check_sources(
            http_get=get,
            resolver=public_resolver,
            sections={"fixture": self.SECTION},
        )

        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("selector_mismatch", result.details["sources"][0]["error_type"])

    def test_missing_image_is_degraded_and_valid_article_succeeds(self):
        from utils.preflight import check_sources
        from utils.stage_result import StageStatus

        section = f'<a href="{self.ARTICLE}">Nota</a>'
        body = "<p>" + ("contenido verificable " * 8) + "</p>"
        without_image = f"<html><h1>Título</h1><article>{body}</article></html>"
        with_image = (
            f'<html><head><meta property="og:image" content="https://8.8.8.8/image.jpg"></head>'
            f"<body><h1>Título</h1><article>{body}</article></body></html>"
        )
        for article_html, expected in (
            (without_image, StageStatus.DEGRADED),
            (with_image, StageStatus.SUCCESS),
        ):
            with self.subTest(status=expected):
                result = check_sources(
                    http_get=lambda url, **kwargs: FakeResponse(
                        text=section if url == self.SECTION else article_html,
                        content_type="text/html",
                    ),
                    resolver=public_resolver,
                    sections={"fixture": self.SECTION},
                )
                self.assertEqual(expected, result.status)

    def test_timeout_is_failed(self):
        from utils.preflight import check_sources
        from utils.stage_result import StageStatus

        def timeout(*args, **kwargs):
            raise requests.Timeout()

        result = check_sources(
            http_get=timeout,
            resolver=public_resolver,
            sections={"fixture": self.SECTION},
        )
        self.assertEqual(StageStatus.FAILED, result.status)
        self.assertEqual("timeout", result.details["sources"][0]["error_type"])


class ExternalPreflightTests(unittest.TestCase):
    def test_missing_credentials_are_blocked_not_success(self):
        from utils.preflight import (
            check_cms,
            check_facebook,
            check_instagram,
            check_openai,
            check_r2,
        )
        from utils.stage_result import StageStatus

        for checker in (check_openai, check_r2, check_cms, check_facebook, check_instagram):
            with self.subTest(check=checker.__name__):
                result = checker({})
                self.assertEqual(StageStatus.BLOCKED, result.status)
                self.assertEqual(3, result.exit_code)

    def test_openai_structured_success_and_invalid_token(self):
        from utils.preflight import check_openai
        from utils.stage_result import StageStatus

        response = SimpleNamespace(output_text='{"status":"ok","purpose":"lvr_preflight"}')
        client = SimpleNamespace(
            responses=SimpleNamespace(create=mock.Mock(return_value=response))
        )
        success = check_openai(
            {"OPENAI_API_KEY": "test", "OPENAI_MODEL": "model"},
            client_factory=lambda **kwargs: client,
        )

        class Unauthorized(Exception):
            status_code = 401

        denied_client = SimpleNamespace(
            responses=SimpleNamespace(create=mock.Mock(side_effect=Unauthorized()))
        )
        denied = check_openai(
            {"OPENAI_API_KEY": "test"},
            client_factory=lambda **kwargs: denied_client,
        )

        self.assertEqual(StageStatus.SUCCESS, success.status)
        self.assertEqual("invalid_credential", denied.error_type)
        self.assertEqual(StageStatus.FAILED, denied.status)

    def test_cms_contract_401_429_and_non_json(self):
        from utils.preflight import check_cms
        from utils.stage_result import StageStatus

        env = {
            "WEBAPP_BASE_URL": "https://8.8.8.8",
            "PRIVATE_API_KEY": "test",
            "WEBAPP_PREFLIGHT_PATH": "/health",
        }
        cases = (
            (FakeResponse(401, payload={}), StageStatus.FAILED, "invalid_credential"),
            (FakeResponse(429, payload={}), StageStatus.DEGRADED, "rate_limit"),
            (FakeResponse(200, payload=ValueError()), StageStatus.FAILED, "non_json_response"),
            (
                FakeResponse(
                    200,
                    payload={
                        "ok": True,
                        "contract_version": "1",
                        "capabilities": {"posts_create": True},
                    },
                ),
                StageStatus.SUCCESS,
                None,
            ),
        )
        for response, status, error_type in cases:
            with self.subTest(status=status, error=error_type):
                result = check_cms(env, http_get=lambda *args, current=response, **kwargs: current)
                self.assertEqual(status, result.status)
                self.assertEqual(error_type, result.error_type)

    def test_facebook_and_instagram_validate_identity_without_publish(self):
        from utils.preflight import check_facebook, check_instagram
        from utils.stage_result import StageStatus

        env = {
            "META_GRAPH_API": "https://8.8.8.8/v19.0",
            "FB_PAGE_ID": "page-1",
            "FB_PAGE_ACCESS_TOKEN": "test",
            "IG_ACCOUNT_ID": "ig-1",
            "IG_ACCESS_TOKEN": "test",
        }

        def get(url, **kwargs):
            if url.endswith("/me/permissions"):
                return FakeResponse(
                    payload={
                        "data": [
                            {"permission": "pages_manage_posts", "status": "granted"},
                            {
                                "permission": "instagram_content_publish",
                                "status": "granted",
                            },
                        ]
                    }
                )
            if url.endswith("/page-1") and kwargs["params"]["fields"] == "id,name":
                return FakeResponse(
                    payload={"id": "page-1", "name": "Página"}
                )
            if url.endswith("/page-1"):
                return FakeResponse(
                    payload={"id": "page-1", "instagram_business_account": {"id": "ig-1"}}
                )
            return FakeResponse(payload={"id": "ig-1", "username": "lvr"})

        facebook = check_facebook(env, http_get=get)
        instagram = check_instagram(env, http_get=get)

        self.assertEqual(StageStatus.SUCCESS, facebook.status)
        self.assertEqual(StageStatus.SUCCESS, instagram.status)

    def test_facebook_preflight_does_not_request_removed_tasks_field(self):
        from utils.preflight import check_facebook
        from utils.stage_result import StageStatus

        env = {
            "META_GRAPH_API": "https://8.8.8.8/v19.0",
            "FB_PAGE_ID": "page-1",
            "FB_PAGE_ACCESS_TOKEN": "test",
        }

        def get(url, **kwargs):
            if url.endswith("/me/permissions"):
                return FakeResponse(
                    payload={
                        "data": [
                            {"permission": "pages_manage_posts", "status": "granted"},
                        ]
                    }
                )
            fields = kwargs["params"]["fields"]
            if fields == "id,name,tasks":
                return FakeResponse(
                    status_code=400,
                    payload={
                        "error": {
                            "code": 100,
                            "message": "Tried accessing nonexisting field (tasks)",
                        }
                    },
                )
            return FakeResponse(payload={"id": "page-1", "name": "Página"})

        result = check_facebook(env, http_get=get)

        self.assertEqual(StageStatus.SUCCESS, result.status)
        self.assertTrue(result.details["publish_permission_verified"])

    def test_r2_cleanup_failure_never_reports_success(self):
        from utils.preflight import check_r2
        from utils.stage_result import StageStatus

        class Client:
            def put_object(self, **kwargs):
                return {}

            def head_object(self, **kwargs):
                return {}

            def delete_object(self, **kwargs):
                raise OSError("cleanup down")

        env = {
            "R2_ACCOUNT_ID": "account",
            "R2_ACCESS_KEY_ID": "key",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_BUCKET_NAME": "bucket",
            "R2_PUBLIC_URL": "https://8.8.8.8",
        }
        result = check_r2(
            env,
            client_factory=lambda: Client(),
            http_get=lambda *args, **kwargs: FakeResponse(200, payload={}),
        )

        self.assertEqual(StageStatus.DEGRADED, result.status)
        self.assertEqual("cleanup_error", result.error_type)
        self.assertTrue(result.details["cleanup_error"])

    def test_r2_success_confirms_object_is_gone(self):
        from botocore.exceptions import ClientError
        from utils.preflight import check_r2
        from utils.stage_result import StageStatus

        class Client:
            deleted = False

            def put_object(self, **kwargs):
                return {}

            def head_object(self, **kwargs):
                if self.deleted:
                    raise ClientError(
                        {
                            "Error": {"Code": "NoSuchKey"},
                            "ResponseMetadata": {"HTTPStatusCode": 404},
                        },
                        "HeadObject",
                    )
                return {}

            def delete_object(self, **kwargs):
                self.deleted = True
                return {}

        env = {
            "R2_ACCOUNT_ID": "account",
            "R2_ACCESS_KEY_ID": "key",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_BUCKET_NAME": "bucket",
            "R2_PUBLIC_URL": "https://8.8.8.8",
        }
        result = check_r2(
            env,
            client_factory=lambda: Client(),
            http_get=lambda *args, **kwargs: FakeResponse(200, payload={}),
        )

        self.assertEqual(StageStatus.SUCCESS, result.status)
        self.assertIsNone(result.details["cleanup_error"])

    def test_all_scope_preserves_blocked(self):
        from utils.preflight import run_preflight
        from utils.stage_result import StageResult, StageStatus

        overrides = {
            name: (lambda current=name: StageResult(f"preflight_{current}", StageStatus.SUCCESS))
            for name in (
                "sources",
                "openai",
                "r2",
                "cms",
                "facebook",
                "instagram",
                "filesystem",
                "supervisor",
            )
        }
        overrides["openai"] = lambda: StageResult("preflight_openai", StageStatus.BLOCKED)
        result = run_preflight("all", {}, overrides=overrides)

        self.assertEqual(StageStatus.BLOCKED, result.status)
        self.assertNotEqual(0, result.exit_code)


class FilesystemPreflightTests(unittest.TestCase):
    def test_filesystem_exercises_concurrency_backup_restore_and_corruption(self):
        from utils.preflight import check_filesystem
        from utils.stage_result import StageStatus

        with tempfile.TemporaryDirectory() as temp:
            result = check_filesystem(root=temp, min_free_mb=1)

        self.assertEqual(StageStatus.SUCCESS, result.status, result.to_dict())
        self.assertTrue(result.details["backup_restore"])
        self.assertTrue(result.details["corruption_quarantine"])
        self.assertEqual(2, result.details["concurrent_writers"])

    def test_insufficient_space_and_invalid_root_fail(self):
        from utils.preflight import check_filesystem
        from utils.stage_result import StageStatus

        with tempfile.TemporaryDirectory() as temp:
            low = check_filesystem(root=temp, min_free_mb=10**15)
            root_file = Path(temp) / "not-a-directory"
            root_file.write_text("x", encoding="utf-8")
            invalid = check_filesystem(root=root_file, min_free_mb=1)

        self.assertEqual(StageStatus.FAILED, low.status)
        self.assertEqual("disk_space_low", low.error_type)
        self.assertEqual(StageStatus.FAILED, invalid.status)


if __name__ == "__main__":
    unittest.main()
