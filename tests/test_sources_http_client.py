import socket
import unittest
from unittest.mock import MagicMock, patch

import requests

from sources import http_client
from sources.registry import SourceDefinition


def _resolver_for(*addresses):
    def resolver(host, port, type=socket.SOCK_STREAM):
        return [(socket.AF_INET, type, 6, "", (address, port)) for address in addresses]

    return resolver


_PUBLIC_RESOLVER = _resolver_for("93.184.216.34")


def _source(**overrides):
    defaults = dict(
        source_id="test_source",
        name="Test",
        scheme="https",
        host="ejemplo.gob.ar",
        path="/noticias/",
        allowed_hosts=("ejemplo.gob.ar",),
    )
    defaults.update(overrides)
    return SourceDefinition(**defaults)


def _fake_response(status_code=200, text="<html></html>", headers=None):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.headers = headers or {}
    return response


class FetchTests(unittest.TestCase):
    def test_successful_fetch_returns_ok_result(self):
        with patch.object(http_client._SESSION, "get", return_value=_fake_response(200, "<html>ok</html>")):
            result = http_client.fetch(_source(), resolver=_PUBLIC_RESOLVER)
        self.assertTrue(result.ok)
        self.assertEqual(result.status_code, 200)
        self.assertIn("ok", result.text)

    def test_host_not_in_allowlist_raises(self):
        source = _source(host="ejemplo.gob.ar", path="/x", allowed_hosts=("otro.gob.ar",))
        with patch.object(http_client._SESSION, "get", return_value=_fake_response(200)):
            with self.assertRaises(http_client.SourceFetchError):
                http_client.fetch(source, resolver=_PUBLIC_RESOLVER)

    def test_304_marks_not_modified(self):
        with patch.object(http_client._SESSION, "get", return_value=_fake_response(304, "")):
            result = http_client.fetch(_source(), etag='"abc"', resolver=_PUBLIC_RESOLVER)
        self.assertTrue(result.not_modified)
        self.assertTrue(result.ok)

    def test_conditional_headers_are_sent(self):
        captured = {}

        def fake_get(url, **kwargs):
            captured.update(kwargs)
            return _fake_response(200, "ok")

        with patch.object(http_client._SESSION, "get", side_effect=fake_get):
            http_client.fetch(_source(), etag='"abc"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT", resolver=_PUBLIC_RESOLVER)

        self.assertEqual(captured["headers"]["If-None-Match"], '"abc"')
        self.assertEqual(captured["headers"]["If-Modified-Since"], "Mon, 01 Jan 2026 00:00:00 GMT")

    def test_network_error_is_wrapped(self):
        with patch.object(http_client._SESSION, "get", side_effect=requests.ConnectionError("boom")):
            with self.assertRaises(http_client.SourceFetchError):
                http_client.fetch(_source(), resolver=_PUBLIC_RESOLVER)


if __name__ == "__main__":
    unittest.main()
