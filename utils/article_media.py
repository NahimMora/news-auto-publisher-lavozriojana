"""Metadatos y foto original de una nota publicada en lavozriojana.com.

La imagen OG del sitio ya trae el titular escrito; las piezas sociales usan
la foto original, que el CMS guarda en ``media.lavozriojana.com/noticias/``
con el mismo código que cierra el nombre de la OG
(``.../og/<slug>-43d83091fd.jpg`` → ``.../noticias/2026/10/43d83091fd....webp``).
"""
from __future__ import annotations

import html
import re

import requests

from utils.logging_setup import setup_logger
from utils.safe_http import UnsafeURLError, safe_get

logger = setup_logger("article_media", "social_formats.log")

_UA = {"User-Agent": "LaVozRiojanaBot/1.0 (+https://lavozriojana.com)"}
_SITE_SUFFIX = re.compile(r"\s*\|\s*La Voz Riojana\s*$", re.IGNORECASE)


def _meta(page: str, prop: str) -> str:
    for pattern in (
        rf'<meta[^>]+property="{re.escape(prop)}"[^>]+content="([^"]*)"',
        rf'<meta[^>]+content="([^"]*)"[^>]+property="{re.escape(prop)}"',
    ):
        match = re.search(pattern, page)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def _truncated(text: str) -> bool:
    return text.rstrip().endswith(("...", "…"))


def parse_article_page(page: str) -> dict:
    title_match = re.search(r"<title>([^<]*)</title>", page)
    title = _SITE_SUFFIX.sub("", html.unescape(title_match.group(1)).strip()) if title_match else ""
    og_image = _meta(page, "og:image")
    photo = ""
    code = re.search(r"-([0-9a-f]{10})\.(?:jpg|jpeg|png|webp)$", og_image)
    if code:
        found = re.search(r"https://media\.lavozriojana\.com/noticias/[0-9/]+" + code.group(1) + r"[0-9a-f]*\.(?:webp|jpg|jpeg|png)", page)
        photo = found.group(0) if found else ""
    # El <title> se corta con "..." en titulares largos: se usa el título
    # social (también propio) o, si ambos están cortados, nada.
    social = _meta(page, "og:title")
    if _truncated(title):
        title = social if social and not _truncated(social) else ""
    return {
        "title": title,
        "social_title": _meta(page, "og:title"),
        "description": _meta(page, "og:description"),
        "section": _meta(page, "article:section"),
        "photo_url": photo,
    }


def fetch_article(web_url: str) -> dict | None:
    if not web_url.startswith("https://lavozriojana.com/"):
        return None
    try:
        response = safe_get(web_url, headers=_UA, timeout=30)
    except (UnsafeURLError, requests.RequestException) as exc:
        logger.warning("No se pudo leer la nota %s: %s", web_url, type(exc).__name__)
        return None
    if response.status_code != 200:
        logger.warning("Nota %s respondió %s", web_url, response.status_code)
        return None
    data = parse_article_page(response.text)
    data["url"] = web_url
    return data
