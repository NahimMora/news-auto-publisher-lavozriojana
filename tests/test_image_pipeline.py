import io
import os
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


class AutomaticInstagramEngineDispatchTests(unittest.TestCase):
    """generate_instagram_with_engine (Editorial Cinemática Riojana, ver
    docs/DECISIONS.md) — dispatch mockeado, sin depender de Node/Remotion
    real. Mismo patrón que RemotionEngineDispatchTests en
    tests/test_remotion_visual.py."""

    ARTICLE = {"titulo": "Detuvieron a un hombre en un control policial", "seccion": "policiales"}

    def test_pillow_engine_uses_generate_post_and_returns_pillow(self):
        with patch("utils.remotion_renderer.resolve_engine", return_value="pillow"):
            jpeg_bytes, engine = image_generator.generate_instagram_with_engine(self.ARTICLE)
        self.assertEqual(engine, "pillow")
        self.assertEqual(jpeg_bytes[:2], b"\xff\xd8")
        with Image.open(io.BytesIO(jpeg_bytes)) as img:
            self.assertEqual(img.size, (image_generator.IG_W, image_generator.IG_H))

    def test_remotion_engine_success_returns_remotion(self):
        fake_png = io.BytesIO()
        Image.new("RGB", (1080, 1350), (10, 10, 10)).save(fake_png, "PNG")
        with patch("utils.remotion_renderer.resolve_engine", return_value="remotion"), patch(
            "utils.remotion_renderer.render_still", return_value=(fake_png.getvalue(), {"engine": "remotion"})
        ) as render_still_mock:
            jpeg_bytes, engine = image_generator.generate_instagram_with_engine(self.ARTICLE)
        self.assertEqual(engine, "remotion")
        self.assertEqual(jpeg_bytes[:2], b"\xff\xd8")
        render_still_mock.assert_called_once()
        self.assertEqual(render_still_mock.call_args.args[0], "AutomaticInstagramCard")

    def test_remotion_engine_failure_falls_back_to_pillow(self):
        from utils.remotion_renderer import RemotionRenderError

        with patch("utils.remotion_renderer.resolve_engine", return_value="remotion"), patch(
            "utils.remotion_renderer.render_still", side_effect=RemotionRenderError("boom")
        ):
            jpeg_bytes, engine = image_generator.generate_instagram_with_engine(self.ARTICLE)
        self.assertEqual(engine, "pillow")
        self.assertEqual(jpeg_bytes[:2], b"\xff\xd8")

    def test_remotion_unavailable_raises_instead_of_silent_fallback(self):
        from utils.remotion_renderer import RemotionRenderError

        with patch("utils.remotion_renderer.resolve_engine", return_value="remotion_unavailable"):
            with self.assertRaises(RemotionRenderError):
                image_generator.generate_instagram_with_engine(self.ARTICLE)

    def test_local_image_orientation_detected_without_reopening_after_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "landscape.jpg"
            Image.new("RGB", (900, 500), (10, 20, 30)).save(path, "JPEG")
            article = {**self.ARTICLE, "imagen": str(path)}
            local_path, orientation, cleanup = image_generator._materialize_image_for_remotion(article)
            try:
                self.assertEqual(local_path, str(path))
                self.assertEqual(orientation, "landscape")
            finally:
                cleanup()
            self.assertTrue(path.is_file())  # nunca borra un archivo que no creó

    def test_preloaded_image_materializes_to_temp_file_and_cleans_up(self):
        preloaded = Image.new("RGBA", (600, 900), (5, 5, 5, 255))
        local_path, orientation, cleanup = image_generator._materialize_image_for_remotion(
            self.ARTICLE, preloaded_img=preloaded,
        )
        self.assertTrue(os.path.isfile(local_path))
        self.assertEqual(orientation, "portrait")
        cleanup()
        self.assertFalse(os.path.isfile(local_path))

    def test_no_image_available_returns_none_without_error(self):
        with patch.object(image_generator, "_download", return_value=None):
            local_path, orientation, cleanup = image_generator._materialize_image_for_remotion(self.ARTICLE)
        self.assertIsNone(local_path)
        self.assertIsNone(orientation)
        cleanup()  # no-op, no debe lanzar


REMOTION_NODE_MODULES = Path(__file__).resolve().parents[1] / "remotion" / "node_modules"


@unittest.skipUnless(
    str(os.getenv("REMOTION_LIVE_TESTS", "auto")).strip().lower() != "skip" and REMOTION_NODE_MODULES.is_dir(),
    "remotion/node_modules no está instalado en este entorno; se omite el render real "
    "(set REMOTION_LIVE_TESTS=skip para omitir explícitamente aunque esté instalado)",
)
class AutomaticInstagramLiveRenderTests(unittest.TestCase):
    """Render real de punta a punta de generate_instagram_with_engine contra
    Remotion (servidor persistente o subprocess de red, ver
    utils/remotion_renderer.py). Mismo criterio de skip que
    tests/test_remotion_visual.py::RemotionLiveRenderTests."""

    @classmethod
    def setUpClass(cls):
        from utils.remotion_renderer import remotion_available

        if not remotion_available(force_recheck=True):
            raise unittest.SkipTest("Remotion CLI no respondió (Node/npx no operativo en este entorno)")

    def test_generates_via_remotion_end_to_end(self):
        article = {
            "titulo": "La Legislatura debate el presupuesto 2026 en sesión extraordinaria",
            "seccion": "politica",
            "highlight_terms": ["presupuesto 2026"],
        }
        with patch.dict(os.environ, {"AUTOMATIC_STATIC_RENDER_ENGINE": "remotion"}, clear=False):
            jpeg_bytes, engine = image_generator.generate_instagram_with_engine(article)
        self.assertEqual(engine, "remotion")
        self.assertEqual(jpeg_bytes[:2], b"\xff\xd8")
        with Image.open(io.BytesIO(jpeg_bytes)) as img:
            self.assertEqual(img.size, (image_generator.IG_W, image_generator.IG_H))


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
