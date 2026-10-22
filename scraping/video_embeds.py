"""Videos de YouTube incrustados en el cuerpo de las notas de medios locales.

Sólo YouTube: es lo único que estos medios incrustan con cierta frecuencia y lo
que ``yt-dlp`` descarga sin sesión. Facebook, Instagram o X piden login.
"""
from __future__ import annotations

import re

import requests

from utils.logging_setup import setup_logger

logger = setup_logger("scraping.video_embeds", "scrapers.log")

_YOUTUBE_ID_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/)([\w-]{11})"
)
_OEMBED_URL = "https://www.youtube.com/oembed"


def youtube_embed(content) -> dict:
    """``{"video_embed_url", "video_embed_author"}`` del primer YouTube del cuerpo.

    ``content`` es el contenedor del cuerpo (BeautifulSoup); sin video devuelve
    ``{}``. El canal se pide a oEmbed para acreditar el video; si falla, la nota
    sigue igual, sin crédito.
    """
    if content is None:
        return {}
    for iframe in content.find_all("iframe"):
        src = str(iframe.get("src") or iframe.get("data-src") or "")
        match = _YOUTUBE_ID_RE.search(src)
        if match:
            url = f"https://www.youtube.com/watch?v={match.group(1)}"
            embed = {"video_embed_url": url}
            author = _youtube_author(url)
            if author:
                embed["video_embed_author"] = author
            return embed
    return {}


def _youtube_author(url: str) -> str:
    try:
        response = requests.get(_OEMBED_URL, params={"url": url, "format": "json"}, timeout=15)
        response.raise_for_status()
        return " ".join(str(response.json().get("author_name") or "").split())[:80]
    except Exception as exc:
        logger.info("Sin canal de YouTube para %s: %s", url, exc)
        return ""
