"""Cobertura del render Remotion del clip de video paparazzi (carrusel
imagen+video) y su fallback PIL/ffmpeg cuando Remotion/Node no está
disponible — ver docs/DECISIONS.md, remotion/src/PaparazziClip.tsx."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import video_renderer
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _touch(path: str, content: bytes = b"fake-mp4") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)


class RenderRemotionPaparazziClipTests(unittest.TestCase):
    def test_returns_none_when_remotion_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(video_renderer, "REMOTION_DIR", os.path.join(tmp, "no-remotion")):
                result = video_renderer._render_remotion_paparazzi_clip("source.mp4", "espectaculos", 30)
        self.assertIsNone(result)

    def test_success_calls_paparazzi_clip_composition_with_correct_props(self):
        with tempfile.TemporaryDirectory() as tmp:
            remotion_dir = Path(tmp) / "remotion"
            (remotion_dir / "public" / "tmp").mkdir(parents=True)
            renders_dir = Path(tmp) / "renders"
            renders_dir.mkdir()
            source = Path(tmp) / "trimmed.mp4"
            source.write_bytes(b"trimmed-source")

            captured = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                props_arg = next(part for part in cmd if part.startswith("--props="))
                captured["props"] = json.loads(Path(props_arg.split("=", 1)[1]).read_text(encoding="utf-8"))
                output = Path(cmd[cmd.index("PaparazziClip") + 1])
                output.write_bytes(b"fake-branded-clip")
                return FakeCompletedProcess(returncode=0)

            with patch.object(video_renderer, "REMOTION_DIR", str(remotion_dir)), patch.object(
                video_renderer, "RENDERS_DIR", str(renders_dir)
            ), patch.object(video_renderer.subprocess, "run", side_effect=fake_run):
                result = video_renderer._render_remotion_paparazzi_clip(str(source), "espectaculos", 45)

            self.assertIsNotNone(result)
            self.assertTrue(os.path.isfile(result))

        self.assertIn("PaparazziClip", captured["cmd"])
        self.assertEqual("espectaculos", captured["props"]["seccion"])
        self.assertEqual(45 * 30, captured["props"]["durationInFrames"])
        self.assertTrue(captured["props"]["assetFile"].startswith("tmp/"))

    def test_subprocess_failure_returns_none_not_an_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            remotion_dir = Path(tmp) / "remotion"
            (remotion_dir / "public" / "tmp").mkdir(parents=True)
            renders_dir = Path(tmp) / "renders"
            renders_dir.mkdir()
            source = Path(tmp) / "trimmed.mp4"
            source.write_bytes(b"trimmed-source")

            with patch.object(video_renderer, "REMOTION_DIR", str(remotion_dir)), patch.object(
                video_renderer, "RENDERS_DIR", str(renders_dir)
            ), patch.object(
                video_renderer.subprocess,
                "run",
                return_value=FakeCompletedProcess(returncode=1, stderr="boom"),
            ):
                result = video_renderer._render_remotion_paparazzi_clip(str(source), "espectaculos", 45)

        self.assertIsNone(result)

    def test_temp_asset_and_props_are_cleaned_up_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            remotion_dir = Path(tmp) / "remotion"
            (remotion_dir / "public" / "tmp").mkdir(parents=True)
            renders_dir = Path(tmp) / "renders"
            renders_dir.mkdir()
            source = Path(tmp) / "trimmed.mp4"
            source.write_bytes(b"trimmed-source")

            def fake_run(cmd, **kwargs):
                output = Path(cmd[cmd.index("PaparazziClip") + 1])
                output.write_bytes(b"fake-branded-clip")
                return FakeCompletedProcess(returncode=0)

            with patch.object(video_renderer, "REMOTION_DIR", str(remotion_dir)), patch.object(
                video_renderer, "RENDERS_DIR", str(renders_dir)
            ), patch.object(video_renderer.subprocess, "run", side_effect=fake_run):
                video_renderer._render_remotion_paparazzi_clip(str(source), "espectaculos", 10)

            tmp_assets = list((remotion_dir / "public" / "tmp").iterdir())
            self.assertEqual([], tmp_assets, "el asset temporal copiado a remotion/public/tmp debe borrarse")


class RenderPaparazziClipsEngineSelectionTests(unittest.TestCase):
    """render_paparazzi_clips debe usar Remotion cuando está disponible y
    caer al overlay PIL/ffmpeg cuando no — mismo patrón que render_video()
    con Main/EditorialReel."""

    def _fake_source(self, path: str):
        return path, OperationResult(StageStatus.SUCCESS)

    def test_uses_remotion_engine_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            remotion_dir = Path(tmp) / "remotion"
            (remotion_dir / "public" / "tmp").mkdir(parents=True)
            renders_dir = Path(tmp) / "renders"
            renders_dir.mkdir()
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"source-video")

            def fake_run(cmd, **kwargs):
                if "ffmpeg" in cmd[0]:
                    # el recorte previo (_ffmpeg_trim_clip)
                    output = Path(cmd[-1])
                    output.write_bytes(b"trimmed")
                    return FakeCompletedProcess(returncode=0)
                # npx remotion render PaparazziClip <output> ...
                output = Path(cmd[cmd.index("PaparazziClip") + 1])
                output.write_bytes(b"branded")
                return FakeCompletedProcess(returncode=0)

            with patch.object(video_renderer, "REMOTION_DIR", str(remotion_dir)), patch.object(
                video_renderer, "RENDERS_DIR", str(renders_dir)
            ), patch.object(
                video_renderer, "check_ffmpeg", return_value=True
            ), patch.object(
                video_renderer, "get_source_video", return_value=self._fake_source(str(source))
            ), patch.object(
                video_renderer, "get_video_duration", return_value=30.0
            ), patch.object(video_renderer.subprocess, "run", side_effect=fake_run):
                paths, info = video_renderer.render_paparazzi_clips(
                    {"titulo": "x", "seccion": "espectaculos", "video_url": "https://x/y.mp4"}
                )

        self.assertEqual(1, len(paths))
        self.assertEqual("remotion", info["engine"])

    def test_falls_back_to_pillow_ffmpeg_when_remotion_dir_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            renders_dir = Path(tmp) / "renders"
            renders_dir.mkdir()
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"source-video")

            def fake_run(cmd, **kwargs):
                output = Path(cmd[-1])
                output.write_bytes(b"composed")
                return FakeCompletedProcess(returncode=0)

            with patch.object(
                video_renderer, "REMOTION_DIR", os.path.join(tmp, "no-remotion")
            ), patch.object(video_renderer, "RENDERS_DIR", str(renders_dir)), patch.object(
                video_renderer, "check_ffmpeg", return_value=True
            ), patch.object(
                video_renderer, "get_source_video", return_value=self._fake_source(str(source))
            ), patch.object(
                video_renderer, "get_video_duration", return_value=30.0
            ), patch.object(video_renderer.subprocess, "run", side_effect=fake_run):
                paths, info = video_renderer.render_paparazzi_clips(
                    {"titulo": "x", "seccion": "espectaculos", "video_url": "https://x/y.mp4"}
                )

        self.assertEqual(1, len(paths))
        self.assertEqual("ffmpeg_fallback", info["engine"])

    def test_falls_back_to_pillow_ffmpeg_when_remotion_render_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            remotion_dir = Path(tmp) / "remotion"
            (remotion_dir / "public" / "tmp").mkdir(parents=True)
            renders_dir = Path(tmp) / "renders"
            renders_dir.mkdir()
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"source-video")

            def fake_run(cmd, **kwargs):
                if "ffmpeg" in cmd[0]:
                    output = Path(cmd[-1])
                    output.write_bytes(b"composed-or-trimmed")
                    return FakeCompletedProcess(returncode=0)
                # el render Remotion siempre falla en este test
                return FakeCompletedProcess(returncode=1, stderr="remotion boom")

            with patch.object(video_renderer, "REMOTION_DIR", str(remotion_dir)), patch.object(
                video_renderer, "RENDERS_DIR", str(renders_dir)
            ), patch.object(
                video_renderer, "check_ffmpeg", return_value=True
            ), patch.object(
                video_renderer, "get_source_video", return_value=self._fake_source(str(source))
            ), patch.object(
                video_renderer, "get_video_duration", return_value=30.0
            ), patch.object(video_renderer.subprocess, "run", side_effect=fake_run):
                paths, info = video_renderer.render_paparazzi_clips(
                    {"titulo": "x", "seccion": "espectaculos", "video_url": "https://x/y.mp4"}
                )

        self.assertEqual(1, len(paths))
        self.assertEqual("ffmpeg_fallback", info["engine"])


if __name__ == "__main__":
    unittest.main()
