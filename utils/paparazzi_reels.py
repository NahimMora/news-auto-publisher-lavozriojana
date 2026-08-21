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


def publish_paparazzi_reel(noticia: dict) -> None:
    """Best-effort: nunca lanza, nunca afecta el resultado del llamador.

    Pensada para invocarse justo después de que el carrusel/video estándar
    de paparazzi ya se publicó con éxito (ver meta/run_ig.py).
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

    from utils.video_renderer import render_video

    titulo_reel = str(noticia.get("titulo_instagram") or noticia.get("titulo") or "")[:80].upper()
    caption = str(noticia.get("texto_instagram") or noticia.get("caption") or "")
    seccion = str(noticia.get("seccion") or "espectaculos")
    render_item = {
        "source_url": noticia.get("canonical_url") or noticia.get("url") or "",
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
        logger.warning("No se pudo renderizar el reel de paparazzi: %s", exc)
        return

    if render_info.get("source_used") != "video":
        # El video fuente no se pudo descargar (ver fallback_reason) y se cayó a
        # Ken Burns/overlay — este flujo es "el video solo", no publica ese fallback.
        logger.info(
            "Reel de paparazzi sin video fuente utilizable (%s); no se publica",
            render_info.get("fallback_reason", {}).get("error_type"),
        )
        _cleanup_local(video_path)
        return

    from utils import r2_storage

    if not r2_storage.is_configured():
        logger.warning("R2 no configurado; no se puede publicar el reel de paparazzi")
        _cleanup_local(video_path)
        return

    try:
        public_url, r2_key = r2_storage.upload_temp(video_path, ttl_hint="reel")
    except RuntimeError as exc:
        logger.warning("No se pudo subir el reel de paparazzi a R2: %s", exc)
        _cleanup_local(video_path)
        return
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
        try:
            from meta.fb_client import post_reel_video_to_facebook

            fb_result = post_reel_video_to_facebook(reel_item)
            fb_ok = fb_result.ok
            fb_id = fb_result.external_id or ""
            if not fb_ok:
                logger.warning(
                    "Reel de paparazzi no publicado en Facebook: %s", fb_result.error_type
                )
        except Exception:
            logger.exception("Error inesperado publicando el reel de paparazzi en Facebook")

    if ig_ok or fb_ok:
        try:
            _mark_posted(dedup_key, noticia, ig_id=ig_id, fb_id=fb_id)
        except JsonStateError as exc:
            logger.error("Reel de paparazzi publicado pero no se persistió la evidencia: %s", exc)
    else:
        try:
            r2_storage.delete(r2_key)
        except Exception:
            logger.warning("No se pudo limpiar el reel de paparazzi en R2 tras el fallo")
