"""Fixtures + contact sheet del rediseño "Editorial Cinemática Riojana".

Renderiza casos reales (títulos corto/largo, fotos horizontal/vertical/
clara/oscura, sin foto, policiales/política/deportes, y un carrusel premium
de 5 slides en los 3 modos) comparando el diseño anterior (Pillow, sin
tocar) contra el sistema nuevo (Remotion, vía los mismos puntos de entrada
que usa el pipeline real: ``layout.image_generator.generate_instagram_with_engine``
y ``utils.premium_renderer.render_package_remotion``).

Usa fotografía real de ``FotosLVR/`` (banco existente del proyecto) — nunca
descarga ni inventa contenido nuevo. No toca ``data/``/``output/`` productivo
ni publica nada; la salida va a ``docs/design/editorial-cinematica/``.

Uso:
    python scripts/generate_visual_contact_sheet.py
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
FOTOS_DIR = os.path.join(BASE_DIR, "FotosLVR")
OUT_DIR = os.path.join(BASE_DIR, "docs", "design", "editorial-cinematica")
BEFORE_AFTER_DIR = os.path.join(OUT_DIR, "before_after")

THUMB_W = 340
LABEL_H = 34
PAD = 16


def _photo(name: str) -> str:
    path = os.path.join(FOTOS_DIR, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"fixture de foto no encontrada: {path}")
    return path


# ── Fixtures de la card automática ──────────────────────────────────────
# Cada una cubre al menos uno de los casos pedidos: título corto/largo,
# horizontal/vertical/clara/oscura/sin foto, policiales/política/deportes.
AUTOMATIC_FIXTURES = [
    {
        "id": "policiales_corto",
        "label": "Policiales · título corto · horizontal",
        "titulo": "Detuvieron a un hombre por robo en el centro",
        "seccion": "policiales",
        "imagen": _photo("policiales_4ce973fa681bda75135ce07a5682f1138d61f228_opt.jpg"),
        "highlight_terms": ["Detuvieron"],
    },
    {
        "id": "politica_largo_oscura",
        "label": "Política · título muy largo · foto oscura",
        "titulo": (
            "El gobierno provincial anunció un plan integral de obras públicas que incluye "
            "pavimentación, alumbrado y desagües pluviales en distintos departamentos de La Rioja"
        ),
        "seccion": "politica",
        "imagen": _photo("nuevarioja_politica_67aa8562791b9d92ca91b106f4e12b9550743af3_opt.jpg"),
        "highlight_terms": ["obras públicas"],
    },
    {
        "id": "deportes_vertical",
        "label": "Deportes · foto vertical (retrato)",
        "titulo": "Un riojano se consagró campeón provincial de ciclismo de montaña",
        "seccion": "deportes",
        "imagen": _photo("deportes_b0d92a03ba33b4bbad695fe0288b2d2d0a050f5b_opt.jpg"),
        "highlight_terms": ["campeón"],
    },
    {
        "id": "deportes_clara",
        "label": "Deportes · foto muy clara",
        "titulo": "La selección riojana debuta este fin de semana en el torneo regional",
        "seccion": "deportes",
        "imagen": _photo("nuevarioja_deportes_45a6c770648ac98add4657a69e4e23011488b053_opt.jpg"),
        "highlight_terms": [],
    },
    {
        "id": "sociedad_sin_foto",
        "label": "Sociedad · sin fotografía (fallback)",
        "titulo": "Vecinos de Aimogasta reclaman por el estado de la ruta provincial 26",
        "seccion": "sociedad",
        "imagen": None,
        "highlight_terms": ["ruta provincial"],
    },
    {
        "id": "politica_horizontal",
        "label": "Política · foto horizontal panorámica",
        "titulo": "El gobierno recibió a intendentes de toda la provincia",
        "seccion": "politica",
        "imagen": _photo("nuevarioja_politica_b23fe4887997f1e6bfe91538bf019d72fe21d4ba_opt.jpg"),
        "highlight_terms": [],
    },
]


def _orientation(path: str | None) -> str | None:
    if not path:
        return None
    with Image.open(path) as im:
        w, h = im.size
    return "landscape" if w > h else ("portrait" if h > w else "square")


def _render_automatic_old(fixture: dict) -> Image.Image:
    from layout.image_generator import IG_H, IG_W, generate_post

    preloaded = None
    if fixture["imagen"]:
        preloaded = Image.open(fixture["imagen"]).convert("RGBA")
    article = {"titulo": fixture["titulo"], "seccion": fixture["seccion"], "imagen_url": ""}
    return generate_post(article, IG_W, IG_H, preloaded_img=preloaded)


def _render_automatic_new(fixture: dict) -> Image.Image:
    from utils.remotion_renderer import render_still

    props = {
        "titulo": fixture["titulo"],
        "seccion": fixture["seccion"],
        "assetFile": "",
        "highlightTerms": fixture["highlight_terms"],
    }
    orientation = _orientation(fixture["imagen"])
    if orientation:
        props["assetOrientation"] = orientation
    asset_paths = {"assetFile": fixture["imagen"]} if fixture["imagen"] else {}
    png_bytes, _meta = render_still("AutomaticInstagramCard", props, asset_paths=asset_paths)
    return Image.open(io.BytesIO(png_bytes)).convert("RGB")


# ── Carrusel premium: mismo contenido, 3 modos ──────────────────────────
def _build_premium_package(template: str) -> dict:
    from utils.premium_contract import add_slide, new_package

    package = new_package(
        title="La Legislatura aprobó el presupuesto 2026 tras un debate de diez horas",
        section="politica",
        template=template,
    )
    package["highlight_terms"] = ["presupuesto 2026"]
    add_slide(package, "cover", title="La Legislatura aprobó el presupuesto 2026 tras un debate de diez horas")
    add_slide(
        package,
        "image_text",
        title="Diez horas de sesión",
        text="El oficialismo consiguió los votos necesarios pasada la medianoche.",
    )
    add_slide(
        package,
        "key_points",
        title="Puntos clave",
        items=["Aumenta la obra pública", "Sube el presupuesto educativo", "Se crea un fondo de emergencia"],
    )
    add_slide(package, "number", items=["10"], text="horas duró el debate en el recinto")
    add_slide(package, "closing", text="Seguí la cobertura completa en nuestras redes")
    return package


def _render_premium_new(template: str) -> list[Image.Image]:
    from utils.premium_renderer import render_package_remotion

    package = _build_premium_package(template)
    images_bytes, _warnings = render_package_remotion(package)
    return [Image.open(io.BytesIO(b)).convert("RGB") for b in images_bytes]


def _render_premium_old(template: str) -> list[Image.Image]:
    from utils.premium_renderer import render_package_bytes

    package = _build_premium_package(template)
    images_bytes, _warnings = render_package_bytes(package)
    return [Image.open(io.BytesIO(b)).convert("RGB") for b in images_bytes]


# ── Contact sheet ────────────────────────────────────────────────────────
def _label_font(size: int) -> ImageFont.FreeTypeFont:
    for path in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _thumb(img: Image.Image, width: int = THUMB_W) -> Image.Image:
    ratio = width / img.width
    return img.resize((width, int(img.height * ratio)), Image.LANCZOS)


def _grid_sheet(title: str, col_headers: list[str], row_labels: list[str], cells: list[list[Image.Image]]) -> Image.Image:
    thumbs = [[_thumb(cell) for cell in row] for row in cells]
    cell_h = max(t.height for row in thumbs for t in row)
    row_label_w = 300
    col_w = THUMB_W + PAD
    n_cols = len(col_headers)
    n_rows = len(row_labels)

    sheet_w = row_label_w + col_w * n_cols + PAD
    sheet_h = 70 + (LABEL_H + cell_h + PAD) * n_rows + LABEL_H
    sheet = Image.new("RGB", (sheet_w, sheet_h), "#0B0B0B")
    draw = ImageDraw.Draw(sheet)

    draw.text((PAD, 18), title, font=_label_font(28), fill="#FFFFFF")

    header_y = 62
    for c, header in enumerate(col_headers):
        x = row_label_w + c * col_w
        draw.text((x, header_y), header, font=_label_font(18), fill="#B30000")

    label_font = _label_font(15)
    y = header_y + LABEL_H
    for r, row_label in enumerate(row_labels):
        lines = row_label.split(" · ")
        text_y = y + cell_h // 2 - (len(lines) * 20) // 2
        for line in lines:
            draw.text((PAD, text_y), line, font=label_font, fill="#DDDDDD")
            text_y += 20
        for c in range(n_cols):
            x = row_label_w + c * col_w
            sheet.paste(thumbs[r][c], (x, y))
        y += cell_h + PAD

    return sheet


def main() -> int:
    os.makedirs(BEFORE_AFTER_DIR, exist_ok=True)

    print("Renderizando fixtures de card automática (actual vs nuevo)...")
    auto_cells: list[list[Image.Image]] = []
    auto_labels: list[str] = []
    for fixture in AUTOMATIC_FIXTURES:
        print(f"  - {fixture['id']}")
        old_img = _render_automatic_old(fixture)
        new_img = _render_automatic_new(fixture)
        old_img.save(os.path.join(BEFORE_AFTER_DIR, f"{fixture['id']}_actual.jpg"), "JPEG", quality=92)
        new_img.save(os.path.join(BEFORE_AFTER_DIR, f"{fixture['id']}_nuevo.jpg"), "JPEG", quality=92)
        auto_cells.append([old_img, new_img])
        auto_labels.append(fixture["label"])

    auto_sheet = _grid_sheet(
        "Card automática — diseño actual vs Editorial Cinemática Riojana",
        ["Actual (Pillow)", "Nuevo (Remotion)"],
        auto_labels,
        auto_cells,
    )
    auto_sheet_path = os.path.join(OUT_DIR, "contact_sheet_automatico.png")
    auto_sheet.save(auto_sheet_path)
    print("Guardado:", auto_sheet_path)

    print("Renderizando carrusel premium en los 3 modos (Crónica/Editorial/Datos)...")
    modes = [("lvr_cronica", "Crónica"), ("lvr_visual", "Editorial"), ("lvr_datos", "Datos")]
    slide_labels = ["cover", "image_text", "key_points", "number", "closing"]
    mode_slides = {}
    for template, label in modes:
        mode_slides[label] = _render_premium_new(template)
    old_slides = _render_premium_old("lvr_cronica")

    premium_cells = []
    for i, slide_label in enumerate(slide_labels):
        row = [old_slides[i]] + [mode_slides[label][i] for _, label in modes]
        premium_cells.append(row)
        for _, label in modes:
            mode_slides[label][i].save(
                os.path.join(BEFORE_AFTER_DIR, f"premium_{slide_label}_{label.lower()}.jpg"), "JPEG", quality=92
            )
        old_slides[i].save(os.path.join(BEFORE_AFTER_DIR, f"premium_{slide_label}_actual.jpg"), "JPEG", quality=92)

    premium_sheet = _grid_sheet(
        "Carrusel premium — diseño actual vs Crónica / Editorial / Datos",
        ["Actual (Pillow)"] + [label for _, label in modes],
        slide_labels,
        premium_cells,
    )
    premium_sheet_path = os.path.join(OUT_DIR, "contact_sheet_premium.png")
    premium_sheet.save(premium_sheet_path)
    print("Guardado:", premium_sheet_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
