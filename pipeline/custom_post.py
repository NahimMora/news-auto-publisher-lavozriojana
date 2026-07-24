"""
Publicaciones personalizadas - La Voz Riojana

Pipeline: pegar un link (X/Instagram/cualquiera) -> bajar la imagen -> el usuario
escribe titulo + texto -> se publica como una noticia mas: articulo real en la
web + cross-post en Instagram y Facebook, reusando el mismo pipeline del
autopublicador de noticias (pipeline/node_webapp/publisher.py, meta/ig_client.py,
meta/fb_client.py, layout/image_generator.py).
"""
from __future__ import annotations

import io
import os
import re
from uuid import uuid4
from pathlib import Path
from urllib.parse import urlsplit

from pipeline.node_webapp.editorial import category_to_slug
from utils.logging_setup import setup_logger
from utils.manual_video_queue import detect_platform
from utils.url_normalization import canonical_url as _canonical_url
from utils.paths import output_dir
from utils.safe_http import UnsafeURLError, validate_public_http_url

logger = setup_logger("custom_post", "video_reel_manager.log")

SECTIONS = [
    "politica", "policiales", "interior", "sociedad", "economia",
    "salud", "educacion", "deportes", "cultura", "espectaculos",
]


def _uploaded_local_path(value: str) -> str:
    """Resuelve únicamente uploads generados por la UI local."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        return ""
    prefix = "/api/uploads/"
    if not parsed.path.startswith(prefix):
        return ""
    filename = parsed.path[len(prefix):]
    if not re.fullmatch(r"[a-f0-9]{32}\.(?:jpe?g|png|webp|gif)", filename, re.IGNORECASE):
        return ""
    root = (output_dir() / "uploads").resolve()
    candidate = (root / filename).resolve()
    if candidate.parent != root or not candidate.is_file():
        return ""
    return str(candidate)


def fetch_image_from_url(source_url: str) -> dict:
    """Intenta sacar titulo + og:image de un link pegado por el usuario.

    Nunca lanza excepcion: si falla (comun en X/Instagram, que suelen bloquear
    el scraping simple), devuelve ok=False para que la UI ofrezca el campo
    manual de imagen.
    """
    source_url = str(source_url or "").strip()
    if not source_url:
        return {"ok": False, "imagen_url": "", "titulo_hint": "", "error": "source_url_requerida"}

    try:
        from openIA.reel_generator import scrape_url
        data = scrape_url(source_url)
    except Exception as exc:
        logger.warning("fetch_image_from_url fallo para %s: %s", source_url, exc)
        return {"ok": False, "imagen_url": "", "titulo_hint": "", "error": str(exc)}

    imagen_url = str(data.get("imagen_url") or "").strip()
    titulo_hint = str(data.get("titulo") or "").strip()
    if not imagen_url:
        return {"ok": False, "imagen_url": "", "titulo_hint": titulo_hint, "error": "no_se_encontro_imagen"}
    return {"ok": True, "imagen_url": imagen_url, "titulo_hint": titulo_hint, "error": None}


def _split_paragraphs(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n+", str(body or "")) if p.strip()]


def build_custom_noticia(payload: dict, *, require_image: bool = True) -> dict:
    """Arma el dict 'noticia' a partir de lo que carga el usuario.

    El link pegado se mapea a url/canonical_url igual que en una noticia
    scrapeada normal, para que classify()/source_display_name()/dedup se
    comporten igual que para cualquier otra nota.
    """
    titulo = " ".join(str(payload.get("titulo") or "").split())
    if not (8 <= len(titulo) <= 240):
        raise ValueError("El titulo debe tener entre 8 y 240 caracteres")

    parrafos = _split_paragraphs(payload.get("cuerpo"))
    if not parrafos:
        raise ValueError("El cuerpo no puede estar vacio")

    imagen_url = str(payload.get("imagen_url") or "").strip()
    if require_image and not imagen_url:
        raise ValueError("Falta la imagen (automatica o manual)")
    local_image = _uploaded_local_path(imagen_url) if imagen_url else ""
    if imagen_url and not local_image:
        try:
            imagen_url = validate_public_http_url(imagen_url)
        except UnsafeURLError as exc:
            raise ValueError(f"URL de imagen insegura: {exc}") from exc

    seccion = category_to_slug(str(payload.get("seccion") or "sociedad"))
    source_url = str(payload.get("source_url") or "").strip()
    if source_url:
        try:
            source_url = validate_public_http_url(source_url)
        except UnsafeURLError as exc:
            raise ValueError(f"URL de origen insegura: {exc}") from exc
    canonical = _canonical_url(source_url) if source_url else ""

    caption = "\n\n".join(parrafos)[:2200] or titulo
    dedup_key = str(payload.get("dedup_key") or f"custom:{uuid4().hex[:16]}")

    noticia = {
        "media_type": "image",
        "titulo": titulo,
        "titulo_original": titulo,
        "parrafos": parrafos,
        "seccion": seccion,
        "categoria": seccion,
        "imagen_url": imagen_url,
        "imagen": local_image,
        "url": source_url,
        "canonical_url": canonical,
        "source_platform": detect_platform(source_url) if source_url else "manual",
        "source": "manual_custom_post",
        "titulo_instagram": titulo[:80],
        "texto_instagram": caption,
        "caption": caption,
        "dedup_key": dedup_key,
        "manual_status": "ready",
    }
    return {key: value for key, value in noticia.items() if value not in ("", None, [], {})}


def render_preview_image(item: dict) -> bytes:
    """Renderiza el post con el mismo layout real que se usa al publicar (no un mockup)."""
    from PIL import Image
    from layout.image_generator import IG_H, IG_W, generate_post

    local = str(item.get("imagen") or "")
    preloaded = Image.open(local).convert("RGBA") if local else None
    img = generate_post(item, IG_W, IG_H, preloaded_img=preloaded)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _dry_run_enabled() -> bool:
    return os.getenv("CUSTOM_POST_DRY_RUN", "false").strip().lower() in {"1", "true", "yes", "on"}


def publish_custom_post(item: dict, *, log=None) -> dict:
    """Orquesta las 3 patas del pipeline: web -> Instagram -> Facebook.

    Facebook depende del link web (post_to_facebook solo publica un link +
    mensaje, usando la imagen OG de esa pagina), por eso si el paso web falla
    se aborta sin intentar IG/FB.
    """
    log = log or (lambda msg: None)
    result = {
        "status": "failed",
        "web_ok": False,
        "ig_ok": False,
        "fb_ok": False,
        "public_url": "",
        "error": None,
        "dry_run": False,
    }

    if _dry_run_enabled():
        log("DRY-RUN activo (CUSTOM_POST_DRY_RUN=true): no se publica de verdad.")
        result.update(
            status="no_work",
            dry_run=True,
            simulated_channels=["web", "instagram", "facebook"],
        )
        return result

    from pipeline.node_webapp.publisher import publish_one_detailed

    log("Publicando articulo en la web...")
    web = publish_one_detailed(item)
    result["web_ok"] = web["published"]
    result["public_url"] = web.get("public_url", "")
    result["web_degraded"] = bool(web.get("degraded"))
    if result["web_degraded"]:
        result["web_degraded_reason"] = web.get("degraded_reason")
    if not result["web_ok"]:
        result["error"] = web.get("error") or "web_publish_failed"
        log(f"Fallo la publicacion web ({result['error']}); se aborta Instagram/Facebook.")
        return result
    log(f"Publicado en la web: {result['public_url']}")

    item["web_url"] = result["public_url"]

    from meta.fb_client import post_to_facebook_detailed
    from meta.ig_client import post_to_instagram_detailed

    log("Publicando en Instagram...")
    try:
        instagram = post_to_instagram_detailed(item)
        result["ig_ok"] = instagram.ok
        result["instagram_result"] = instagram.to_dict()
    except Exception as exc:
        logger.exception("Error publicando en Instagram")
        result["instagram_result"] = {
            "status": "failed",
            "error_type": type(exc).__name__,
        }
        log(f"Instagram fallo: {exc}")

    log("Publicando en Facebook...")
    try:
        facebook = post_to_facebook_detailed(item)
        result["fb_ok"] = facebook.ok
        result["facebook_result"] = facebook.to_dict()
    except Exception as exc:
        logger.exception("Error publicando en Facebook")
        result["facebook_result"] = {
            "status": "failed",
            "error_type": type(exc).__name__,
        }
        log(f"Facebook fallo: {exc}")

    if result["ig_ok"] and result["fb_ok"] and not result["web_degraded"]:
        result["status"] = "success"
    else:
        result["status"] = "degraded"
        result["error_type"] = "partial_external_publication"
    return result
