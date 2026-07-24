"""Cliente tipado de Facebook Graph API."""
from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import requests

from meta.facebook_token_manager import get_page_token
from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.operation_result import OperationResult
from utils.paths import data_dir
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


def _build_message(noticia: dict) -> str:
    cuerpo = str(noticia.get("texto_instagram") or "").strip()
    if not cuerpo:
        parrafos = noticia.get("parrafos") or []
        primero = noticia.get("excerpt") or (parrafos[0] if parrafos else "")
        cuerpo = f"{noticia.get('titulo', '')}\n\n{primero}"
    localidad = str(noticia.get("hashtag_localidad") or "").strip()
    seccion = str(noticia.get("seccion") or "").lower()
    section_tags = {
        "policiales": "#PoliciaLaRioja #Seguridad",
        "deportes": "#DeportesRioja #Deportes",
        "cultura": "#CulturaRioja #Cultura",
        "espectaculos": "#EspectaculosRioja #Cultura",
        "politica": "#PoliticaRioja #LaRiojaGobierna",
        "economia": "#EconomiaRioja #Economia",
        "salud": "#SaludRioja #Salud",
        "educacion": "#EducacionRioja #Educacion",
        "interior": "#InteriorRioja #LaRioja",
        "sociedad": "#LaRiojaHoy #Sociedad",
    }
    tags = f"{section_tags.get(seccion, '#RiojaHoy')} #LaVozRiojana #LaRioja #Noticias"
    if localidad:
        tags = f"{localidad} {tags}"
    return f"{cuerpo}\n\n{tags}"


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
        payload["link"] = link

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
