"""Cliente tipado de Instagram Graph API."""
from __future__ import annotations

import os
import tempfile
import time
import uuid
from urllib.parse import urlparse

import requests

from layout.image_generator import generate_instagram as _gen_ig_img
from utils import r2_storage
from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.news_dedup import duplicate_reason
from utils.operation_result import OperationResult
from utils.paths import data_dir
from utils.social_caption import build_instagram_caption
from utils.stage_result import StageStatus
from utils.url_normalization import url_hash

logger = setup_logger("ig_client", "ig_client.log")

IG_STATE_PATH = str(data_dir() / "ig_posted.json")
IG_RATE_LIMIT_PATH = str(data_dir() / "ig_rate_limit.json")
GRAPH_API = os.getenv("META_GRAPH_API", "https://graph.facebook.com/v19.0").rstrip("/")

IG_ACCOUNT_ID = os.getenv("IG_ACCOUNT_ID", "")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "")
IG_RATE_LIMIT_BACKOFF_SECONDS = int(os.getenv("IG_RATE_LIMIT_BACKOFF_SECONDS", "10800"))
IG_VIDEO_PROCESSING_TIMEOUT_SECONDS = int(
    os.getenv("IG_VIDEO_PROCESSING_TIMEOUT_SECONDS", "300")
)
IG_VIDEO_PROCESSING_POLL_SECONDS = int(os.getenv("IG_VIDEO_PROCESSING_POLL_SECONDS", "10"))
IG_POSTED_DEDUP_THRESHOLD = float(
    os.getenv(
        "IG_POSTED_DEDUP_THRESHOLD",
        os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.5"),
    )
)


class IGRateLimitError(Exception):
    """Compatibilidad: indica backoff activo de Instagram."""


def _load_rate_limit() -> dict:
    return load_json(IG_RATE_LIMIT_PATH, {}, expected_type=dict)


def rate_limit_until() -> int:
    return int(_load_rate_limit().get("blocked_until", 0) or 0)


def is_rate_limited() -> bool:
    until = rate_limit_until()
    if time.time() < until:
        remaining = max(0, int(until - time.time()))
        logger.warning("IG rate limit activo: faltan %ss", remaining)
        return True
    return False


def _set_rate_limit_backoff() -> int:
    blocked_until = int(time.time()) + IG_RATE_LIMIT_BACKOFF_SECONDS
    update_json(
        IG_RATE_LIMIT_PATH,
        lambda current: {
            **current,
            "blocked_until": max(
                int(current.get("blocked_until", 0) or 0),
                blocked_until,
            ),
            "set_at": int(time.time()),
        },
        {},
        expected_type=dict,
    )
    logger.error("IG rate limit detectado; backoff hasta %s", blocked_until)
    return blocked_until


def _is_rate_limit_error(data: dict, status_code: int | None = None) -> bool:
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    return status_code == 429 or int(error.get("code") or 0) in {4, 32, 613}


def _is_credential_error(data: dict, status_code: int | None = None) -> bool:
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    return status_code == 401 or int(error.get("code") or 0) == 190


def _load_state() -> dict:
    return load_json(IG_STATE_PATH, {"posted": {}}, expected_type=dict)


def _mark_posted(dedup_key: str, noticia: dict, external_id: str) -> None:
    def mutate(state):
        record = {
            "posted_at": int(time.time()),
            "dedup_key": dedup_key,
            "external_id": external_id,
        }
        for field in (
            "titulo",
            "titulo_instagram",
            "texto_instagram",
            "url",
            "canonical_url",
            "meta_queue_key",
            "web_queue_key",
            "seccion",
            "source",
            "media_type",
        ):
            if noticia.get(field):
                record[field] = noticia[field]
        state.setdefault("posted", {})[dedup_key] = record
        return state

    update_json(IG_STATE_PATH, mutate, {"posted": {}}, expected_type=dict)


def _posted_records(state: dict) -> list[dict]:
    posted = state.get("posted", {})
    if not isinstance(posted, dict):
        return []
    records = []
    for key, value in posted.items():
        if isinstance(value, dict):
            item = dict(value)
            item.setdefault("dedup_key", key)
            records.append(item)
    return records


def _posted_duplicate_reason(state: dict, noticia: dict) -> str | None:
    return duplicate_reason(
        noticia,
        _posted_records(state),
        key_fields=(
            "dedup_key",
            "meta_queue_key",
            "web_queue_key",
            "canonical_url",
            "url",
        ),
        threshold=IG_POSTED_DEDUP_THRESHOLD,
    )


def _is_http_url(value: object) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_video_item(noticia: dict) -> bool:
    return str(noticia.get("media_type") or "").lower() == "video" or bool(
        noticia.get("video_url")
    )


def _video_url(noticia: dict) -> str:
    for field in ("video_url", "direct_video_url", "mp4_url"):
        value = str(noticia.get(field) or "").strip()
        if _is_http_url(value):
            return value
    return ""


def _build_caption(noticia: dict) -> str:
    return build_instagram_caption(noticia)


def _safe_json(response) -> dict:
    try:
        data = response.json()
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _error_result(response, *, outcome: str = "not_published") -> OperationResult:
    data = _safe_json(response)
    if _is_credential_error(data, response.status_code):
        return OperationResult(
            StageStatus.FAILED,
            error_type="invalid_credential",
            error_code=response.status_code,
            response=data or None,
        )
    if _is_rate_limit_error(data, response.status_code):
        until = _set_rate_limit_backoff()
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="rate_limit",
            error_code=response.status_code,
            retryable=True,
            next_retry_at=until,
            response=data or None,
        )
    if response.status_code >= 500:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="server_error",
            error_code=response.status_code,
            retryable=True,
            response=data or None,
            details={"publication_outcome": outcome},
        )
    return OperationResult(
        StageStatus.FAILED,
        error_type="request_rejected" if data else "invalid_response",
        error_code=response.status_code,
        response=data or None,
        details={"publication_outcome": outcome},
    )


def _wait_video_container(container_id: str) -> OperationResult:
    deadline = time.time() + IG_VIDEO_PROCESSING_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            response = requests.get(
                f"{GRAPH_API}/{container_id}",
                params={
                    "fields": "status_code,status",
                    "access_token": IG_ACCESS_TOKEN,
                },
                timeout=int(os.getenv("IG_REQUEST_TIMEOUT_SECONDS", "30")),
            )
        except requests.RequestException as exc:
            logger.warning("Error consultando procesamiento de Reel: %s", exc)
            time.sleep(IG_VIDEO_PROCESSING_POLL_SECONDS)
            continue
        data = _safe_json(response)
        if _is_rate_limit_error(data, response.status_code):
            until = _set_rate_limit_backoff()
            return OperationResult(
                StageStatus.DEGRADED,
                error_type="rate_limit",
                retryable=True,
                next_retry_at=until,
            )
        if _is_credential_error(data, response.status_code):
            return OperationResult(StageStatus.FAILED, error_type="invalid_credential")
        status = str(data.get("status_code") or "").upper()
        if status in {"FINISHED", "PUBLISHED"}:
            return OperationResult(StageStatus.SUCCESS, external_id=container_id)
        if status == "ERROR":
            return OperationResult(
                StageStatus.FAILED,
                error_type="media_processing_error",
                response=data,
            )
        time.sleep(IG_VIDEO_PROCESSING_POLL_SECONDS)
    return OperationResult(
        StageStatus.DEGRADED,
        error_type="media_processing_timeout",
        retryable=True,
        details={"container_id": container_id, "publication_outcome": "not_published"},
    )


def _publish_container(container_id: str) -> OperationResult:
    try:
        response = requests.post(
            f"{GRAPH_API}/{IG_ACCOUNT_ID}/media_publish",
            data={"creation_id": container_id, "access_token": IG_ACCESS_TOKEN},
            timeout=int(os.getenv("IG_REQUEST_TIMEOUT_SECONDS", "30")),
        )
    except requests.RequestException as exc:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="network_error",
            error_code=type(exc).__name__,
            retryable=True,
            details={
                "container_id": container_id,
                "publication_outcome": "unknown",
            },
        )
    data = _safe_json(response)
    external_id = str(data.get("id") or "")
    if response.status_code in {200, 201} and external_id:
        return OperationResult(
            StageStatus.SUCCESS,
            external_id=external_id,
            response=data,
        )
    return _error_result(response, outcome="unknown")


def _create_container(payload: dict) -> OperationResult:
    try:
        response = requests.post(
            f"{GRAPH_API}/{IG_ACCOUNT_ID}/media",
            data=payload,
            timeout=int(os.getenv("IG_REQUEST_TIMEOUT_SECONDS", "60")),
        )
    except requests.RequestException as exc:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="network_error",
            error_code=type(exc).__name__,
            retryable=True,
            details={"publication_outcome": "not_published"},
        )
    data = _safe_json(response)
    container_id = str(data.get("id") or "")
    if response.status_code in {200, 201} and container_id:
        return OperationResult(
            StageStatus.SUCCESS,
            external_id=container_id,
            response=data,
        )
    return _error_result(response)


def _prepare_image(noticia: dict) -> tuple[OperationResult, str, str | None]:
    original_url = str(noticia.get("imagen_url") or "").strip()
    if not r2_storage.is_configured():
        allow_original = str(
            os.getenv("IG_ALLOW_ORIGINAL_IMAGE_FALLBACK", "false")
        ).lower() in {"1", "true", "yes", "si", "sí"}
        if not allow_original:
            return (
                OperationResult(
                    StageStatus.FAILED,
                    error_type="missing_r2_configuration",
                    details={"fallback_allowed": False},
                ),
                "",
                None,
            )
        if not _is_http_url(original_url):
            return OperationResult(StageStatus.FAILED, error_type="missing_public_image"), "", None
        return (
            OperationResult(
                StageStatus.SUCCESS,
                public_url=original_url,
                details={"image_source": "original", "fallback_used": True},
            ),
            original_url,
            None,
        )

    tmp_path = ""
    try:
        local_image = str(noticia.get("imagen") or noticia.get("imagen_optimizada") or "")
        if local_image and os.path.isfile(local_image):
            from PIL import Image
            from layout.image_generator import IG_H, IG_W, generate_post

            with Image.open(local_image) as source:
                image = generate_post(
                    noticia,
                    IG_W,
                    IG_H,
                    preloaded_img=source.convert("RGBA"),
                )
        else:
            image = _gen_ig_img(noticia)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            tmp_path = handle.name
            image.save(tmp_path, "JPEG", quality=90)
        public_url, key = r2_storage.upload_temp(tmp_path, ttl_hint="ig")
        return (
            OperationResult(
                StageStatus.SUCCESS,
                public_url=public_url,
                details={"image_source": "r2", "fallback_used": False},
            ),
            public_url,
            key,
        )
    except Exception as exc:
        allow = str(os.getenv("IG_ALLOW_ORIGINAL_IMAGE_FALLBACK", "false")).lower() in {
            "1", "true", "yes", "si", "sí",
        }
        if allow and _is_http_url(original_url):
            logger.warning(
                "R2 falló (%s); fallback original habilitado explícitamente",
                type(exc).__name__,
            )
            return (
                OperationResult(
                    StageStatus.SUCCESS,
                    public_url=original_url,
                    details={
                        "image_source": "original",
                        "fallback_used": True,
                        "fallback_reason": "r2_error",
                    },
                ),
                original_url,
                None,
            )
        return (
            OperationResult(
                StageStatus.FAILED,
                error_type="r2_upload_error",
                details={"fallback_allowed": allow},
            ),
            "",
            None,
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


def post_to_instagram_detailed(noticia: dict) -> OperationResult:
    if not IG_ACCOUNT_ID or IG_ACCOUNT_ID == "PENDIENTE":
        return OperationResult(StageStatus.FAILED, error_type="missing_configuration")
    if not IG_ACCESS_TOKEN or IG_ACCESS_TOKEN == "PENDIENTE":
        return OperationResult(StageStatus.FAILED, error_type="invalid_credential")
    try:
        until = rate_limit_until()
    except JsonStateError:
        return OperationResult(StageStatus.FAILED, error_type="state_read_error")
    if time.time() < until:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="rate_limit",
            retryable=True,
            next_retry_at=until,
        )
    try:
        state = _load_state()
    except JsonStateError:
        return OperationResult(StageStatus.FAILED, error_type="state_read_error")

    dedup_key = str(
        noticia.get("dedup_key")
        or f"link:{url_hash(noticia.get('canonical_url') or noticia.get('url', ''))}"
    )
    existing = state.get("posted", {}).get(dedup_key)
    if existing is not None:
        external_id = str(existing.get("external_id") or "") if isinstance(existing, dict) else ""
        return OperationResult(
            StageStatus.SUCCESS,
            external_id=external_id,
            deduplicated=True,
        )
    duplicate = _posted_duplicate_reason(state, noticia)
    if duplicate:
        logger.warning("Instagram omitido por publicación similar previa: %s", duplicate)
        return OperationResult(
            StageStatus.SUCCESS,
            deduplicated=True,
            details={"duplicate_reason": duplicate},
        )

    r2_key: str | None = None
    image_details: dict = {}
    if _is_video_item(noticia):
        video_url = _video_url(noticia)
        if not video_url:
            return OperationResult(StageStatus.FAILED, error_type="invalid_video_url")
        payload = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": _build_caption(noticia),
            "access_token": IG_ACCESS_TOKEN,
        }
        if str(noticia.get("share_to_feed", True)).lower() not in {
            "0", "false", "no", "off",
        }:
            payload["share_to_feed"] = "true"
        cover_url = str(noticia.get("cover_url") or noticia.get("imagen_url") or "").strip()
        if _is_http_url(cover_url):
            payload["cover_url"] = cover_url
    else:
        prepared, image_url, r2_key = _prepare_image(noticia)
        if not prepared.ok:
            return prepared
        image_details = prepared.details
        payload = {
            "image_url": image_url,
            "caption": _build_caption(noticia),
            "access_token": IG_ACCESS_TOKEN,
        }

    created = _create_container(payload)
    if not created.ok:
        if r2_key:
            r2_storage.delete(r2_key)
        return created
    container_id = created.external_id

    # Una vez creado el contenedor, Instagram ya descargó la imagen.
    if r2_key:
        r2_storage.delete(r2_key)
    if _is_video_item(noticia):
        ready = _wait_video_container(container_id)
        if not ready.ok:
            return ready
    else:
        delay = float(os.getenv("IG_IMAGE_CONTAINER_WAIT_SECONDS", "5"))
        if delay > 0:
            time.sleep(delay)

    published = _publish_container(container_id)
    if not published.ok:
        return published
    try:
        _mark_posted(dedup_key, noticia, published.external_id)
    except JsonStateError as exc:
        logger.error("Instagram publicó pero no se persistió la evidencia: %s", exc)
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="published_state_write_error",
            external_id=published.external_id,
            response=published.response,
            details={"publication_outcome": "confirmed", "container_id": container_id},
        )
    published.details.update(image_details)
    logger.info("Publicado en Instagram: %s", str(noticia.get("titulo") or "")[:70])
    return published


def post_to_instagram(noticia: dict) -> bool:
    """Wrapper booleano histórico; mantiene IGRateLimitError para callers antiguos."""
    result = post_to_instagram_detailed(noticia)
    if result.error_type == "rate_limit":
        raise IGRateLimitError("IG en período de backoff por rate limit")
    return result.ok


# ── Carrusel premium (Fase 3): flujo social-only, dedup y cola propias ────
# Reutiliza el mismo backoff de rate limit (misma cuenta de Meta), pero un
# estado de publicados independiente de ``ig_posted.json`` para no mezclar
# el dedup del lote automático con el de publicaciones premium manuales.
PREMIUM_IG_STATE_PATH = str(data_dir() / "premium_ig_posted.json")
PREMIUM_CAROUSEL_MIN_SLIDES = 2
PREMIUM_CAROUSEL_MAX_SLIDES = 10


def _load_premium_state() -> dict:
    return load_json(PREMIUM_IG_STATE_PATH, {"posted": {}}, expected_type=dict)


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

    update_json(PREMIUM_IG_STATE_PATH, mutate, {"posted": {}}, expected_type=dict)


def premium_dedup_key(package: dict) -> str:
    explicit = str(package.get("premium_dedup_key") or "").strip()
    if explicit:
        return explicit
    basis = str(package.get("id") or package.get("title") or "")
    return f"premium:{url_hash(basis) if basis else uuid.uuid4().hex}"


def premium_carousel_already_posted(package: dict) -> str | None:
    """Devuelve el external_id ya publicado para este paquete, si existe."""
    try:
        state = _load_premium_state()
    except JsonStateError:
        return None
    record = state.get("posted", {}).get(premium_dedup_key(package))
    if isinstance(record, dict):
        return str(record.get("external_id") or "") or None
    return None


def post_premium_carousel_to_instagram(package: dict, slide_images: list[bytes]) -> OperationResult:
    """Publica un carrusel premium social-only (sin artículo web, sin CMS).

    ``slide_images`` son los bytes ya renderizados de cada slide (mismo
    renderer que el preview del Estudio Premium), en el orden final.
    """
    if not IG_ACCOUNT_ID or IG_ACCOUNT_ID == "PENDIENTE":
        return OperationResult(StageStatus.FAILED, error_type="missing_configuration")
    if not IG_ACCESS_TOKEN or IG_ACCESS_TOKEN == "PENDIENTE":
        return OperationResult(StageStatus.FAILED, error_type="invalid_credential")
    count = len(slide_images)
    if not (PREMIUM_CAROUSEL_MIN_SLIDES <= count <= PREMIUM_CAROUSEL_MAX_SLIDES):
        return OperationResult(
            StageStatus.FAILED,
            error_type="invalid_slide_count",
            details={"count": count},
        )

    try:
        until = rate_limit_until()
    except JsonStateError:
        return OperationResult(StageStatus.FAILED, error_type="state_read_error")
    if time.time() < until:
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="rate_limit",
            retryable=True,
            next_retry_at=until,
        )

    dedup_key = premium_dedup_key(package)
    try:
        state = _load_premium_state()
    except JsonStateError:
        return OperationResult(StageStatus.FAILED, error_type="state_read_error")
    existing = state.get("posted", {}).get(dedup_key)
    if existing is not None:
        return OperationResult(
            StageStatus.SUCCESS,
            external_id=str(existing.get("external_id") or ""),
            deduplicated=True,
        )

    uploaded: list[tuple[str, str]] = []
    try:
        for image_bytes in slide_images:
            tmp_path = ""
            try:
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
                    tmp_path = handle.name
                    handle.write(image_bytes)
                public_url, key = r2_storage.upload_temp(tmp_path, ttl_hint="ig")
                uploaded.append((public_url, key))
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except FileNotFoundError:
                        pass
    except Exception as exc:
        for _, key in uploaded:
            r2_storage.delete(key)
        return OperationResult(
            StageStatus.FAILED,
            error_type="r2_upload_error",
            details={"message": type(exc).__name__},
        )

    child_ids: list[str] = []
    for public_url, _ in uploaded:
        created = _create_container(
            {
                "image_url": public_url,
                "is_carousel_item": "true",
                "access_token": IG_ACCESS_TOKEN,
            }
        )
        if not created.ok:
            for _, key in uploaded:
                r2_storage.delete(key)
            return created
        child_ids.append(created.external_id)

    # Instagram ya descargó cada imagen al crear su contenedor hijo.
    for _, key in uploaded:
        r2_storage.delete(key)

    parent = _create_container(
        {
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": str(package.get("caption") or ""),
            "access_token": IG_ACCESS_TOKEN,
        }
    )
    if not parent.ok:
        return parent

    published = _publish_container(parent.external_id)
    if not published.ok:
        return published
    try:
        _mark_premium_posted(dedup_key, package, published.external_id)
    except JsonStateError as exc:
        logger.error("Carrusel premium publicado pero no se persistió la evidencia: %s", exc)
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="published_state_write_error",
            external_id=published.external_id,
            details={"publication_outcome": "confirmed", "container_id": parent.external_id},
        )
    logger.info("Carrusel premium publicado en Instagram: %s", str(package.get("title") or "")[:70])
    return published
