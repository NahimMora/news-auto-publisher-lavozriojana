"""
Scraping de la sección Locales de fenix951.com.ar (Multiplataforma Fénix).

El sitio es PHP sin RSS ni metadatos ``og`` salvo la imagen. Las notas viven en
``noticia.php?id=N``; el listado de la categoría trae cada una como
``a.enlace``. La categoría "Locales" mezcla notas riojanas con entrevistas de
temas nacionales, así que ``has_riojan_link`` decide qué entra al pipeline.
"""
import os
import re
import shutil
import unicodedata

import requests
from bs4 import BeautifulSoup

from utils.editorial_router import RIOJAN_LOCALITY_TERMS
from utils.image_processor import FOTOS_DIR, optimize_image, process_image
from utils.logging_setup import setup_logger
from utils.safe_http import safe_get
from utils.scraper_contract import (
    ArticleScrapeResult,
    LinkScrapeResult,
    request_error_details,
)
from utils.stage_result import StageStatus
from utils.url_normalization import url_hash

BASE_SITE = "https://www.fenix951.com.ar"
SECTION_URL = f"{BASE_SITE}/categoria.php?id=1"
SECTION_NAME = "locales"
SOURCE_NAME = "fenix_locales"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}

MAX_LINKS = int(os.getenv("SCRAPER_MAX_LINKS", "8"))

_ARTICLE_ID_RE = re.compile(r"noticia\.php\?id=(\d+)")
# "16:48 | Jueves 22 de Octubre de 2026 | La Rioja, Argentina | Fenix Multiplataforma":
# está en todas las notas, incluso las nacionales; no cuenta como cuerpo ni como vínculo.
_DATELINE_RE = re.compile(r"^\s*\d{1,2}:\d{2}\s*\|")
_DATE_RE = re.compile(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", re.IGNORECASE)
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
_IN_PROGRESS_MARKERS = ("nota en redaccion", "nota en desarrollo")

# Localidades e instituciones riojanas que la lista del router no cubre y que
# Fénix nombra sin decir "La Rioja" (p. ej. "vecino de Villa Castelli").
FENIX_RIOJAN_TERMS = {
    "sanagasta", "villa sanagasta", "villa castelli", "chanarmuyo", "olta",
    "ulapes", "aminga", "anillaco", "malanzan", "catuna", "tama",
    "villa mazan", "sanogasta", "vichigasta", "pituil", "los sarmientos",
    "unlar", "vera barros", "unidad regional", "quintela",
}


def scrap_links_result() -> LinkScrapeResult:
    """Lista las notas de la sección Locales de Fénix."""
    logger = setup_logger("scraper.fenix.links", "scrapers.log")
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
    links: list[str] = []
    # Sólo ``a.enlace``: los menús desplegables repiten notas de otras categorías.
    for a in soup.select("a.enlace[href]"):
        url = article_url(a.get("href", ""))
        if url and url not in links:
            links.append(url)
        if len(links) >= MAX_LINKS:
            break

    logger.info(f"Fénix {SECTION_NAME}: {len(links)} artículos encontrados")
    return LinkScrapeResult(
        status=StageStatus.SUCCESS if links else StageStatus.NO_WORK,
        links=links,
    )


def article_url(href: str) -> str | None:
    """URL canónica de una nota (host con www, sin parámetros extra)."""
    match = _ARTICLE_ID_RE.search(href or "")
    if not match:
        return None
    return f"{BASE_SITE}/noticia.php?id={match.group(1)}"


def scrap_noticia_result(url: str) -> ArticleScrapeResult:
    """Extrae título, copete, cuerpo, imagen, fecha y categoría de una nota."""
    logger = setup_logger("scraper.fenix.noticia", "scrapers.log")
    canonical = article_url(url)
    if not canonical:
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type="selector_mismatch",
            message="url_without_article_id",
        )
    try:
        r = requests.get(canonical, headers=HEADERS, timeout=25)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Error accediendo a {canonical}: {e}")
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
        logger.warning(f"Sin título en: {canonical}")
        return ArticleScrapeResult(
            status=StageStatus.FAILED,
            error_type="selector_mismatch",
            message="title_missing",
        )

    cuerpo = _extract_body(soup)
    if not cuerpo:
        # Fénix publica primero "NOTA EN REDACCIÓN" y completa después: el
        # runner la difiere sin marcarla en el histórico y la reintenta.
        logger.info(f"Nota sin cuerpo todavía: {canonical}")
        return ArticleScrapeResult(
            status=StageStatus.NO_WORK,
            error_type="article_in_progress",
            message="body_missing",
        )

    # Copete, categoría y fecha se buscan junto al ``h1``: los menús
    # desplegables tienen sus propios ``p.copete`` de otras notas.
    heading = soup.select_one("h1.titulo")
    copete = _text(heading.find_next_sibling("p", class_="copete")) if heading else ""
    parrafos = ([copete] if len(copete) >= 40 else []) + cuerpo
    imagen_url = _extract_image(soup, canonical)
    imagen_local, imagen_optimizada = _download_image(imagen_url, canonical, logger)

    article = {
        "titulo": titulo,
        "url": canonical,
        "canonical_url": canonical,
        "seccion": SECTION_NAME,
        "categoria_origen": (
            _text(heading.find_previous_sibling("p", class_="categoria")).lower() if heading else ""
        ),
        "parrafos": parrafos,
        "imagen_url": imagen_url,
        "imagen": imagen_local,
        "imagen_optimizada": imagen_optimizada,
        "fecha": _extract_date(soup, heading),
        "source": SOURCE_NAME,
    }
    warnings = []
    if imagen_url and not imagen_optimizada:
        warnings.append("image_download_failed")
    return ArticleScrapeResult(
        status=StageStatus.DEGRADED if warnings else StageStatus.SUCCESS,
        article=article,
        warnings=warnings,
    )


def has_riojan_link(article: dict) -> bool:
    """True si título o texto nombran una localidad o institución riojana."""
    text = _ascii_lower(" ".join([str(article.get("titulo") or "")] + list(article.get("parrafos") or [])))
    terms = {_ascii_lower(term) for term in RIOJAN_LOCALITY_TERMS} | FENIX_RIOJAN_TERMS
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)


def _extract_title(soup: BeautifulSoup) -> str | None:
    text = _text(soup.select_one("h1.titulo")) or _text(soup.select_one("h1"))
    if text:
        return text
    if soup.title:
        return _clean_text(soup.title.get_text(" ", strip=True)) or None
    return None


def _extract_body(soup: BeautifulSoup) -> list[str]:
    content = soup.select_one("div.cuerpo")
    if not content:
        return []
    parrafos = []
    for el in content.find_all(["p", "div"], recursive=False):
        text = _text(el)
        if len(text) < 40 or _DATELINE_RE.match(text):
            continue
        parrafos.append(text)
    body = _ascii_lower(" ".join(parrafos))
    if not parrafos or (any(marker in body for marker in _IN_PROGRESS_MARKERS) and len(body) < 200):
        return []
    return parrafos


def _extract_image(soup: BeautifulSoup, url: str) -> str | None:
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"].strip()
    match = _ARTICLE_ID_RE.search(url)
    if match:
        img = soup.select_one(f'img[src^="imagenes/{match.group(1)}_"]')
        if img:
            return f"{BASE_SITE}/{img['src'].lstrip('/')}"
    return None


def _extract_date(soup: BeautifulSoup, heading) -> str | None:
    candidates = [_text(heading.find_next_sibling("p", class_="fecha")) if heading else ""]
    content = soup.select_one("div.cuerpo")
    if content:
        candidates.append(_text(content.find("p")))
    for value in candidates:
        match = _DATE_RE.search(value or "")
        if not match:
            continue
        month = _MONTHS.get(_ascii_lower(match.group(2)))
        if month:
            return f"{match.group(3)}-{month:02d}-{int(match.group(1)):02d}"
    return None


def _download_image(imagen_url: str | None, article_url_: str, logger) -> tuple[str | None, str | None]:
    if not imagen_url:
        return None, None

    uid = url_hash(article_url_)
    raw_path = os.path.join(FOTOS_DIR, f"{SOURCE_NAME}_{uid}_raw.jpg")
    opt_path = os.path.join(FOTOS_DIR, f"{SOURCE_NAME}_{uid}_opt.jpg")
    try:
        resp = safe_get(imagen_url, requester=requests.get, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        if not process_image(resp.content, raw_path):
            return None, None
        shutil.copy2(raw_path, opt_path)
        optimize_image(opt_path)
        return raw_path, opt_path
    except Exception as e:
        logger.warning(f"Error descargando imagen {imagen_url}: {e}")
        return None, None


def _text(el) -> str:
    return _clean_text(el.get_text(" ", strip=True)) if el else ""


def _ascii_lower(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())
