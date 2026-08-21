"""
Scraping de paparazzi.com.ar (farándula/espectáculos). Estructura WordPress
estándar, igual que tiempopopular.com.ar — ver scraping/base_tiempopopular.py.

Diferencia principal: algunas notas embeben un video JWPlayer
(``<div class="contenedor_video_intro"><script src=".../players/{MEDIA_ID}-{SITE_ID}.js">``)
que se puede resolver contra el endpoint público de JWPlayer
(``https://cdn.jwplayer.com/v2/media/{MEDIA_ID}``, sin auth) para obtener una URL
mp4 directa y la duración real. Esas notas son entrevistas largas — el ``video_url``
resultante nunca es apto para publicar tal cual, siempre requiere recorte
(ver utils/video_renderer.py y meta/ig_client.py, flujo carrusel paparazzi).
"""
import os
import re
import shutil
import time

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlsplit

from utils.url_normalization import canonical_url, url_hash
from utils.image_processor import process_image, optimize_image, FOTOS_DIR
from utils.logging_setup import setup_logger
from utils.safe_http import safe_get
from utils.scraper_contract import (
    ArticleScrapeResult,
    LinkScrapeResult,
    request_error_details,
)
from utils.stage_result import StageStatus

BASE_SITE = "https://www.paparazzi.com.ar"
SECTION_URL = f"{BASE_SITE}/"
SECTION_NAME = "paparazzi"

# Categorías con contenido noticioso real; excluye horóscopo (no es noticia) y
# branded-content (publicidad paga) por defecto.
ARTICLE_CATEGORIES = {"teve", "looks", "romances", "internacionales", "deportes", "videos"}
EXCLUDED_CATEGORIES = {
    value.strip().lower()
    for value in os.getenv("PAPARAZZI_EXCLUDED_CATEGORIES", "horoscopo,branded-content").split(",")
    if value.strip()
}
ARTICLE_URL_RE = re.compile(r"^/([a-z0-9-]+)/([a-z0-9-]{8,})/?$")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}

MAX_LINKS = int(os.getenv("SCRAPER_MAX_LINKS", "8"))
JWPLAYER_MEDIA_RE = re.compile(r"cdn\.jwplayer\.com/players/([A-Za-z0-9]+)-[A-Za-z0-9]+\.js")
JWPLAYER_MP4_LABEL_PRIORITY = ["540p", "480p", "360p", "720p", "270p", "180p", "1080p"]

# paparazzi.com.ar devuelve 429 (Cloudflare) tras ~10-15 requests seguidos sin
# pausa — a diferencia de las demás fuentes, necesita este throttle propio.
REQUEST_DELAY_SECONDS = float(os.getenv("PAPARAZZI_REQUEST_DELAY_SECONDS", "2.5"))


# ── LINKS SCRAPER ────────────────────────────────────────────────────────────

def scrap_links_result() -> LinkScrapeResult:
    """Extrae URLs de artículos desde el home de paparazzi.com.ar (cruza categorías)."""
    logger = setup_logger(f"scraper.{SECTION_NAME}.links", "scrapers.log")
    try:
        r = requests.get(SECTION_URL, headers=HEADERS, timeout=25)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Error accediendo a {SECTION_URL}: {e}")
        error_type, http_status = request_error_details(e)
        return LinkScrapeResult(
            status=StageStatus.FAILED,
            error_type=error_type,
            http_status=http_status,
            message=str(e),
        )

    soup = BeautifulSoup(r.text, "html.parser")
    seen = set()
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if _is_article_url(href) and href not in seen:
            seen.add(href)
            links.append(canonical_url(urljoin(BASE_SITE + "/", href)))
        if len(links) >= MAX_LINKS:
            break

    logger.info(f"Paparazzi: {len(links)} artículos encontrados")
    return LinkScrapeResult(
        status=StageStatus.SUCCESS if links else StageStatus.NO_WORK,
        links=links,
    )


def _is_article_url(href: str) -> bool:
    if not href:
        return False
    parsed = urlsplit(urljoin(BASE_SITE + "/", href))
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or host != "paparazzi.com.ar":
        return False
    match = ARTICLE_URL_RE.fullmatch(parsed.path)
    if not match:
        return False
    category = match.group(1).lower()
    if category in EXCLUDED_CATEGORIES:
        return False
    return category in ARTICLE_CATEGORIES


# ── NOTICIA SCRAPER ──────────────────────────────────────────────────────────

def scrap_noticia_result(url: str) -> ArticleScrapeResult:
    """Extrae título, párrafos, imagen y (si existe) video de una nota de paparazzi.com.ar."""
    logger = setup_logger(f"scraper.{SECTION_NAME}.noticia", "scrapers.log")
    if REQUEST_DELAY_SECONDS > 0:
        time.sleep(REQUEST_DELAY_SECONDS)
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Error accediendo a {url}: {e}")
        error_type, http_status = request_error_details(e)
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type=error_type,
            http_status=http_status,
            message=str(e),
        )

    soup = BeautifulSoup(r.text, "html.parser")

    titulo = _extract_title(soup)
    if not titulo:
        logger.warning(f"Sin título en: {url}")
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type="selector_mismatch",
            message="title_missing",
        )

    parrafos = _extract_paragraphs(soup)
    if not parrafos:
        logger.warning(f"Sin contenido en: {url}")
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type="selector_mismatch",
            message="body_missing",
        )

    imagen_url = _extract_image(soup)
    fecha = _extract_date(soup)
    imagen_local, imagen_optimizada = _download_image(imagen_url, url, logger)
    video_url, video_duration_seconds = _extract_video(r.text, logger)

    article = {
        "titulo": titulo,
        "url": url,
        "canonical_url": canonical_url(url),
        "seccion": SECTION_NAME,
        "parrafos": parrafos,
        "imagen_url": imagen_url,
        "imagen": imagen_local,
        "imagen_optimizada": imagen_optimizada,
        "fecha": fecha,
        "source": SECTION_NAME,
    }
    if video_url:
        article["video_url"] = video_url
        if video_duration_seconds:
            article["video_duration_seconds"] = video_duration_seconds

    warnings = []
    if imagen_url and not imagen_optimizada:
        warnings.append("image_download_failed")
    return ArticleScrapeResult(
        status=StageStatus.DEGRADED if warnings else StageStatus.SUCCESS,
        article=article,
        warnings=warnings,
    )


def _extract_title(soup: BeautifulSoup) -> str | None:
    for sel in ["h1.entry-title", "h1.post-title", "h1"]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if text:
                return text
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    return None


def _extract_paragraphs(soup: BeautifulSoup) -> list[str]:
    content = (
        soup.select_one("div.entry-content")
        or soup.select_one("div.post-content")
        or soup.select_one("article")
    )
    if not content:
        return []

    parrafos = []
    for p in content.find_all("p"):
        text = p.get_text(separator=" ", strip=True)
        if len(text) < 40:
            continue
        lower = text.lower()
        if any(kw in lower for kw in ["foto:", "fuente:", "crédito:", "credito:"]):
            continue
        parrafos.append(text)

    return parrafos


def _extract_image(soup: BeautifulSoup) -> str | None:
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"].strip()

    content = soup.select_one("div.entry-content, div.post-content, article")
    if content:
        img = content.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src and src.startswith("http"):
                return src

    img = soup.select_one(".post-thumbnail img, .wp-post-image, .featured-image img")
    if img:
        src = img.get("src") or img.get("data-src")
        if src and src.startswith("http"):
            return src

    return None


def _extract_date(soup: BeautifulSoup) -> str | None:
    meta = soup.find("meta", property="article:published_time")
    if meta and meta.get("content"):
        return meta["content"][:10]
    return None


def _extract_video(html: str, logger) -> tuple[str | None, int | None]:
    """Resuelve el video JWPlayer embebido (si existe) contra la API pública de JWPlayer.

    Nunca falla el scraping de la nota: si no hay video, o la API de JWPlayer no
    responde/cambia de forma, se degrada silenciosamente a "sin video" (la nota
    igual se publica, solo con imagen).
    """
    match = JWPLAYER_MEDIA_RE.search(html)
    if not match:
        return None, None
    media_id = match.group(1)
    try:
        resp = safe_get(
            f"https://cdn.jwplayer.com/v2/media/{media_id}",
            requester=requests.get,
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.info(f"No se pudo resolver video JWPlayer {media_id}: {e}")
        return None, None

    playlist = data.get("playlist") or []
    if not playlist or not isinstance(playlist, list):
        return None, None
    item = playlist[0] if isinstance(playlist[0], dict) else {}
    sources = item.get("sources") or []
    mp4_by_label = {
        s.get("label"): s.get("file")
        for s in sources
        if isinstance(s, dict) and s.get("type") == "video/mp4" and s.get("file")
    }
    video_url = None
    for label in JWPLAYER_MP4_LABEL_PRIORITY:
        if label in mp4_by_label:
            video_url = mp4_by_label[label]
            break
    if not video_url and mp4_by_label:
        video_url = next(iter(mp4_by_label.values()))
    if not video_url:
        return None, None

    duration = item.get("duration")
    try:
        duration_seconds = int(duration) if duration else None
    except (TypeError, ValueError):
        duration_seconds = None
    return video_url, duration_seconds


def _download_image(
    imagen_url: str | None, article_url: str, logger
) -> tuple[str | None, str | None]:
    if not imagen_url:
        return None, None

    uid = url_hash(article_url)
    raw_path = os.path.join(FOTOS_DIR, f"{SECTION_NAME}_{uid}_raw.jpg")
    opt_path = os.path.join(FOTOS_DIR, f"{SECTION_NAME}_{uid}_opt.jpg")

    try:
        resp = safe_get(
            imagen_url,
            requester=requests.get,
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        if not process_image(resp.content, raw_path):
            return None, None
        shutil.copy2(raw_path, opt_path)
        optimize_image(opt_path)
        return raw_path, opt_path
    except Exception as e:
        logger.warning(f"Error descargando imagen {imagen_url}: {e}")
        return None, None
