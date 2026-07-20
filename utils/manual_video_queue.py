from __future__ import annotations

import os
import time
from copy import deepcopy
from urllib.parse import urlparse

from utils.editorial_priority import normalize_category
from utils.file_manager import load_json, save_json
from utils.logging_setup import setup_logger
from utils.url_normalization import canonical_url, url_hash

logger = setup_logger("manual_video_queue")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SOCIAL_QUEUE_PATH = os.path.join(DATA_DIR, "noticias_sociales_pendientes.json")
DRAFTS_PATH = os.path.join(DATA_DIR, "videos_manuales_borradores.json")

DIRECT_VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v")

DEFAULT_REEL_LAYOUT = {
    "name": "La Voz Riojana Reel 9:16",
    "canvas": {
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "background": "#0B0B0B",
    },
    "content_frame": {
        "aspect_ratio": "4:5",
        "width": 1080,
        "height": 1350,
        "x": 0,
        "y": 285,
        "background": "#B30000",
        "overflow": "hidden",
    },
    "media_area": {
        "x": 0,
        "y": 285,
        "width": 1080,
        "height": 760,
        "fit": "cover",
        "position": "top",
    },
    "headline_block": {
        "x": 0,
        "y": 1045,
        "width": 1080,
        "height": 500,
        "background": "#B30000",
        "padding": {"top": 75, "left": 60, "right": 60, "bottom": 40},
    },
    "footer": {
        "x": 0,
        "y": 1545,
        "width": 1080,
        "height": 90,
        "background": "#111111",
    },
    "colors": {
        "primary_red": "#B30000",
        "black": "#0B0B0B",
        "footer_black": "#111111",
        "white": "#FFFFFF",
        "rioja_sky_blue": "#75AADB",
        "rioja_gold": "#F6C343",
    },
    "export": {
        "format": "mp4",
        "fps": 30,
        "duration_seconds": 8,
        "safe_for_instagram_reels": True,
        "safe_for_feed_preview": True,
    },
}


def detect_platform(url: object) -> str:
    host = urlparse(str(url or "")).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    if host in {"x.com", "twitter.com", "mobile.twitter.com"}:
        return "x"
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith("facebook.com") or host == "fb.watch":
        return "facebook"
    if host in {"youtu.be", "youtube.com", "m.youtube.com"} or host.endswith(".youtube.com"):
        return "youtube"
    return "direct" if is_probable_direct_video_url(url) else "web"


def is_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_probable_direct_video_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    path = parsed.path.lower()
    return parsed.scheme in {"http", "https"} and path.endswith(DIRECT_VIDEO_EXTENSIONS)


def _clean_text(value: object, *, max_chars: int | None = None) -> str:
    text = " ".join(str(value or "").strip().split())
    if max_chars and len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def _dedup_key(source_url: str) -> str:
    return f"video:{url_hash(source_url)}"


def _video_url(payload: dict, source_url: str) -> str:
    direct = _clean_text(
        payload.get("video_url")
        or payload.get("direct_video_url")
        or payload.get("mp4_url")
    )
    if direct:
        return direct
    if is_probable_direct_video_url(source_url):
        return source_url
    return ""


def _bool_value(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def build_video_item(payload: dict, *, require_direct_video: bool = True) -> dict:
    source_url = _clean_text(payload.get("source_url") or payload.get("url"))
    if not is_http_url(source_url):
        raise ValueError("source_url debe ser una URL http/https valida")

    video_url = _video_url(payload, source_url)
    if video_url and not is_http_url(video_url):
        raise ValueError("video_url debe ser una URL http/https valida")
    if require_direct_video and not video_url:
        raise ValueError("Para publicar ahora hace falta una URL directa a MP4/MOV publica")

    title = _clean_text(payload.get("title") or payload.get("titulo"), max_chars=120)
    if not title:
        raise ValueError("El titulo es obligatorio")

    caption = _clean_text(
        payload.get("caption")
        or payload.get("texto_instagram")
        or title,
        max_chars=2200,
    )
    seccion = normalize_category(payload.get("seccion") or payload.get("category") or "sociedad")
    layout = deepcopy(DEFAULT_REEL_LAYOUT)
    duration = payload.get("duration_seconds")
    if duration:
        try:
            layout["export"]["duration_seconds"] = max(3, min(90, int(duration)))
        except (TypeError, ValueError):
            pass

    item = {
        "media_type": "video",
        "source_platform": detect_platform(source_url),
        "source_video_url": source_url,
        "url": source_url,
        "canonical_url": canonical_url(source_url),
        "video_url": video_url,
        "titulo": title,
        "titulo_instagram": title[:80],
        "texto_instagram": caption,
        "caption": caption,
        "cta": _clean_text(payload.get("cta"), max_chars=180),
        "seccion": seccion,
        "top_text": _clean_text(payload.get("top_text"), max_chars=80),
        "bottom_text": _clean_text(payload.get("bottom_text"), max_chars=100),
        "share_to_feed": _bool_value(payload.get("share_to_feed"), True),
        "video_layout": layout,
        "dedup_key": _dedup_key(source_url),
        "social_queued_at": int(time.time()),
        "facebook_done": False,
        "instagram_done": False,
    }
    if not video_url:
        item["needs_direct_video_url"] = True
    return {key: value for key, value in item.items() if value not in ("", None, [], {})}


def enqueue_video(payload: dict) -> tuple[dict, bool]:
    item = build_video_item(payload, require_direct_video=True)
    queue = load_json(SOCIAL_QUEUE_PATH, [])
    if not isinstance(queue, list):
        queue = []

    if any(existing.get("dedup_key") == item["dedup_key"] for existing in queue if isinstance(existing, dict)):
        logger.info("Video manual ya en cola: %s", item.get("titulo", "")[:70])
        return item, False

    queue.append(item)
    save_json(SOCIAL_QUEUE_PATH, queue)
    logger.info("Video manual encolado: %s", item.get("titulo", "")[:70])
    return item, True


def save_video_draft(payload: dict) -> tuple[dict, bool]:
    item = build_video_item(payload, require_direct_video=False)
    item["manual_status"] = "draft"
    drafts = load_json(DRAFTS_PATH, [])
    if not isinstance(drafts, list):
        drafts = []

    for index, existing in enumerate(drafts):
        if isinstance(existing, dict) and existing.get("dedup_key") == item["dedup_key"]:
            drafts[index] = item
            save_json(DRAFTS_PATH, drafts)
            logger.info("Borrador de video actualizado: %s", item.get("titulo", "")[:70])
            return item, False

    drafts.append(item)
    save_json(DRAFTS_PATH, drafts)
    logger.info("Borrador de video guardado: %s", item.get("titulo", "")[:70])
    return item, True


def load_video_state() -> dict:
    queue = load_json(SOCIAL_QUEUE_PATH, [])
    drafts = load_json(DRAFTS_PATH, [])
    videos = [
        item for item in queue
        if isinstance(item, dict) and item.get("media_type") == "video"
    ]
    return {
        "queue": videos,
        "drafts": drafts if isinstance(drafts, list) else [],
    }
