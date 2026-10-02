"""LVR-IMPROVEMENT-0003: re-scrape de Facebook y titular de la imagen OG."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from meta import fb_client


class _Response:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data
        self.headers = {"Content-Type": "application/json"}
        self.text = ""

    def json(self):
        return self._data


class ForceRescrapeTests(unittest.TestCase):
    def setUp(self):
        fb_client._rescrape_disabled_reason = ""
        self.addCleanup(setattr, fb_client, "_rescrape_disabled_reason", "")

    def test_success(self):
        with mock.patch("meta.fb_client.requests.post", return_value=_Response(200, {"id": "x"})):
            self.assertTrue(fb_client.force_facebook_rescrape("https://x/n", "tok").ok)

    def test_permanent_rejection_is_logged_and_skipped_for_rest_of_run(self):
        error = {"error": {"code": 100, "error_subcode": 1611016, "message": "Invalid parameter"}}
        with mock.patch("meta.fb_client.requests.post", return_value=_Response(400, error)) as post:
            with self.assertLogs("fb_client", level="WARNING") as captured:
                first = fb_client.force_facebook_rescrape("https://x/1", "tok")
            second = fb_client.force_facebook_rescrape("https://x/2", "tok")

        self.assertEqual(1, post.call_count)
        self.assertFalse(first.retryable)
        self.assertIn("subcode=1611016", first.details["reason"])
        self.assertTrue(any("1611016" in line for line in captured.output))
        self.assertEqual("disabled_for_run", second.error_code)
        self.assertNotIn("tok", first.details["reason"])

    def test_transient_rejection_keeps_trying(self):
        error = {"error": {"code": 2, "message": "Service temporarily unavailable"}}
        with mock.patch("meta.fb_client.requests.post", return_value=_Response(500, error)) as post:
            fb_client.force_facebook_rescrape("https://x/1", "tok")
            result = fb_client.force_facebook_rescrape("https://x/2", "tok")
        self.assertEqual(2, post.call_count)
        self.assertTrue(result.retryable)


class OgHeadlineTests(unittest.TestCase):
    def test_og_uses_instagram_hook_title(self):
        from pipeline.node_webapp import media

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src.jpg"
            Image.new("RGB", (800, 450), "gray").save(source)
            with mock.patch.object(media, "_media_work_dir", return_value=Path(tmp)), mock.patch(
                "layout.image_generator.generate_facebook_with_engine",
                return_value=(b"jpeg", "pillow"),
            ) as render:
                media.generate_og_image(
                    source, "abcdef1234567", "Titulo web largo", {"titulo_instagram": "Gancho corto", "seccion": "interior"}
                )
                media.generate_og_image(source, "abcdef1234567", "Titulo web largo", {"seccion": "interior"})

        self.assertEqual("Gancho corto", render.call_args_list[0].args[0]["titulo"])
        self.assertEqual("Titulo web largo", render.call_args_list[1].args[0]["titulo"])


if __name__ == "__main__":
    unittest.main()
