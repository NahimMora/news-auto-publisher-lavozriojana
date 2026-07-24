from __future__ import annotations

import socket
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def _resolver_for(*addresses):
    def resolver(host, port, type=socket.SOCK_STREAM):
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, type, 6, "", (address, port))
            for address in addresses
        ]

    return resolver


class SafeUrlTests(unittest.TestCase):
    def test_public_https_url_is_allowed(self):
        from utils.safe_http import validate_public_http_url

        value = validate_public_http_url(
            "https://news.example.com/article",
            resolver=_resolver_for("93.184.216.34"),
        )

        self.assertEqual("https://news.example.com/article", value)

    def test_loopback_private_link_local_and_credentials_are_rejected(self):
        from utils.safe_http import UnsafeURLError, validate_public_http_url

        cases = [
            ("http://127.0.0.1/admin", _resolver_for("127.0.0.1")),
            ("http://10.0.0.5/internal", _resolver_for("10.0.0.5")),
            ("http://169.254.169.254/latest/meta-data", _resolver_for("169.254.169.254")),
            ("http://[::1]/admin", _resolver_for("::1")),
            ("https://user:pass@example.com/", _resolver_for("93.184.216.34")),
        ]
        for url, resolver in cases:
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    validate_public_http_url(url, resolver=resolver)

    def test_redirect_to_private_address_is_rejected(self):
        from utils.safe_http import UnsafeURLError, safe_request

        response = Mock(status_code=302, headers={"Location": "http://127.0.0.1/admin"})
        requester = Mock(return_value=response)
        with self.assertRaises(UnsafeURLError):
            safe_request(
                "GET",
                "https://public.example/start",
                requester=requester,
                resolver=_resolver_for("93.184.216.34"),
            )
        requester.assert_called_once()
        response.close.assert_called_once()

    def test_scrapers_do_not_fetch_private_image_urls(self):
        from scraping import base_nuevarioja, base_tiempopopular

        logger = Mock()
        for scraper in (base_nuevarioja, base_tiempopopular):
            with self.subTest(scraper=scraper.__name__), patch.object(
                scraper.requests,
                "get",
            ) as requester:
                downloaded = scraper._download_image(
                    "http://169.254.169.254/latest/meta-data",
                    "sociedad",
                    "https://example.com/2026/07/23/nota/",
                    logger,
                )

                self.assertEqual((None, None), downloaded)
                requester.assert_not_called()


class ManualInterfaceSecurityTests(unittest.TestCase):
    def test_manual_ui_renders_persisted_text_with_text_content(self):
        import video_reel_manager

        html = video_reel_manager.HTML
        self.assertNotIn("innerHTML = items.map", html)
        self.assertNotIn("(d.ig_ok || d.fb_ok) ? 'ok'", html)
        self.assertNotIn("(d.web_ok) ? 'ok'", html)
        self.assertIn("title.textContent = listText(it.titulo)", html)
        self.assertIn("detail.textContent = listText(", html)
        designer = (
            Path(__file__).resolve().parents[1] / "instagram_layout_designer.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn(".innerHTML =", designer)
        self.assertIn("infoTitle.textContent", designer)

    def test_external_bind_is_rejected(self):
        from video_reel_manager import _safe_object_id, validate_bind_host

        self.assertEqual("127.0.0.1", validate_bind_host("127.0.0.1"))
        self.assertEqual("::1", validate_bind_host("::1"))
        with self.assertRaises(ValueError):
            validate_bind_host("0.0.0.0")
        with self.assertRaises(ValueError):
            validate_bind_host("192.168.1.20")
        self.assertIsNone(_safe_object_id("../../secret"))
        self.assertEqual("a" * 32, _safe_object_id("a" * 32))

    def test_dns_rebinding_and_cross_origin_requests_are_rejected(self):
        from video_reel_manager import validate_local_request_headers

        validate_local_request_headers(
            "127.0.0.1:8765",
            "http://localhost:8765",
        )
        with self.assertRaises(ValueError):
            validate_local_request_headers("attacker.example:8765")
        with self.assertRaises(ValueError):
            validate_local_request_headers(
                "127.0.0.1:8765",
                "https://attacker.example",
            )

    def test_upload_content_must_match_extension(self):
        from utils.upload_validation import InvalidUploadError, validate_upload_content

        with self.assertRaises(InvalidUploadError):
            validate_upload_content(b"not an image", "photo.jpg", "image")
        with self.assertRaises(InvalidUploadError):
            validate_upload_content(b"not a video", "clip.mp4", "video")

    def test_valid_png_and_mp4_signatures_are_accepted(self):
        import io
        from PIL import Image
        from utils.upload_validation import validate_upload_content

        image = Image.new("RGB", (16, 16), "red")
        buf = io.BytesIO()
        image.save(buf, "PNG")
        validate_upload_content(buf.getvalue(), "photo.png", "image")

        minimal_mp4_header = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
        validate_upload_content(minimal_mp4_header, "clip.mp4", "video")

    def test_custom_post_rejects_ssrf_and_accepts_only_owned_local_upload(self):
        from pipeline.custom_post import build_custom_noticia

        base = {
            "titulo": "Título manual válido",
            "cuerpo": "Cuerpo manual suficiente para una publicación de prueba.",
            "seccion": "sociedad",
        }
        with self.assertRaises(ValueError):
            build_custom_noticia(
                {**base, "imagen_url": "http://169.254.169.254/metadata"}
            )

        with tempfile.TemporaryDirectory() as tmp:
            uploads = Path(tmp) / "uploads"
            uploads.mkdir()
            filename = f"{'a' * 32}.jpg"
            (uploads / filename).write_bytes(b"owned")
            with patch.dict(os.environ, {"LVR_OUTPUT_DIR": tmp}, clear=False):
                item = build_custom_noticia(
                    {
                        **base,
                        "imagen_url": f"http://127.0.0.1:8765/api/uploads/{filename}",
                    }
                )
        self.assertTrue(item["imagen"].endswith(filename))

    def test_manual_dry_run_never_returns_fake_publication_success(self):
        from pipeline.custom_post import publish_custom_post

        with patch.dict(os.environ, {"CUSTOM_POST_DRY_RUN": "true"}, clear=False):
            result = publish_custom_post({"titulo": "Prueba"})
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["web_ok"])
        self.assertFalse(result["ig_ok"])
        self.assertFalse(result["fb_ok"])
        self.assertEqual(result["public_url"], "")

    def test_manual_partial_publication_is_degraded(self):
        from pipeline.custom_post import publish_custom_post
        from utils.operation_result import OperationResult
        from utils.stage_result import StageStatus

        web = {
            "published": True,
            "public_url": "https://lavozriojana.example/nota",
        }
        instagram = OperationResult(
            StageStatus.SUCCESS,
            external_id="ig-1",
        )
        facebook = OperationResult(
            StageStatus.FAILED,
            error_type="invalid_credential",
        )
        with patch.dict(
            os.environ,
            {"CUSTOM_POST_DRY_RUN": "false"},
            clear=False,
        ), patch(
            "pipeline.node_webapp.publisher.publish_one_detailed",
            return_value=web,
        ), patch(
            "meta.ig_client.post_to_instagram_detailed",
            return_value=instagram,
        ), patch(
            "meta.fb_client.post_to_facebook_detailed",
            return_value=facebook,
        ):
            result = publish_custom_post({"titulo": "Prueba"})

        self.assertEqual("degraded", result["status"])
        self.assertTrue(result["web_ok"])
        self.assertTrue(result["ig_ok"])
        self.assertFalse(result["fb_ok"])


if __name__ == "__main__":
    unittest.main()
