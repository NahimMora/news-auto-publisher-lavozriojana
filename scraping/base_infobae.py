"""
Scraping de infobae.com/sociedad/policiales/ (policiales nacional).

A diferencia de tn.com.ar (evaluado y descartado — su player vodgc/Genoa
resuelve el video con JS ofuscado, sin endpoint público), Infobae embebe
JWPlayer estándar: el JSON-LD ``VideoObject.contentUrl`` de la nota ya trae
la URL mp4 directa (``cdn.jwplayer.com/videos/{id}.mp4``), sin necesidad de
resolver nada contra una API ni de headless browser.

El resto de los campos (título, cuerpo, imagen, fecha) también salen del
JSON-LD ``NewsArticle`` embebido en cada nota — más estable que parsear la
maquetación visual.
"""
import json
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

BASE_SITE = "https://www.infobae.com"
SECTION_URL = f"{BASE_SITE}/sociedad/policiales/"
SECTION_NAME = "infobae_policiales"

ARTICLE_URL_RE = re.compile(r"^/sociedad/policiales/\d{4}/\d{2}/\d{2}/[a-z0-9-]+/?$")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}

MAX_LINKS = int(os.getenv("SCRAPER_MAX_LINKS", "8"))
# No se observó rate-limit en pruebas manuales (a diferencia de paparazzi.com.ar
# con Cloudflare) — se deja una pausa chica por las dudas en corridas 24x7.
REQUEST_DELAY_SECONDS = float(os.getenv("INFOBAE_REQUEST_DELAY_SECONDS", "1.0"))

ISO_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


# ── LINKS SCRAPER ────────────────────────────────────────────────────────────

def scrap_links_result() -> LinkScrapeResult:
    """Extrae URLs de notas desde infobae.com/sociedad/policiales/."""
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

    logger.info(f"Infobae Policiales: {len(links)} artículos encontrados")
    return LinkScrapeResult(
        status=StageStatus.SUCCESS if links else StageStatus.NO_WORK,
        links=links,
    )


def _is_article_url(href: str) -> bool:
    if not href:
        return False
    parsed = urlsplit(urljoin(BASE_SITE + "/", href))
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or host != "infobae.com":
        return False
    return bool(ARTICLE_URL_RE.fullmatch(parsed.path))


# ── NOTICIA SCRAPER ──────────────────────────────────────────────────────────

def scrap_noticia_result(url: str) -> ArticleScrapeResult:
    """Extrae título, párrafos, imagen y (si existe) video de una nota de Infobae."""
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
    article_ld, video_ld = _extract_ld_json(soup)

    titulo = _extract_title(soup, article_ld)
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

    imagen_url = _extract_image(soup, article_ld)
    fecha = _extract_date(soup, article_ld)
    imagen_local, imagen_optimizada = _download_image(imagen_url, url, logger)
    video_url, video_duration_seconds = _extract_video(video_ld)

    article = {
        "titulo": titulo,
        "url": url,
        "canonical_url": canonical_url(url),
        "seccion": "policiales",
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


def _extract_ld_json(soup: BeautifulSoup) -> tuple[dict, dict | None]:
    """Devuelve (NewsArticle, VideoObject|None) de los bloques JSON-LD de la nota."""
    article_ld: dict = {}
    video_ld: dict | None = None
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("@type")
            if block_type == "NewsArticle" and not article_ld:
                article_ld = block
            elif block_type == "VideoObject" and video_ld is None:
                video_ld = block
    return article_ld, video_ld


def _extract_title(soup: BeautifulSoup, article_ld: dict) -> str | None:
    if article_ld.get("headline"):
        return str(article_ld["headline"]).strip()
    el = soup.select_one("h1")
    if el:
        text = el.get_text(strip=True)
        if text:
            return text
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    return None


def _extract_paragraphs(soup: BeautifulSoup) -> list[str]:
    parrafos = []
    for p in soup.select("p.paragraph"):
        text = p.get_text(separator=" ", strip=True)
        if len(text) < 40:
            continue
        lower = text.lower()
        if any(kw in lower for kw in ["foto:", "fuente:", "crédito:", "credito:"]):
            continue
        parrafos.append(text)
    return parrafos


def _extract_image(soup: BeautifulSoup, article_ld: dict) -> str | None:
    image = article_ld.get("image")
    if isinstance(image, dict) and image.get("url"):
        return image["url"].strip()
    if isinstance(image, str) and image:
        return image.strip()

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"].strip()
    return None


def _extract_date(soup: BeautifulSoup, article_ld: dict) -> str | None:
    if article_ld.get("datePublished"):
        return str(article_ld["datePublished"])[:10]
    meta = soup.find("meta", property="article:published_time")
    if meta and meta.get("content"):
        return meta["content"][:10]
    return None


def _parse_iso_duration(value: str) -> int | None:
    match = ISO_DURATION_RE.fullmatch(value.strip()) if value else None
    if not match:
        return None
    hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    total = hours * 3600 + minutes * 60 + seconds
    return total or None


def _extract_video(video_ld: dict | None) -> tuple[str | None, int | None]:
    if not video_ld:
        return None, None
    video_url = video_ld.get("contentUrl")
    if not video_url or not str(video_url).startswith("http"):
        return None, None
    duration_seconds = _parse_iso_duration(str(video_ld.get("duration") or ""))
    return str(video_url).strip(), duration_seconds


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
