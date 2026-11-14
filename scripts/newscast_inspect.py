"""Inspección visual y técnica de un noticiero renderizado (QA, sólo lectura).

Genera, junto al MP4 o en ``--out``:
  - ``hoja_1fps.jpg``: un cuadro por segundo de toda la edición;
  - ``apertura.jpg``: 0, 0,1, 0,25, 0,5, 1, 1,5, 2 y 3 s a 360 px (tamaño de
    teléfono): el primer segundo decide si se sigue mirando;
  - ``fronteras.jpg``: antes / en / después de cada cambio de historia y de
    toma (según ``visual_plan.json``) y entrada, sostén y último cuadro del cierre;
  - ``movil_360.jpg``: la hoja a 360×640 con la zona de interfaz de Reels
    sombreada (perfil conservador propio: arriba de y288 y abajo de y1248);
  - ``movil_ui.jpg``: cuadros clave a 360×640 con una interfaz de Reels
    simulada encima (barra superior, botones laterales, usuario/caption/audio):
    lo que tapa la app, no una especificación de Meta;
  - ``inspeccion.json``: formato, decodificación, negro, congelamiento,
    sonoridad, silencios, energía de movimiento por segundo y tramos
    estáticos (≥ 2,5 s con cambio medio < ``STATIC_DIFF`` sobre 255) y la
    duración de cada historia según el plan.

Uso:
    python scripts/newscast_inspect.py output/noticiero/2026-10-30/noticiero-2026-10-30.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from PIL import Image, ImageDraw  # noqa: E402

from utils.newscast_v3 import inspect_video  # noqa: E402

STATIC_DIFF = 1.2      # cambio medio por píxel (0–255) entre cuadros a 5 fps
STATIC_MIN_S = 2.5


def frame_at(video: str, seconds: float, width: int, dest: str) -> str:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, seconds):.3f}", "-i", video, "-frames:v", "1",
                    "-vf", f"scale={width}:-2", dest], check=True, capture_output=True, timeout=60)
    return dest


def reels_ui(im: Image.Image) -> Image.Image:
    """Interfaz de Reels aproximada sobre el cuadro (proporcional a 1080×1920)."""
    w, h = im.size
    sx, sy = w / 1080, h / 1920
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([0, 0, w, int(190 * sy)], fill=(0, 0, 0, 70))
    d.text((int(40 * sx), int(110 * sy)), "Reels", fill=(255, 255, 255, 230))
    for k, y in enumerate((1080, 1250, 1420, 1590)):
        cx, cy, r = int(1010 * sx), int(y * sy), int(34 * sx)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 230), width=max(1, int(5 * sx)))
    d.rectangle([0, int(1500 * sy), w, h], fill=(0, 0, 0, 90))
    d.ellipse([int(40 * sx), int(1560 * sy), int(110 * sx), int(1630 * sy)], fill=(255, 255, 255, 200))
    d.rectangle([int(130 * sx), int(1580 * sy), int(520 * sx), int(1610 * sy)], fill=(255, 255, 255, 200))
    d.rectangle([int(40 * sx), int(1670 * sy), int(880 * sx), int(1700 * sy)], fill=(255, 255, 255, 160))
    d.rectangle([int(40 * sx), int(1760 * sy), int(600 * sx), int(1785 * sy)], fill=(255, 255, 255, 140))
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


def sheet(paths: list[tuple[str, str]], cols: int, dest: str, ui: bool = False, app: bool = False) -> None:
    images = [(Image.open(p).convert("RGB"), label) for p, label in paths]
    w, h = images[0][0].size
    rows = (len(images) + cols - 1) // cols
    out = Image.new("RGB", (cols * w, rows * (h + 22)), "white")
    for k, (im, label) in enumerate(images):
        if ui:
            shade = Image.new("RGBA", im.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(shade)
            draw.rectangle([0, 0, w, int(h * 288 / 1920)], fill=(255, 0, 255, 70))
            draw.rectangle([0, int(h * 1248 / 1920), w, h], fill=(255, 0, 255, 70))
            draw.rectangle([int(w * 900 / 1080), 0, w, h], fill=(255, 0, 255, 40))
            im = Image.alpha_composite(im.convert("RGBA"), shade).convert("RGB")
        if app:
            im = reels_ui(im)
        x, y = (k % cols) * w, (k // cols) * (h + 22)
        out.paste(im, (x, y + 22))
        ImageDraw.Draw(out).text((x + 4, y + 4), label, fill="black")
    out.save(dest, quality=88)


def motion_profile(video: str, fps: int = 5, size: tuple[int, int] = (90, 160)) -> list[float]:
    """Cambio medio por píxel entre cuadros consecutivos (gris, 90×160)."""
    w, h = size
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, timeout=900).stdout
    n = w * h
    frames = [raw[k:k + n] for k in range(0, len(raw) - n + 1, n)]
    diffs = []
    for a, b in zip(frames, frames[1:]):
        diffs.append(round(sum(abs(x - y) for x, y in zip(a, b)) / n, 3))
    return diffs


def static_spans(diffs: list[float], fps: int = 5) -> list[list[float]]:
    spans, start = [], None
    for k, d in enumerate(diffs + [99.0]):
        if d < STATIC_DIFF and start is None:
            start = k
        elif d >= STATIC_DIFF and start is not None:
            if (k - start) / fps >= STATIC_MIN_S:
                spans.append([round(start / fps, 1), round(k / fps, 1)])
            start = None
    return spans


def silences(video: str) -> list[list[float]]:
    log = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", video, "-af", "silencedetect=n=-42dB:d=0.5", "-f", "null", "-"],
                         capture_output=True, text=True, timeout=600).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    return [[round(a, 2), round(b, 2)] for a, b in zip(starts, ends + [None] * len(starts)) if b is not None]


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspección del noticiero")
    parser.add_argument("video")
    parser.add_argument("--out", default="")
    opts = parser.parse_args()
    video = os.path.abspath(opts.video)
    out = opts.out or os.path.join(os.path.dirname(video), "inspeccion")
    os.makedirs(out, exist_ok=True)
    report = inspect_video(video)
    duration = report["duration"]
    plan_path = os.path.join(os.path.dirname(video), "visual_plan.json")
    plan = json.load(open(plan_path, encoding="utf-8")) if os.path.isfile(plan_path) else None
    with tempfile.TemporaryDirectory() as tmp:
        grab = lambda t, w=270: frame_at(video, t, w, os.path.join(tmp, f"{t:.3f}_{w}.jpg"))  # noqa: E731
        seconds = [float(t) for t in range(int(duration))]
        sheet([(grab(t), f"{t:.0f}s") for t in seconds], 10, os.path.join(out, "hoja_1fps.jpg"))
        sheet([(grab(t, 360), f"{t}s") for t in (0, 0.1, 0.25, 0.5, 1, 1.5, 2, 3)], 4, os.path.join(out, "apertura.jpg"))
        sheet([(grab(t, 180), f"{t:.0f}s") for t in seconds[::2]], 12, os.path.join(out, "movil_360.jpg"), ui=True)
        key = [0.0, 0.5, 1.5, 3.0]
        if plan:
            fps = plan["fps"]
            marks = []
            for s in plan["stories"]:
                for shot in s["shots"]:
                    marks.append((s["from"] + shot["from"]) / fps)
            marks.append(plan["outro"]["from"] / fps)
            tiles = []
            for m in sorted(set(marks))[1:]:
                for d, tag in ((-0.2, "antes"), (0.0, "corte"), (0.2, "después"), (0.5, "+0,5")):
                    tiles.append((grab(m + d, 216), f"{m:.1f}s {tag}"))
            end = plan["totalFrames"] / fps
            for t, tag in ((plan["outro"]["from"] / fps + 0.1, "cierre entra"), ((plan["outro"]["from"] / fps + end) / 2, "sostén"), (end - 0.05, "último")):
                tiles.append((grab(t, 216), tag))
            sheet(tiles, 8, os.path.join(out, "fronteras.jpg"))
            key += [(s["from"] + s["durationInFrames"] * 0.5) / fps for s in plan["stories"]] + [(plan["outro"]["from"] + 40) / fps]
            report["stories"] = [{"index": s["index"], "titulo": s.get("headline") or s.get("titulo"), "seconds": round(s["durationInFrames"] / fps, 2),
                                  "shots": len(s["shots"])} for s in plan["stories"]]
        sheet([(grab(t, 360), f"{t:.1f}s") for t in key if t < duration], 6, os.path.join(out, "movil_ui.jpg"), app=True)
    diffs = motion_profile(video)
    report["motion_per_second"] = [round(sum(diffs[k:k + 5]) / max(1, len(diffs[k:k + 5])), 2) for k in range(0, len(diffs), 5)]
    report["static_spans"] = static_spans(diffs)
    report["silences"] = silences(video)
    with open(os.path.join(out, "inspeccion.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k not in ("streams", "motion_per_second")}, ensure_ascii=False))
    print(f"Hojas en {out}")
    return 0 if report["decode_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
