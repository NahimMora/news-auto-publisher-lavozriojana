from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from PIL import Image


def _jpeg_bytes(color=(180, 20, 20)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (80, 60), color).save(buffer, format="JPEG")
    return buffer.getvalue()


class _ImageResponse:
    def __init__(self, data: bytes, *, content_type: str = "image/jpeg"):
        self.data = data
        self.status_code = 200
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(data)),
        }
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        for offset in range(0, len(self.data), chunk_size):
            yield self.data[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class PremiumImageDownloadTests(unittest.TestCase):
    def test_download_uses_safe_http_and_enforces_image_content_type(self):
        import video_reel_manager as manager

        response = _ImageResponse(_jpeg_bytes())
        with patch.object(
            manager,
            "validate_public_http_url",
            return_value="https://cdn.example/foto",
        ) as validate, patch.object(
            manager,
            "safe_get",
            return_value=response,
        ) as safe_get:
            data, normalized_url, filename = manager._download_premium_image(
                "https://cdn.example/foto"
            )

        self.assertEqual(_jpeg_bytes(), data)
        self.assertEqual("https://cdn.example/foto", normalized_url)
        self.assertEqual("premium_link.jpg", filename)
        validate.assert_called_once_with("https://cdn.example/foto")
        safe_get.assert_called_once()
        self.assertTrue(response.closed)

    def test_private_url_is_rejected_before_any_download(self):
        import video_reel_manager as manager
        from utils.safe_http import UnsafeURLError

        with patch.object(manager, "safe_get") as safe_get:
            with self.assertRaises(UnsafeURLError):
                manager._download_premium_image("http://127.0.0.1/private.jpg")

        safe_get.assert_not_called()

    def test_non_image_response_is_rejected_and_closed(self):
        import video_reel_manager as manager

        response = _ImageResponse(b"<html>not an image</html>", content_type="text/html")
        with patch.object(
            manager,
            "validate_public_http_url",
            return_value="https://example.test/page",
        ), patch.object(manager, "safe_get", return_value=response):
            with self.assertRaisesRegex(ValueError, "formato de imagen"):
                manager._download_premium_image("https://example.test/page")

        self.assertTrue(response.closed)


class PremiumStudioHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.output = self.root / "output"
        self.uploads = self.output / "uploads"
        self.data.mkdir()
        self.uploads.mkdir(parents=True)
        self.env_patch = patch.dict(
            os.environ,
            {
                "LVR_DATA_DIR": str(self.data),
                "LVR_LOGS_DIR": str(self.root / "logs"),
                "LVR_OUTPUT_DIR": str(self.output),
                "LVR_BACKUP_DIR": str(self.root / "backups"),
                "LVR_QUARANTINE_DIR": str(self.root / "quarantine"),
                "JSON_BACKUP_ENABLED": "false",
                "PYTHON_DOTENV_DISABLED": "1",
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

        import video_reel_manager as manager
        from utils import premium_post_queue

        self.manager = manager
        self.packages_patch = patch.object(
            premium_post_queue,
            "PACKAGES_PATH",
            str(self.data / "premium_packages.json"),
        )
        self.packages_patch.start()
        self.addCleanup(self.packages_patch.stop)
        self.uploads_patch = patch.object(
            manager,
            "UPLOADS_DIR",
            str(self.uploads),
        )
        self.uploads_patch.start()
        self.addCleanup(self.uploads_patch.stop)

        self.server = manager.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            manager.VideoReelHandler,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(self._stop_server)
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _request(self, method: str, path: str, payload: dict | None = None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                return (
                    response.status,
                    response.headers.get_content_type(),
                    response.read(),
                )
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get_content_type(), exc.read()

    def _json_request(self, method: str, path: str, payload: dict | None = None):
        status, _content_type, body = self._request(method, path, payload)
        return status, json.loads(body.decode("utf-8"))

    def test_generate_endpoint_validates_imports_and_saves_package(self):
        generated = json.dumps(
            {
                "title": "Texto confirmado",
                "caption": "Resumen",
                "section": "sociedad",
                "suggested_template": "lvr_cronica",
                "slides": [
                    {"type": "cover", "text": "Texto confirmado"},
                    {"type": "closing", "text": "La Voz Riojana"},
                ],
                "sources": [],
                "unknowns": [],
            }
        )
        with patch(
            "openIA.premium_package_generator.generate_premium_package_json",
            return_value=generated,
        ):
            status, body = self._json_request(
                "POST",
                "/api/premium/generate",
                {"raw_text": "Texto pegado por el operador"},
            )

        self.assertEqual(200, status)
        self.assertEqual(generated, body["generated_json"])
        self.assertEqual("Texto confirmado", body["package"]["title"])
        self.assertRegex(body["package"]["id"], r"^[a-f0-9]{32}$")
        self.assertTrue((self.data / "premium_packages.json").exists())

    def test_generate_endpoint_reports_manual_openai_failure(self):
        from openIA.premium_package_generator import PremiumGenerationError

        with patch(
            "openIA.premium_package_generator.generate_premium_package_json",
            side_effect=PremiumGenerationError("OpenAI no respondió"),
        ):
            status, body = self._json_request(
                "POST",
                "/api/premium/generate",
                {"raw_text": "Texto pegado por el operador"},
            )

        self.assertEqual(422, status)
        self.assertEqual("OpenAI no respondió", body["error"])

    def test_asset_from_url_ingests_bytes_and_returns_http_thumbnail(self):
        with patch.object(
            self.manager,
            "_download_premium_image",
            return_value=(
                _jpeg_bytes(),
                "https://cdn.example/foto.jpg",
                "premium_link.jpg",
            ),
        ):
            status, body = self._json_request(
                "POST",
                "/api/premium/asset-from-url",
                {
                    "url": "https://cdn.example/foto.jpg",
                    "titulo": "Foto confirmada",
                    "seccion": "sociedad",
                },
            )

        self.assertEqual(200, status)
        self.assertRegex(body["asset_id"], r"^[a-f0-9]{32}$")
        self.assertEqual(
            f"/api/media-library/thumb/{body['asset_id']}",
            body["thumbnail"],
        )

        from utils.media_library import get_asset

        asset = get_asset(body["asset_id"])
        self.assertEqual("premium_link", asset["origin"])
        self.assertEqual("https://cdn.example/foto.jpg", asset["source_url"])

    def test_uploaded_image_can_be_promoted_to_library_asset(self):
        stored_name = f"{'a' * 32}.jpg"
        (self.uploads / stored_name).write_bytes(_jpeg_bytes(color=(20, 80, 180)))

        status, body = self._json_request(
            "POST",
            "/api/premium/asset-from-upload",
            {
                "stored_name": stored_name,
                "titulo": "Imagen propia",
                "seccion": "cultura",
            },
        )

        self.assertEqual(200, status)
        from utils.media_library import get_asset

        asset = get_asset(body["asset_id"])
        self.assertEqual("premium_upload", asset["origin"])
        self.assertEqual("Imagen propia", asset["titulo"])

    def test_upload_promotion_rejects_unowned_path(self):
        status, body = self._json_request(
            "POST",
            "/api/premium/asset-from-upload",
            {"stored_name": "../../secret.jpg"},
        )

        self.assertEqual(400, status)
        self.assertIn("inválido", body["error"])

    def test_thumbnail_endpoint_serves_valid_jpeg_and_rejects_invalid_id(self):
        from utils.media_library import ingest_image_bytes

        asset = ingest_image_bytes(
            _jpeg_bytes(),
            filename="owned.jpg",
            origin="premium_upload",
        )

        status, content_type, body = self._request(
            "GET",
            f"/api/media-library/thumb/{asset['asset_id']}",
        )
        self.assertEqual(200, status)
        self.assertEqual("image/jpeg", content_type)
        self.assertTrue(body.startswith(b"\xff\xd8\xff"))
        with Image.open(io.BytesIO(body)) as thumbnail:
            self.assertEqual((80, 60), thumbnail.size)

        invalid_status, invalid_body = self._json_request(
            "GET",
            "/api/media-library/thumb/not-valid",
        )
        self.assertEqual(400, invalid_status)
        self.assertIn("asset_id", invalid_body["error"])

    def test_thumbnail_endpoint_returns_404_for_purged_asset(self):
        from utils.file_manager import update_json
        from utils.media_library import ingest_image_bytes

        asset = ingest_image_bytes(
            _jpeg_bytes(),
            filename="purged.jpg",
            origin="premium_upload",
        )

        def purge(assets):
            for item in assets:
                if item["asset_id"] == asset["asset_id"]:
                    item["files_purged"] = True
                    item["thumb_path"] = None
            return assets

        update_json(
            str(self.data / "media_library.json"),
            purge,
            [],
            expected_type=list,
        )

        status, body = self._json_request(
            "GET",
            f"/api/media-library/thumb/{asset['asset_id']}",
        )
        self.assertEqual(404, status)
        self.assertIn("miniatura", body["error"])

    def test_html_exposes_four_steps_and_all_three_image_sources(self):
        html = self.manager.HTML
        self.assertIn("premium_raw_article_text", html)
        self.assertIn("Generar estructura con IA", html)
        self.assertIn("premium_import_text", html)
        self.assertIn("/api/premium/asset-from-url", html)
        self.assertIn("/api/premium/asset-from-upload", html)
        self.assertIn("premium-library-thumb", html)
        for badge in ("pbadge1", "pbadge2", "pbadge3", "pbadge4"):
            self.assertIn(badge, html)


if __name__ == "__main__":
    unittest.main()
