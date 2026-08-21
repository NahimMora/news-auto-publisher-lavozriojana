"""Cliente tipado de Facebook Graph API."""
from __future__ import annotations

import json
import os
import time
import uuid
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from meta.facebook_token_manager import get_page_token
from utils import r2_storage
from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.operation_result import OperationResult
from utils.paths import data_dir
from utils.safe_http import UnsafeURLError, safe_get
from utils.social_caption import build_instagram_caption
from utils.stage_result import StageStatus
from utils.url_normalization import url_hash

logger = setup_logger("fb_client", "fb_client.log")

FB_STATE_PATH = str(data_dir() / "fb_posted.json")
GRAPH_API = os.getenv("META_GRAPH_API", "https://graph.facebook.com/v19.0").rstrip("/")
PAGE_ID = os.getenv("FB_PAGE_ID", "")
DISABLED_PAGE_IDS = {
    value.strip()
    for value in os.getenv("FB_DISABLED_PAGE_IDS", "").split(",")
    if value.strip()
}
TEMP_BLOCK_BACKOFF = int(os.getenv("FB_TEMP_BLOCK_BACKOFF_SECONDS", "1800"))


def _load_state() -> dict:
    return load_json(FB_STATE_PATH, {"posted": {}, "page_backoff": {}}, expected_type=dict)


def _update_state(mutator) -> dict:
    return update_json(
        FB_STATE_PATH,
        mutator,
        {"posted": {}, "page_backoff": {}},
        expected_type=dict,
    )


def _is_posted(state: dict, dedup_key: str) -> bool:
    return dedup_key in state.get("posted", {})


def _mark_posted(dedup_key: str, external_id: str, noticia: dict) -> None:
    def mutate(state):
        state.setdefault("posted", {})[dedup_key] = {
            "posted_at": int(time.time()),
            "external_id": external_id,
            "titulo": noticia.get("titulo", ""),
            "canonical_url": noticia.get("canonical_url") or noticia.get("url") or "",
        }
        return state

    _update_state(mutate)


def _backoff_until(state: dict) -> int:
    return int(state.get("page_backoff", {}).get(PAGE_ID, 0) or 0)


def _set_backoff() -> int:
    until = int(time.time()) + TEMP_BLOCK_BACKOFF

    def mutate(state):
        state.setdefault("page_backoff", {})[PAGE_ID] = until
        return state

    _update_state(mutate)
    logger.warning("Backoff activado para la página configurada por %ss", TEMP_BLOCK_BACKOFF)
    return until


def _build_message(noticia: dict, link: str = "") -> str:
    parts = [
        part
        for part in (build_instagram_caption(noticia), link.strip())
        if part
    ]
    return "\n\n".join(parts)


def _prewarm_enabled() -> bool:
    return os.getenv("FB_LINK_PREWARM_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def prewarm_link_preview(link: str) -> OperationResult:
    """Calienta la nota y su og:image sin publicar ni llamar a Graph."""
    timeout = int(os.getenv("FB_LINK_PREWARM_TIMEOUT_SECONDS", "20"))
    max_bytes = int(os.getenv("FB_LINK_PREWARM_MAX_BYTES", str(5 * 1024 * 1024)))
    user_agent = (
        "facebookexternalhit/1.1 "
        "(+https://www.facebook.com/externalhit_uatext.php)"
    )
    try:
        page = safe_get(
            link,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=timeout,
        )
        status = int(getattr(page, "status_code", 0) or 0)
        content_type = str(
            getattr(page, "headers", {}).get("Content-Type") or ""
        ).lower()
        if status != 200:
            return OperationResult(
                StageStatus.DEGRADED,
                error_type="link_preview_page_http_error",
                error_code=status,
                retryable=True,
                details={"publication_outcome": "not_published"},
            )
        if "html" not in content_type:
            return OperationResult(
                StageStatus.DEGRADED,
                error_type="link_preview_page_content_type",
                retryable=True,
                details={"publication_outcome": "not_published"},
            )

        soup = BeautifulSoup(str(getattr(page, "text", "") or ""), "html.parser")
        try:
            page.close()
        except (AttributeError, TypeError):
            pass
        tag = soup.find("meta", attrs={"property": "og:image"})
        og_image = str(tag.get("content") or "").strip() if tag else ""
        if not _is_http_url(og_image):
            return OperationResult(
                StageStatus.DEGRADED,
                error_type="link_preview_missing_og_image",
                retryable=True,
                details={"publication_outcome": "not_published"},
            )

        image = safe_get(
            og_image,
            headers={"User-Agent": user_agent, "Accept": "image/*"},
            timeout=timeout,
            stream=True,
        )
        image_status = int(getattr(image, "status_code", 0) or 0)
        image_type = str(
            getattr(image, "headers", {}).get("Content-Type") or ""
        ).lower()
        if image_status != 200 or not image_type.startswith("image/"):
            try:
                image.close()
            except (AttributeError, TypeError):
                pass
            return OperationResult(
                StageStatus.DEGRADED,
                error_type="link_preview_og_image_unavailable",
                error_code=image_status,
                retryable=True,
                details={"publication_outcome": "not_published"},
            )
        total = 0
        iterator = getattr(image, "iter_content", None)
        if callable(iterator):
            for chunk in iterator(chunk_size=64 * 1024):
                total += len(chunk or b"")
                if total > max_bytes:
                    image.close()
                    return OperationResult(
                        StageStatus.DEGRADED,
                        error_type="link_preview_og_image_too_large",
                        retryable=False,
                        details={"publication_outcome": "not_published"},
                    )
        try:
            image.close()
        except (AttributeError, TypeError):
            pass
        logger.info(
            "Preview de Facebook verificado page_status=%s image_status=%s image_bytes=%s",
            status,
            image_status,
            total,
        )
        return OperationResult(
            StageStatus.SUCCESS,
            details={"og_image_url": og_image},
        )
    except (requests.RequestException, UnsafeURLError, ValueError) as exc:
        logger.warning(
            "No se pudo precalentar el preview de Facebook: %s",
            type(exc).__name__,
        )
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="link_preview_prewarm_error",
            error_code=type(exc).__name__,
            retryable=True,
            details={"publication_outcome": "not_published"},
        )


def force_facebook_rescrape(link: str, token: str) -> OperationResult:
    """Fuerza a Facebook a re-scrapear la URL (equivalente a "Scrape Again" del
    Sharing Debugger). Best-effort: nunca debe bloquear la publicación, porque
    `prewarm_link_preview` sólo valida desde la red de la app, no desde la de
    Facebook, y el post igual puede publicarse aunque este llamado falle."""
    timeout = int(os.getenv("FB_REQUEST_TIMEOUT_SECONDS", "60"))
    try:
        response = requests.post(
            f"{GRAPH_API}/",
            data={"id": link, "scrape": "true", "access_token": token},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="network_error",
            error_code=type(exc).__name__,
            retryable=True,
        )
    data = _safe_json(response)
    if response.status_code == 200 and not data.get("error"):
        logger.info("Facebook re-scrape forzado ok para %s", link)
        return OperationResult(StageStatus.SUCCESS, response=data)
    return OperationResult(
        StageStatus.DEGRADED,
        error_type="scrape_rejected",
        error_code=response.status_code,
        response=data or None,
        retryable=True,
    )


def _is_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_video_item(noticia: dict) -> bool:
    return str(noticia.get("media_type") or "").lower() == "video" or bool(
        noticia.get("video_url")
    )


def _video_url(noticia: dict) -> str:
    for key in ("video_url", "direct_video_url", "mp4_url"):
        value = str(noticia.get(key) or "").strip()
        if _is_http_url(value):
            return value
    return ""


def _web_link(noticia: dict) -> str:
    for key in ("web_url", "noticia_url", "public_url", "publicUrl", "permalink", "link"):
        value = str(noticia.get(key) or "").strip()
        if _is_http_url(value):
            return value
    return ""


def _dedup_key(noticia: dict) -> str:
    basis = (
        noticia.get("canonical_url")
        or noticia.get("url")
        or _web_link(noticia)
        or noticia.get("titulo", "")
    )
    return f"link:{url_hash(str(basis))}"


def _safe_json(response) -> dict:
    try:
        data = response.json()
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _api_result(response) -> OperationResult:
    data = _safe_json(response)
    external_id = str(data.get("id") or data.get("post_id") or data.get("video_id") or "")
    if response.status_code in {200, 201} and external_id:
        return OperationResult(
            StageStatus.SUCCESS,
            external_id=external_id,
            response=data,
        )
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    code = error.get("code") or response.status_code
    message = str(error.get("message") or "")
    if int(code or 0) == 190 or response.status_code == 401:
        return OperationResult(
            StageStatus.FAILED,
            error_type="invalid_credential",
            error_code=code,
            response=data,
        )
    if response.status_code == 429 or int(code or 0) in {4, 32, 613} or "temporarily blocked" in message.lower():
        until = _set_backoff()
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="rate_limit",
            error_code=code,
            retryable=True,
            next_retry_at=until,
            response=data,
        )
    if response.status_code >= 500:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="server_error",
            error_code=response.status_code,
            retryable=True,
            response=data,
        )
    return OperationResult(
        StageStatus.FAILED,
        error_type="request_rejected" if data else "invalid_response",
        error_code=response.status_code,
        response=data or None,
    )


def post_to_facebook_detailed(noticia: dict) -> OperationResult:
    """Publica una noticia y conserva evidencia externa antes de confirmar éxito."""
    if not PAGE_ID or PAGE_ID == "PENDIENTE":
        return OperationResult(StageStatus.FAILED, error_type="missing_configuration")
    if PAGE_ID in DISABLED_PAGE_IDS:
        return OperationResult(
            StageStatus.NO_WORK,
            error_type="platform_disabled",
            details={"page_id_configured": True},
        )
    try:
        state = _load_state()
    except JsonStateError as exc:
        logger.error("Estado Facebook ilegible: %s", exc)
        return OperationResult(StageStatus.FAILED, error_type="state_read_error")

    until = _backoff_until(state)
    if time.time() < until:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="rate_limit",
            retryable=True,
            next_retry_at=until,
        )

    dedup_key = str(noticia.get("dedup_key") or _dedup_key(noticia))
    if _is_posted(state, dedup_key):
        record = state["posted"].get(dedup_key)
        external_id = str(record.get("external_id") or "") if isinstance(record, dict) else ""
        return OperationResult(
            StageStatus.SUCCESS,
            external_id=external_id,
            deduplicated=True,
        )

    endpoint = "feed"
    payload = {"message": _build_message(noticia)}
    timeout = int(os.getenv("FB_REQUEST_TIMEOUT_SECONDS", "60"))
    token: str | None = None
    if _is_video_item(noticia):
        video_url = _video_url(noticia)
        if not video_url:
            return OperationResult(StageStatus.FAILED, error_type="invalid_video_url")
        endpoint = "videos"
        payload = {
            "description": _build_message(noticia),
            "file_url": video_url,
        }
        timeout = int(os.getenv("FB_VIDEO_REQUEST_TIMEOUT_SECONDS", "120"))
    else:
        link = _web_link(noticia)
        if not link:
            logger.warning("Facebook requiere URL web pública para el preview OG")
            return OperationResult(StageStatus.FAILED, error_type="missing_web_url")
        if _prewarm_enabled():
            prewarm = prewarm_link_preview(link)
            if not prewarm.ok:
                logger.error(
                    "Facebook no publica porque el preview web no quedo verificable: %s",
                    prewarm.error_type,
                )
                return prewarm
        try:
            token = get_page_token()
        except ValueError as exc:
            logger.error("No se obtuvo token de página: %s", exc)
            return OperationResult(StageStatus.FAILED, error_type="invalid_credential")
        rescrape = force_facebook_rescrape(link, token)
        if not rescrape.ok:
            logger.warning(
                "No se pudo forzar el re-scrape de Facebook para %s (se publica igual): %s",
                link,
                rescrape.error_type,
            )
        payload["message"] = _build_message(noticia, link)
        payload["link"] = link

    if token is None:
        try:
            token = get_page_token()
        except ValueError as exc:
            logger.error("No se obtuvo token de página: %s", exc)
            return OperationResult(StageStatus.FAILED, error_type="invalid_credential")
    payload["access_token"] = token

    try:
        response = requests.post(
            f"{GRAPH_API}/{PAGE_ID}/{endpoint}",
            data=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.error("Error de red publicando en Facebook: %s", exc)
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="network_error",
            error_code=type(exc).__name__,
            retryable=True,
            details={"publication_outcome": "unknown"},
        )

    result = _api_result(response)
    if result.ok:
        try:
            _mark_posted(dedup_key, result.external_id, noticia)
        except JsonStateError as exc:
            logger.error("Publicado en Facebook pero no se persistió la evidencia: %s", exc)
            return OperationResult(
                StageStatus.DEGRADED,
                error_type="published_state_write_error",
                external_id=result.external_id,
                response=result.response,
                details={"publication_outcome": "confirmed"},
            )
        logger.info("Publicado en Facebook: %s", str(noticia.get("titulo") or "")[:70])
    else:
        logger.error("Facebook rechazó la publicación: %s", result.to_dict())
    return result


def post_to_facebook(noticia: dict) -> bool:
    """Wrapper compatible con el contrato booleano histórico."""
    return post_to_facebook_detailed(noticia).ok


# ── Video paparazzi editado (fuente automática) ────────────────────────────
# post_to_facebook_detailed ya publica video nativo cuando hay video_url, pero
# usaría la URL cruda del scraper (entrevista larga, sin recortar, sin marca
# — ver scraping/base_paparazzi.py). Esta función reemplaza esa URL por un
# clip editado con la misma marca que la portada antes de subirlo, igual que
# meta/ig_client.py::post_paparazzi_carousel_to_instagram del lado de
# Instagram. Reutiliza el mismo fb_posted.json/dedup que el flujo estándar.


def post_paparazzi_video_to_facebook(noticia: dict) -> OperationResult:
    """Publica una nota de paparazzi.com.ar en Facebook.

    Si hay un video fuente utilizable, sube un único clip editado
    (``utils.video_renderer.render_paparazzi_clips`` con ``split=False`` —
    Facebook no tiene el límite de 60s por hijo que sí tiene el carrusel de
    Instagram, así que no hace falta dividir en partes; hasta
    PAPARAZZI_CAROUSEL_VIDEO_TOTAL_MAX_SECONDS reales, nunca la entrevista
    completa). Sin video utilizable, o si el recorte falla, cae al post
    estándar (link/imagen) — ``post_to_facebook_detailed``.
    """
    if not PAGE_ID or PAGE_ID == "PENDIENTE":
        return OperationResult(StageStatus.FAILED, error_type="missing_configuration")
    if PAGE_ID in DISABLED_PAGE_IDS:
        return OperationResult(
            StageStatus.NO_WORK,
            error_type="platform_disabled",
            details={"page_id_configured": True},
        )
    try:
        state = _load_state()
    except JsonStateError as exc:
        logger.error("Estado Facebook ilegible: %s", exc)
        return OperationResult(StageStatus.FAILED, error_type="state_read_error")

    until = _backoff_until(state)
    if time.time() < until:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="rate_limit",
            retryable=True,
            next_retry_at=until,
        )

    dedup_key = str(noticia.get("dedup_key") or _dedup_key(noticia))
    if _is_posted(state, dedup_key):
        record = state["posted"].get(dedup_key)
        external_id = str(record.get("external_id") or "") if isinstance(record, dict) else ""
        return OperationResult(StageStatus.SUCCESS, external_id=external_id, deduplicated=True)

    def _as_standard_post() -> OperationResult:
        stripped = {
            key: value
            for key, value in noticia.items()
            if key not in ("video_url", "video_duration_seconds", "media_type")
        }
        return post_to_facebook_detailed(stripped)

    if not noticia.get("video_url"):
        return _as_standard_post()

    from utils.video_renderer import render_paparazzi_clips

    clip_paths, clip_info = render_paparazzi_clips(noticia, split=False)
    if not clip_paths:
        logger.info(
            "Sin clip de video utilizable para paparazzi en Facebook (%s); publicando post estándar",
            clip_info.get("error_type"),
        )
        return _as_standard_post()
    clip_path = clip_paths[0]

    r2_key: str | None = None
    try:
        try:
            video_url, r2_key = r2_storage.upload_temp(clip_path, ttl_hint="fb")
        except RuntimeError as exc:
            return OperationResult(
                StageStatus.FAILED,
                error_type="r2_upload_error",
                details={"message": str(exc)},
            )

        try:
            token = get_page_token()
        except ValueError as exc:
            logger.error("No se obtuvo token de página: %s", exc)
            return OperationResult(StageStatus.FAILED, error_type="invalid_credential")

        payload = {
            "description": _build_message(noticia),
            "file_url": video_url,
            "access_token": token,
        }
        timeout = int(os.getenv("FB_VIDEO_REQUEST_TIMEOUT_SECONDS", "120"))
        try:
            response = requests.post(f"{GRAPH_API}/{PAGE_ID}/videos", data=payload, timeout=timeout)
        except requests.RequestException as exc:
            logger.error("Error de red publicando video paparazzi en Facebook: %s", exc)
            return OperationResult(
                StageStatus.DEGRADED,
                error_type="network_error",
                error_code=type(exc).__name__,
                retryable=True,
                details={"publication_outcome": "unknown"},
            )

        result = _api_result(response)
        if result.ok:
            try:
                _mark_posted(dedup_key, result.external_id, noticia)
            except JsonStateError as exc:
                logger.error(
                    "Video paparazzi publicado en Facebook pero no se persistió la evidencia: %s", exc
                )
                return OperationResult(
                    StageStatus.DEGRADED,
                    error_type="published_state_write_error",
                    external_id=result.external_id,
                    response=result.response,
                    details={"publication_outcome": "confirmed"},
                )
            logger.info(
                "Video paparazzi editado publicado en Facebook (%ss): %s",
                clip_info.get("duration_seconds"),
                str(noticia.get("titulo") or "")[:70],
            )
        else:
            logger.error("Facebook rechazó el video paparazzi: %s", result.to_dict())
        return result
    finally:
        if r2_key:
            r2_storage.delete(r2_key)
        try:
            os.unlink(clip_path)
        except OSError:
            pass


# ── Reel independiente de paparazzi (video solo, sin video nativo simple) ──
# Publica un video ya hosteado en R2. A diferencia de post_to_facebook_detailed
# y post_paparazzi_video_to_facebook, no hace dedup propio: el llamador
# (utils/paparazzi_reels.py) es dueño de la idempotencia con su propio
# estado, porque esta publicación es intencionalmente una segunda
# publicación de la misma nota (distinto formato, título superpuesto estilo
# Reel Manager 127.0.0.1:8765) y no debe chocar con el dedup del post
# estándar/video nativo.


def post_reel_video_to_facebook(item: dict) -> OperationResult:
    if not PAGE_ID or PAGE_ID == "PENDIENTE":
        return OperationResult(StageStatus.FAILED, error_type="missing_configuration")
    if PAGE_ID in DISABLED_PAGE_IDS:
        return OperationResult(
            StageStatus.NO_WORK,
            error_type="platform_disabled",
            details={"page_id_configured": True},
        )
    try:
        state = _load_state()
    except JsonStateError as exc:
        logger.error("Estado Facebook ilegible: %s", exc)
        return OperationResult(StageStatus.FAILED, error_type="state_read_error")

    until = _backoff_until(state)
    if time.time() < until:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="rate_limit",
            retryable=True,
            next_retry_at=until,
        )

    video_url = _video_url(item)
    if not video_url:
        return OperationResult(StageStatus.FAILED, error_type="invalid_video_url")

    try:
        token = get_page_token()
    except ValueError as exc:
        logger.error("No se obtuvo token de página: %s", exc)
        return OperationResult(StageStatus.FAILED, error_type="invalid_credential")

    payload = {
        "description": _build_message(item),
        "file_url": video_url,
        "access_token": token,
    }
    timeout = int(os.getenv("FB_VIDEO_REQUEST_TIMEOUT_SECONDS", "120"))
    try:
        response = requests.post(f"{GRAPH_API}/{PAGE_ID}/videos", data=payload, timeout=timeout)
    except requests.RequestException as exc:
        logger.error("Error de red publicando reel de paparazzi en Facebook: %s", exc)
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="network_error",
            error_code=type(exc).__name__,
            retryable=True,
            details={"publication_outcome": "unknown"},
        )

    result = _api_result(response)
    if result.ok:
        logger.info(
            "Reel de paparazzi publicado en Facebook: %s",
            str(item.get("titulo_reel") or item.get("titulo") or "")[:70],
        )
    else:
        logger.error("Facebook rechazó el reel de paparazzi: %s", result.to_dict())
    return result


# ── Media directa premium (Fase 3): social-only, sin link, sin CMS ────────
# El backoff se comparte con el flujo automático (misma página/cuenta real
# de Meta, vía ``_load_state``/``_backoff_until``/``_set_backoff`` sobre
# ``FB_STATE_PATH``). El dedup usa un registro propio para no mezclar
# identidades premium con el lote automático.
PREMIUM_FB_STATE_PATH = str(data_dir() / "premium_fb_posted.json")


def _load_premium_state() -> dict:
    return load_json(PREMIUM_FB_STATE_PATH, {"posted": {}}, expected_type=dict)


def _mark_premium_posted(dedup_key: str, package: dict, external_id: str) -> None:
    def mutate(state):
        state.setdefault("posted", {})[dedup_key] = {
            "posted_at": int(time.time()),
            "dedup_key": dedup_key,
            "external_id": external_id,
            "package_id": package.get("id"),
            "titulo": package.get("title"),
        }
        return state

    update_json(PREMIUM_FB_STATE_PATH, mutate, {"posted": {}}, expected_type=dict)


def premium_dedup_key(package: dict) -> str:
    explicit = str(package.get("premium_dedup_key") or "").strip()
    if explicit:
        return explicit
    basis = str(package.get("id") or package.get("title") or "")
    return f"premium:{url_hash(basis) if basis else uuid.uuid4().hex}"


def post_premium_direct_media_to_facebook(package: dict, slide_images: list[bytes]) -> OperationResult:
    """Publica foto(s) directas sin URL web, social-only.

    Se activa únicamente si ``publish_mode == "direct_media"`` y
    ``workflow == "manual_premium"`` están presentes de forma explícita en
    el paquete — nunca se infiere el modo por ausencia de link. El caption
    nunca incluye una URL.
    """
    if package.get("publish_mode") != "direct_media" or package.get("workflow") != "manual_premium":
        return OperationResult(StageStatus.FAILED, error_type="invalid_publish_mode")
    if not PAGE_ID or PAGE_ID == "PENDIENTE":
        return OperationResult(StageStatus.FAILED, error_type="missing_configuration")
    if PAGE_ID in DISABLED_PAGE_IDS:
        return OperationResult(
            StageStatus.NO_WORK,
            error_type="platform_disabled",
            details={"page_id_configured": True},
        )
    if not slide_images:
        return OperationResult(StageStatus.FAILED, error_type="invalid_slide_count")

    try:
        automatic_state = _load_state()
    except JsonStateError:
        return OperationResult(StageStatus.FAILED, error_type="state_read_error")
    until = _backoff_until(automatic_state)
    if time.time() < until:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="rate_limit",
            retryable=True,
            next_retry_at=until,
        )

    try:
        premium_state = _load_premium_state()
    except JsonStateError:
        return OperationResult(StageStatus.FAILED, error_type="state_read_error")
    dedup_key = premium_dedup_key(package)
    existing = premium_state.get("posted", {}).get(dedup_key)
    if existing is not None:
        return OperationResult(
            StageStatus.SUCCESS,
            external_id=str(existing.get("external_id") or ""),
            deduplicated=True,
        )

    try:
        token = get_page_token()
    except ValueError as exc:
        logger.error("No se obtuvo token de página: %s", exc)
        return OperationResult(StageStatus.FAILED, error_type="invalid_credential")

    caption = str(package.get("caption") or "")  # nunca se agrega link acá
    timeout = int(os.getenv("FB_REQUEST_TIMEOUT_SECONDS", "60"))

    try:
        if len(slide_images) == 1:
            files = {"source": ("slide.jpg", slide_images[0], "image/jpeg")}
            data = {"caption": caption, "access_token": token}
            response = requests.post(f"{GRAPH_API}/{PAGE_ID}/photos", data=data, files=files, timeout=timeout)
            result = _api_result(response)
        else:
            media_fbids: list[str] = []
            for index, image_bytes in enumerate(slide_images):
                files = {"source": (f"slide-{index}.jpg", image_bytes, "image/jpeg")}
                data = {"published": "false", "access_token": token}
                response = requests.post(f"{GRAPH_API}/{PAGE_ID}/photos", data=data, files=files, timeout=timeout)
                uploaded = _api_result(response)
                if not uploaded.ok:
                    return uploaded
                media_fbids.append(uploaded.external_id)
            attached_media = json.dumps([{"media_fbid": fbid} for fbid in media_fbids])
            data = {"message": caption, "attached_media": attached_media, "access_token": token}
            response = requests.post(f"{GRAPH_API}/{PAGE_ID}/feed", data=data, timeout=timeout)
            result = _api_result(response)
    except requests.RequestException as exc:
        logger.error("Error de red publicando media directa premium: %s", exc)
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="network_error",
            error_code=type(exc).__name__,
            retryable=True,
            details={"publication_outcome": "unknown"},
        )

    if result.ok:
        try:
            _mark_premium_posted(dedup_key, package, result.external_id)
        except JsonStateError as exc:
            logger.error("Publicado media directa premium pero no se persistió evidencia: %s", exc)
            return OperationResult(
                StageStatus.DEGRADED,
                error_type="published_state_write_error",
                external_id=result.external_id,
                details={"publication_outcome": "confirmed"},
            )
        logger.info("Publicación premium directa en Facebook: %s", str(package.get("title") or "")[:70])
    else:
        logger.error("Facebook rechazó la publicación premium: %s", result.to_dict())
    return result
