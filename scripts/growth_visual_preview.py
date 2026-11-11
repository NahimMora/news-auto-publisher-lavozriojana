"""Previews ANTES/DESPUÉS de las reglas visuales de crecimiento (T02).

Renderiza los cinco casos reales del plan maestro (sección 9.4) y casos de
estrés con los MISMOS puntos de entrada que usa producción
(``generate_facebook_with_engine`` para el OG 1200×630 y
``generate_instagram_with_engine`` para el post 1080×1350), una vez con
``GROWTH_IMAGE_RULES_ENABLED=false`` (comportamiento actual) y otra con
``true``. Nunca publica ni sube nada: todo queda en ``--out``.

Aísla estado, logs y salidas con ``LVR_*_DIR`` temporales antes de importar
el proyecto. Las fotos reales se leen de ``--media-dir`` (sólo lectura).

Uso:
    python scripts/growth_visual_preview.py --out C:/LVR-QA/growth-t02 \
        --media-dir C:/LVR/output/web_media [--baseline-dir DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

_QA_ROOT = os.path.join(tempfile.gettempdir(), "lvr-qa-growth")
for _name in ("DATA", "LOGS", "OUTPUT", "FOTOS"):
    os.environ[f"LVR_{_name}_DIR"] = os.path.join(_QA_ROOT, _name.lower())
    os.makedirs(os.environ[f"LVR_{_name}_DIR"], exist_ok=True)
# Igual que producción (scripts/start_24x7_production.ps1), motor explícito.
os.environ["VISUAL_STYLE_VERSION"] = "v2"
os.environ["AUTOMATIC_STATIC_RENDER_ENGINE"] = "remotion"
os.environ["OG_STATIC_RENDER_ENGINE"] = "remotion"
os.environ.pop("GROWTH_IMAGE_RULES_ENABLED", None)
os.environ.pop("GROWTH_IMAGE_RULES_WORKFLOWS", None)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_QA_ROOT, "no-existe.env"))  # nunca carga el .env real

import psutil  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

CASES_PATH = os.path.join(BASE_DIR, "tests", "fixtures", "growth_visual", "cases.json")
FONT_PATH = os.path.join(BASE_DIR, "remotion", "public", "fonts", "Archivo[wdth,wght].ttf")
MOBILE_W = 360


def _font(size: int, weight: int = 700) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(FONT_PATH, size)
    try:
        font.set_variation_by_axes([weight, 100])
    except (OSError, ValueError):
        pass
    return font


def synthetic_photo(seed: str, size=(1200, 800)) -> Image.Image:
    """Foto sintética determinística para casos de estrés (sin terceros)."""
    digest = hashlib.sha256(seed.encode()).digest()
    img = Image.new("RGB", size, (digest[0] // 2, digest[1] // 2, 60 + digest[2] // 3))
    draw = ImageDraw.Draw(img)
    for i in range(12):
        x = digest[i] * size[0] // 256
        y = digest[i + 12] * size[1] // 256
        r = 40 + digest[i + 4] // 3
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(120 + digest[i] // 3, 90, 70 + digest[i + 2] // 4))
    return img


def _node_rss_mb() -> float | None:
    info_path = os.path.join(BASE_DIR, "remotion", ".render-server.json")
    try:
        with open(info_path, encoding="utf-8") as fh:
            pid = int(json.load(fh).get("pid"))
        proc = psutil.Process(pid)
        return round(sum(p.memory_info().rss for p in [proc, *proc.children(recursive=True)]) / 1e6, 1)
    except (OSError, ValueError, TypeError, psutil.Error):
        return None


def _render(kind: str, article: dict, photo: Image.Image | None, growth: bool) -> tuple[bytes, str, float]:
    from layout.image_generator import generate_facebook_with_engine, generate_instagram_with_engine

    os.environ["GROWTH_IMAGE_RULES_ENABLED"] = "true" if growth else "false"
    started = time.perf_counter()
    fn = generate_facebook_with_engine if kind == "og" else generate_instagram_with_engine
    data, engine = fn(dict(article), preloaded_img=photo.convert("RGBA") if photo is not None else None)
    return data, engine, (time.perf_counter() - started) * 1000


def _label(img: Image.Image, text: str, width: int) -> Image.Image:
    img = img.copy()
    img.thumbnail((width, 10_000))
    canvas = Image.new("RGB", (img.width, img.height + 44), "#ffffff")
    canvas.paste(img, (0, 44))
    ImageDraw.Draw(canvas).text((4, 8), text, fill="#111111", font=_font(24, 800))
    return canvas


def _sheet(images: list[Image.Image], title: str, gap: int = 24) -> Image.Image:
    width = sum(i.width for i in images) + gap * (len(images) + 1)
    height = max(i.height for i in images) + gap * 2 + 56
    sheet = Image.new("RGB", (width, height), "#e7e3da")
    ImageDraw.Draw(sheet).text((gap, 14), title, fill="#111111", font=_font(30, 800))
    x = gap
    for img in images:
        sheet.paste(img, (x, 56 + gap))
        x += img.width + gap
    return sheet


def _mobile(images: list[tuple[str, Image.Image]]) -> Image.Image:
    """Lado a lado a 360 px de ancho: tamaño real de lectura en un celular (1×)."""
    tiles = []
    for label, img in images:
        small = img.copy()
        small = small.resize((MOBILE_W, round(img.height * MOBILE_W / img.width)), Image.LANCZOS)
        tiles.append(_label(small, label, MOBILE_W))
    return _sheet(tiles, "Lectura en celular (360 px, sin zoom)", gap=20)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--media-dir", required=True)
    parser.add_argument("--baseline-dir", default="", help="Renders previos con el flag apagado para comparar paridad")
    parser.add_argument("--only-off", action="store_true", help="Sólo el comportamiento actual (línea base)")
    args = parser.parse_args()

    with open(CASES_PATH, encoding="utf-8") as fh:
        cases = json.load(fh)["cases"]
    os.makedirs(args.out, exist_ok=True)
    report = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": []}
    process = psutil.Process()

    for case in cases:
        case_dir = os.path.join(args.out, case["id"])
        os.makedirs(case_dir, exist_ok=True)
        if case["kind"] == "real":
            with Image.open(os.path.join(args.media_dir, case["photo"])) as opened:
                photo = opened.convert("RGB")
            published = os.path.join(args.media_dir, case["published_og"])
            if os.path.isfile(published):
                shutil.copyfile(published, os.path.join(case_dir, "og_00_publicado.jpg"))
        else:
            photo = synthetic_photo(case["id"])
        # Mismos campos que pipeline/node_webapp/media.py::generate_og_image.
        og_article = {"titulo": case["titulo"], "seccion": case["seccion"], "imagen_url": ""}
        ig_article = {
            "titulo": case["titulo"], "seccion": case["seccion"], "imagen_url": "",
            "locality": case.get("locality", ""), "deck": case.get("deck", ""), "breaking": bool(case.get("breaking")),
        }
        entry = {"id": case["id"], "kind": case["kind"], "renders": {}}
        for kind, article in (("og", og_article), ("ig", ig_article)):
            for growth in ((False,) if args.only_off else (False, True)):
                rss_before = process.memory_info().rss
                data, engine, ms = _render(kind, article, photo, growth)
                name = f"{kind}_{'02_despues' if growth else '01_antes'}.jpg"
                with open(os.path.join(case_dir, name), "wb") as fh:
                    fh.write(data)
                with Image.open(io.BytesIO(data)) as rendered:
                    size = rendered.size
                parity = None
                if not growth and args.baseline_dir:
                    base = os.path.join(args.baseline_dir, case["id"], name)
                    if os.path.isfile(base):
                        with Image.open(base) as a, Image.open(io.BytesIO(data)) as b:
                            parity = a.size == b.size and a.convert("RGB").tobytes() == b.convert("RGB").tobytes()
                entry["renders"][name] = {
                    "engine": engine, "ms": round(ms), "bytes": len(data), "size": size,
                    "python_rss_delta_mb": round((process.memory_info().rss - rss_before) / 1e6, 1),
                    "node_rss_mb": _node_rss_mb(), "parity_with_baseline": parity,
                }
        if not args.only_off:
            published_path = os.path.join(case_dir, "og_00_publicado.jpg")
            og_before = Image.open(os.path.join(case_dir, "og_01_antes.jpg")).convert("RGB")
            og_after = Image.open(os.path.join(case_dir, "og_02_despues.jpg")).convert("RGB")
            ig_before = Image.open(os.path.join(case_dir, "ig_01_antes.jpg")).convert("RGB")
            ig_after = Image.open(os.path.join(case_dir, "ig_02_despues.jpg")).convert("RGB")
            tiles = []
            if os.path.isfile(published_path):
                tiles.append(_label(Image.open(published_path).convert("RGB"), "Publicado (original)", 600))
            tiles += [_label(og_before, "Antes (flag apagado)", 600), _label(og_after, "Después (reglas T02)", 600)]
            _sheet(tiles, f"{case['id']} · OG 1200×630").save(os.path.join(case_dir, "og_03_comparacion.jpg"), quality=90)
            _sheet(
                [_label(ig_before, "Antes (flag apagado)", 540), _label(ig_after, "Después (reglas T02)", 540)],
                f"{case['id']} · Instagram 1080×1350",
            ).save(os.path.join(case_dir, "ig_03_comparacion.jpg"), quality=90)
            _mobile([("OG antes", og_before), ("OG después", og_after)]).save(os.path.join(case_dir, "og_04_celular.png"))
            _mobile([("IG antes", ig_before), ("IG después", ig_after)]).save(os.path.join(case_dir, "ig_04_celular.png"))
        report["cases"].append(entry)
        print(json.dumps(entry, ensure_ascii=False))

    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
