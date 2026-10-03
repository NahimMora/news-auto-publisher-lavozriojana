"""Reel independiente para notas de paparazzi.com.ar (video solo, sin carrusel).

Ver docs/DECISIONS.md. Cuando el carrusel/video estándar de paparazzi
(``meta.ig_client.post_paparazzi_carousel_to_instagram``,
``meta.fb_client.post_paparazzi_video_to_facebook``) ya publicó una nota con
video fuente, esta capa genera además un Reel con el mismo motor que la UI
manual de 127.0.0.1:8765 (``utils.video_renderer.render_video`` — Remotion
EditorialReel con título superpuesto, distinto del clip de marca simple del
carrusel, que no lleva título) y lo publica como una segunda publicación
independiente en Instagram y Facebook.

Usa su propio estado de publicados (``data/paparazzi_reels_posted.json``)
para no interferir con el dedup del carrusel/video estándar — misma nota,
dos publicaciones intencionales en formatos distintos.
"""
from __future__ import annotations

import os
import time

from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.url_normalization import url_hash

logger = setup_logger("paparazzi_reels", "paparazzi_reels.log")

STATE_PATH = str(data_dir() / "paparazzi_reels_posted.json")

_TRUE = {"1", "true", "yes", "on", "si", "sí"}


def _enabled(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _load_state() -> dict:
    return load_json(STATE_PATH, {"posted": {}}, expected_type=dict)


def reel_dedup_key(noticia: dict) -> str:
    basis = str(
        noticia.get("dedup_key")
        or noticia.get("canonical_url")
        or noticia.get("url")
        or noticia.get("titulo")
        or ""
    )
    return f"reel:{url_hash(basis)}"


def _mark_posted(dedup_key: str, noticia: dict, *, ig_id: str, fb_id: str) -> None:
    def mutate(state):
        state.setdefault("posted", {})[dedup_key] = {
            "posted_at": int(time.time()),
            "titulo": noticia.get("titulo", ""),
            "canonical_url": noticia.get("canonical_url") or noticia.get("url") or "",
            "instagram_id": ig_id,
            "facebook_id": fb_id,
        }
        return state

    update_json(STATE_PATH, mutate, {"posted": {}}, expected_type=dict)


def _cleanup_local(path: str | None) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def render_reel_item(noticia: dict) -> tuple[dict, str] | None:
    """Renderiza el reel (EditorialReel) con el video fuente y lo sube a R2.

    Devuelve ``(reel_item, r2_key)`` listo para publicar, o ``None`` si no hay
    video fuente utilizable: un reel sin video (Ken Burns/overlay) no se publica.
    """
    video_url = str(noticia.get("video_url") or "").strip()
    source_url = str(noticia.get("source_url") or "").strip()
    if not video_url and not source_url:
        return None

    from utils.video_renderer import render_video

    titulo_reel = str(noticia.get("titulo_instagram") or noticia.get("titulo") or "")[:80].upper()
    caption = str(noticia.get("texto_instagram") or noticia.get("caption") or "")
    seccion = str(noticia.get("seccion") or "espectaculos")
    render_item = {
        "source_url": source_url or noticia.get("canonical_url") or noticia.get("url") or "",
        "video_url": video_url,
        "titulo_reel": titulo_reel,
        "caption": caption,
        "seccion": seccion,
        "duration_seconds": int(os.getenv("PAPARAZZI_REEL_FALLBACK_DURATION_SECONDS", "20")),
        "imagen_url": noticia.get("imagen_url") or "",
    }

    try:
        video_path, _video_id, _duration, render_info = render_video(render_item)
    except Exception as exc:
        logger.warning("No se pudo renderizar el reel: %s", exc)
        return None

    if render_info.get("source_used") != "video":
        # El video fuente no se pudo descargar (ver fallback_reason) y se cayó a
        # Ken Burns/overlay — este flujo es "el video solo", no publica ese fallback.
        logger.info(
            "Reel sin video fuente utilizable (%s); no se publica",
            (render_info.get("fallback_reason") or {}).get("error_type"),
        )
        _cleanup_local(video_path)
        return None

    from utils import r2_storage

    if not r2_storage.is_configured():
        logger.warning("R2 no configurado; no se puede publicar el reel")
        _cleanup_local(video_path)
        return None

    try:
        public_url, r2_key = r2_storage.upload_temp(video_path, ttl_hint="reel")
    except RuntimeError as exc:
        logger.warning("No se pudo subir el reel a R2: %s", exc)
        _cleanup_local(video_path)
        return None
    finally:
        _cleanup_local(video_path)

    reel_item = {
        "titulo": titulo_reel,
        "titulo_reel": titulo_reel,
        "titulo_instagram": titulo_reel,
        "texto_instagram": caption,
        "caption": caption,
        "seccion": seccion,
        "imagen_url": render_item["imagen_url"],
        "video_url": public_url,
        "share_to_feed": True,
        # Portada = frame del video en vez de la foto original de la noticia:
        # apunta al momento en que el título de EditorialReel ya achicó su
        # animación de entrada (ver utils/video_renderer.py). Sólo Instagram
        # soporta elegir un frame por offset (thumb_offset, ms) — la API
        # clásica de video de Facebook no lo documenta, así que ahí Facebook
        # sigue eligiendo su propio frame por defecto.
        "thumb_offset_ms": int(os.getenv("PAPARAZZI_REEL_THUMB_OFFSET_MS", "2500")),
    }
    return reel_item, r2_key


def publish_facebook_reel(reel_item: dict) -> tuple[bool, str]:
    """Publica en Facebook un reel ya renderizado. Nunca lanza."""
    try:
        from meta.fb_client import post_reel_video_to_facebook

        fb_result = post_reel_video_to_facebook(reel_item)
        if not fb_result.ok:
            logger.warning("Reel no publicado en Facebook: %s", fb_result.error_type)
        return fb_result.ok, fb_result.external_id or ""
    except Exception:
        logger.exception("Error inesperado publicando el reel en Facebook")
        return False, ""


def delete_reel_upload(r2_key: str) -> None:
    from utils import r2_storage

    try:
        r2_storage.delete(r2_key)
    except Exception:
        logger.warning("No se pudo limpiar el reel en R2 tras el fallo")


def _instagram_dedup_key(noticia: dict) -> str:
    return str(
        noticia.get("dedup_key")
        or f"link:{url_hash(noticia.get('canonical_url') or noticia.get('url', ''))}"
    )


def publish_paparazzi_reel_as_instagram_post(noticia: dict):
    """Publica la nota con video como un único Reel en Instagram.

    Reemplaza al carrusel portada+video seguido de un reel aparte: una nota con
    video sale sólo como Reel. Devuelve ``None`` si no hay video fuente
    utilizable (el llamador publica la imagen sola). El Reel en Facebook se
    mantiene detrás de ``PAPARAZZI_REEL_ENABLED`` como antes.
    """
    from meta import ig_client
    from utils.operation_result import OperationResult
    from utils.stage_result import StageStatus

    if not str(noticia.get("video_url") or "").strip():
        return None
    dedup_key = reel_dedup_key(noticia)
    try:
        state = _load_state()
    except JsonStateError as exc:
        logger.error("Estado de reels de paparazzi ilegible: %s", exc)
        return OperationResult(StageStatus.FAILED, error_type="state_read_error")
    existing = state.get("posted", {}).get(dedup_key) or {}
    if existing.get("instagram_id"):
        return OperationResult(
            StageStatus.SUCCESS, external_id=str(existing["instagram_id"]), deduplicated=True
        )

    rendered = render_reel_item(noticia)
    if rendered is None:
        return None
    reel_item, r2_key = rendered

    ig_result = ig_client.post_reel_video_to_instagram(reel_item)
    if not ig_result.ok:
        delete_reel_upload(r2_key)
        return ig_result

    ig_id = ig_result.external_id or ""
    fb_id = ""
    if _enabled("PAPARAZZI_REEL_ENABLED") and _enabled("FB_PUBLISH_ENABLED"):
        _fb_ok, fb_id = publish_facebook_reel(reel_item)
    try:
        _mark_posted(dedup_key, noticia, ig_id=ig_id, fb_id=fb_id)
        ig_client._mark_posted(_instagram_dedup_key(noticia), {**noticia, "media_type": "reel"}, ig_id)
    except JsonStateError as exc:
        logger.error("Reel publicado en Instagram pero no se persistió la evidencia: %s", exc)
    return ig_result


def publish_paparazzi_reel(noticia: dict) -> None:
    """Best-effort: nunca lanza, nunca afecta el resultado del llamador.

    Reel adicional en Instagram y Facebook para una nota ya publicada por otra
    vía. El flujo automático de Instagram usa
    ``publish_paparazzi_reel_as_instagram_post`` (el reel ES la publicación).
    """
    if not _enabled("PAPARAZZI_REEL_ENABLED"):
        return
    video_url = str(noticia.get("video_url") or "").strip()
    if not video_url:
        return

    dedup_key = reel_dedup_key(noticia)
    try:
        state = _load_state()
    except JsonStateError as exc:
        logger.error("Estado de reels de paparazzi ilegible: %s", exc)
        return
    if dedup_key in state.get("posted", {}):
        return

    ig_allowed = _enabled("IG_PUBLISH_ENABLED")
    fb_allowed = _enabled("FB_PUBLISH_ENABLED")
    if not ig_allowed and not fb_allowed:
        return

    rendered = render_reel_item(noticia)
    if rendered is None:
        return
    reel_item, r2_key = rendered

    ig_id = fb_id = ""
    ig_ok = fb_ok = False

    if ig_allowed:
        try:
            from meta.ig_client import post_reel_video_to_instagram

            ig_result = post_reel_video_to_instagram(reel_item)
            ig_ok = ig_result.ok
            ig_id = ig_result.external_id or ""
            if not ig_ok:
                logger.warning(
                    "Reel de paparazzi no publicado en Instagram: %s", ig_result.error_type
                )
        except Exception:
            logger.exception("Error inesperado publicando el reel de paparazzi en Instagram")

    if fb_allowed:
        fb_ok, fb_id = publish_facebook_reel(reel_item)

    if ig_ok or fb_ok:
        try:
            _mark_posted(dedup_key, noticia, ig_id=ig_id, fb_id=fb_id)
        except JsonStateError as exc:
            logger.error("Reel de paparazzi publicado pero no se persistió la evidencia: %s", exc)
    else:
        delete_reel_upload(r2_key)
