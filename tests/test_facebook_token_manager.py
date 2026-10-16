import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from meta import facebook_token_manager as manager


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class PageTokenTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name) / "fb_token_cache.json"
        self._patches = [
            patch.object(manager, "TOKEN_CACHE", str(self.cache)),
            patch.object(manager, "PAGE_ID", "page-1"),
        ]
        for item in self._patches:
            item.start()

    def tearDown(self):
        for item in reversed(self._patches):
            item.stop()
        self._tmp.cleanup()

    def _get(self, routes, calls):
        def get(url, **kwargs):
            calls.append(url)
            for suffix, payload in routes.items():
                if url.endswith(suffix):
                    return FakeResponse(payload)
            raise AssertionError(f"URL inesperada: {url}")

        return get

    def test_page_token_in_env_is_used_directly_and_cached(self):
        calls = []
        routes = {"/me": {"id": "page-1", "name": "Página"}}
        with patch.object(manager, "USER_TOKEN", "page-token"), patch.object(
            manager.requests, "get", side_effect=self._get(routes, calls)
        ):
            self.assertEqual("page-token", manager.get_page_token())
            self.assertEqual("page-token", manager.get_page_token())

        self.assertEqual(1, len(calls))
        saved = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertEqual(manager._fingerprint("page-token"), saved["source_fingerprint"])
        self.assertNotIn("page-token", saved["source_fingerprint"])

    def test_user_token_is_exchanged_via_me_accounts(self):
        calls = []
        routes = {
            "/me/accounts": {
                "data": [
                    {"id": "otra", "name": "Otra", "access_token": "otro"},
                    {"id": "page-1", "name": "Página", "access_token": "derived"},
                ]
            },
            "/me": {"id": "user-9", "name": "Operador"},
        }
        with patch.object(manager, "USER_TOKEN", "user-token"), patch.object(
            manager.requests, "get", side_effect=self._get(routes, calls)
        ):
            self.assertEqual("derived", manager.get_page_token())

        self.assertEqual(2, len(calls))

    def test_rotating_env_token_ignores_stale_or_legacy_cache(self):
        for legacy in (
            {"page_token": "dead", "page_id": "page-1", "updated_at": 1},
            {
                "page_token": "dead",
                "page_id": "page-1",
                "source_fingerprint": manager._fingerprint("old-token"),
            },
        ):
            with self.subTest(cache=legacy):
                self.cache.write_text(json.dumps(legacy), encoding="utf-8")
                calls = []
                routes = {"/me": {"id": "page-1", "name": "Página"}}
                with patch.object(manager, "USER_TOKEN", "new-token"), patch.object(
                    manager.requests, "get", side_effect=self._get(routes, calls)
                ):
                    self.assertEqual("new-token", manager.get_page_token())
                self.assertEqual(1, len(calls))

    def test_invalid_token_raises_without_fallback(self):
        routes = {"/me": {"error": {"code": 190, "message": "Session invalidated"}}}
        with patch.object(manager, "USER_TOKEN", "dead-token"), patch.object(
            manager.requests, "get", side_effect=self._get(routes, [])
        ):
            with self.assertRaises(ValueError):
                manager.get_page_token()
        self.assertFalse(self.cache.exists())

    def test_invalidate_cache_forces_rederivation(self):
        calls = []
        routes = {"/me": {"id": "page-1", "name": "Página"}}
        with patch.object(manager, "USER_TOKEN", "page-token"), patch.object(
            manager.requests, "get", side_effect=self._get(routes, calls)
        ):
            manager.get_page_token()
            manager.invalidate_cache()
            manager.get_page_token()
        self.assertEqual(2, len(calls))


if __name__ == "__main__":
    unittest.main()
