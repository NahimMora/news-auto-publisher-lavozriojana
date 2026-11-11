"""Historia de Instagram "Sumate a nuestro WhatsApp": días fijos a las 20.

Imagen propia (Pillow, sin IA) con un sticker de enlace nativo (instagrapi)
sobre el botón dibujado: los stickers de la API son invisibles, así que el
botón va pintado debajo (igual que ``utils/native_story.py``).

* ``WA_JOIN_STORY_ENABLED=false`` (default): no hace nada.
* ``WA_JOIN_STORY_DAYS`` (default ``0,2,4``: lunes, miércoles y viernes),
  ``WA_JOIN_STORY_HOUR`` (20) y ``WA_JOIN_STORY_UNTIL_HOUR`` (23): la ventana.
* ``WHATSAPP_JOIN_URL``: el enlace del canal (whatsapp.com/channel/...).

Una por día como máximo. Si la subida falla después de enviarse, queda
``unverified`` y ese día no se reintenta (nunca se publica dos veces a ciegas).
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFilter

from utils import native_story as ns
from utils.file_manager import load_json, update_json
from utils.paths import data_dir
from utils.social_time import now_ar

W, H = ns.CANVAS_W, ns.CANVAS_H
GREEN = (37, 211, 102)
GREEN_DARK = (18, 140, 74)
# Caja del sticker de enlace (fracciones del lienzo): el botón va debajo.
LINK_BOX = {"x": 0.5, "y": 0.735, "width": 0.74, "height": 0.085}
_ALLOWED_HOSTS = {"whatsapp.com", "www.whatsapp.com", "chat.whatsapp.com"}


def enabled() -> bool:
    return ns._flag("WA_JOIN_STORY_ENABLED")


def join_url() -> str:
    """Enlace de invitación validado (https y de WhatsApp). ``ValueError`` si no."""
    url = os.getenv("WHATSAPP_JOIN_URL", "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in _ALLOWED_HOSTS or len(parts.path) < 6:
        raise ValueError("WHATSAPP_JOIN_URL no es un enlace de WhatsApp")
    return url


def state_path() -> str:
    return str(data_dir() / "wa_join_story.json")


def _days() -> set[int]:
    raw = os.getenv("WA_JOIN_STORY_DAYS", "0,2,4")
    return {int(d) for d in raw.split(",") if d.strip().isdigit() and 0 <= int(d) <= 6}


def due(now: datetime | None = None, *, state: dict | None = None) -> bool:
    moment = now_ar(now)
    start = ns._int("WA_JOIN_STORY_HOUR", 20)
    until = ns._int("WA_JOIN_STORY_UNTIL_HOUR", 23)
    if moment.weekday() not in _days() or not start <= moment.hour < until:
        return False
    state = state if state is not None else load_json(state_path(), {}, expected_type=dict)
    return moment.date().isoformat() not in (state.get("days") or {})


def mark(day: str, **fields) -> None:
    def mutate(state):
        state.setdefault("days", {})[day] = fields
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)


# ── Imagen ───────────────────────────────────────────────────────────────
def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(trial, font=font) <= width:
            lines[-1] = trial
        else:
            lines.append(word)
    return lines


def _whatsapp_glyph(draw, center: tuple[int, int], radius: int) -> None:
    """Burbuja con auricular, dibujada (sin fuentes de íconos)."""
    cx, cy = center
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=GREEN)
    draw.polygon([(cx - radius * 0.62, cy + radius * 0.55), (cx - radius * 0.95, cy + radius * 0.98),
                  (cx - radius * 0.2, cy + radius * 0.82)], fill=GREEN)
    inner = radius * 0.72
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), outline=ns.WHITE, width=max(4, radius // 11))
    r = radius * 0.2
    draw.rounded_rectangle((cx - r * 1.4, cy - r * 1.6, cx - r * 0.3, cy - r * 0.2), radius=int(r * 0.4), fill=ns.WHITE)
    draw.rounded_rectangle((cx + r * 0.2, cy + r * 0.3, cx + r * 1.6, cy + r * 1.4), radius=int(r * 0.4), fill=ns.WHITE)
    draw.line((cx - r * 0.9, cy - r * 0.4, cx + r * 0.5, cy + r * 0.9), fill=ns.WHITE, width=int(r * 0.7))


def compose() -> Image.Image:
    image = Image.new("RGB", (W, H), ns.BACKGROUND_HEX)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-W * 0.3, H * 0.05, W * 1.3, H * 0.75), fill=(20, 70, 44))
    image = Image.blend(image, glow.filter(ImageFilter.GaussianBlur(160)), 0.55)
    draw = ImageDraw.Draw(image)
    margin = int(W * 0.09)

    # Firma
    top = int(H * ns.SAFE_TOP) + 30
    draw.rectangle((margin, top, margin + 10, top + 46), fill=ns.RED)
    draw.text((margin + 28, top + 23), "LA VOZ RIOJANA", font=ns._condensed(46, 900), fill=ns.WHITE, anchor="lm")

    # Ícono y titular
    _whatsapp_glyph(draw, (margin + 70, int(H * 0.30)), 70)
    headline = ns._condensed(118, 900)
    y = int(H * 0.37)
    for line in _wrap(draw, "LAS NOTICIAS DE LA RIOJA EN TU WHATSAPP", headline, W - 2 * margin):
        draw.text((margin, y), line, font=headline, fill=ns.WHITE)
        y += 116
    sub = ns._font(46, weight=500, path=ns.SERIF_ITALIC_PATH)
    y += 26
    for line in _wrap(draw, "Último momento apenas pasa. Seguí el canal y recibí lo importante.", sub, W - 2 * margin):
        draw.text((margin, y), line, font=sub, fill=(205, 222, 212))
        y += 60

    # Botón bajo el sticker de enlace
    box = LINK_BOX
    left, right = int((box["x"] - box["width"] / 2) * W), int((box["x"] + box["width"] / 2) * W)
    upper, lower = int((box["y"] - box["height"] / 2) * H), int((box["y"] + box["height"] / 2) * H)
    draw.rounded_rectangle((left, upper + 8, right, lower + 8), radius=34, fill=GREEN_DARK)
    draw.rounded_rectangle((left, upper, right, lower), radius=34, fill=GREEN)
    label = ns._condensed(64, 900)
    draw.text(((left + right) // 2 - 24, (upper + lower) // 2), "UNIRME AL CANAL", font=label, fill=ns.INK, anchor="mm")
    ax, ay = right - 70, (upper + lower) // 2
    draw.line((ax - 26, ay, ax + 22, ay), fill=ns.INK, width=9)
    draw.line((ax + 2, ay - 22, ax + 24, ay), fill=ns.INK, width=9)
    draw.line((ax + 2, ay + 22, ax + 24, ay), fill=ns.INK, width=9)
    hint = ns._font(36, weight=600)
    draw.text((W // 2, lower + 70), "Tocá el botón · Es gratis", font=hint, fill=(160, 180, 170), anchor="mm")
    return image


def write_image(path: str | None = None) -> str:
    if not path:
        handle, path = tempfile.mkstemp(suffix=".jpg", prefix="lvr_wa_story_")
        os.close(handle)
    compose().save(path, "JPEG", quality=97, subsampling=0, optimize=True)
    return path
