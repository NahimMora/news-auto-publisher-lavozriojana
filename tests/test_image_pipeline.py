import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from layout import image_generator
from pipeline.node_webapp import media
from utils import image_processor


def image_bytes(fmt="PNG", size=(800, 600), color=(20, 40, 60)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


class ImageProcessingTests(unittest.TestCase):
    def test_dimensions_format_and_quality_constraints(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "small.png"
            target = Path(tmp) / "result.jpg"
            source.write_bytes(image_bytes(size=(400, 300)))
            with patch.dict(
                "os.environ",
                {
                    "IMAGE_MIN_WIDTH": "700",
                    "IMAGE_MAX_WIDTH": "1400",
                    "IMAGE_MAX_PIXELS": "40000000",
                },
                clear=False,
            ):
                self.assertTrue(image_processor.process_image(str(source), str(target)))
            with Image.open(target) as result:
                self.assertEqual(result.format, "JPEG")
                self.assertGreaterEqual(result.width, 700)
                self.assertLessEqual(result.width, 1400)

    def test_corrupt_empty_and_excessive_dimensions_fail_visibly(self):
        with tempfile.TemporaryDirectory() as tmp:
            corrupt = Path(tmp) / "corrupt.jpg"
            target = Path(tmp) / "result.jpg"
            corrupt.write_bytes(b"not-an-image")
            self.assertFalse(image_processor.process_image(str(corrupt), str(target)))

            source = Path(tmp) / "valid.png"
            source.write_bytes(image_bytes(size=(100, 100)))
            with patch.dict("os.environ", {"IMAGE_MAX_PIXELS": "5000"}, clear=False):
                self.assertFalse(image_processor.process_image(str(source), str(target)))

    def test_private_image_url_is_rejected_before_network(self):
        with patch.object(image_processor.requests, "get") as request:
            ok = image_processor.download_image(
                "http://127.0.0.1/internal.png",
                "unused.jpg",
            )
        self.assertFalse(ok)
        request.assert_not_called()


class LayoutTests(unittest.TestCase):
    def test_instagram_and_facebook_dimensions_with_long_or_empty_title(self):
        source = Image.new("RGBA", (900, 700), (30, 70, 110, 255))
        with patch.object(image_generator, "LOGO_PATH", "missing-logo.png"), patch.object(
            image_generator, "FB_ICON_PATH", "missing-fb.png"
        ), patch.object(image_generator, "IG_ICON_PATH", "missing-ig.png"):
            instagram = image_generator.generate_post(
                {"titulo": "Título " * 80, "seccion": "sociedad"},
                image_generator.IG_W,
                image_generator.IG_H,
                preloaded_img=source,
            )
            facebook = image_generator.generate_post(
                {"titulo": "", "seccion": "sociedad"},
                image_generator.FB_W,
                image_generator.FB_H,
                preloaded_img=source,
            )
        self.assertEqual(instagram.size, (1080, 1350))
        self.assertEqual(facebook.size, (1200, 630))

    def test_missing_remote_image_still_returns_structural_fallback(self):
        with patch.object(image_generator, "_download", return_value=None):
            result = image_generator.generate_instagram(
                {"titulo": "Nota sin imagen", "seccion": "sociedad"}
            )
        self.assertEqual(result.size, (1080, 1350))


class WebMediaFallbackTests(unittest.TestCase):
    def test_og_failure_falls_back_to_verified_main_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.webp"
            source.write_bytes(image_bytes("WEBP"))
            with patch.object(media, "generate_og_image", return_value=source), patch.object(
                media.r2_storage,
                "upload_file",
                side_effect=RuntimeError("r2 down"),
            ):
                result = media.upload_og_image(
                    source,
                    "digest",
                    "Título",
                    "https://media.example/main.webp",
                )
        self.assertEqual(result, "https://media.example/main.webp")


if __name__ == "__main__":
    unittest.main()
