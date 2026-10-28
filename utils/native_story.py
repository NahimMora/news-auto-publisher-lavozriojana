"""Historias nativas de Instagram con stickers interactivos reales.

Después de que una nota sale en el feed de Instagram por Graph, esta capa arma
UNA historia con tres stickers nativos (no dibujados sobre la imagen):

* la publicación del feed compartida (``feed_media``): al tocarla abre el post;
* el enlace a la nota en lavozriojana.com (``story_link``);
* la ubicación de la nota (``location``), si la nota la tiene.

La API Graph no permite stickers en historias, así que la publicación usa la
API privada de la app mediante ``instagrapi`` (``meta/instagrapi_client.py``).
Este módulo no importa ``instagrapi``: es lógica pura (candidatos, URL,
ubicación, conversión de IDs, diseño, payload, vista previa y estado) y se
prueba sin red.

Reutiliza lo que ya existe:

* candidatos: ``data/ig_posted.json`` (ID real de Graph de cada publicación);
* URL web y localidad: la nota en ``data/noticias_meta.json`` (``web_url`` /
  ``noticia_url``, ``locality``);
* ubicación: ``utils/ig_location.location_id_for`` (el mismo
  ``facebook_places_id`` que va en el ``location_id`` del post). Ese ID es
  justamente el que pide el sticker de ubicación: no se recalcula nada.

Estado propio en ``data/ig_native_stories.json``: no comparte cupos ni dedup
con el feed ni con las historias de Graph (``data/stories_state.json``).
Apagado por defecto: ``IG_NATIVE_STORIES_ENABLED``; con
``IG_NATIVE_STORIES_DRY_RUN`` (encendido por defecto) sólo genera la vista
previa y valida el payload, sin publicar.
"""
from __future__ import annotations

import io
import json
import os
import re
import string
import tempfile
import time
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFont

from utils import ig_location
from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir, output_dir
from utils.safe_http import UnsafeURLError, safe_get, validate_public_http_url
from utils.social_time import today_ar

logger = setup_logger("native_story", "native_stories.log")

_TRUE = {"1", "true", "yes", "on", "si", "sí"}

CANVAS_W, CANVAS_H = 1080, 1920
BACKGROUND_HEX = "#111318"

# Zonas seguras: la barra de progreso y el usuario ocupan ~el 12 % de arriba;
# la caja de respuesta, ~el 14 % de abajo.
SAFE_TOP = 0.12
SAFE_BOTTOM = 0.86

LINK_BOX = {"x": 0.5, "y": 0.17, "width": 0.46, "height": 0.055}
LOCATION_BOX = {"x": 0.5, "y": 0.25, "width": 0.42, "height": 0.05}
MEDIA_CENTER_Y = 0.57
MEDIA_MAX_WIDTH = 0.88
MEDIA_GAP = 0.025

STATUS_COMPLETED = "completed"
STATUS_PROCESSING = "processing"
STATUS_UNVERIFIED = "unverified"  # pudo haber salido: se reconcilia antes de reintentar
STATUS_FAILED = "failed"  # reintentable con backoff
STATUS_DEAD = "dead_letter"  # agotó intentos: no se reintenta
STATUS_SKIPPED = "skipped"  # nunca va a salir (sin enlace válido, etc.)
_FINAL = {STATUS_COMPLETED, STATUS_DEAD, STATUS_SKIPPED}


# ── Configuración ────────────────────────────────────────────────────────
def _flag(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return _flag("IG_NATIVE_STORIES_ENABLED")


def dry_run() -> bool:
    return _flag("IG_NATIVE_STORIES_DRY_RUN", "true")


def include_reels() -> bool:
    return _flag("IG_NATIVE_STORY_INCLUDE_REELS")


def max_per_cycle() -> int:
    return max(0, _int("IG_NATIVE_STORY_MAX_PER_CYCLE", 2))


def max_per_day() -> int:
    return max(0, _int("IG_NATIVE_STORY_MAX_PER_DAY", 40))


def max_attempts() -> int:
    return max(1, _int("IG_NATIVE_STORY_MAX_ATTEMPTS", 3))


def lookback_hours() -> float:
    return _float("IG_NATIVE_STORY_LOOKBACK_HOURS", 6.0)


def min_age_seconds() -> float:
    """Espera desde la publicación del post antes de compartirlo."""
    return _float("IG_NATIVE_STORY_MIN_AGE_SECONDS", 120.0)


def retry_base_seconds() -> float:
    return _float("IG_NATIVE_STORY_RETRY_BASE_SECONDS", 900.0)


def block_hours() -> float:
    return _float("IG_NATIVE_STORY_BLOCK_HOURS", 24.0)


def link_hosts() -> set[str]:
    raw = os.getenv("IG_NATIVE_STORY_LINK_HOSTS", "lavozriojana.com,www.lavozriojana.com")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def state_path() -> str:
    return str(data_dir() / "ig_native_stories.json")


# ── IDs: Graph → media pk de la app ──────────────────────────────────────
# El ID de Graph (``1789…``) no es el pk que pide el sticker. El pk sale del
# shortcode del permalink (base64 con este alfabeto), sin pedir nada a la red.
_CODE_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "-_"
_PERMALINK_RE = re.compile(r"^https://(?:www\.)?instagram\.com/(?:[A-Za-z0-9_.]+/)?(p|reel|reels|tv)/([A-Za-z0-9_-]{5,})/?")


def shortcode_from_permalink(permalink: str) -> str:
    match = _PERMALINK_RE.match(str(permalink or "").strip())
    return match.group(2) if match else ""


def media_pk_from_shortcode(code: str) -> int:
    code = str(code or "")[:11]
    if not code or any(c not in _CODE_ALPHABET for c in code):
        raise ValueError("shortcode inválido")
    value = 0
    for char in code:
        value = value * 64 + _CODE_ALPHABET.index(char)
    return value


def media_pk_from_permalink(permalink: str) -> int:
    code = shortcode_from_permalink(permalink)
    if not code:
        raise ValueError("permalink sin shortcode")
    return media_pk_from_shortcode(code)


# ── URL de la nota ───────────────────────────────────────────────────────
def validate_web_url(url: str) -> str:
    """URL https de la nota en lavozriojana.com. Lanza ``ValueError``."""
    try:
        clean = validate_public_http_url(url, resolve=False)
    except UnsafeURLError as exc:
        raise ValueError(f"URL inválida: {exc}") from exc
    parts = urlsplit(clean)
    if parts.scheme != "https":
        raise ValueError("la URL de la nota no es https")
    if (parts.hostname or "").lower() not in link_hosts():
        raise ValueError("la URL no es de lavozriojana.com")
    if len(parts.path.strip("/")) < 3:
        raise ValueError("la URL no apunta a una nota")
    return clean


def web_url_of(item: dict) -> str:
    return str(item.get("web_url") or item.get("noticia_url") or "").strip()


# ── Ubicación ────────────────────────────────────────────────────────────
def location_for(item: dict) -> tuple[dict | None, str]:
    """``({"external_id", "name"}, "")`` o ``(None, motivo)``.

    Sólo el ``location_id`` que efectivamente llevó el post original
    (``ig_location_id`` en ``ig_posted.json``). Nunca se agrega una ubicación
    que la publicación no tenía: ni por la tabla ni por la localidad de la
    nota. Registros anteriores a ese campo salen sin ubicación.
    """
    from utils.visual_v2_props import locality_for

    if not ig_location.enabled():
        return None, "location_disabled"
    applied = str(item.get("ig_location_id") or "").strip()
    if not applied:
        return None, "post_without_location"
    if not re.fullmatch(r"\d{5,20}", applied):
        return None, "invalid_post_location_id"
    locality = locality_for(item).split("·", 1)[0].strip()
    return {"external_id": applied, "name": locality or "La Rioja"}, ""


# ── Alcance temático ─────────────────────────────────────────────────────
def scope_of(item: dict) -> tuple[bool, str]:
    """Sólo notas policiales o con vínculo riojano determinístico (el mismo
    criterio del router editorial, más el caption publicado)."""
    from utils.editorial_priority import normalize_category
    from utils.editorial_router import detect_riojan_link

    if normalize_category(item.get("seccion") or item.get("categoria")) == "policiales":
        return True, "category:policiales"
    excerpt = f"{item.get('excerpt') or ''} {item.get('texto_instagram') or ''}"
    riojan, reason = detect_riojan_link({**item, "excerpt": excerpt})
    return riojan, reason if riojan else "out_of_scope"


# ── Candidatos ───────────────────────────────────────────────────────────
def load_state() -> dict:
    return load_json(state_path(), {"jobs": {}}, expected_type=dict)


def _posted_at(record: dict) -> float:
    try:
        return float(record.get("posted_at") or 0)
    except (TypeError, ValueError):
        return 0.0


def _graph_story_media_ids() -> set[str]:
    """Publicaciones que ya tienen historia de Graph en Instagram."""
    from utils import story_publisher

    try:
        posted = (story_publisher.load_state().get("posted") or {})
    except JsonStateError:
        return set()
    return {key.split(":", 1)[1] for key, v in posted.items() if key.startswith("post:") and v.get("ig_id")}


def _meta_index() -> dict[str, dict]:
    """Notas de ``noticias_meta.json`` por clave de cola, dedup y URL."""
    try:
        queue = load_json(str(data_dir() / "noticias_meta.json"), [], expected_type=list)
    except JsonStateError:
        logger.error("noticias_meta.json ilegible: sin URL web para las historias")
        return {}
    index: dict[str, dict] = {}
    for item in queue:
        if not isinstance(item, dict):
            continue
        for field in ("meta_queue_key", "dedup_key", "canonical_url", "url"):
            value = str(item.get(field) or "")
            if value and value not in index:
                index[value] = item
    return index


def candidates(state: dict, *, now: float | None = None) -> list[dict]:
    """Publicaciones de Instagram recientes sin historia nativa (más nueva primero)."""
    now = now or time.time()
    jobs = state.get("jobs") or {}
    window = lookback_hours() * 3600
    recent = []
    for record in _posted_records():
        age = now - _posted_at(record)
        if age > window or age < 0:
            continue
        media_id = str(record["external_id"])
        entry = jobs.get(media_id) or {}
        if entry.get("status") in _FINAL:
            continue
        if entry.get("status") == STATUS_FAILED and float(entry.get("next_attempt_at") or 0) > now:
            continue
        if str(record.get("media_type") or "") == "reel" and not include_reels():
            continue
        recent.append(record)
    # Fuera de alcance no consume cupo ni se registra: simplemente no aplica.
    return [c for c in _enrich(recent, now) if c["in_scope"]]


def _posted_records() -> list[dict]:
    try:
        posted = load_json(str(data_dir() / "ig_posted.json"), {"posted": {}}, expected_type=dict).get("posted") or {}
    except JsonStateError:
        logger.error("ig_posted.json ilegible: sin candidatos")
        return []
    return [r for r in posted.values() if isinstance(r, dict) and r.get("external_id")]


def candidate_for(media_id: str, *, now: float | None = None) -> dict | None:
    """Candidato de una publicación puntual, sin ventana ni estado (vista
    previa y prueba real controlada)."""
    records = [r for r in _posted_records() if str(r["external_id"]) == str(media_id)]
    found = _enrich(records, now or time.time())
    return found[0] if found else None


def _enrich(recent: list[dict], now: float) -> list[dict]:
    if not recent:
        return []
    with_graph_story = _graph_story_media_ids()
    index = _meta_index()
    out = []
    for record in recent:
        media_id = str(record["external_id"])
        item = {}
        for field in ("meta_queue_key", "dedup_key", "canonical_url", "url"):
            item = index.get(str(record.get(field) or "")) or {}
            if item:
                break
        # Lo que guardó el publicador del post (localidad, ubicación aplicada,
        # URL web) gana sobre la cola.
        merged = {**item, **{k: v for k, v in record.items() if v}}
        in_scope, scope_reason = scope_of(merged)
        out.append({
            "in_scope": in_scope,
            "scope_reason": scope_reason,
            "media_id": media_id,
            "posted_at": _posted_at(record),
            "ready": now - _posted_at(record) >= min_age_seconds(),
            "reel": str(record.get("media_type") or "") == "reel",
            "has_graph_story": media_id in with_graph_story,
            "title": str(merged.get("titulo_instagram") or merged.get("titulo") or "")[:120],
            "web_url": web_url_of(merged),
            "locality": str(merged.get("locality") or ""),
            "item": merged,
        })
    out.sort(key=lambda c: -c["posted_at"])
    return out


# ── Diseño ───────────────────────────────────────────────────────────────
def layout(aspect: float, *, with_location: bool) -> dict:
    """Cajas relativas (centro x/y, ancho, alto) de los tres stickers.

    ``aspect`` = ancho/alto de la publicación (4:5 → 0,8; Reel → 0,5625). El
    post compartido ocupa hasta el 88 % del ancho sin pisar los stickers de
    arriba ni la zona de respuesta de abajo, y conserva su proporción.
    """
    aspect = aspect if 0.3 <= aspect <= 2.0 else 0.8
    upper = LOCATION_BOX if with_location else LINK_BOX
    top = upper["y"] + upper["height"] / 2 + MEDIA_GAP
    bottom = SAFE_BOTTOM
    width = min(MEDIA_MAX_WIDTH, (bottom - top) * CANVAS_H * aspect / CANVAS_W)
    height = width * CANVAS_W / aspect / CANVAS_H
    center = min(max(MEDIA_CENTER_Y, top + height / 2), bottom - height / 2)
    boxes = {"link": dict(LINK_BOX), "media": {"x": 0.5, "y": round(center, 5), "width": round(width, 5), "height": round(height, 5)}}
    if with_location:
        boxes["location"] = dict(LOCATION_BOX)
    return boxes


def write_background(path: str | None = None) -> str:
    """Fondo liso #111318 de 1080×1920 (JPEG). Devuelve la ruta."""
    if not path:
        handle, path = tempfile.mkstemp(suffix=".jpg", prefix="lvr_native_story_")
        os.close(handle)
    Image.new("RGB", (CANVAS_W, CANVAS_H), BACKGROUND_HEX).save(path, "JPEG", quality=95)
    return path


def measure_aspect(image_url: str) -> tuple[float, bytes]:
    """Proporción real de la imagen del post (y sus bytes, para la vista previa)."""
    try:
        response = safe_get(image_url, timeout=30, headers={"User-Agent": "LaVozRiojanaBot/1.0"})
        content = getattr(response, "content", b"") or b""
        if getattr(response, "status_code", 0) != 200 or not content or len(content) > 15 * 1024 * 1024:
            return 0.0, b""
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
        return (width / height if height else 0.0), content
    except Exception as exc:  # noqa: BLE001 — sin imagen se usa la proporción por defecto
        logger.warning("No se pudo medir la imagen del post: %s", type(exc).__name__)
        return 0.0, b""


# ── Payload ──────────────────────────────────────────────────────────────
def build_payload(*, media_id: str, media_pk: int, web_url: str, aspect: float, location: dict | None, reel: bool) -> dict:
    url = validate_web_url(web_url)
    if int(media_pk) <= 0:
        raise ValueError("media pk inválido")
    boxes = layout(aspect, with_location=bool(location))
    payload = {
        "graph_media_id": str(media_id),
        "media": {"media_pk": int(media_pk), "reel": bool(reel), **boxes["media"]},
        "link": {"url": url, **boxes["link"]},
        "location": {**location, **boxes["location"]} if location else None,
        "background": {"width": CANVAS_W, "height": CANVAS_H, "color": BACKGROUND_HEX},
    }
    errors = validate_payload(payload)
    if errors:
        raise ValueError("; ".join(errors))
    return payload


def _edges(box: dict) -> tuple[float, float, float, float]:
    return (box["x"] - box["width"] / 2, box["y"] - box["height"] / 2, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def validate_payload(payload: dict) -> list[str]:
    errors: list[str] = []
    boxes = {name: payload.get(name) for name in ("link", "location", "media") if payload.get(name)}
    if "link" not in boxes:
        errors.append("falta el sticker de enlace")
    if "media" not in boxes:
        errors.append("falta la publicación compartida")
    else:
        try:
            if int(payload["media"]["media_pk"]) <= 0:
                errors.append("media pk inválido")
        except (TypeError, ValueError, KeyError):
            errors.append("media pk inválido")
    if "link" in boxes:
        try:
            validate_web_url(boxes["link"].get("url", ""))
        except ValueError as exc:
            errors.append(str(exc))
    if payload.get("location") and not re.fullmatch(r"\d{5,20}", str(payload["location"].get("external_id") or "")):
        errors.append("ID de ubicación inválido")
    for name, box in boxes.items():
        left, top, right, bottom = _edges(box)
        if left < 0 or right > 1 or top < SAFE_TOP or bottom > SAFE_BOTTOM:
            errors.append(f"{name} fuera de la zona segura")
    names = list(boxes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            al, at, ar, ab = _edges(boxes[a])
            bl, bt, br, bb = _edges(boxes[b])
            if al < br and bl < ar and at < bb and bt < ab:
                errors.append(f"{a} se superpone con {b}")
    return errors


# ── Imagen de la historia ────────────────────────────────────────────────
# Los stickers que llegan por la API son sólo zonas tocables: Instagram no los
# dibuja (la app los pega en la imagen antes de subirla). Por eso la imagen
# lleva, exactamente debajo de cada zona, la publicación y las dos pastillas.
FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "layout", "fonts", "Archivo[wdth,wght].ttf")
LINK_TEXT = "NOTICIA COMPLETA AQUÍ"
LINK_COLOR = "#0A66C2"
LOCATION_COLOR = "#8A2BE2"
PILL_FILL = "#FFFFFF"


def _font(size: int, weight: int = 800):
    try:
        font = ImageFont.truetype(FONT_PATH, size)
        try:
            font.set_variation_by_axes([weight, 100])  # ejes: peso, ancho
        except Exception:  # noqa: BLE001 — FreeType sin ejes variables: peso por defecto
            pass
        return font
    except OSError:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # Pillow viejo
            return ImageFont.load_default()


def _px(box: dict) -> tuple[int, int, int, int]:
    left, top, right, bottom = _edges(box)
    return (round(left * CANVAS_W), round(top * CANVAS_H), round(right * CANVAS_W), round(bottom * CANVAS_H))


def _fit_font(draw, text: str, max_width: int, size: int):
    while size > 18:
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _font(size)


def _pill(image: Image.Image, box: tuple[int, int, int, int], text: str, color: str, icon) -> None:
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = box
    height = bottom - top
    draw.rounded_rectangle(box, radius=height // 2, fill=PILL_FILL)
    icon_size = int(height * 0.5)
    gap = int(height * 0.18)
    font = _fit_font(draw, text, (right - left) - icon_size - gap - height, int(height * 0.42))
    text_w = draw.textlength(text, font=font)
    start = left + ((right - left) - (icon_size + gap + text_w)) / 2
    icon(image, (int(start), top + (height - icon_size) // 2, int(start) + icon_size, top + (height + icon_size) // 2), color)
    draw.text((start + icon_size + gap, top + height / 2), text, fill=color, font=font, anchor="lm")


def _link_icon(image, box, color) -> None:
    left, top, right, bottom = box
    size = right - left
    scale = 4  # se dibuja grande y se reduce: bordes suaves
    big = size * scale
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    stroke = max(3, big // 9)
    w, h = int(big * 0.58), int(big * 0.34)
    y = (big - h) // 2
    # Dos eslabones encadenados, girados en diagonal.
    draw.rounded_rectangle((int(big * 0.04), y, int(big * 0.04) + w, y + h), radius=h // 2, outline=color, width=stroke)
    draw.rounded_rectangle((big - w - int(big * 0.04), y, big - int(big * 0.04), y + h), radius=h // 2, outline=color, width=stroke)
    layer = layer.rotate(45, resample=Image.BICUBIC).resize((size, size), Image.LANCZOS)
    image.paste(layer, (left, top), layer)


def _pin_icon(image, box, color) -> None:
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = box
    size = right - left
    r = size * 0.36
    cx, cy = left + size / 2, top + r + size * 0.04
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    draw.polygon([(cx - r * 0.82, cy + r * 0.45), (cx + r * 0.82, cy + r * 0.45), (cx, bottom)], fill=color)
    inner = r * 0.4
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=PILL_FILL)


def compose_story(payload: dict, post_image: bytes) -> Image.Image:
    """Imagen 1080×1920 con la publicación y las pastillas visibles debajo de
    cada sticker. Sin la imagen del post no se arma (``ValueError``)."""
    if not post_image:
        raise ValueError("sin imagen de la publicación")
    image = Image.new("RGB", (CANVAS_W, CANVAS_H), BACKGROUND_HEX)
    media = _px(payload["media"])
    with Image.open(io.BytesIO(post_image)) as post:
        post = post.convert("RGB")
        post.thumbnail((media[2] - media[0], media[3] - media[1]), Image.LANCZOS)
        mask = Image.new("L", post.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, post.width - 1, post.height - 1), radius=28, fill=255)
        image.paste(post, (media[0] + (media[2] - media[0] - post.width) // 2,
                           media[1] + (media[3] - media[1] - post.height) // 2), mask)
    _pill(image, _px(payload["link"]), LINK_TEXT, LINK_COLOR, _link_icon)
    if payload.get("location"):
        name = str(payload["location"].get("name") or "").split(",", 1)[0].strip().upper() or "LA RIOJA"
        _pill(image, _px(payload["location"]), name, LOCATION_COLOR, _pin_icon)
    return image


def write_story_image(payload: dict, post_image: bytes, path: str | None = None) -> str:
    """JPEG temporal con la imagen de la historia. Devuelve la ruta."""
    image = compose_story(payload, post_image)
    if not path:
        handle, path = tempfile.mkstemp(suffix=".jpg", prefix="lvr_native_story_")
        os.close(handle)
    image.save(path, "JPEG", quality=95)
    return path


def render_preview(payload: dict, out_path: str, post_image: bytes = b"") -> str:
    """Vista previa: la misma imagen que se publicaría (más el payload en
    .json). Sin imagen del post, sólo el fondo con las pastillas."""
    try:
        image = compose_story(payload, post_image)
    except ValueError:
        image = Image.new("RGB", (CANVAS_W, CANVAS_H), BACKGROUND_HEX)
        _pill(image, _px(payload["link"]), LINK_TEXT, LINK_COLOR, _link_icon)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    image.save(out_path, "PNG")
    with open(os.path.splitext(out_path)[0] + ".json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return out_path


def preview_dir() -> str:
    return str(output_dir() / "native_stories_preview")


# ── Estado ───────────────────────────────────────────────────────────────
def mark(media_id: str, **fields) -> dict:
    """Actualiza la entrada de una publicación (lectura-modificación-escritura atómica)."""
    result: dict = {}

    def mutate(state):
        jobs = state.setdefault("jobs", {})
        entry = jobs.setdefault(str(media_id), {})
        entry.update({k: v for k, v in fields.items() if v is not None})
        entry["updated_at"] = int(time.time())
        cutoff = time.time() - 30 * 86400
        state["jobs"] = {k: v for k, v in jobs.items() if int(v.get("updated_at") or 0) >= cutoff}
        result.update(entry)
        return state

    update_json(state_path(), mutate, {"jobs": {}}, expected_type=dict)
    return result


def register_failure(media_id: str, error: str, *, attempts: int) -> dict:
    """Fallo reintentable: backoff exponencial y dead-letter al agotar intentos."""
    if attempts >= max_attempts():
        logger.error("Historia nativa %s agotó %s intentos (%s): dead-letter", media_id, attempts, error)
        return mark(media_id, status=STATUS_DEAD, error=error, attempts=attempts)
    delay = retry_base_seconds() * (2 ** max(0, attempts - 1))
    return mark(media_id, status=STATUS_FAILED, error=error, attempts=attempts, next_attempt_at=int(time.time() + delay))


def set_blocked(reason: str, hours: float | None = None) -> float:
    until = time.time() + 3600 * (block_hours() if hours is None else hours)

    def mutate(state):
        state["blocked_until"] = int(until)
        state["block_reason"] = reason
        return state

    update_json(state_path(), mutate, {"jobs": {}}, expected_type=dict)
    return until


def clear_blocked() -> None:
    def mutate(state):
        state.pop("blocked_until", None)
        state.pop("block_reason", None)
        return state

    update_json(state_path(), mutate, {"jobs": {}}, expected_type=dict)


def stories_today(state: dict) -> int:
    today = today_ar().isoformat()
    return sum(1 for v in (state.get("jobs") or {}).values() if v.get("status") == STATUS_COMPLETED and v.get("day") == today)
