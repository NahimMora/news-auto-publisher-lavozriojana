"""Renderer de slides premium.

``render_slide``/``render_package``/``render_package_bytes`` son el motor
Pillow interino de la Fase 3 — siguen existiendo tal cual para tests y como
fallback garantizado. ``render_package_with_engine`` (Fase 4) es el punto de
entrada real para preview/publicación: intenta Remotion primero
(``STATIC_RENDER_ENGINE=auto|remotion|pillow``, ver
``utils/remotion_renderer.py``) y cae a Pillow si no está disponible o el
modo lo pide explícitamente. Preview y publicación deben llamar exactamente
a la misma función — nunca un renderer distinto para cada uno.
"""
from __future__ import annotations

import io
import os
import re
import unicodedata

from PIL import Image, ImageDraw

from layout.image_generator import AZUL, ROJO, _font
from utils.logging_setup import setup_logger

logger = setup_logger("premium_renderer", "premium_renderer.log")

PREMIUM_SLIDE_COMPOSITION = "PremiumSlide"

SLIDE_W, SLIDE_H = 1080, 1350
NEGRO = "#0B0B0B"
BLANCO = "#FFFFFF"
BORDO = "#5A0E17"

_TEMPLATE_ACCENTS = {
    "lvr_cronica": ROJO,
    "lvr_datos": AZUL,
    "lvr_visual": BORDO,
}


def _ascii_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _accent_for(package: dict) -> str:
    return _TEMPLATE_ACCENTS.get(package.get("template"), ROJO)


def _wrap_text(draw: ImageDraw.Draw, text: str, font, max_width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _highlight_spans(text: str, terms: list[str]) -> list[tuple[str, bool]]:
    """Parte ``text`` en (fragmento, es_highlight) preservando tildes/mayúsculas."""
    if not terms:
        return [(text, False)]
    pattern = "|".join(re.escape(term) for term in terms if term.strip())
    if not pattern:
        return [(text, False)]
    regex = re.compile(rf"\b({pattern})\b", re.IGNORECASE | re.UNICODE)
    spans: list[tuple[str, bool]] = []
    last = 0
    for match in regex.finditer(text):
        if match.start() > last:
            spans.append((text[last : match.start()], False))
        spans.append((text[match.start() : match.end()], True))
        last = match.end()
    if last < len(text):
        spans.append((text[last:], False))
    return spans or [(text, False)]


def _draw_wrapped_highlighted(
    draw: ImageDraw.Draw,
    text: str,
    terms: list[str],
    *,
    font,
    max_width: int,
    x: int,
    y: int,
    line_height: int,
    fill: str,
    highlight_fill: str,
) -> int:
    """Dibuja texto envuelto con términos resaltados; devuelve la altura usada."""
    words_with_flags: list[tuple[str, bool]] = []
    for fragment, is_hl in _highlight_spans(text, terms):
        for word in fragment.split(" "):
            if word:
                words_with_flags.append((word, is_hl))

    lines: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    current_width = 0
    space_width = draw.textlength(" ", font=font)
    for word, is_hl in words_with_flags:
        word_width = draw.textlength(word, font=font)
        added_width = word_width + (space_width if current else 0)
        if current and current_width + added_width > max_width:
            lines.append(current)
            current = [(word, is_hl)]
            current_width = word_width
        else:
            current.append((word, is_hl))
            current_width += added_width
    if current:
        lines.append(current)

    cursor_y = y
    for line in lines:
        cursor_x = x
        for word, is_hl in line:
            color = highlight_fill if is_hl else fill
            draw.text((cursor_x, cursor_y), word, font=font, fill=color)
            cursor_x += draw.textlength(word + " ", font=font)
        cursor_y += line_height
    return cursor_y - y


def _base_canvas(accent: str) -> tuple[Image.Image, ImageDraw.Draw]:
    canvas = Image.new("RGB", (SLIDE_W, SLIDE_H), NEGRO)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, 14, SLIDE_H], fill=accent)
    return canvas, draw


def _paste_cover_image(canvas: Image.Image, image: Image.Image | None, *, box: tuple[int, int, int, int]) -> None:
    if image is None:
        return
    x0, y0, x1, y1 = box
    target_w, target_h = x1 - x0, y1 - y0
    source_ratio = image.width / image.height
    target_ratio = target_w / target_h
    if source_ratio > target_ratio:
        new_h = target_h
        new_w = int(new_h * source_ratio)
    else:
        new_w = target_w
        new_h = int(new_w / source_ratio)
    resized = image.resize((max(1, new_w), max(1, new_h)), Image.LANCZOS)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    cropped = resized.crop((left, top, left + target_w, top + target_h))
    canvas.paste(cropped, (x0, y0))


def render_slide(
    slide: dict,
    package: dict,
    *,
    asset_resolver=None,
) -> tuple[Image.Image, list[str]]:
    """Renderiza un slide. Devuelve (imagen, warnings) — nunca lanza por
    contenido faltante: degrada visualmente y deja constancia en warnings."""
    warnings: list[str] = []
    accent = _accent_for(package)
    canvas, draw = _base_canvas(accent)
    slide_type = slide.get("type")
    pad = 64

    image = None
    asset_id = str(slide.get("asset_id") or "").strip()
    if asset_id and asset_resolver:
        image = asset_resolver(asset_id)
        if image is None:
            warnings.append(f"slide_{slide.get('id')}_asset_no_resoluble:{asset_id}")
    elif slide_type in {"cover", "image_text", "full_image"}:
        warnings.append(f"slide_{slide.get('id')}_sin_imagen")

    title = slide.get("title") or (package.get("title") if slide_type == "cover" else "")
    text = slide.get("text") or ""
    highlights = slide.get("highlights") or package.get("highlight_terms") or []
    title_font = _font(64, bold=True)
    body_font = _font(38, bold=False)
    small_font = _font(30, bold=False)

    if slide_type in {"cover", "full_image"}:
        _paste_cover_image(canvas, image, box=(0, 0, SLIDE_W, SLIDE_H))
        overlay = Image.new("RGBA", (SLIDE_W, 420), (0, 0, 0, 160))
        canvas.paste(Image.alpha_composite(canvas.crop((0, SLIDE_H - 420, SLIDE_W, SLIDE_H)).convert("RGBA"), overlay).convert("RGB"), (0, SLIDE_H - 420))
        draw = ImageDraw.Draw(canvas)
        used_h = _draw_wrapped_highlighted(
            draw, title, highlights, font=title_font, max_width=SLIDE_W - 2 * pad,
            x=pad, y=SLIDE_H - 380, line_height=78, fill=BLANCO, highlight_fill=accent,
        )
        if used_h > 360:
            warnings.append(f"slide_{slide.get('id')}_titulo_desborda")

    elif slide_type == "image_text":
        _paste_cover_image(canvas, image, box=(0, 0, SLIDE_W, 700))
        draw = ImageDraw.Draw(canvas)
        used_h = _draw_wrapped_highlighted(
            draw, title, highlights, font=title_font, max_width=SLIDE_W - 2 * pad,
            x=pad, y=740, line_height=72, fill=BLANCO, highlight_fill=accent,
        )
        _draw_wrapped_highlighted(
            draw, text, [], font=body_font, max_width=SLIDE_W - 2 * pad,
            x=pad, y=740 + used_h + 30, line_height=48, fill=BLANCO, highlight_fill=accent,
        )

    elif slide_type == "key_points":
        draw.text((pad, 90), (title or "Puntos clave"), font=title_font, fill=BLANCO)
        y = 240
        for item in (slide.get("items") or [])[:6]:
            draw.ellipse([pad, y + 14, pad + 16, y + 30], fill=accent)
            _draw_wrapped_highlighted(
                draw, str(item), [], font=body_font, max_width=SLIDE_W - 2 * pad - 60,
                x=pad + 44, y=y, line_height=48, fill=BLANCO, highlight_fill=accent,
            )
            y += 100
        if not slide.get("items"):
            warnings.append(f"slide_{slide.get('id')}_sin_items")

    elif slide_type == "quote":
        draw.text((pad, 120), "“", font=_font(140, bold=True), fill=accent)
        _draw_wrapped_highlighted(
            draw, text, highlights, font=_font(48, bold=True), max_width=SLIDE_W - 2 * pad,
            x=pad, y=320, line_height=64, fill=BLANCO, highlight_fill=accent,
        )
        if title:
            draw.text((pad, SLIDE_H - 160), f"— {title}", font=body_font, fill=accent)
        if not (slide.get("source_ids") or package.get("sources")):
            warnings.append(f"slide_{slide.get('id')}_sin_fuente")

    elif slide_type == "number":
        number = str((slide.get("items") or [""])[0] or "")
        draw.text((pad, 380), number, font=_font(220, bold=True), fill=accent)
        _draw_wrapped_highlighted(
            draw, text, [], font=body_font, max_width=SLIDE_W - 2 * pad,
            x=pad, y=750, line_height=48, fill=BLANCO, highlight_fill=accent,
        )

    elif slide_type == "closing":
        draw.text((pad, SLIDE_H // 2 - 60), "La Voz Riojana", font=title_font, fill=accent)
        _draw_wrapped_highlighted(
            draw, text or "Seguinos para más noticias", [], font=body_font,
            max_width=SLIDE_W - 2 * pad, x=pad, y=SLIDE_H // 2 + 40, line_height=48,
            fill=BLANCO, highlight_fill=accent,
        )

    else:
        warnings.append(f"slide_{slide.get('id')}_tipo_no_renderizable:{slide_type}")
        draw.text((pad, SLIDE_H // 2), f"[{slide_type}]", font=title_font, fill=BLANCO)

    # Footer + numeración (jerarquía visual compartida entre slides).
    footer_h = 70
    draw.rectangle([0, SLIDE_H - footer_h, SLIDE_W, SLIDE_H], fill="#111111")
    section = str(package.get("section") or "").upper()
    draw.text((pad, SLIDE_H - footer_h + 20), section, font=small_font, fill=accent)
    index = None
    slides = package.get("slides") or []
    for position, item in enumerate(slides):
        if item.get("id") == slide.get("id"):
            index = position
            break
    if index is not None:
        counter = f"{index + 1}/{len(slides)}"
        counter_width = draw.textlength(counter, font=small_font)
        draw.text((SLIDE_W - pad - counter_width, SLIDE_H - footer_h + 20), counter, font=small_font, fill=BLANCO)

    return canvas, warnings


def render_package(package: dict, *, asset_resolver=None) -> tuple[list[Image.Image], list[str]]:
    images: list[Image.Image] = []
    warnings: list[str] = []
    for slide in package.get("slides") or []:
        image, slide_warnings = render_slide(slide, package, asset_resolver=asset_resolver)
        images.append(image)
        warnings.extend(slide_warnings)
    return images, warnings


def render_package_bytes(package: dict, *, asset_resolver=None, quality: int = 88) -> tuple[list[bytes], list[str]]:
    images, warnings = render_package(package, asset_resolver=asset_resolver)
    payloads = []
    for image in images:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=quality)
        payloads.append(buffer.getvalue())
    return payloads, warnings


def default_asset_resolver(asset_id: str) -> Image.Image | None:
    """Resuelve un ``asset_id`` de ``data/media_library.json`` a una imagen PIL."""
    path = default_asset_path_resolver(asset_id)
    if not path:
        return None
    try:
        with Image.open(path) as opened:
            return opened.convert("RGB").copy()
    except (OSError, ValueError):
        return None


def default_asset_path_resolver(asset_id: str) -> str | None:
    """Resuelve un ``asset_id`` a la ruta local de su copia maestra (para Remotion)."""
    from utils.file_manager import JsonStateError, load_json
    from utils.paths import data_dir

    try:
        assets = load_json(str(data_dir() / "media_library.json"), [], expected_type=list)
    except JsonStateError:
        return None
    for asset in assets:
        if isinstance(asset, dict) and asset.get("asset_id") == asset_id and not asset.get("files_purged"):
            master_path = asset.get("master_path")
            if master_path and os.path.isfile(master_path):
                return master_path
    return None


def _slide_props_for_remotion(slide: dict, package: dict, *, index: int, total: int) -> dict:
    slide_type = slide.get("type")
    title = slide.get("title") or (package.get("title") if slide_type == "cover" else "") or ""
    return {
        "slideType": slide_type,
        "template": package.get("template") or "lvr_cronica",
        "title": title,
        "text": slide.get("text") or "",
        "items": [str(item) for item in (slide.get("items") or [])],
        "highlightTerms": list(slide.get("highlights") or package.get("highlight_terms") or []),
        "assetFile": "",  # se completa vía asset_paths en render_still
        "section": package.get("section") or "",
        "index": index,
        "total": total,
    }


def render_package_remotion(
    package: dict,
    *,
    asset_path_resolver=None,
) -> tuple[list[bytes], list[str]]:
    """Renderiza el paquete completo con Remotion. Lanza
    ``remotion_renderer.RemotionRenderError`` si cualquier slide falla — el
    llamador decide si cae a Pillow (modo ``auto``) o reporta el fallo
    (modo ``remotion`` explícito)."""
    from utils.remotion_renderer import render_still

    slides = package.get("slides") or []
    images: list[bytes] = []
    warnings: list[str] = []
    for index, slide in enumerate(slides):
        props = _slide_props_for_remotion(slide, package, index=index + 1, total=len(slides))
        asset_id = str(slide.get("asset_id") or "").strip()
        asset_paths = {}
        if asset_id and asset_path_resolver:
            local_path = asset_path_resolver(asset_id)
            if local_path:
                asset_paths["assetFile"] = local_path
            else:
                warnings.append(f"slide_{slide.get('id')}_asset_no_resoluble:{asset_id}")
        elif slide.get("type") in {"cover", "image_text", "full_image"}:
            warnings.append(f"slide_{slide.get('id')}_sin_imagen")

        png_bytes, _metadata = render_still(PREMIUM_SLIDE_COMPOSITION, props, asset_paths=asset_paths)
        with Image.open(io.BytesIO(png_bytes)) as opened:
            buffer = io.BytesIO()
            opened.convert("RGB").save(buffer, format="JPEG", quality=90)
            images.append(buffer.getvalue())
    return images, warnings


def render_package_with_engine(
    package: dict,
    *,
    asset_resolver=None,
    asset_path_resolver=None,
    workflow: str = "premium",
) -> tuple[list[bytes], list[str], str]:
    """Punto de entrada real para preview/publicación del Estudio Premium
    (Fase 4). ``workflow`` es ``"premium"`` por defecto (el único workflow
    con wiring real a Remotion en esta entrega; ver
    ``utils/remotion_renderer.py::resolve_engine`` para la política
    completa por workflow, incluidos ``automatic``/``og``).

    Devuelve ``(images, warnings, engine_used)``. ``engine_used`` es
    ``"remotion"`` o ``"pillow"`` — nunca silencioso: un fallback queda
    registrado acá y en el log rotativo (``utils.remotion_renderer`` ya deja
    ``workflow``/``engine_requested``/``engine_used``/``fallback_reason``).
    """
    from utils.remotion_renderer import RemotionRenderError, resolve_engine

    asset_resolver = asset_resolver or default_asset_resolver
    asset_path_resolver = asset_path_resolver or default_asset_path_resolver
    engine = resolve_engine(workflow)

    if engine == "remotion_unavailable":
        raise RemotionRenderError(
            f"el motor de {workflow} exige Remotion pero no está disponible en este entorno"
        )

    if engine == "remotion":
        try:
            images, warnings = render_package_remotion(package, asset_path_resolver=asset_path_resolver)
            return images, warnings, "remotion"
        except RemotionRenderError as exc:
            logger.warning(
                "Remotion falló para workflow=%s, cae a Pillow: %s", workflow, exc
            )

    images, warnings = render_package_bytes(package, asset_resolver=asset_resolver)
    return images, warnings, "pillow"
