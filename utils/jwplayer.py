"""Versión alternativa de un MP4 de JWPlayer cuando el enlace original no existe.

Infobae publica en su JSON-LD un ``contentUrl`` del tipo
``cdn.jwplayer.com/videos/{MEDIA_ID}-{VERSION}.mp4``; para algunas notas esa
versión no existe (404) aunque el video sí (KNOWN_ISSUES 97). La API pública de
JWPlayer (``cdn.jwplayer.com/v2/media/{MEDIA_ID}``, sin auth, la misma que usa
``scraping/base_paparazzi.py``) lista las versiones MP4 disponibles.
"""
from __future__ import annotations

import re

import requests

from utils.logging_setup import setup_logger
from utils.safe_http import safe_get

logger = setup_logger("jwplayer", "jwplayer.log")

_VIDEO_URL_RE = re.compile(r"^https://cdn\.jwplayer\.com/videos/([A-Za-z0-9]{8})-[A-Za-z0-9]+\.mp4(?:[?#].*)?$")
# Misma prioridad que paparazzi: calidad suficiente para un Reel sin bajar 1080p.
MP4_LABEL_PRIORITY = ("540p", "480p", "360p", "720p", "270p", "180p", "1080p")


def media_id(url: str) -> str | None:
    match = _VIDEO_URL_RE.match(str(url or "").strip())
    return match.group(1) if match else None


def alternative_mp4(url: str, *, requester=requests.get) -> str | None:
    """Otra versión MP4 del mismo video, o ``None``. Nunca lanza."""
    identifier = media_id(url)
    if not identifier:
        return None
    try:
        response = safe_get(
            f"https://cdn.jwplayer.com/v2/media/{identifier}",
            requester=requester,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        playlist = response.json().get("playlist") or []
        first = playlist[0] if playlist and isinstance(playlist[0], dict) else {}
        sources = first.get("sources") or []
    except Exception as exc:
        logger.info("No se pudo consultar JWPlayer para %s: %s", identifier, exc)
        return None

    by_label = {
        source.get("label"): str(source.get("file"))
        for source in sources
        if isinstance(source, dict)
        and source.get("type") == "video/mp4"
        and str(source.get("file") or "").startswith("https://")
    }
    original = str(url).split("?", 1)[0]
    for label in MP4_LABEL_PRIORITY:
        candidate = by_label.get(label)
        if candidate and candidate.split("?", 1)[0] != original:
            logger.info("Video JWPlayer %s: versión alternativa %s", identifier, label)
            return candidate
    return None
