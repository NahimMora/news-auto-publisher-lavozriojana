from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from pipeline.node_webapp.editorial import (
    EditorialResult,
    category_to_name,
    category_to_slug,
    clean_text,
    news_category,
    prepare_editorial,
    source_display_name,
)
from pipeline.node_webapp.media import MediaResult, prepare_media
from utils.classifier import clasificar as _clasificar
from utils.editorial_priority import priority_interleave, split_priority_batch
from utils.file_manager import load_json, save_json
from utils.logging_setup import setup_logger
from utils.news_dedup import duplicate_reason
from utils.url_normalization import url_hash

logger = setup_logger("node_webapp.publisher", "publish_web.log")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
INPUT = os.getenv("WEB_QUEUE_PATH", os.path.join(DATA_DIR, "noticias_web_pending.json"))
META_OUTPUT = os.getenv("META_QUEUE_PATH", os.path.join(DATA_DIR, "noticias_meta.json"))
SOCIAL_OUTPUT = os.getenv("SOCIAL_QUEUE_PATH", os.path.join(DATA_DIR, "noticias_sociales_pendientes.json"))
PUBLISHED_HISTORY = os.getenv("WEB_PUBLISHED_HISTORY_PATH", os.path.join(DATA_DIR, "noticias_web_publicadas.json"))
WEB_DEDUP_HISTORY_DAYS = int(os.getenv("WEB_DEDUP_HISTORY_DAYS", "7"))
ALLOWED_STATUS = {"published", "draft", "archived"}

_CATEGORY_AUTHORS: dict[str, str] = {
    "politica":     "Redacción Política",
    "policiales":   "Redacción Policiales",
    "interior":     "Redacción Interior",
    "sociedad":     "Redacción Sociedad",
    "economia":     "Redacción Economía",
    "salud":        "Redacción Salud",
    "educacion":    "Redacción Educación",
    "deportes":     "Redacción Deportes",
    "cultura":      "Redacción Cultura",
    "espectaculos": "Redacción Espectáculos",
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _web_max_per_run() -> int | None:
    value = _env_int("WEB_PUBLISH_MAX_PER_RUN", 0)
    return value if value > 0 else None


def _web_category_caps() -> dict[str, int]:
    max_deportes = _env_int(
        "WEB_MAX_DEPORTES_PER_RUN",
        _env_int("MAX_DEPORTES_PER_RUN", 1),
    )
    return {"deportes": max_deportes}


class InvalidCredentialError(RuntimeError):
    pass


def classify(noticia: dict) -> str:
    seccion = news_category(noticia)
    if seccion and category_to_slug(seccion) != "sociedad":
        return seccion
    if seccion and seccion.lower().strip() == "sociedad":
        return seccion
    return _clasificar(noticia.get("titulo", ""), noticia.get("parrafos", []))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def external_id(noticia: dict) -> str:
    basis = "|".join(
        str(noticia.get(key) or "")
        for key in ("canonical_url", "url", "titulo_original", "titulo", "fecha")
    )
    return hashlib.sha1(basis.encode("utf-8", errors="ignore")).hexdigest()


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {key: _drop_empty(item) for key, item in value.items()}
        return {
            key: item
            for key, item in cleaned.items()
            if item is not None and item != "" and item != [] and item != {}
        }
    if isinstance(value, list):
        return [item for item in (_drop_empty(item) for item in value) if item not in (None, "", [], {})]
    return value


def _is_http_url(value: object) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _text_len(value: object) -> int:
    return len(clean_text(value))


def _parse_iso_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_post_payload(payload: dict, *, now: datetime | None = None) -> list[str]:
    warnings: list[str] = []

    title_len = _text_len(payload.get("title"))
    if title_len < 8 or title_len > 240:
        warnings.append(f"title_length_out_of_range:{title_len}")

    excerpt_len = _text_len(payload.get("excerpt"))
    if excerpt_len < 20 or excerpt_len > 1500:
        warnings.append(f"excerpt_length_out_of_range:{excerpt_len}")

    if not clean_text(payload.get("contentHtml")):
        warnings.append("contentHtml_empty")

    if category_to_slug(str(payload.get("categorySlug") or "")) != payload.get("categorySlug"):
        warnings.append(f"invalid_categorySlug:{payload.get('categorySlug')}")

    status = payload.get("status")
    if status not in ALLOWED_STATUS:
        warnings.append(f"invalid_status:{status}")

    published_at = _parse_iso_datetime(payload.get("publishedAt"))
    if payload.get("publishedAt") and not published_at:
        warnings.append("publishedAt_invalid_iso")
    if status == "published":
        if not published_at:
            warnings.append("publishedAt_required_for_published")
        else:
            now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            if published_at > now_utc:
                warnings.append("publishedAt_in_future")

    main_image = payload.get("mainImage")
    if not isinstance(main_image, dict):
        warnings.append("mainImage_required")
    else:
        if not _is_http_url(main_image.get("url")) or len(str(main_image.get("url") or "")) > 500:
            warnings.append("mainImage_url_invalid")
        for field in ("width", "height"):
            try:
                if int(main_image.get(field) or 0) <= 0:
                    warnings.append(f"mainImage_{field}_invalid")
            except (TypeError, ValueError):
                warnings.append(f"mainImage_{field}_invalid")
        if not clean_text(main_image.get("alt")):
            warnings.append("mainImage_alt_required")

    og_image_url = payload.get("ogImageUrl")
    if og_image_url and (not _is_http_url(og_image_url) or len(str(og_image_url)) > 500):
        warnings.append("ogImageUrl_invalid")

    source_url = payload.get("sourceUrl")
    if source_url and (not _is_http_url(source_url) or len(str(source_url)) > 500):
        warnings.append("sourceUrl_invalid")

    source_name_len = _text_len(payload.get("sourceName"))
    if source_name_len > 180:
        warnings.append(f"sourceName_too_long:{source_name_len}")

    for field, max_len in (
        ("seoTitle", 255),
        ("ogTitle", 255),
        ("seoDescription", 320),
        ("ogDescription", 320),
    ):
        length = _text_len(payload.get(field))
        if length > max_len:
            warnings.append(f"{field}_too_long:{length}")

    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        warnings.append("tags_must_be_list")
    else:
        if len(tags) > 20:
            warnings.append(f"too_many_tags:{len(tags)}")
        for tag in tags:
            tag_len = _text_len(tag)
            if tag_len == 0 or tag_len > 100:
                warnings.append(f"invalid_tag_length:{tag_len}")

    return warnings


def build_post_payload(
    noticia: dict,
    editorial: EditorialResult,
    media: MediaResult,
    *,
    published_at: str | None = None,
    is_breaking: bool = False,
    is_featured: bool = False,
) -> dict:
    if not media.main_image:
        raise ValueError("mainImage is required")
    if not editorial.content_html:
        raise ValueError("contentHtml is required")

    category_slug = category_to_slug(classify(noticia))
    category_name = category_to_name(category_slug)
    source_url = clean_text(noticia.get("canonical_url") or noticia.get("url") or "")
    source_name = source_display_name(noticia)
    imported_at = utc_now_iso()
    author = _CATEGORY_AUTHORS.get(category_slug, os.getenv("WEBAPP_DEFAULT_AUTHOR", "Redacci\u00f3n La Voz Riojana"))

    metadata = {
        "externalId": external_id(noticia),
        "sourceSystem": clean_text(noticia.get("source") or "autopublicador_lavozriojana"),
        "sourceUrl": source_url,
        "sourceName": source_name,
        "scrapedPublishedDate": clean_text(noticia.get("fecha") or ""),
        "importedAt": imported_at,
        "focusKeyword": editorial.focus_keyword,
        "editorialQualityScore": editorial.quality_score,
        "editorialFallbackUsed": editorial.fallback_used,
        "editorialWarnings": editorial.warnings,
    }

    payload = {
        "title": editorial.title.upper(),
        "excerpt": editorial.excerpt,
        "contentHtml": editorial.content_html,
        "categorySlug": category_slug,
        "categoryName": category_name,
        "authorName": author,
        "tags": editorial.tags,
        "sourceName": source_name,
        "sourceUrl": source_url,
        "mainImage": media.main_image,
        "ogImageUrl": media.og_image_url or media.main_image["url"],
        "seoTitle": editorial.seo_title,
        "seoDescription": editorial.meta_description,
        "ogTitle": editorial.social_title,
        "ogDescription": editorial.social_description,
        "status": "published",
        "publishedAt": published_at or utc_now_iso(),
        "metadata": metadata,
    }

    if is_breaking:
        payload["isBreaking"] = True
    if is_featured:
        payload["isFeatured"] = True
        payload["editorialPriority"] = 100

    payload = _drop_empty(payload)
    warnings = validate_post_payload(payload)
    if warnings:
        raise ValueError("Payload invalido: " + ", ".join(warnings))
    return payload


def _webapp_config() -> tuple[str, str, int, int, float]:
    base_url = os.getenv("WEBAPP_BASE_URL", "").strip()
    # Acepta PRIVATE_API_KEY (nombre interno) o WEBAPP_API_KEY (nombre en .env)
    private_api_key = (
        os.getenv("PRIVATE_API_KEY", "").strip()
        or os.getenv("WEBAPP_API_KEY", "").strip()
    )
    timeout = int(os.getenv("WEBAPP_REQUEST_TIMEOUT", "30"))
    retries = int(os.getenv("WEBAPP_REQUEST_RETRIES", "3"))
    retry_sleep = float(os.getenv("WEBAPP_RETRY_SLEEP_SECONDS", "5"))
    return base_url, private_api_key, timeout, retries, retry_sleep


def post_payload(payload: dict) -> dict | None:
    base_url, private_api_key, timeout, retries, retry_sleep = _webapp_config()
    if not base_url or base_url == "PENDIENTE":
        logger.warning("WEBAPP_BASE_URL no configurada, saltando publicacion web")
        return None
    if not private_api_key or private_api_key == "PENDIENTE":
        logger.error("PRIVATE_API_KEY no configurada, no se publica en WebApp")
        return None

    endpoint = f"{base_url.rstrip('/')}/api/private/posts"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": private_api_key,
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
            if response.status_code == 401:
                logger.error("WebApp devolvio 401: PRIVATE_API_KEY invalida")
                raise InvalidCredentialError("PRIVATE_API_KEY invalida")

            if response.status_code in (200, 201):
                try:
                    data = response.json()
                except ValueError:
                    logger.error("WebApp HTTP %s sin JSON valido: %s", response.status_code, response.text[:200])
                    return None
                if data.get("ok") is True:
                    logger.info("Publicado en WebApp: %s", payload.get("title", "")[:70])
                    return data
                logger.error("WebApp respondio ok:false: %s", str(data)[:300])
                return None

            if response.status_code == 429:
                logger.warning("Rate limit WebApp HTTP 429 intento %s/%s", attempt, retries)
                if attempt < retries:
                    time.sleep(retry_sleep)
                continue

            logger.error("Error WebApp HTTP %s: %s", response.status_code, response.text[:300])
            return None
        except InvalidCredentialError:
            raise
        except requests.RequestException as exc:
            logger.error("Error de red WebApp intento %s/%s: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(retry_sleep)
    return None


def _queue_key(noticia: dict) -> str:
    url = noticia.get("canonical_url") or noticia.get("url") or ""
    if url:
        return f"link:{url_hash(url)}"
    if noticia.get("web_queue_key"):
        return str(noticia["web_queue_key"])
    if noticia.get("meta_queue_key"):
        return str(noticia["meta_queue_key"])
    return f"item:{external_id(noticia)}"


def _item_queue_key(item: dict) -> str:
    for field in ("web_queue_key", "meta_queue_key", "dedup_key"):
        if item.get(field):
            return str(item[field])
    return _queue_key(item)


_DEDUP_KEY_FIELDS = ("web_queue_key", "meta_queue_key", "dedup_key", "canonical_url", "url")


def _history_timestamp(item: dict) -> int:
    for field in ("published_at_ts", "web_published_at_ts"):
        try:
            value = int(item.get(field) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def _load_published_history() -> list[dict]:
    history = load_json(PUBLISHED_HISTORY, [])
    if not isinstance(history, list):
        history = []
    cutoff = int(time.time()) - WEB_DEDUP_HISTORY_DAYS * 86400
    active = [
        item for item in history
        if isinstance(item, dict) and _history_timestamp(item) >= cutoff
    ]
    if active != history:
        save_json(PUBLISHED_HISTORY, active)
    return active


def _filter_publish_duplicates(
    noticias: list[dict],
    published_history: list[dict],
) -> tuple[list[dict], int]:
    unique = []
    skipped = 0
    for noticia in noticias:
        reason = duplicate_reason(
            noticia,
            published_history,
            key_fields=_DEDUP_KEY_FIELDS,
        )
        if reason:
            skipped += 1
            logger.info(
                "WebApp: duplicado ya publicado (%s), se omite: %s",
                reason,
                noticia.get("titulo", "")[:70],
            )
            continue

        reason = duplicate_reason(
            noticia,
            unique,
            key_fields=_DEDUP_KEY_FIELDS,
        )
        if reason:
            skipped += 1
            logger.info(
                "WebApp: duplicado pendiente (%s), se omite: %s",
                reason,
                noticia.get("titulo", "")[:70],
            )
            continue
        unique.append(noticia)
    return unique, skipped


def _history_item(noticia: dict, payload: dict, public_url: str) -> dict:
    parrafos = noticia.get("parrafos") or []
    first_paragraph = str(parrafos[0] or "").strip() if isinstance(parrafos, list) and parrafos else ""
    return _drop_empty({
        "web_queue_key": noticia.get("web_queue_key"),
        "meta_queue_key": noticia.get("meta_queue_key"),
        "dedup_key": noticia.get("dedup_key"),
        "titulo": payload.get("title") or noticia.get("titulo"),
        "titulo_original": noticia.get("titulo_original"),
        "titulo_original_scrapeado": noticia.get("titulo_original_scrapeado"),
        "excerpt": payload.get("excerpt") or first_paragraph,
        "source": noticia.get("source"),
        "canonical_url": noticia.get("canonical_url"),
        "url": noticia.get("url"),
        "web_url": public_url,
        "published_at_ts": int(time.time()),
    })


def _record_published_history(noticia: dict, payload: dict, public_url: str) -> None:
    history = _load_published_history()
    item = _history_item(noticia, payload, public_url)
    if duplicate_reason(item, history, key_fields=_DEDUP_KEY_FIELDS):
        return
    history.append(item)
    save_json(PUBLISHED_HISTORY, history)


def _response_post_data(response_data: dict | None) -> dict:
    if not isinstance(response_data, dict):
        return {}
    data = response_data.get("data")
    if isinstance(data, dict):
        return data
    return response_data


def _response_value(data: dict, *names: str) -> str:
    for name in names:
        value = data.get(name)
        if value:
            return clean_text(value)
    for child_name in ("post", "article", "news", "noticia"):
        child = data.get(child_name)
        if isinstance(child, dict):
            value = _response_value(child, *names)
            if value:
                return value
    return ""


def public_post_url(response_data: dict | None, base_url: str) -> str:
    data = _response_post_data(response_data)
    direct_url = _response_value(
        data,
        "url",
        "publicUrl",
        "public_url",
        "link",
        "permalink",
        "permalinkUrl",
        "permalink_url",
    )
    if _is_http_url(direct_url):
        return direct_url

    slug = _response_value(data, "slug")
    if slug and base_url:
        return f"{base_url.rstrip('/')}/noticias/{slug.strip('/')}"
    return ""


def sync_meta_web_link(noticia: dict, response_data: dict | None, base_url: str) -> str:
    public_url = public_post_url(response_data, base_url)
    if not public_url:
        logger.warning("WebApp no devolvio URL/slug publico para sincronizar Meta")
        return ""

    data = _response_post_data(response_data)
    updates = {
        "web_url": public_url,
        "noticia_url": public_url,
        "web_published_at": utc_now_iso(),
    }
    slug = _response_value(data, "slug")
    post_id = _response_value(data, "id", "postId", "post_id")
    if slug:
        updates["web_slug"] = slug
    if post_id:
        updates["web_post_id"] = post_id

    key = _queue_key(noticia)
    updated_files = 0
    for path in (META_OUTPUT, SOCIAL_OUTPUT):
        queue = load_json(path, [])
        if not isinstance(queue, list):
            continue
        changed = False
        for item in queue:
            if isinstance(item, dict) and _item_queue_key(item) == key:
                item.update(updates)
                changed = True
        if changed:
            save_json(path, queue)
            updated_files += 1

    logger.info("Link web sincronizado para Meta (%s archivos): %s", updated_files, public_url)
    return public_url


def publish_one_detailed(noticia: dict, *, featured_claimed: bool = False) -> dict:
    """
    Publica una noticia en la WebApp y devuelve el detalle completo del resultado.

    Retorna {"published", "featured", "public_url", "post_id", "response", "error"}.
    featured_claimed: True si ya se asignó isFeatured a otra nota en este lote;
                      evita múltiples featured por ciclo.
    """
    from pipeline.node_webapp.editorial_flags import (
        clear_breaking,
        clear_featured,
        detect_breaking,
        detect_featured,
        load_flags,
        register_breaking,
        register_featured,
        resolve_post_id,
        save_flags,
    )

    empty = {
        "published": False,
        "featured": False,
        "public_url": "",
        "post_id": "",
        "response": None,
        "error": None,
    }

    editorial = prepare_editorial(noticia)
    media = prepare_media(noticia, editorial.title)
    if not media.ok:
        logger.error("No se publica sin imagen principal publica verificada: %s", media.warnings)
        return {**empty, "error": "media_not_ok:" + ",".join(media.warnings)}

    category_slug = category_to_slug(classify(noticia))
    is_breaking = detect_breaking(editorial.title, category_slug)
    is_featured = (
        not featured_claimed
        and not is_breaking
        and detect_featured(category_slug, editorial.quality_score)
    )

    try:
        payload = build_post_payload(
            noticia, editorial, media,
            is_breaking=is_breaking,
            is_featured=is_featured,
        )
    except ValueError as exc:
        logger.error("No se publica por payload invalido: %s", exc)
        return {**empty, "error": f"invalid_payload:{exc}"}

    logger.info(
        "Payload listo category=%s breaking=%s featured=%s score=%.2f tags=%s fallback=%s",
        payload.get("categorySlug"),
        is_breaking,
        is_featured,
        editorial.quality_score,
        payload.get("tags", []),
        editorial.fallback_used,
    )

    # Desactivar flags anteriores antes de publicar
    flags = load_flags()
    if is_breaking:
        flags = clear_breaking(flags)
    if is_featured:
        flags = clear_featured(flags)

    response_data = post_payload(payload)
    if not response_data:
        return {**empty, "error": "post_payload_failed"}

    # Registrar el ID del nuevo post publicado
    post_id = resolve_post_id(response_data)
    if post_id:
        if is_breaking:
            flags = register_breaking(flags, post_id)
        if is_featured:
            flags = register_featured(flags, post_id)
        save_flags(flags)
    else:
        logger.warning(
            "WebApp no devolvió ID del post; los flags %s no quedan rastreados",
            [f for f, active in (("breaking", is_breaking), ("featured", is_featured)) if active],
        )

    base_url, *_ = _webapp_config()
    public_url = sync_meta_web_link(noticia, response_data, base_url)
    _record_published_history(noticia, payload, public_url)
    return {
        "published": True,
        "featured": is_featured,
        "public_url": public_url,
        "post_id": post_id,
        "response": response_data,
        "error": None,
    }


def publish_one(noticia: dict, *, featured_claimed: bool = False) -> tuple[bool, bool]:
    """
    Publica una noticia en la WebApp.

    Retorna (publicado, fue_featured).
    """
    result = publish_one_detailed(noticia, featured_claimed=featured_claimed)
    return result["published"], result["featured"]


def publish_pending() -> None:
    noticias = load_json(INPUT, [])
    if not noticias:
        logger.info("Sin noticias pendientes para publicar en WebApp")
        return

    published_history = _load_published_history()
    noticias, skipped_duplicates = _filter_publish_duplicates(noticias, published_history)
    if skipped_duplicates:
        logger.info("WebApp: %s duplicados descartados antes de publicar", skipped_duplicates)
        save_json(INPUT, noticias)
    if not noticias:
        logger.info("Sin noticias pendientes para publicar en WebApp tras deduplicar")
        return

    noticias, diferidas = split_priority_batch(
        noticias,
        max_items=_web_max_per_run(),
        category_caps=_web_category_caps(),
    )
    if diferidas:
        logger.info(
            "WebApp: prioridad editorial dejo %s notas diferidas (cupo Deportes=%s)",
            len(diferidas),
            _web_category_caps().get("deportes"),
        )

    publicadas: list[dict] = []
    fallidas: list[dict] = []
    stopped_for_auth = False
    featured_claimed = False  # solo una nota isFeatured por lote

    for index, noticia in enumerate(noticias):
        try:
            success, was_featured = publish_one(noticia, featured_claimed=featured_claimed)
            if success:
                publicadas.append(noticia)
                if was_featured:
                    featured_claimed = True
            else:
                fallidas.append(noticia)
        except InvalidCredentialError:
            stopped_for_auth = True
            fallidas.append(noticia)
            fallidas.extend(noticias[index + 1 :])
            break
        except Exception as exc:
            logger.exception("Fallo inesperado publicando noticia: %s", exc)
            fallidas.append(noticia)

    fallidas.extend(diferidas)
    logger.info("WebApp: %s publicadas, %s pendientes", len(publicadas), len(fallidas))
    if stopped_for_auth:
        logger.error("Lote detenido por credencial invalida; las noticias restantes quedan en cola")
    save_json(INPUT, priority_interleave(fallidas))
