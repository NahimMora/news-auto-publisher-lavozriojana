"""
Video Reel Manager - La Voz Riojana

Pipeline interactivo:
  1. Pegás el link de la noticia → IA genera título + caption
  2. Aprobás o modificás el contenido
  3. Se renderiza el video (PIL + ffmpeg) → previsualización
  4. Modificás si hay algo mal → re-renderizás
  5. Publicás → sube a R2 y publica en Instagram y Facebook
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from utils.manual_video_queue import enqueue_video, load_video_state, save_video_draft
from utils.manual_post_queue import save_post_draft, load_post_state
from utils.logging_setup import setup_logger
from utils.safe_http import UnsafeURLError, safe_get, validate_public_http_url
from utils.upload_validation import InvalidUploadError, validate_upload_content
from utils.paths import output_dir

logger = setup_logger("video_reel_manager", "video_reel_manager.log")

# Renders en memoria: video_id → ruta al MP4
_renders: dict[str, str] = {}

# Jobs de publicación: job_id → {done, ig_ok, fb_ok, messages, error}
_publish_jobs: dict[str, dict] = {}

# Previews de Publicaciones en memoria: preview_id → bytes JPEG
_custom_previews: dict[str, bytes] = {}

# Archivos subidos a mano (drag&drop / seleccionar archivo)
UPLOADS_DIR = str(output_dir() / "uploads")
_UPLOAD_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".gif"},
    "video": {".mp4", ".mov", ".m4v", ".webm"},
}
_UPLOAD_MAX_BYTES = {
    "image": 20 * 1024 * 1024,
    "video": 300 * 1024 * 1024,
}
_UPLOAD_CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/x-m4v", ".webm": "video/webm",
}
_PREMIUM_IMAGE_MAX_BYTES = _UPLOAD_MAX_BYTES["image"]
_PREMIUM_IMAGE_EXTENSIONS_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# Jobs de publicación de Publicaciones: job_id → {done, web_ok, ig_ok, fb_ok, messages, error, public_url}
_custom_jobs: dict[str, dict] = {}

# Jobs de publicación del Estudio Premium: job_id → {done, status, result, error}
_premium_jobs: dict[str, dict] = {}


def _premium_publish_background(job_id: str, package_id: str) -> None:
    try:
        from utils.premium_publisher import publish_package

        result = publish_package(package_id)
        _premium_jobs[job_id] = {"done": True, "status": result.get("status"), "result": result, "error": None}
    except Exception as exc:
        logger.exception("Error en premium_publish_background job %s", job_id[:8])
        _premium_jobs[job_id] = {"done": True, "status": "failed", "result": None, "error": str(exc)}


def validate_bind_host(host: str) -> str:
    """La interfaz manual sólo puede escuchar en loopback.

    No ofrece autenticación remota; exponerla en LAN/Internet permitiría disparar
    publicaciones y uploads. Una futura exposición deberá incorporar un proxy
    autenticado como cambio explícito, no un flag inseguro.
    """
    value = str(host or "").strip()
    if value.lower() == "localhost":
        return "127.0.0.1"
    candidate = value.strip("[]")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError as exc:
        raise ValueError("El Reel Manager sólo puede usar localhost/loopback") from exc
    if not address.is_loopback:
        raise ValueError("Se rechaza exposición externa: use 127.0.0.1 o ::1")
    return candidate


def _is_loopback_hostname(value: str) -> bool:
    host = str(value or "").rstrip(".").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_local_request_headers(host_header: str, origin_header: str = "") -> None:
    """Bloquea Host/Origin externos, incluido DNS rebinding contra loopback."""
    try:
        host = urlparse(f"//{str(host_header or '')}").hostname or ""
    except ValueError as exc:
        raise ValueError("Host HTTP inválido") from exc
    if not _is_loopback_hostname(host):
        raise ValueError("Host HTTP no permitido")
    origin = str(origin_header or "").strip()
    if not origin:
        return
    try:
        origin_host = urlparse(origin).hostname or ""
    except ValueError as exc:
        raise ValueError("Origin HTTP inválido") from exc
    if not _is_loopback_hostname(origin_host):
        raise ValueError("Origin HTTP no permitido")


def _safe_object_id(value: str) -> str | None:
    candidate = str(value or "")
    return candidate if re.fullmatch(r"[a-f0-9]{16,64}", candidate) else None


def _owned_upload_path(value: str, *, kind: str) -> str:
    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return ""
    if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        return ""
    prefix = "/api/uploads/"
    if not parsed.path.startswith(prefix):
        return ""
    filename = parsed.path[len(prefix):]
    return _owned_upload_name_path(filename, kind=kind)


def _owned_upload_name_path(value: str, *, kind: str) -> str:
    filename = str(value or "").strip()
    extensions = "|".join(
        re.escape(ext.lstrip("."))
        for ext in sorted(_UPLOAD_EXTENSIONS[kind])
    )
    if not re.fullmatch(rf"[a-f0-9]{{32}}\.(?:{extensions})", filename, re.IGNORECASE):
        return ""
    root = os.path.realpath(UPLOADS_DIR)
    candidate = os.path.realpath(os.path.join(root, filename))
    if os.path.dirname(candidate) != root or not os.path.isfile(candidate):
        return ""
    return candidate


def _validated_optional_url(value: object, *, kind: str | None = None) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    local = _owned_upload_path(raw, kind=kind) if kind else ""
    if local:
        return raw, local
    return validate_public_http_url(raw), ""


def _download_premium_image(value: object) -> tuple[bytes, str, str]:
    """Descarga una imagen pública con redirects SSRF-safe y límite de bytes."""
    normalized_url = validate_public_http_url(value)
    try:
        response = safe_get(
            normalized_url,
            timeout=(5, 20),
            stream=True,
            headers={"User-Agent": "LaVozRiojana-PremiumStudio/1.0"},
        )
    except UnsafeURLError:
        raise
    except Exception as exc:
        raise ValueError("No se pudo descargar la imagen") from exc

    try:
        try:
            response.raise_for_status()
        except Exception as exc:
            raise ValueError("La URL de imagen respondió con error HTTP") from exc

        content_type = str(response.headers.get("Content-Type") or "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        extension = _PREMIUM_IMAGE_EXTENSIONS_BY_TYPE.get(media_type)
        if not extension:
            raise ValueError("La URL no devolvió un formato de imagen permitido")

        raw_length = str(response.headers.get("Content-Length") or "").strip()
        if raw_length:
            try:
                declared_length = int(raw_length)
            except ValueError as exc:
                raise ValueError("Content-Length inválido en la imagen remota") from exc
            if declared_length > _PREMIUM_IMAGE_MAX_BYTES:
                raise ValueError("La imagen remota supera el máximo de 20 MB")

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > _PREMIUM_IMAGE_MAX_BYTES:
                raise ValueError("La imagen remota supera el máximo de 20 MB")
            chunks.append(bytes(chunk))
        data = b"".join(chunks)
        if not data:
            raise ValueError("La imagen remota está vacía")
        return data, normalized_url, f"premium_link{extension}"
    finally:
        response.close()


def _premium_asset_payload(asset: dict) -> dict:
    asset_id = str(asset.get("asset_id") or "")
    return {
        "ok": True,
        "asset_id": asset_id,
        "resource_id": f"asset:{asset_id}",
        "thumbnail": f"/api/media-library/thumb/{asset_id}",
        "titulo": asset.get("titulo"),
        "origin": asset.get("origin"),
    }


# ── HTML ─────────────────────────────────────────────────────

HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Videos Reel · La Voz Riojana</title>
<style>
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:#090a0d;color:#eef2f7;font-family:Inter,Segoe UI,Arial,sans-serif;height:100vh;display:flex;flex-direction:column;overflow:hidden}
header{height:52px;border-bottom:1px solid #1e2533;background:#0f1219;display:flex;align-items:center;justify-content:space-between;padding:0 20px;flex-shrink:0}
h1{font-size:14px;margin:0;font-weight:900;letter-spacing:.01em}
h1 span{color:#ffcf4a}
.sub{font-size:11px;color:#6e7a90}
.app{display:grid;grid-template-columns:370px 1fr 300px;flex:1;min-height:0;overflow:hidden}

/* ── Left panel ── */
aside{background:#0f1219;border-right:1px solid #1e2533;padding:0;overflow-y:auto;display:flex;flex-direction:column}
.pipe-block{padding:16px;border-bottom:1px solid #1a2030}
.pipe-block:last-child{border-bottom:0;flex:1}
.block-title{display:flex;align-items:center;gap:8px;margin-bottom:12px}
.step-badge{width:22px;height:22px;border-radius:50%;background:#b30000;color:#fff;font-size:11px;font-weight:900;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.step-badge.done{background:#3d7a4e}
.block-title h3{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:#7f8aa0;margin:0;font-weight:900}
.field{display:flex;flex-direction:column;gap:5px;margin-bottom:10px}
label{font-size:11px;color:#8c97aa;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
input,textarea,select{width:100%;border:1px solid #273040;background:#090a0d;color:#f0f4f8;border-radius:6px;padding:8px 10px;font:inherit;font-size:13px;outline:none;transition:border-color .15s}
textarea{min-height:100px;resize:vertical;font-size:12px}
input:focus,textarea:focus,select:focus{border-color:#75aadb}
.char-count{font-size:10px;color:#5a6378;text-align:right;margin-top:2px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.actions{display:flex;gap:8px;margin-top:10px}
button{border:0;border-radius:6px;padding:9px 13px;font-weight:800;cursor:pointer;color:#fff;font-size:12px;background:#232c3d;flex:1;transition:filter .12s}
button:hover{filter:brightness(1.1)}
button.primary{background:#b30000}
button.secondary{background:#1c2535}
button.ghost{background:transparent;border:1px solid #304050;color:#8899aa}
.full-btn{width:100%;margin-top:6px;flex:none}
.status{font-size:11px;line-height:1.5;color:#8a98b0;margin-top:8px;min-height:18px;word-break:break-word}
.status.ok{color:#6fcf97}
.status.err{color:#fca5a5}
.status.warn{color:#f5c56d}
.hidden{display:none}

/* ── Center ── */
main{display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:auto;padding:24px;background:#080a0c;gap:12px}
#render_overlay{position:absolute;display:none;background:rgba(8,10,12,.85);border-radius:12px;padding:24px 36px;text-align:center;z-index:10;color:#eef2f7;font-size:14px;font-weight:700}
.preview-wrap{position:relative}

/* CSS Mockup */
.reel{position:relative;width:243px;height:432px;background:#0b0b0b;box-shadow:0 24px 80px rgba(0,0,0,.65);border-radius:8px;overflow:hidden;flex-shrink:0}
/* Bloque superior: rojo con línea blanca abajo */
.r-top{position:absolute;left:0;right:0;top:0;height:64px;background:#b30000;border-bottom:2px solid #fff;display:flex;align-items:center;justify-content:flex-end;padding:0 10px;z-index:6}
/* LVR badge: blanco con texto rojo, en esquina derecha del bloque rojo */
.r-logo{background:#fff;color:#b30000;border-radius:4px;padding:3px 7px;font-size:11px;font-weight:900;z-index:7}
/* Área de imagen/video */
.r-frame{position:absolute;left:0;top:64px;width:243px;height:304px;background:#b30000;overflow:hidden}
.r-img{position:absolute;left:0;top:64px;width:243px;height:171px;background:#1b1f28;overflow:hidden;display:flex;align-items:center;justify-content:center}
.r-img img{width:100%;height:100%;object-fit:cover}
.r-img .hint{padding:14px;text-align:center;color:#94a3b8;font-size:11px;line-height:1.4}
/* Badge sección: cuadrado blanco que sobresale la mitad sobre el bloque rojo */
.r-badge{position:absolute;left:14px;top:222px;width:27px;height:27px;background:#fff;color:#b30000;border-radius:3px;display:flex;align-items:center;justify-content:center;font-size:7px;font-weight:900;text-align:center;text-transform:uppercase;z-index:7;line-height:1.1;padding:2px}
/* Título: empieza debajo del badge */
.r-headline{position:absolute;left:0;top:253px;width:243px;bottom:84px;background:#b30000;padding:6px 14px 8px;display:flex;align-items:flex-start;z-index:3}
.r-headline span{font-family:Impact,Arial Black,sans-serif;font-size:17px;line-height:.98;text-transform:uppercase;color:#fff;word-break:break-word}
/* Footer + área inferior: todo #111 */
.r-footer{position:absolute;left:0;bottom:64px;width:243px;height:20px;background:#111;display:flex;align-items:center;justify-content:space-between;padding:0 10px;font-size:8px;font-weight:800;color:#fff;z-index:5}
.r-footer span:last-child{color:#ffcf4a}
.r-bottom{position:absolute;left:0;bottom:0;right:0;height:64px;background:#111}

/* Video player */
#video_wrap{display:none;flex-direction:column;align-items:center;gap:10px}
#reel_video{max-height:calc(100vh - 140px);width:auto;max-width:300px;border-radius:8px;box-shadow:0 24px 80px rgba(0,0,0,.65)}
.video-label{font-size:11px;color:#6e7a90}

/* ── Right panel ── */
.list{background:#0f1219;border-left:1px solid #1e2533;padding:14px;overflow-y:auto}
.list-title{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:#6e7a90;margin:0 0 8px;font-weight:900}
.item{border:1px solid #1e2a3a;border-radius:7px;padding:9px;margin-bottom:8px;background:#0b0d14;cursor:default}
.item b{display:block;font-size:12px;margin-bottom:4px;line-height:1.3}
.item small{display:block;color:#7a8598;line-height:1.3;font-size:10px;word-break:break-all}
.pill{display:inline-block;font-size:9px;font-weight:900;color:#0b0b0b;background:#ffcf4a;border-radius:999px;padding:2px 7px;margin-bottom:5px;text-transform:uppercase}
.sep{margin:12px 0 8px;border-top:1px solid #1e2a3a;padding-top:10px}

/* ── Tabs ── */
.tabnav{display:flex;gap:4px}
.tabbtn{background:transparent;border:1px solid #273040;color:#8899aa;font-size:11px;font-weight:800;padding:6px 12px;border-radius:6px;cursor:pointer;flex:none}
.tabbtn.active{background:#b30000;border-color:#b30000;color:#fff}
.preview-img{max-width:320px;max-height:calc(100vh - 140px);border-radius:8px;box-shadow:0 24px 80px rgba(0,0,0,.65)}

/* ── Dropzone (drag&drop / seleccionar archivo) ── */
.dropzone{border:2px dashed #304050;border-radius:8px;padding:14px 10px;text-align:center;font-size:11px;line-height:1.5;color:#7f8aa0;cursor:pointer;margin-top:8px;transition:border-color .15s,background .15s}
.dropzone:hover,.dropzone.dragover{border-color:#75aadb;background:rgba(117,170,219,.08)}
.dropzone strong{color:#c9d2e0;font-size:12px}
#app_premium{grid-template-columns:minmax(400px,440px) 1fr 300px}
.premium-help{font-size:11px;color:#7f8aa0;line-height:1.5;margin:0 0 10px}
.premium-secondary{margin-top:12px;border-top:1px solid #1e2a3a;padding-top:10px}
.premium-secondary summary{cursor:pointer;color:#9cabc0;font-size:11px;font-weight:800}
.premium-slide-card textarea{margin-top:8px}
.premium-asset-card{border-color:#2b384c}
.premium-asset-summary{display:grid;grid-template-columns:92px 1fr;gap:10px;align-items:center;margin:8px 0 10px}
.premium-asset-thumb{width:92px;height:72px;object-fit:cover;border-radius:7px;background:#161b24;border:1px solid #273040}
.premium-asset-placeholder{width:92px;height:72px;border-radius:7px;border:1px dashed #304050;background:#111620;color:#718096;display:flex;align-items:center;justify-content:center;text-align:center;font-size:10px;line-height:1.25;padding:7px}
.premium-asset-card .asset-current{color:#9fb0c5;word-break:break-word}
.premium-asset-card .actions{margin-top:0}
.premium-gallery-backdrop{position:fixed;inset:0;background:rgba(3,5,8,.82);z-index:100;display:flex;align-items:center;justify-content:center;padding:18px}
.premium-gallery-backdrop.hidden{display:none}
.premium-gallery-modal{width:min(760px,94vw);max-height:84vh;overflow:hidden;background:#0f1219;border:1px solid #2a3547;border-radius:12px;box-shadow:0 26px 90px rgba(0,0,0,.72);display:flex;flex-direction:column}
.premium-gallery-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:16px 18px;border-bottom:1px solid #1e2a3a}
.premium-gallery-head b{display:block;font-size:14px;margin-bottom:3px}
.premium-gallery-head small{color:#7f8aa0;font-size:11px}
.premium-gallery-close{flex:none;width:34px;height:34px;padding:0;border:1px solid #304050;background:transparent;color:#aab6c8;font-size:18px}
.premium-gallery-tools{padding:14px 18px 10px;border-bottom:1px solid #1e2a3a}
.premium-gallery-search{display:grid;grid-template-columns:1fr auto;gap:8px}
.premium-gallery-search button{flex:none;min-width:92px}
.premium-gallery-body{padding:14px 18px;overflow-y:auto;min-height:190px}
.premium-gallery-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.premium-gallery-tile{border:1px solid #263246;border-radius:8px;background:#0b0d14;padding:7px;cursor:pointer;min-width:0;transition:border-color .15s,background .15s}
.premium-gallery-tile:hover{border-color:#75aadb;background:#121a26}
.premium-gallery-tile.loading{opacity:.58;pointer-events:none}
.premium-library-thumb{display:block;width:100%;height:112px;object-fit:cover;border-radius:6px;background:#161b24;margin-bottom:7px}
.premium-thumb-fallback{width:100%;height:112px;border-radius:6px;background:#151b24;color:#7f8aa0;display:flex;align-items:center;justify-content:center;text-align:center;font-size:10px;line-height:1.3;padding:8px;margin-bottom:7px}
.premium-gallery-tile b{display:block;font-size:11px;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.premium-gallery-tile small{display:block;color:#707d91;font-size:9px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.premium-gallery-sources{padding:0 18px 16px;border-top:1px solid #1e2a3a}
.premium-gallery-sources summary{cursor:pointer;color:#9cabc0;font-size:11px;font-weight:800;padding:12px 0 8px}
.premium-gallery-sources .dropzone{padding:10px;margin-top:8px}
.premium-gallery-sources .actions{margin-top:7px}
body.premium-gallery-open{overflow:hidden}
@media(max-width:720px){.premium-gallery-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.premium-gallery-modal{max-height:92vh}}

/* ── Candidatas ── */
#app_candidates{grid-template-columns:minmax(0,1fr);background:#080a0c}
#app_candidates main{align-items:stretch;justify-content:flex-start;padding:30px;gap:0}
.candidates-shell{width:min(1120px,100%);margin:0 auto;display:flex;flex-direction:column;gap:18px}
.candidates-hero{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:2px 2px 4px}
.candidates-eyebrow{display:block;color:#e54343;font-size:10px;font-weight:900;letter-spacing:.12em;text-transform:uppercase;margin-bottom:7px}
.candidates-hero h2{font-size:24px;line-height:1.15;margin:0 0 8px;letter-spacing:-.02em}
.candidates-hero p{max-width:700px;margin:0;color:#8491a5;font-size:12px;line-height:1.55}
.candidates-refresh{flex:none;min-width:112px;background:#131a26;border:1px solid #2a3547;color:#b7c2d2}
.candidates-layout{display:grid;grid-template-columns:minmax(280px,340px) minmax(0,1fr);gap:18px;align-items:start}
.candidates-panel{min-width:0;border:1px solid #202a39;border-radius:12px;background:#0f1219;box-shadow:0 18px 50px rgba(0,0,0,.18);overflow:hidden}
.candidates-panel-head{padding:18px 20px 14px;border-bottom:1px solid #1c2533}
.candidates-panel-head h3{font-size:14px;line-height:1.3;margin:0;color:#e8edf4}
.candidates-panel-head p{font-size:11px;line-height:1.5;color:#7f8aa0;margin:6px 0 0}
.candidates-panel-body{padding:18px 20px}
.candidates-panel .status{margin:0;min-height:0}
.candidates-action-status{margin:0 0 12px!important;min-height:0!important}
.candidates-count-row{display:flex;align-items:center;justify-content:space-between;gap:12px}
.candidates-count{font-size:10px;font-weight:800;color:#91a0b5;white-space:nowrap}
.candidates-count.err{color:#fca5a5}
.candidates-count.warn{color:#f5c56d}
.candidate-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.candidate-card{min-width:0;border:1px solid #243044;border-radius:10px;background:#0a0d13;padding:15px;display:flex;flex-direction:column;gap:11px}
.candidate-card-head{display:flex;align-items:center;flex-wrap:wrap;gap:6px}
.candidate-chip{display:inline-flex;align-items:center;max-width:100%;border-radius:999px;padding:4px 8px;background:#182131;color:#aab7ca;font-size:9px;font-weight:900;letter-spacing:.04em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.candidate-chip.reason{background:rgba(179,0,0,.2);color:#ff9a9a}
.candidate-card h4{font-size:14px;line-height:1.4;margin:0;color:#f2f5f8}
.candidate-reason{font-size:11px;line-height:1.45;color:#8f9caf;margin:0}
.candidate-meta{display:flex;flex-direction:column;gap:4px;padding-top:10px;border-top:1px solid #192231;color:#6f7c90;font-size:10px;line-height:1.35}
.candidate-meta-row{display:flex;gap:6px;min-width:0}
.candidate-meta-label{color:#99a8bc;font-weight:800;flex:none}
.candidate-meta-value{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.candidate-card .actions{margin-top:auto}
.candidate-card button{min-width:0}
.candidate-empty{grid-column:1/-1;border:1px dashed #2b3749;border-radius:10px;padding:38px 22px;text-align:center;background:#0a0d13}
.candidate-empty b{display:block;color:#dbe3ee;font-size:13px;margin-bottom:6px}
.candidate-empty span{display:block;color:#718096;font-size:11px;line-height:1.5}
@media(max-width:900px){
  #app_candidates main{padding:22px}
  .candidates-layout{grid-template-columns:1fr}
  .candidates-override{order:2}
  .candidates-inbox{order:1}
}
@media(max-width:640px){
  #app_candidates main{padding:18px 14px}
  .candidates-hero{flex-direction:column}
  .candidates-refresh{width:100%}
  .candidate-list{grid-template-columns:1fr}
  .candidates-panel-head,.candidates-panel-body{padding-left:15px;padding-right:15px}
}
</style>
</head>
<body>
<header>
  <h1>La Voz Riojana <span id="tab_title">· Videos Reel</span></h1>
  <div class="tabnav">
    <button class="tabbtn active" id="navbtn_videos" onclick="showTab('videos')">Videos</button>
    <button class="tabbtn" id="navbtn_custom" onclick="showTab('custom')">Publicaciones</button>
    <button class="tabbtn" id="navbtn_premium" onclick="showTab('premium')">Estudio Premium</button>
    <button class="tabbtn" id="navbtn_candidates" onclick="showTab('candidates')">Candidatas</button>
  </div>
</header>
<div class="app" id="app_videos">

<!-- ══ LEFT PANEL ═══════════════════════════════════════════ -->
<aside>

  <!-- PASO 1: URL -->
  <div class="pipe-block">
    <div class="block-title">
      <div class="step-badge" id="badge1">1</div>
      <h3>Enlace origen</h3>
    </div>
    <div class="field">
      <label>Link de la noticia (para IA)</label>
      <input id="source_url" placeholder="https://tiempopopular.com.ar/...">
    </div>
    <div class="field">
      <label>URL del video <span style="font-weight:400;color:#5a6378">(YouTube · Instagram · Facebook · X · TikTok · MP4 directo)</span></label>
      <input id="video_url_input" placeholder="https://youtube.com/watch?v=... , https://facebook.com/.../videos/... o .mp4">
      <div class="char-count" style="text-align:left;color:#4a5870">Opcional · si está vacío usa la imagen del artículo con Ken Burns</div>
      <div class="dropzone" id="video_dropzone">
        <strong>Arrastrá un video acá</strong><br>o hacé click para elegir un archivo de tu computadora
        <input type="file" id="video_file_input" accept="video/*" style="display:none">
      </div>
    </div>
    <div class="actions">
      <button class="primary" onclick="analyzeUrl()">Analizar con IA</button>
    </div>
    <div class="status" id="st_analyze"></div>
  </div>

  <!-- PASO 2: CONTENIDO IA -->
  <div class="pipe-block hidden" id="block_ai">
    <div class="block-title">
      <div class="step-badge" id="badge2">2</div>
      <h3>Contenido IA — revisá y editá</h3>
    </div>
    <div class="field">
      <label>Título del reel</label>
      <input id="titulo_reel" maxlength="80" oninput="draw();updateChars('titulo_reel','tc_titulo',80)">
      <div class="char-count" id="tc_titulo">0/80</div>
    </div>
    <div class="field">
      <label>Caption (IG + FB)</label>
      <textarea id="caption" maxlength="2200" oninput="updateChars('caption','tc_caption',2200)"></textarea>
      <div class="char-count" id="tc_caption">0/2200</div>
    </div>
    <div class="row2">
      <div class="field">
        <label>Sección</label>
        <select id="seccion" onchange="draw()">
          <option>policiales</option><option>politica</option><option>interior</option>
          <option>sociedad</option><option>economia</option><option>salud</option>
          <option>educacion</option><option>deportes</option><option>cultura</option>
        </select>
      </div>
      <div class="field">
        <label>Duración (seg)</label>
        <input id="duration_seconds" type="number" min="3" max="90" value="8">
      </div>
    </div>
    <div class="actions">
      <button class="ghost" onclick="analyzeUrl()">Regenerar IA</button>
      <button class="primary" onclick="renderVideo()">Generar video</button>
    </div>
    <div class="status" id="st_render"></div>
  </div>

  <!-- PASO 3: PUBLICAR -->
  <div class="pipe-block hidden" id="block_publish">
    <div class="block-title">
      <div class="step-badge" id="badge3">3</div>
      <h3>Publicar</h3>
    </div>
    <div class="actions">
      <button class="ghost" onclick="renderVideo()">Re-renderizar</button>
      <button class="primary" onclick="publishReel()">Publicar IG + FB</button>
    </div>
    <button class="secondary full-btn" onclick="saveToQueue()">Guardar en cola manual</button>
    <div class="status" id="st_publish"></div>
  </div>

</aside>

<!-- ══ CENTER ════════════════════════════════════════════════ -->
<main>
  <div class="preview-wrap">
    <div id="render_overlay">Renderizando video…<br><span style="font-size:12px;font-weight:400;color:#94a3b8">Esto puede tardar ~15 seg</span></div>

    <!-- Mockup CSS (fases 1-2) -->
    <div class="reel" id="css_mockup">
      <div class="r-top"><div class="r-logo">LVR</div></div>
      <div class="r-frame"></div>
      <div class="r-img" id="imgPreview"><div class="hint">La imagen de la noticia aparecerá aquí al renderizar el video.</div></div>
      <div class="r-badge" id="badgePreview">SEC</div>
      <div class="r-headline"><span id="titlePreview">TÍTULO DEL REEL</span></div>
      <div class="r-footer"><span>lavozriojana.com.ar</span><span>@lavozriojana</span></div>
      <div class="r-bottom"></div>
    </div>

    <!-- Video player (fase 3) -->
    <div id="video_wrap">
      <div class="video-label">Vista previa del video renderizado</div>
      <video id="reel_video" controls playsinline>
        <source id="reel_video_src" type="video/mp4">
      </video>
      <div class="video-label" id="video_size_label"></div>
    </div>
  </div>
</main>

<!-- ══ RIGHT PANEL ═══════════════════════════════════════════ -->
<section class="list">
  <p class="list-title">En cola</p>
  <div id="queueList"></div>
  <div class="sep">
    <p class="list-title">Borradores</p>
  </div>
  <div id="draftList"></div>
</section>

</div><!-- #app_videos -->

<!-- ══════════════════════════════════════════════════════════ -->
<!-- ══ PUBLICACIONES (tab aparte, pipeline de noticias)  ═══════ -->
<!-- ══════════════════════════════════════════════════════════ -->
<div class="app hidden" id="app_custom">

<!-- ══ LEFT PANEL ═══════════════════════════════════════════ -->
<aside>

  <!-- PASO 1: IMAGEN -->
  <div class="pipe-block">
    <div class="block-title">
      <div class="step-badge" id="cbadge1">1</div>
      <h3>Imagen de origen</h3>
    </div>
    <div class="field">
      <label>Link del posteo <span style="font-weight:400;color:#5a6378">(X · Instagram · Facebook · cualquier link)</span></label>
      <input id="custom_source_url" placeholder="https://x.com/... , https://instagram.com/p/... o https://facebook.com/...">
    </div>
    <div class="actions">
      <button class="primary" onclick="fetchImageCustom()">Buscar imagen</button>
    </div>
    <div class="status" id="st_custom_fetch"></div>
    <div class="field" id="custom_manual_wrap" style="margin-top:8px">
      <label>O pegá la URL de la imagen directamente</label>
      <input id="custom_imagen_manual" placeholder="https://.../foto.jpg" oninput="useManualImageCustom()">
      <div class="char-count" style="text-align:left;color:#4a5870">X/Instagram/Facebook suelen bloquear el scraping automático (piden login) — si "Buscar imagen" falla, pegá acá el link directo a la foto.</div>
      <div class="dropzone" id="custom_dropzone">
        <strong>Arrastrá una imagen acá</strong><br>o hacé click para elegir un archivo de tu computadora
        <input type="file" id="custom_file_input" accept="image/*" style="display:none">
      </div>
    </div>
    <div style="margin-top:10px" id="custom_thumb_wrap" class="hidden">
      <img id="custom_img_thumb" style="width:100%;border-radius:6px;display:block">
    </div>
  </div>

  <!-- PASO 2: CONTENIDO -->
  <div class="pipe-block hidden" id="cblock_content">
    <div class="block-title">
      <div class="step-badge" id="cbadge2">2</div>
      <h3>Título y texto — lo escribís vos</h3>
    </div>
    <div class="field">
      <label>Título <span style="font-weight:400;color:#5a6378">(máximo 120 caracteres)</span></label>
      <input id="custom_titulo" maxlength="120" oninput="updateChars('custom_titulo','ctc_titulo',120)">
      <div class="char-count" id="ctc_titulo">0/120</div>
      <div class="char-count" style="text-align:left;color:#4a5870">Una frase relevante se destaca automáticamente en azul o rojo según la card.</div>
    </div>
    <div class="field">
      <label>Texto (separá párrafos con una línea en blanco)</label>
      <textarea id="custom_cuerpo" style="min-height:160px"></textarea>
    </div>
    <div class="field">
      <label>Sección</label>
      <select id="custom_seccion">
        <option>politica</option><option>policiales</option><option>interior</option>
        <option selected>sociedad</option><option>economia</option><option>salud</option>
        <option>educacion</option><option>deportes</option><option>cultura</option>
        <option>espectaculos</option>
      </select>
    </div>
    <div class="actions">
      <button class="primary" onclick="previewCustom()">Vista previa</button>
    </div>
    <div class="status" id="st_custom_preview"></div>
  </div>

  <!-- PASO 3: PUBLICAR -->
  <div class="pipe-block hidden" id="cblock_publish">
    <div class="block-title">
      <div class="step-badge" id="cbadge3">3</div>
      <h3>Publicar</h3>
    </div>
    <div class="actions">
      <button class="primary" onclick="publishCustom()">Publicar (Web + IG + FB)</button>
    </div>
    <button class="secondary full-btn" onclick="saveCustomDraft()">Guardar en borradores</button>
    <div class="status" id="st_custom_publish"></div>
  </div>

</aside>

<!-- ══ CENTER ════════════════════════════════════════════════ -->
<main>
  <div id="custom_preview_placeholder" style="color:#6e7a90;font-size:13px;text-align:center;max-width:280px">
    Completá la imagen, el título y el texto, y tocá "Vista previa" para ver cómo va a quedar el posteo.
  </div>
  <img id="custom_preview_img" class="preview-img hidden">
</main>

<!-- ══ RIGHT PANEL ═══════════════════════════════════════════ -->
<section class="list">
  <p class="list-title">Publicados</p>
  <div id="customPublishedList"></div>
  <div class="sep">
    <p class="list-title">Borradores</p>
  </div>
  <div id="customDraftList"></div>
</section>

</div><!-- #app_custom -->

<div class="app hidden" id="app_premium">
<aside>
  <div class="pipe-block">
    <div class="block-title">
      <div class="step-badge" id="pbadge1">1</div>
      <h3>Pegá la noticia y generá la estructura</h3>
    </div>
    <p class="premium-help">La IA trabaja únicamente con el texto que pegás acá: no busca ni completa información externa.</p>
    <div class="field">
      <label>Pegá acá el texto actualizado de la noticia</label>
      <textarea id="premium_raw_article_text" rows="10" placeholder="Título, datos confirmados, contexto y texto completo de la noticia…"></textarea>
    </div>
    <div class="actions">
      <button class="primary" id="premium_generate_btn" onclick="generatePremiumPackage()">Generar estructura con IA</button>
    </div>
    <div class="status" id="st_premium_generate"></div>
    <details class="premium-secondary">
      <summary>¿Ya tenés el JSON? Pegalo acá</summary>
      <div class="field" style="margin-top:10px">
        <label>Paquete JSON manual</label>
        <textarea id="premium_import_text" rows="7" placeholder='{"title": "...", "slides": [...]}'></textarea>
      </div>
      <div class="actions">
        <button class="secondary" onclick="importPremiumPackage()">Importar JSON</button>
      </div>
      <div class="status" id="st_premium_import"></div>
    </details>
  </div>

  <div class="pipe-block">
    <div class="block-title">
      <div class="step-badge" id="pbadge2">2</div>
      <h3>Revisá y editá el borrador</h3>
    </div>
    <div class="field"><label>Título</label><input id="premium_title"></div>
    <div class="field"><label>Caption (sin link)</label><textarea id="premium_caption" rows="3"></textarea></div>
    <div class="field"><label>Sección</label><input id="premium_section"></div>
    <div class="field">
      <label>Plantilla</label>
      <select id="premium_template">
        <option value="lvr_cronica">lvr_cronica</option>
        <option value="lvr_datos">lvr_datos</option>
        <option value="lvr_visual">lvr_visual</option>
      </select>
    </div>
    <div class="field">
      <label>Highlight terms (separados por coma, 1-3)</label>
      <input id="premium_highlights" placeholder="incendio, Chilecito">
    </div>
    <div class="field">
      <label><input type="checkbox" id="premium_dest_ig" checked> Instagram</label>
      <label><input type="checkbox" id="premium_dest_fb" checked> Facebook</label>
    </div>
    <div id="premium_slides_list"></div>
    <button class="secondary full-btn" onclick="addPremiumSlide('image_text')">+ Agregar slide</button>
  </div>

  <div class="pipe-block">
    <div class="block-title">
      <div class="step-badge" id="pbadge3">3</div>
      <h3>Elegí las imágenes</h3>
    </div>
    <p class="premium-help">Sólo aparecen los slides que usan foto. Abrí su galería y elegí una miniatura: se asigna y guarda directamente.</p>
    <div id="premium_asset_slides_list"></div>
    <div class="status" id="st_premium_assets"></div>
  </div>

  <div class="pipe-block">
    <div class="block-title">
      <div class="step-badge" id="pbadge4">4</div>
      <h3>Guardá, previsualizá y publicá</h3>
    </div>
    <div class="actions">
      <button class="secondary" onclick="savePremiumDraft()">Guardar borrador</button>
      <button class="secondary" onclick="previewPremium()">Previsualizar</button>
      <button class="primary" onclick="publishPremium()">Publicar (IG + FB)</button>
    </div>
    <div class="status" id="st_premium_draft"></div>
    <div class="status" id="st_premium_publish"></div>
  </div>
</aside>

<main>
  <div id="premium_preview_grid" style="display:flex;flex-wrap:wrap;gap:10px;justify-content:center"></div>
</main>

<section class="list">
  <p class="list-title">Borradores premium</p>
  <div id="premiumDraftList"></div>
</section>
</div><!-- #app_premium -->

<div class="premium-gallery-backdrop hidden" id="premium_gallery_modal" onclick="closePremiumGallery(event)">
  <div class="premium-gallery-modal" role="dialog" aria-modal="true" aria-labelledby="premium_gallery_title">
    <div class="premium-gallery-head">
      <div>
        <b id="premium_gallery_title">Galería de imágenes</b>
        <small id="premium_gallery_target">Elegí una imagen para el slide</small>
      </div>
      <button class="premium-gallery-close" type="button" onclick="closePremiumGallery()" aria-label="Cerrar galería">×</button>
    </div>
    <div class="premium-gallery-tools">
      <div class="premium-gallery-search">
        <input id="premium_library_query" placeholder="Buscar por título, sección o lugar" onkeydown="if(event.key==='Enter'){event.preventDefault();searchPremiumLibrary()}">
        <button class="secondary" type="button" onclick="searchPremiumLibrary()">Buscar</button>
      </div>
      <div class="status" id="st_premium_gallery"></div>
    </div>
    <div class="premium-gallery-body">
      <div class="premium-gallery-grid" id="premium_library_results"></div>
    </div>
    <details class="premium-gallery-sources">
      <summary>Agregar otra imagen</summary>
      <div class="field">
        <label>Link directo a una imagen</label>
        <input id="premium_gallery_url" type="url" placeholder="https://…/imagen.jpg">
      </div>
      <div class="actions">
        <button class="secondary" type="button" onclick="assignPremiumGalleryUrl()">Usar este link</button>
      </div>
      <div class="dropzone" id="premium_gallery_dropzone">
        <strong>Subir desde mi computadora</strong><br>Arrastrá una imagen o hacé click para elegirla
        <input type="file" id="premium_gallery_file" accept="image/*" style="display:none">
      </div>
    </details>
  </div>
</div>

<div class="app hidden" id="app_candidates">
<main>
  <div class="candidates-shell">
    <section class="candidates-hero">
      <div>
        <span class="candidates-eyebrow">Selección editorial</span>
        <h2>Bandeja de candidatas</h2>
        <p>Revisá las noticias apartadas del flujo automático de Instagram. “Enviar a automática” es una decisión manual autoritativa: habilita su publicación aunque la categoría no esté en la selección habitual o todavía no tenga URL Web.</p>
      </div>
      <button class="candidates-refresh" id="candidates_refresh_btn" type="button" onclick="loadCandidates()">Actualizar</button>
    </section>

    <div class="candidates-layout">
      <section class="candidates-panel candidates-override">
        <div class="candidates-panel-head">
          <span class="candidates-eyebrow">Gestión manual</span>
          <h3>Mover una noticia por identidad</h3>
          <p>Usá esta opción para una automática pendiente o para reutilizar una publicación ya confirmada en una pieza premium.</p>
        </div>
        <div class="candidates-panel-body">
          <div class="field">
            <label>Identidad (meta_queue_key / dedup_key / canonical_url)</label>
            <input id="override_identity" placeholder="link:abc123...">
          </div>
          <div class="field"><label>Motivo</label><input id="override_reason" placeholder="Nota nacional sin vínculo riojano comprobado"></div>
          <div class="actions">
            <button class="secondary" onclick="demoteAutomaticToCandidate()">Quitar de automático</button>
            <button class="secondary" onclick="addPublishedToCandidates()">Reutilizar publicada</button>
          </div>
          <div class="status" id="st_override" role="status" aria-live="polite"></div>
        </div>
      </section>

      <section class="candidates-panel candidates-inbox">
        <div class="candidates-panel-head">
          <div class="candidates-count-row">
            <div>
              <span class="candidates-eyebrow">Instagram</span>
              <h3>Candidatas pendientes</h3>
            </div>
            <div class="candidates-count" id="st_candidates" role="status" aria-live="polite"></div>
          </div>
        </div>
        <div class="candidates-panel-body">
          <div class="status candidates-action-status" id="st_candidates_action" role="status" aria-live="polite"></div>
          <div class="candidate-list" id="candidates_list"></div>
        </div>
      </section>
    </div>
  </div>
</main>
</div><!-- #app_candidates -->

<script>
// ── State ────────────────────────────────────────────────────
let _currentVideoId = null;
let _currentArticle = null;
let _pollTimer = null;

// ── Utils ────────────────────────────────────────────────────
function val(id) {
  const el = document.getElementById(id);
  if (!el) return '';
  return el.type === 'checkbox' ? el.checked : el.value.trim();
}
function setVal(id, v) {
  const el = document.getElementById(id);
  if (el) el.value = v || '';
}
function show(id) { document.getElementById(id)?.classList.remove('hidden'); }
function hide(id) { document.getElementById(id)?.classList.add('hidden'); }
function setStatus(id, msg, type='') {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className = 'status' + (type ? ' ' + type : '');
}
function updateChars(inputId, countId, max) {
  const el = document.getElementById(inputId);
  const cnt = document.getElementById(countId);
  if (el && cnt) cnt.textContent = `${el.value.length}/${max}`;
}

// ── Dropzone (drag&drop / seleccionar archivo) ────────────────
function setupDropzone(zoneId, fileInputId, kind, onUploaded, onError) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(fileInputId);
  if (!zone || !input) return;

  async function handleFile(file) {
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    fd.append('kind', kind);
    try {
      const r = await fetch('/api/upload', {method: 'POST', body: fd});
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.error || 'Error al subir el archivo');
      onUploaded(d, file);
    } catch (e) {
      onError(e);
    }
  }

  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => handleFile(input.files[0]));
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    handleFile(e.dataTransfer.files[0]);
  });
}

// ── CSS Mockup live update ────────────────────────────────────
function draw() {
  document.getElementById('titlePreview').textContent =
    (val('titulo_reel') || 'TÍTULO DEL REEL').toUpperCase();
  const sec = (val('seccion') || 'sociedad').toUpperCase();
  // Badge: máximo 3 líneas de ~3 chars para que entre en el cuadrado
  document.getElementById('badgePreview').textContent = sec;
  const imgUrl = _currentArticle?.imagen_url;
  const imgEl = document.getElementById('imgPreview');
  if (imgUrl && imgEl) {
    imgEl.textContent = '';
    const image = document.createElement('img');
    image.src = imgUrl;
    image.alt = '';
    image.addEventListener('error', () => { image.style.display = 'none'; });
    imgEl.appendChild(image);
  }
}

// ── PASO 1: Analizar URL ──────────────────────────────────────
async function analyzeUrl() {
  const url = val('source_url');
  if (!url) { setStatus('st_analyze', 'Pegá una URL primero.', 'err'); return; }
  setStatus('st_analyze', '⏳ Analizando con IA (puede tardar ~10s)…');
  try {
    const r = await fetch('/api/analyze-url', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({source_url: url}),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Error al analizar');
    _currentArticle = d;
    setVal('titulo_reel', d.titulo_reel || '');
    setVal('caption', d.caption || '');
    setVal('seccion', d.seccion || 'sociedad');
    setVal('top_text', '');
    setVal('bottom_text', '');
    updateChars('titulo_reel', 'tc_titulo', 80);
    updateChars('caption', 'tc_caption', 2200);
    document.getElementById('badge1').textContent = '✓';
    document.getElementById('badge1').classList.add('done');
    show('block_ai');
    setStatus('st_analyze', '✓ IA generó título y caption. Revisá y editá abajo.', 'ok');
    draw();
  } catch (e) {
    setStatus('st_analyze', `✗ ${e.message}`, 'err');
  }
}

// ── PASO 2: Renderizar video ──────────────────────────────────
async function renderVideo() {
  const payload = {
    source_url: val('source_url'),
    video_url: val('video_url_input'),
    titulo_reel: val('titulo_reel'),
    caption: val('caption'),
    seccion: val('seccion'),
    duration_seconds: parseInt(val('duration_seconds') || '15'),
    imagen_url: _currentArticle?.imagen_url || '',
  };
  if (!payload.titulo_reel) {
    setStatus('st_render', '✗ El título del reel es obligatorio.', 'err');
    return;
  }
  setStatus('st_render', '⏳ Renderizando video…');
  document.getElementById('render_overlay').style.display = 'flex';
  document.getElementById('render_overlay').style.display = 'block';
  try {
    const r = await fetch('/api/render-video', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Error al renderizar');
    _currentVideoId = d.video_id;
    document.getElementById('render_overlay').style.display = 'none';
    // Mostrar video player, ocultar mockup
    document.getElementById('css_mockup').style.display = 'none';
    const wrap = document.getElementById('video_wrap');
    wrap.style.display = 'flex';
    const src = document.getElementById('reel_video_src');
    src.src = `/api/preview/${d.video_id}.mp4?t=${Date.now()}`;
    document.getElementById('reel_video').load();
    document.getElementById('video_size_label').textContent =
      d.size_mb ? `${d.size_mb} MB · ${d.duration}s` : '';
    document.getElementById('badge2').textContent = '✓';
    document.getElementById('badge2').classList.add('done');
    show('block_publish');
    if (d.source_used === 'video') {
      setStatus('st_render', '✓ Video generado con el video fuente original.', 'ok');
    } else {
      const motivos = {
        not_installed: 'yt-dlp no está instalado/en PATH',
        extractor_error: 'la plataforma cambió algo y yt-dlp no pudo extraer el video',
        auth_required: 'la plataforma pide sesión iniciada (configurá YTDLP_COOKIES_FILE)',
        unsupported_url: 'el link no tiene un video reconocible',
        network_error: 'error de red al descargar',
        rate_limit: 'la plataforma limitó las descargas (reintentá más tarde)',
        file_too_large: 'el video supera el tamaño máximo permitido',
      };
      const reason = d.fallback_reason || {};
      const motivo = motivos[reason.error_type] || reason.error_type || 'motivo desconocido';
      const usado = d.source_used === 'overlay_only'
        ? 'solo el layout (sin imagen ni video)'
        : 'una imagen animada';
      setStatus(
        'st_render',
        `⚠ No se pudo traer el video original — se usó ${usado}. Motivo: ${motivo}.`,
        'warn',
      );
    }
    setStatus('st_publish', '');
  } catch (e) {
    document.getElementById('render_overlay').style.display = 'none';
    setStatus('st_render', `✗ ${e.message}`, 'err');
  }
}

// ── PASO 3: Publicar ──────────────────────────────────────────
async function publishReel() {
  if (!_currentVideoId) {
    setStatus('st_publish', '✗ Primero generá el video.', 'err');
    return;
  }
  setStatus('st_publish', '⏳ Iniciando publicación…');
  const payload = {
    video_id: _currentVideoId,
    titulo_reel: val('titulo_reel'),
    caption: val('caption'),
    seccion: val('seccion'),
    source_url: val('source_url'),
    imagen_url: _currentArticle?.imagen_url || '',
  };
  try {
    const r = await fetch('/api/publish-reel', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Error al publicar');
    pollPublish(d.job_id);
  } catch (e) {
    setStatus('st_publish', `✗ ${e.message}`, 'err');
  }
}

function pollPublish(jobId) {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(async () => {
    try {
      const r = await fetch(`/api/publish-status/${jobId}`);
      const d = await r.json();
      const msgs = (d.messages || []).join(' · ');
      setStatus('st_publish', msgs || '⏳ Publicando…', d.error ? 'err' : '');
      if (d.done) {
        clearInterval(_pollTimer);
        _pollTimer = null;
        if (d.error) {
          setStatus('st_publish', `✗ ${d.error}`, 'err');
        } else {
          const ig = d.ig_ok ? '✓ IG' : '✗ IG';
          const fb = d.fb_ok ? '✓ FB' : '✗ FB';
          const success = d.status === 'success';
          setStatus('st_publish', `Listo (${d.status || 'failed'}): ${ig} · ${fb}`, success ? 'ok' : 'err');
          document.getElementById('badge3').textContent = success ? '✓' : '!';
          document.getElementById('badge3').classList.toggle('done', success);
          loadLists();
        }
      }
    } catch (e) {
      clearInterval(_pollTimer);
      setStatus('st_publish', `✗ Error de red: ${e.message}`, 'err');
    }
  }, 2500);
}

// ── Guardar en cola manual ────────────────────────────────────
async function saveToQueue() {
  const payload = {
    source_url: val('source_url'),
    title: val('titulo_reel'),
    caption: val('caption'),
    seccion: val('seccion'),
    top_text: val('top_text'),
    bottom_text: val('bottom_text'),
    duration_seconds: val('duration_seconds'),
    video_url: '',
  };
  try {
    const r = await fetch('/api/draft-video', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    setStatus('st_publish', d.added ? '✓ Guardado como borrador.' : '✓ Borrador actualizado.', 'ok');
    loadLists();
  } catch (e) {
    setStatus('st_publish', `✗ ${e.message}`, 'err');
  }
}

// ── Queue / Drafts list ──────────────────────────────────────
function listText(value) {
  return String(value ?? '');
}
function emptyList(el) {
  const small = document.createElement('small');
  small.style.color = '#4a5568';
  small.textContent = 'Sin items';
  el.replaceChildren(small);
}
function buildListItem(it, onClick=null) {
  const item = document.createElement('div');
  item.className = 'item';
  if (onClick) {
    item.style.cursor = 'pointer';
    item.addEventListener('click', onClick);
  }
  const pill = document.createElement('span');
  pill.className = 'pill';
  pill.textContent = listText(it.seccion || 'general');
  const title = document.createElement('b');
  title.textContent = listText(it.titulo);
  const detail = document.createElement('small');
  detail.textContent = listText(it.source_video_url || it.web_url || it.url);
  item.append(pill, title, detail);
  return item;
}
function renderList(id, items) {
  const el = document.getElementById(id);
  if (!items?.length) { emptyList(el); return; }
  el.replaceChildren(...items.map(it => buildListItem(it)));
}
async function loadLists() {
  const r = await fetch('/api/videos');
  const d = await r.json();
  renderList('queueList', d.queue);
  renderList('draftList', d.drafts);
}

// ══════════════════════════════════════════════════════════════
// ── PUBLICACIONES (tab aparte) ───────────────────────────────
// ══════════════════════════════════════════════════════════════
let _customImagenUrl = '';
let _customPollTimer = null;
let _customDedupKey = '';

function showTab(name) {
  const tabs = ['videos', 'custom', 'premium', 'candidates'];
  const titles = {
    videos: '· Videos Reel',
    custom: '· Publicaciones',
    premium: '· Estudio Premium',
    candidates: '· Candidatas',
  };
  for (const tab of tabs) {
    document.getElementById('app_' + tab).classList.toggle('hidden', tab !== name);
    document.getElementById('navbtn_' + tab).classList.toggle('active', tab === name);
  }
  document.getElementById('tab_title').textContent = titles[name] || '';
  if (name === 'custom') loadCustomLists();
  if (name === 'premium') loadPremiumDraftList();
  if (name === 'candidates') loadCandidates();
}

function _customSetThumb(url) {
  _customImagenUrl = url || '';
  const wrap = document.getElementById('custom_thumb_wrap');
  const img = document.getElementById('custom_img_thumb');
  if (_customImagenUrl) {
    img.src = _customImagenUrl;
    wrap.classList.remove('hidden');
  } else {
    wrap.classList.add('hidden');
  }
}

function useManualImageCustom() {
  const url = val('custom_imagen_manual');
  _customSetThumb(url);
  if (url) {
    document.getElementById('cbadge1').textContent = '✓';
    document.getElementById('cbadge1').classList.add('done');
    show('cblock_content');
  }
}

async function fetchImageCustom() {
  const url = val('custom_source_url');
  if (!url) { setStatus('st_custom_fetch', 'Pegá un link primero.', 'err'); return; }
  setStatus('st_custom_fetch', '⏳ Buscando imagen…');
  try {
    const r = await fetch('/api/custom/fetch-image', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({source_url: url}),
    });
    const d = await r.json();
    if (!d.ok) {
      setStatus('st_custom_fetch', `✗ ${d.error || 'No se encontró imagen'} — pegá la URL manualmente abajo.`, 'err');
      if (d.titulo_hint) {
        setVal('custom_titulo', d.titulo_hint);
        updateChars('custom_titulo', 'ctc_titulo', 120);
      }
      return;
    }
    _customSetThumb(d.imagen_url);
    setVal('custom_imagen_manual', d.imagen_url);
    if (d.titulo_hint) {
      setVal('custom_titulo', d.titulo_hint);
      updateChars('custom_titulo', 'ctc_titulo', 120);
    }
    document.getElementById('cbadge1').textContent = '✓';
    document.getElementById('cbadge1').classList.add('done');
    show('cblock_content');
    setStatus('st_custom_fetch', '✓ Imagen encontrada. Revisála abajo.', 'ok');
  } catch (e) {
    setStatus('st_custom_fetch', `✗ ${e.message}`, 'err');
  }
}

function _customPayload() {
  return {
    source_url: val('custom_source_url'),
    imagen_url: _customImagenUrl,
    titulo: val('custom_titulo'),
    cuerpo: val('custom_cuerpo'),
    seccion: val('custom_seccion'),
    dedup_key: _customDedupKey || undefined,
  };
}

async function previewCustom() {
  const payload = _customPayload();
  if (!payload.titulo || !payload.cuerpo) {
    setStatus('st_custom_preview', '✗ Completá título y texto primero.', 'err');
    return;
  }
  setStatus('st_custom_preview', '⏳ Generando vista previa…');
  try {
    const r = await fetch('/api/custom/preview-image', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Error al generar vista previa');
    document.getElementById('custom_preview_placeholder').classList.add('hidden');
    const img = document.getElementById('custom_preview_img');
    img.src = `${d.preview_url}?t=${Date.now()}`;
    img.classList.remove('hidden');
    document.getElementById('cbadge2').textContent = '✓';
    document.getElementById('cbadge2').classList.add('done');
    show('cblock_publish');
    setStatus('st_custom_preview', '✓ Vista previa generada.', 'ok');
  } catch (e) {
    setStatus('st_custom_preview', `✗ ${e.message}`, 'err');
  }
}

async function publishCustom() {
  const payload = _customPayload();
  setStatus('st_custom_publish', '⏳ Publicando (Web → Instagram → Facebook)…');
  try {
    const r = await fetch('/api/custom/publish', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Error al publicar');
    pollCustomPublish(d.job_id);
  } catch (e) {
    setStatus('st_custom_publish', `✗ ${e.message}`, 'err');
  }
}

function pollCustomPublish(jobId) {
  if (_customPollTimer) clearInterval(_customPollTimer);
  _customPollTimer = setInterval(async () => {
    try {
      const r = await fetch(`/api/custom/publish-status/${jobId}`);
      const d = await r.json();
      const msgs = (d.messages || []).join(' · ');
      setStatus('st_custom_publish', msgs || '⏳ Publicando…', d.error ? 'err' : '');
      if (d.done) {
        clearInterval(_customPollTimer);
        _customPollTimer = null;
        if (d.error) {
          setStatus('st_custom_publish', `✗ ${d.error}`, 'err');
        } else {
          const web = d.web_ok ? '✓ Web' : '✗ Web';
          const ig = d.ig_ok ? '✓ IG' : '✗ IG';
          const fb = d.fb_ok ? '✓ FB' : '✗ FB';
          const success = d.status === 'success';
          setStatus('st_custom_publish', `Listo (${d.status || 'failed'}): ${web} · ${ig} · ${fb}`, success ? 'ok' : 'err');
          document.getElementById('cbadge3').textContent = success ? '✓' : '!';
          document.getElementById('cbadge3').classList.toggle('done', success);
          if (d.web_ok) _customDedupKey = '';
          loadCustomLists();
        }
      }
    } catch (e) {
      clearInterval(_customPollTimer);
      setStatus('st_custom_publish', `✗ Error de red: ${e.message}`, 'err');
    }
  }, 2500);
}

async function saveCustomDraft() {
  const payload = _customPayload();
  try {
    const r = await fetch('/api/custom/draft', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Error al guardar borrador');
    setStatus('st_custom_publish', d.added ? '✓ Guardado como borrador.' : '✓ Borrador actualizado.', 'ok');
    loadCustomLists();
  } catch (e) {
    setStatus('st_custom_publish', `✗ ${e.message}`, 'err');
  }
}

let _customDrafts = [];

function renderCustomList(id, items, clickable) {
  const el = document.getElementById(id);
  if (!items?.length) { emptyList(el); return; }
  el.replaceChildren(
    ...items.map((it, i) => buildListItem(
      it,
      clickable ? () => loadCustomDraft(i) : null,
    )),
  );
}

function loadCustomDraft(index) {
  const it = _customDrafts[index];
  if (!it) return;
  _customDedupKey = it.dedup_key || '';
  setVal('custom_source_url', it.url || it.canonical_url || '');
  setVal('custom_titulo', it.titulo || '');
  setVal('custom_cuerpo', (it.parrafos || []).join('\n\n'));
  if (it.seccion) setVal('custom_seccion', it.seccion);
  updateChars('custom_titulo', 'ctc_titulo', 120);
  _customSetThumb(it.imagen_url || '');
  setVal('custom_imagen_manual', it.imagen_url || '');
  if (it.imagen_url) {
    document.getElementById('cbadge1').textContent = '✓';
    document.getElementById('cbadge1').classList.add('done');
  }
  show('cblock_content');
  show('cblock_publish');
  setStatus('st_custom_fetch', '✓ Borrador cargado. Revisá los datos y generá la vista previa.', 'ok');
  setStatus('st_custom_publish', '');
}

async function loadCustomLists() {
  const r = await fetch('/api/custom/posts');
  const d = await r.json();
  _customDrafts = d.drafts || [];
  renderCustomList('customPublishedList', d.published, false);
  renderCustomList('customDraftList', _customDrafts, true);
}

// ── Init ─────────────────────────────────────────────────────
draw();
loadLists();

setupDropzone('video_dropzone', 'video_file_input', 'video', (d, file) => {
  setVal('video_url_input', d.url);
  setStatus('st_analyze', `✓ Video subido: ${file.name}`, 'ok');
}, e => setStatus('st_analyze', `✗ ${e.message}`, 'err'));

setupDropzone('custom_dropzone', 'custom_file_input', 'image', (d, file) => {
  _customSetThumb(d.url);
  setVal('custom_imagen_manual', d.url);
  document.getElementById('cbadge1').textContent = '✓';
  document.getElementById('cbadge1').classList.add('done');
  show('cblock_content');
  setStatus('st_custom_fetch', `✓ Imagen subida: ${file.name}`, 'ok');
}, e => setStatus('st_custom_fetch', `✗ ${e.message}`, 'err'));

// ══ Estudio Premium (Fase 3) ═══════════════════════════════════
let _premiumPackage = null;
let _premiumGallerySlideId = '';
const PREMIUM_SLIDE_TYPES = ['cover', 'image_text', 'full_image', 'key_points', 'quote', 'number', 'closing', 'context', 'impact'];
const PREMIUM_IMAGE_SLIDE_TYPES = new Set(['cover', 'image_text', 'full_image']);
const PREMIUM_SLIDE_LABELS = {
  cover: 'portada', image_text: 'imagen + texto', full_image: 'foto protagonista',
  key_points: 'puntos clave', quote: 'cita', number: 'en números', closing: 'cierre',
  context: 'contexto', impact: 'impacto local / qué sigue',
};

function _fmtErrList(list) {
  return (list && list.length) ? list.join(' · ') : '';
}

async function generatePremiumPackage() {
  const raw_text = val('premium_raw_article_text');
  if (!raw_text.trim()) {
    setStatus('st_premium_generate', 'Pegá el texto de la noticia primero.', 'err');
    return;
  }
  const button = document.getElementById('premium_generate_btn');
  button.disabled = true;
  setStatus('st_premium_generate', '⏳ Generando la estructura con IA…');
  try {
    const r = await fetch('/api/premium/generate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({raw_text}),
    });
    const d = await r.json();
    if (!r.ok || !d.package) {
      const detail = d.error || _fmtErrList(d.errors) || 'No se pudo generar la estructura';
      setStatus('st_premium_generate', `✗ ${detail}`, 'err');
      return;
    }
    _premiumPackage = d.package;
    setVal('premium_import_text', d.generated_json || '');
    renderPremiumEditor();
    const generatedWithErrors = d.errors && d.errors.length;
    document.getElementById('pbadge1').textContent = generatedWithErrors ? '!' : '✓';
    document.getElementById('pbadge1').classList.toggle('done', !generatedWithErrors);
    setStatus(
      'st_premium_generate',
      generatedWithErrors
        ? `✗ La estructura requiere correcciones: ${_fmtErrList(d.errors)}`
        : d.warnings && d.warnings.length
        ? `✓ Estructura generada con avisos: ${_fmtErrList(d.warnings)}`
        : '✓ Estructura generada. Revisala antes de publicar.',
      generatedWithErrors ? 'err' : (d.warnings && d.warnings.length ? 'warn' : 'ok'),
    );
    loadPremiumDraftList();
  } catch (e) {
    setStatus('st_premium_generate', `✗ ${e.message}`, 'err');
  } finally {
    button.disabled = false;
  }
}

async function importPremiumPackage() {
  const raw_text = val('premium_import_text');
  if (!raw_text.trim()) {
    setStatus('st_premium_import', 'Pegá un JSON primero.', 'err');
    return;
  }
  try {
    const r = await fetch('/api/premium/import', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({raw_text}),
    });
    const d = await r.json();
    if (!r.ok || !d.package) {
      setStatus('st_premium_import', `✗ ${d.error || _fmtErrList(d.errors) || 'JSON inválido'}`, 'err');
      return;
    }
    _premiumPackage = d.package;
    renderPremiumEditor();
    const importedWithErrors = d.errors && d.errors.length;
    document.getElementById('pbadge1').textContent = importedWithErrors ? '!' : '✓';
    document.getElementById('pbadge1').classList.toggle('done', !importedWithErrors);
    setStatus(
      'st_premium_import',
      importedWithErrors
        ? `✗ El paquete requiere correcciones: ${_fmtErrList(d.errors)}`
        : d.warnings && d.warnings.length
        ? `✓ Importado con avisos: ${_fmtErrList(d.warnings)}`
        : '✓ Importado',
      importedWithErrors ? 'err' : (d.warnings && d.warnings.length ? 'warn' : 'ok'),
    );
    loadPremiumDraftList();
  } catch (e) {
    setStatus('st_premium_import', `✗ ${e.message}`, 'err');
  }
}

function renderPremiumEditor() {
  if (!_premiumPackage) return;
  setVal('premium_title', _premiumPackage.title);
  setVal('premium_caption', _premiumPackage.caption);
  setVal('premium_section', _premiumPackage.section);
  document.getElementById('premium_template').value = _premiumPackage.template || 'lvr_cronica';
  setVal('premium_highlights', (_premiumPackage.highlight_terms || []).join(', '));
  const dest = _premiumPackage.destination || [];
  document.getElementById('premium_dest_ig').checked = dest.includes('instagram');
  document.getElementById('premium_dest_fb').checked = dest.includes('facebook');
  document.getElementById('pbadge2').textContent = '✓';
  document.getElementById('pbadge2').classList.add('done');
  renderPremiumSlides();
}

function _premiumButton(label, handler, className='secondary') {
  const button = document.createElement('button');
  button.className = className;
  button.textContent = label;
  button.addEventListener('click', handler);
  return button;
}

function _premiumSlideAcceptsImage(slide) {
  return Boolean(slide && PREMIUM_IMAGE_SLIDE_TYPES.has(slide.type));
}

function _premiumGallerySlide() {
  return ((_premiumPackage && _premiumPackage.slides) || []).find(
    slide => slide.id === _premiumGallerySlideId,
  );
}

function openPremiumGallery(slideId) {
  const slide = ((_premiumPackage && _premiumPackage.slides) || []).find(item => item.id === slideId);
  if (!_premiumSlideAcceptsImage(slide)) return;
  _premiumGallerySlideId = slide.id;
  document.getElementById('premium_gallery_target').textContent =
    `Slide #${_premiumPackage.slides.indexOf(slide) + 1} · ${slide.type}`;
  setVal('premium_library_query', slide.asset_hint || slide.title || val('premium_section') || '');
  setVal('premium_gallery_url', '');
  document.getElementById('premium_library_results').textContent = '';
  document.getElementById('premium_gallery_modal').classList.remove('hidden');
  document.body.classList.add('premium-gallery-open');
  setStatus('st_premium_gallery', 'Cargando imágenes…');
  searchPremiumLibrary();
}

function closePremiumGallery(event) {
  const modal = document.getElementById('premium_gallery_modal');
  if (event && event.target !== modal) return;
  modal.classList.add('hidden');
  document.body.classList.remove('premium-gallery-open');
  _premiumGallerySlideId = '';
}

async function _assignPremiumAsset(slide, payload, label) {
  if (!_premiumSlideAcceptsImage(slide) || !payload || !payload.asset_id) {
    setStatus('st_premium_gallery', 'No se pudo asignar la imagen a este tipo de slide.', 'err');
    return false;
  }
  slide.asset_id = payload.asset_id;
  slide.asset_label = label || payload.titulo || payload.asset_id;
  renderPremiumSlides();
  const saved = await savePremiumDraft({quiet: true});
  if (!saved) return false;
  document.getElementById('pbadge3').textContent = '✓';
  document.getElementById('pbadge3').classList.add('done');
  setStatus('st_premium_assets', `✓ Imagen aplicada y guardada en el slide: ${slide.asset_label}`, 'ok');
  closePremiumGallery();
  return true;
}

async function assignPremiumAssetFromUrl(slide, imageUrl) {
  if (!imageUrl.trim()) {
    setStatus('st_premium_gallery', 'Pegá un link de imagen primero.', 'err');
    return;
  }
  setStatus('st_premium_gallery', '⏳ Descargando y validando la imagen…');
  try {
    const r = await fetch('/api/premium/asset-from-url', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        url: imageUrl,
        titulo: val('premium_title'),
        seccion: val('premium_section'),
      }),
    });
    const d = await r.json();
    if (!r.ok || !d.asset_id) throw new Error(d.error || 'No se pudo ingresar la imagen');
    await _assignPremiumAsset(slide, d, d.titulo || 'link externo');
  } catch (e) {
    setStatus('st_premium_gallery', `✗ ${e.message}`, 'err');
  }
}

async function uploadPremiumSlideAsset(slide, file) {
  if (!file) return;
  setStatus('st_premium_gallery', `⏳ Subiendo ${file.name}…`);
  try {
    const form = new FormData();
    form.append('file', file);
    form.append('kind', 'image');
    const uploadResponse = await fetch('/api/upload', {method: 'POST', body: form});
    const upload = await uploadResponse.json();
    if (!uploadResponse.ok || !upload.ok) {
      throw new Error(upload.error || 'No se pudo subir la imagen');
    }
    const promoteResponse = await fetch('/api/premium/asset-from-upload', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        stored_name: upload.stored_name,
        upload_url: upload.url,
        titulo: val('premium_title'),
        seccion: val('premium_section'),
      }),
    });
    const promoted = await promoteResponse.json();
    if (!promoteResponse.ok || !promoted.asset_id) {
      throw new Error(promoted.error || 'No se pudo agregar la imagen a mi galería');
    }
    await _assignPremiumAsset(slide, promoted, file.name);
  } catch (e) {
    setStatus('st_premium_gallery', `✗ ${e.message}`, 'err');
  }
}

function assignPremiumGalleryUrl() {
  const slide = _premiumGallerySlide();
  if (!slide) return;
  assignPremiumAssetFromUrl(slide, val('premium_gallery_url'));
}

function uploadPremiumGalleryFile(file) {
  const slide = _premiumGallerySlide();
  if (!slide || !file) return;
  uploadPremiumSlideAsset(slide, file);
}

function _setupPremiumGalleryDropzone() {
  const zone = document.getElementById('premium_gallery_dropzone');
  const input = document.getElementById('premium_gallery_file');
  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => {
    uploadPremiumGalleryFile(input.files[0]);
    input.value = '';
  });
  zone.addEventListener('dragover', event => {
    event.preventDefault();
    zone.classList.add('dragover');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', event => {
    event.preventDefault();
    zone.classList.remove('dragover');
    uploadPremiumGalleryFile(event.dataTransfer.files[0]);
  });
}

function renderPremiumSlides() {
  const editorList = document.getElementById('premium_slides_list');
  const assetList = document.getElementById('premium_asset_slides_list');
  editorList.textContent = '';
  assetList.textContent = '';
  const slides = (_premiumPackage && _premiumPackage.slides) || [];
  slides.forEach((slide, index) => {
    const row = document.createElement('div');
    row.className = 'item premium-slide-card';

    const header = document.createElement('b');
    header.textContent = `#${index + 1} — ${PREMIUM_SLIDE_LABELS[slide.type] || slide.type}`;
    row.appendChild(header);

    const typeSelect = document.createElement('select');
    const usedTypes = new Set(slides.filter(other => other.id !== slide.id).map(other => other.type));
    PREMIUM_SLIDE_TYPES.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t; opt.textContent = PREMIUM_SLIDE_LABELS[t] || t;
      if (t === slide.type) opt.selected = true;
      if (t !== slide.type && usedTypes.has(t)) opt.disabled = true;
      typeSelect.appendChild(opt);
    });
    typeSelect.addEventListener('change', () => {
      const nextType = typeSelect.value;
      if (slides.some(other => other.id !== slide.id && other.type === nextType)) {
        alert(`El tipo ${nextType} ya está usado en otro slide.`);
        typeSelect.value = slide.type;
        return;
      }
      slide.type = nextType;
      if (!_premiumSlideAcceptsImage(slide)) {
        slide.asset_id = '';
        delete slide.asset_label;
      }
      renderPremiumSlides();
    });
    row.appendChild(typeSelect);

    const titleInput = document.createElement('input');
    titleInput.value = slide.title || '';
    titleInput.placeholder = 'Título opcional del slide';
    titleInput.addEventListener('input', () => { slide.title = titleInput.value; });
    row.appendChild(titleInput);

    const textArea = document.createElement('textarea');
    textArea.rows = 2;
    textArea.value = slide.text || '';
    textArea.placeholder = 'Texto del slide';
    textArea.addEventListener('input', () => { slide.text = textArea.value; });
    row.appendChild(textArea);

    const itemsArea = document.createElement('textarea');
    itemsArea.rows = 2;
    itemsArea.value = (slide.items || []).join('\n');
    itemsArea.placeholder = 'Ítems, uno por línea (opcional)';
    itemsArea.addEventListener('input', () => {
      slide.items = itemsArea.value.split('\n').map(item => item.trim()).filter(Boolean);
    });
    row.appendChild(itemsArea);

    const highlightsInput = document.createElement('input');
    highlightsInput.value = (slide.highlights || []).join(', ');
    highlightsInput.placeholder = 'Palabras destacadas, separadas por coma';
    highlightsInput.addEventListener('input', () => {
      slide.highlights = highlightsInput.value.split(',').map(item => item.trim()).filter(Boolean);
    });
    row.appendChild(highlightsInput);

    const btnRow = document.createElement('div');
    btnRow.className = 'actions';
    btnRow.appendChild(_premiumButton('↑', () => { moveSlide(slide.id, -1); }));
    btnRow.appendChild(_premiumButton('↓', () => { moveSlide(slide.id, 1); }));
    btnRow.appendChild(_premiumButton('Eliminar', () => { removeSlideUI(slide.id); }));
    row.appendChild(btnRow);
    editorList.appendChild(row);

    // Sólo cover, image_text y full_image usan fotografía. El resto de los
    // tipos no muestra controles de imagen ni conserva una asignación vieja.
    if (!_premiumSlideAcceptsImage(slide)) return;

    const assetCard = document.createElement('div');
    assetCard.className = 'item premium-asset-card';

    const assetHeader = document.createElement('b');
    assetHeader.textContent = `#${index + 1} — ${slide.type}`;
    assetCard.appendChild(assetHeader);

    const summary = document.createElement('div');
    summary.className = 'premium-asset-summary';
    if (slide.asset_id) {
      const preview = document.createElement('img');
      preview.className = 'premium-asset-thumb';
      preview.src = `/api/media-library/thumb/${encodeURIComponent(slide.asset_id)}`;
      preview.alt = `Imagen del slide ${index + 1}`;
      preview.addEventListener('error', () => {
        const fallback = document.createElement('div');
        fallback.className = 'premium-asset-placeholder';
        fallback.textContent = 'Miniatura no disponible';
        preview.replaceWith(fallback);
      });
      summary.appendChild(preview);
    } else {
      const placeholder = document.createElement('div');
      placeholder.className = 'premium-asset-placeholder';
      placeholder.textContent = 'Sin imagen';
      summary.appendChild(placeholder);
    }

    const assetLabel = document.createElement('small');
    assetLabel.className = 'asset-current';
    assetLabel.textContent = slide.asset_id
      ? `Imagen asignada: ${slide.asset_label || slide.asset_id}`
      : 'Elegí una imagen para completar este slide.';
    summary.appendChild(assetLabel);
    assetCard.appendChild(summary);

    const assetActions = document.createElement('div');
    assetActions.className = 'actions';
    assetActions.appendChild(
      _premiumButton(slide.asset_id ? 'Cambiar imagen' : 'Abrir galería', () => openPremiumGallery(slide.id)),
    );
    if (slide.asset_id) {
      assetActions.appendChild(_premiumButton('Quitar', async () => {
        slide.asset_id = '';
        delete slide.asset_label;
        renderPremiumSlides();
        await savePremiumDraft({quiet: true});
        setStatus('st_premium_assets', `Imagen quitada del slide #${index + 1}.`, 'ok');
      }, 'ghost'));
    }
    assetCard.appendChild(assetActions);
    assetList.appendChild(assetCard);
  });
}

function _ensurePackage() {
  if (!_premiumPackage) {
    _premiumPackage = {
      schema_version: 1, workflow: 'manual_premium', status: 'draft',
      destination: ['instagram', 'facebook'], publish_mode: 'direct_media',
      template: 'lvr_cronica', title: '', caption: '', section: '',
      highlight_terms: [], source_item_ids: [], slides: [], sources: [],
    };
  }
}

function addPremiumSlide(preferredType) {
  _ensurePackage();
  const usedTypes = new Set((_premiumPackage.slides || []).map(slide => slide.type));
  const availableTypes = PREMIUM_SLIDE_TYPES.filter(type => !usedTypes.has(type));
  if (!availableTypes.length) {
    alert('Ya usaste todos los tipos de slide disponibles.');
    return;
  }
  const type = availableTypes.includes(preferredType) ? preferredType : availableTypes[0];
  _premiumPackage.slides.push({
    id: 'tmp_' + Math.random().toString(16).slice(2),
    type, text: '', title: '', items: [], highlights: [], asset_id: '', source_ids: [],
  });
  renderPremiumSlides();
}

function moveSlide(id, dir) {
  const slides = _premiumPackage.slides;
  const i = slides.findIndex(s => s.id === id);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= slides.length) return;
  [slides[i], slides[j]] = [slides[j], slides[i]];
  renderPremiumSlides();
}

function duplicateSlideUI(id) {
  alert('No se puede duplicar un slide: cada tipo puede aparecer una sola vez.');
}

function removeSlideUI(id) {
  if (_premiumPackage.slides.length <= 2) { alert('El mínimo es 2 slides'); return; }
  _premiumPackage.slides = _premiumPackage.slides.filter(s => s.id !== id);
  renderPremiumSlides();
}

function _syncPremiumPackageFromEditor() {
  _ensurePackage();
  _premiumPackage.title = val('premium_title');
  _premiumPackage.caption = val('premium_caption');
  _premiumPackage.section = val('premium_section');
  _premiumPackage.template = document.getElementById('premium_template').value;
  _premiumPackage.highlight_terms = val('premium_highlights').split(',').map(s => s.trim()).filter(Boolean);
  _premiumPackage.destination = [
    document.getElementById('premium_dest_ig').checked ? 'instagram' : null,
    document.getElementById('premium_dest_fb').checked ? 'facebook' : null,
  ].filter(Boolean);
  (_premiumPackage.slides || []).forEach(slide => {
    if (!_premiumSlideAcceptsImage(slide)) {
      slide.asset_id = '';
      delete slide.asset_label;
    }
  });
}

async function savePremiumDraft({quiet = false} = {}) {
  _syncPremiumPackageFromEditor();

  try {
    const r = await fetch('/api/premium/draft', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({package: _premiumPackage}),
    });
    const d = await r.json();
    if (!r.ok || !d.package) {
      throw new Error(d.error || _fmtErrList(d.errors) || 'No se pudo guardar el borrador');
    }
    _premiumPackage = d.package;
    const saved = !(d.errors && d.errors.length);
    document.getElementById('pbadge4').classList.toggle('done', saved);
    if (!quiet) {
      setStatus(
        'st_premium_draft',
        d.errors && d.errors.length ? `✗ ${_fmtErrList(d.errors)}` : '✓ Borrador guardado',
        d.errors && d.errors.length ? 'err' : 'ok',
      );
    }
    loadPremiumDraftList();
    return true;
  } catch (e) {
    setStatus('st_premium_draft', `✗ ${e.message}`, 'err');
    return false;
  }
}

async function previewPremium() {
  if (!_premiumPackage || !_premiumPackage.id) { alert('Guardá el borrador primero'); return; }
  try {
    const saved = await savePremiumDraft({quiet: true});
    if (!saved) throw new Error('No se pudo sincronizar el borrador antes del preview');
    const r = await fetch('/api/premium/preview', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: _premiumPackage.id}),
    });
    const d = await r.json();
    if (!r.ok) {
      throw new Error(d.error || _fmtErrList(d.errors) || 'No se pudo generar el preview');
    }
    const grid = document.getElementById('premium_preview_grid');
    grid.textContent = '';
    (d.images || []).forEach(b64 => {
      const img = document.createElement('img');
      img.src = 'data:image/jpeg;base64,' + b64;
      img.style.maxWidth = '260px';
      img.style.borderRadius = '8px';
      grid.appendChild(img);
    });
    setStatus('st_premium_publish', _fmtErrList(d.warnings) || '✓ Preview generado', d.warnings?.length ? 'warn' : 'ok');
  } catch (e) {
    setStatus('st_premium_publish', `✗ ${e.message}`, 'err');
  }
}

async function publishPremium() {
  if (!_premiumPackage || !_premiumPackage.id) { alert('Guardá el borrador primero'); return; }
  setStatus('st_premium_publish', 'Publicando…', '');
  try {
    const saved = await savePremiumDraft({quiet: true});
    if (!saved) throw new Error('No se pudo sincronizar el borrador antes de publicar');
    const r = await fetch('/api/premium/publish', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: _premiumPackage.id}),
    });
    const d = await r.json();
    if (!d.ok) { setStatus('st_premium_publish', `✗ ${d.error || 'error'}`, 'err'); return; }
    pollPremiumJob(d.job_id);
  } catch (e) {
    setStatus('st_premium_publish', `✗ ${e.message}`, 'err');
  }
}

function _premiumChannelSummary(channel, result) {
  if (result && result.ok) return `${channel}: OK`;
  const errorType = (result && result.error_type) || 'fallo';
  const metadata = (result && result.failure_metadata) || {};
  const providerCode = metadata.provider_code || '';
  const providerSubcode = metadata.provider_subcode || '';
  const httpStatus = metadata.http_status || (result && result.error_code) || '';
  const code = providerCode
    ? `Meta ${providerCode}${providerSubcode ? '/' + providerSubcode : ''}`
    : (httpStatus ? `HTTP ${httpStatus}` : '');
  const stageLabels = {
    carousel_child_create: 'creación de placa',
    carousel_child_processing: 'procesamiento de placa',
    carousel_parent_create: 'armado del carrusel',
    carousel_parent_processing: 'procesamiento del carrusel',
    carousel_publish: 'publicación final',
  };
  const stage = stageLabels[metadata.stage] || '';
  const detail = [code, stage].filter(Boolean).join(' · ');
  return `${channel}: ${errorType}${detail ? ' (' + detail + ')' : ''}`;
}

async function pollPremiumJob(jobId) {
  try {
    const r = await fetch(`/api/premium/publish-status/${jobId}`);
    const job = await r.json();
    if (!job.done) { setTimeout(() => pollPremiumJob(jobId), 1500); return; }
    if (job.error) { setStatus('st_premium_publish', `✗ ${job.error}`, 'err'); return; }
    const results = (job.result && job.result.channel_results) || {};
    const parts = Object.entries(results).map(([ch, res]) => _premiumChannelSummary(ch, res));
    setStatus('st_premium_publish', `Estado: ${job.status} — ${parts.join(' · ')}`, job.status === 'published' ? 'ok' : 'warn');
    loadPremiumDraftList();
  } catch (e) {
    setStatus('st_premium_publish', `✗ ${e.message}`, 'err');
  }
}

async function searchPremiumLibrary() {
  const query = val('premium_library_query');
  setStatus('st_premium_gallery', '⏳ Buscando en la biblioteca…');
  try {
    const r = await fetch(`/api/media-library?query=${encodeURIComponent(query)}`);
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'No se pudo buscar en la biblioteca');
    const container = document.getElementById('premium_library_results');
    container.textContent = '';
    const rows = (d.rows || []).filter(row =>
      row.thumbnail && (row.asset_id || /^https?:\/\//i.test(String(row.thumbnail))),
    ).slice(0, 12);
    rows.forEach(row => {
      const tile = document.createElement('div');
      tile.className = 'premium-gallery-tile';
      tile.tabIndex = 0;
      tile.setAttribute('role', 'button');
      const thumbnail = document.createElement('img');
      thumbnail.className = 'premium-library-thumb';
      thumbnail.src = row.thumbnail;
      thumbnail.alt = row.titulo || 'Imagen de la biblioteca';
      thumbnail.addEventListener('error', () => {
        const fallback = document.createElement('div');
        fallback.className = 'premium-thumb-fallback';
        fallback.textContent = 'No se pudo cargar esta miniatura';
        thumbnail.replaceWith(fallback);
      });
      tile.appendChild(thumbnail);
      const title = document.createElement('b');
      title.textContent = row.titulo || '(sin título)';
      tile.appendChild(title);
      const meta = document.createElement('small');
      meta.textContent = `${row.resource_type} · ${row.estado || ''} · usado ${row.used_count || 0}x`;
      tile.appendChild(meta);
      const selectRow = async () => {
        if (tile.classList.contains('loading')) return;
        const slide = _premiumGallerySlide();
        if (!slide) return;
        tile.classList.add('loading');
        setStatus('st_premium_gallery', '⏳ Aplicando imagen…');
        try {
          let selected = row;
          if (!row.asset_id) {
            const ingestResponse = await fetch('/api/premium/asset-from-url', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({
                url: row.thumbnail,
                titulo: row.titulo,
                seccion: row.seccion,
              }),
            });
            selected = await ingestResponse.json();
            if (!ingestResponse.ok || !selected.asset_id) {
              throw new Error(selected.error || 'No se pudo agregar la imagen');
            }
          }
          await _assignPremiumAsset(
            slide,
            selected,
            row.titulo || selected.titulo || selected.asset_id,
          );
        } catch (e) {
          tile.classList.remove('loading');
          setStatus('st_premium_gallery', `✗ ${e.message}`, 'err');
        }
      };
      tile.addEventListener('click', selectRow);
      tile.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          selectRow();
        }
      });
      container.appendChild(tile);
    });
    setStatus(
      'st_premium_gallery',
      rows.length ? `${rows.length} imagen(es). Hacé click para aplicarla.` : 'No se encontraron imágenes con miniatura.',
      rows.length ? '' : 'warn',
    );
  } catch (e) {
    setStatus('st_premium_gallery', `✗ ${e.message}`, 'err');
  }
}

async function loadPremiumDraftList() {
  try {
    const r = await fetch('/api/premium/packages');
    const d = await r.json();
    const container = document.getElementById('premiumDraftList');
    container.textContent = '';
    (d.packages || []).forEach(pkg => {
      const item = document.createElement('div');
      item.className = 'item';
      const title = document.createElement('b');
      title.textContent = pkg.title || '(sin título)';
      item.appendChild(title);
      const meta = document.createElement('small');
      meta.textContent = `${pkg.status} · ${(pkg.slides || []).length} slides`;
      item.appendChild(meta);
      const btn = document.createElement('button');
      btn.className = 'secondary';
      btn.textContent = 'Cargar';
      btn.addEventListener('click', () => { _premiumPackage = pkg; renderPremiumEditor(); });
      item.appendChild(btn);
      container.appendChild(item);
    });
  } catch (e) {
    // lista vacía si falla
  }
}

_setupPremiumGalleryDropzone();
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !document.getElementById('premium_gallery_modal').classList.contains('hidden')) {
    closePremiumGallery();
  }
});

// ══ Candidatas ═══════════════════════════════════════════════
function setCandidatesStatus(message, type='') {
  const status = document.getElementById('st_candidates');
  if (!status) return;
  status.textContent = message;
  status.className = 'candidates-count' + (type ? ' ' + type : '');
}

function candidateReasonLabel(reason) {
  const value = String(reason || '').toLowerCase();
  if (value.includes('gate:no_riojan_link')) return 'Sin vínculo riojano';
  if (value.includes('topic_cap_exceeded')) return 'Límite del tema';
  if (value.includes('operator')) return 'Decisión manual';
  return 'Criterio editorial';
}

function candidateOriginLabel(origin) {
  const labels = {
    routed: 'Router editorial',
    operator_demotion: 'Movida manualmente',
    published_reuse: 'Publicación reutilizada',
  };
  return labels[origin] || 'Candidata';
}

function candidateDateLabel(candidate) {
  const timestamp = Number(candidate.updated_at_ts || candidate.created_at_ts || 0);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return '';
  try {
    return new Intl.DateTimeFormat('es-AR', {
      dateStyle: 'short',
      timeStyle: 'short',
    }).format(new Date(timestamp * 1000));
  } catch (_) {
    return '';
  }
}

function appendCandidateMeta(container, label, value) {
  if (!value) return;
  const row = document.createElement('div');
  row.className = 'candidate-meta-row';
  const key = document.createElement('span');
  key.className = 'candidate-meta-label';
  key.textContent = label;
  const detail = document.createElement('span');
  detail.className = 'candidate-meta-value';
  detail.textContent = String(value);
  detail.title = String(value);
  row.appendChild(key);
  row.appendChild(detail);
  container.appendChild(row);
}

function renderCandidateEmpty(
  container,
  titleText='No hay candidatas pendientes',
  detailText='Las noticias que el router o el operador aparten de Instagram van a aparecer acá.',
) {
  const empty = document.createElement('div');
  empty.className = 'candidate-empty';
  const title = document.createElement('b');
  title.textContent = titleText;
  const detail = document.createElement('span');
  detail.textContent = detailText;
  empty.appendChild(title);
  empty.appendChild(detail);
  container.appendChild(empty);
}

async function loadCandidates() {
  const container = document.getElementById('candidates_list');
  const refresh = document.getElementById('candidates_refresh_btn');
  container.replaceChildren();
  setCandidatesStatus('Cargando…');
  if (refresh) refresh.disabled = true;
  try {
    const r = await fetch('/api/editorial/candidates?status=candidate');
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'No se pudieron cargar las candidatas');
    const candidates = Array.isArray(d.candidates) ? d.candidates.slice() : [];
    candidates.sort((a, b) =>
      Number(b.updated_at_ts || b.created_at_ts || 0) - Number(a.updated_at_ts || a.created_at_ts || 0)
    );

    if (!candidates.length) renderCandidateEmpty(container);

    candidates.forEach(c => {
      const item = document.createElement('article');
      item.className = 'candidate-card';

      const head = document.createElement('div');
      head.className = 'candidate-card-head';
      const section = document.createElement('span');
      section.className = 'candidate-chip';
      section.textContent = c.seccion || 'sin sección';
      const reasonChip = document.createElement('span');
      reasonChip.className = 'candidate-chip reason';
      reasonChip.textContent = candidateReasonLabel(c.route_reason);
      head.appendChild(section);
      head.appendChild(reasonChip);
      item.appendChild(head);

      const title = document.createElement('h4');
      title.textContent = c.titulo || '(sin título)';
      item.appendChild(title);

      const reason = document.createElement('p');
      reason.className = 'candidate-reason';
      reason.textContent = c.route_reason || 'Sin motivo registrado';
      item.appendChild(reason);

      const meta = document.createElement('div');
      meta.className = 'candidate-meta';
      appendCandidateMeta(meta, 'Origen:', candidateOriginLabel(c.origin));
      appendCandidateMeta(meta, 'Fecha:', candidateDateLabel(c));
      appendCandidateMeta(meta, 'Tema:', c.topic_key);
      appendCandidateMeta(meta, 'Identidad:', c.identity);
      item.appendChild(meta);

      const btnRow = document.createElement('div');
      btnRow.className = 'actions';
      const promote = document.createElement('button');
      promote.className = 'primary';
      promote.textContent = c.origin === 'published_reuse' ? 'Quitar de candidatas' : 'Enviar a automática';
      promote.addEventListener('click', () => setCandidateStatus(c.candidate_id, 'automatic', promote));
      const discard = document.createElement('button');
      discard.className = 'secondary';
      discard.textContent = 'Descartar';
      discard.addEventListener('click', () => setCandidateStatus(c.candidate_id, 'discarded', discard));
      btnRow.appendChild(promote);
      btnRow.appendChild(discard);
      item.appendChild(btnRow);
      container.appendChild(item);
    });
    setCandidatesStatus(`${candidates.length} ${candidates.length === 1 ? 'pendiente' : 'pendientes'}`);
  } catch (e) {
    setCandidatesStatus(`✗ ${e.message}`, 'err');
    renderCandidateEmpty(
      container,
      'No se pudo cargar la bandeja',
      'Revisá el estado local e intentá actualizar nuevamente.',
    );
  } finally {
    if (refresh) refresh.disabled = false;
  }
}

async function demoteAutomaticToCandidate() {
  const identity = val('override_identity');
  const reason = val('override_reason') || 'manual_ui_override';
  if (!identity) { alert('Ingresá la identidad de la noticia'); return; }
  try {
    const r = await fetch('/api/editorial/candidates/demote', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({identity, reason}),
    });
    const d = await r.json();
    if (!d.ok) { setStatus('st_override', `✗ ${d.error || 'error'}`, 'err'); return; }
    setStatus('st_override', d.changed ? '✓ Movida a candidatas' : 'Ya estaba en candidatas (sin cambios)', 'ok');
    loadCandidates();
  } catch (e) {
    setStatus('st_override', `✗ ${e.message}`, 'err');
  }
}

async function addPublishedToCandidates() {
  const identity = val('override_identity');
  const reason = val('override_reason') || 'reutilizar en carrusel premium';
  if (!identity) { alert('Ingresá la identidad de la noticia'); return; }
  try {
    const r = await fetch('/api/editorial/candidates/add-published', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({identity, reason}),
    });
    const d = await r.json();
    if (!d.ok) { setStatus('st_override', `✗ ${d.error || 'error'}`, 'err'); return; }
    setStatus('st_override', d.changed ? '✓ Agregada a candidatas premium (publicación histórica intacta)' : 'Ya estaba agregada', 'ok');
    loadCandidates();
  } catch (e) {
    setStatus('st_override', `✗ ${e.message}`, 'err');
  }
}

async function setCandidateStatus(candidateId, status, button=null) {
  if (status === 'automatic' && !window.confirm(
    'Esta noticia quedará habilitada para publicarse automáticamente en Instagram, aunque su categoría no esté en la selección habitual o todavía no tenga URL Web. ¿Continuar?'
  )) return;
  if (button) button.disabled = true;
  setCandidatesStatus('Actualizando…');
  setStatus('st_candidates_action', '⏳ Guardando la decisión editorial…');
  try {
    const r = await fetch('/api/editorial/candidates/status', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({candidate_id: candidateId, status}),
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || 'No se pudo actualizar la candidata');
    await loadCandidates();
    setStatus(
      'st_candidates_action',
      status === 'automatic'
        ? '✓ Habilitada para publicación automática. Entrará en la cola de Instagram en el próximo ciclo.'
        : '✓ Candidata descartada por decisión editorial.',
      'ok',
    );
  } catch (e) {
    setCandidatesStatus(`✗ ${e.message}`, 'err');
    setStatus('st_candidates_action', `✗ ${e.message}`, 'err');
    if (button) button.disabled = false;
  }
}
</script>
</body>
</html>"""


# ── Upload de archivos (drag&drop / seleccionar archivo) ───────

def _parse_multipart(content_type: str, body: bytes) -> dict:
    """Parser minimo de multipart/form-data (sin dependencias externas).

    Devuelve {nombre_campo: valor}, donde los campos de archivo quedan como
    tuple (bytes, filename, content_type) y los campos de texto como str.
    """
    if "boundary=" not in content_type:
        return {}
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"')
    delimiter = ("--" + boundary).encode()
    result: dict = {}

    for part in body.split(delimiter):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, _, content = part.partition(b"\r\n\r\n")
        if content.endswith(b"\r\n"):
            content = content[:-2]

        name = ""
        filename = ""
        file_content_type = "application/octet-stream"
        for line in raw_headers.decode("utf-8", errors="ignore").split("\r\n"):
            lower = line.lower()
            if lower.startswith("content-disposition"):
                for piece in line.split(";"):
                    piece = piece.strip()
                    if piece.startswith("name="):
                        name = piece.split("=", 1)[1].strip('"')
                    elif piece.startswith("filename="):
                        filename = piece.split("=", 1)[1].strip('"')
            elif lower.startswith("content-type"):
                file_content_type = line.split(":", 1)[1].strip()

        if not name:
            continue
        if filename:
            result[name] = (content, filename, file_content_type)
        else:
            result[name] = content.decode("utf-8", errors="ignore")

    return result


# ── Publicación en background ─────────────────────────────────

def _publish_background(job_id: str, video_path: str, item: dict) -> None:
    job = _publish_jobs[job_id]

    def log(msg: str) -> None:
        job["messages"].append(msg)
        logger.info("[publish %s] %s", job_id[:8], msg)

    try:
        from utils import r2_storage

        if not r2_storage.is_configured():
            job["status"] = "failed"
            job["error"] = "R2 no configurado (faltan variables R2_* en .env)"
            job["done"] = True
            return

        # 1. Subir video a R2
        log("Subiendo video a R2…")
        import uuid
        r2_key = f"tmp/reels/{uuid.uuid4().hex[:12]}.mp4"
        public_url, r2_key = r2_storage.upload_file(
            video_path, r2_key, "video/mp4",
            cache_control="max-age=86400",
        )
        item["video_url"] = public_url
        log(f"Video subido: {public_url[:60]}…")

        # 2. Publicar en Instagram
        log("Publicando en Instagram (puede tardar hasta 5 min)…")
        try:
            from meta.ig_client import post_to_instagram_detailed
            ig_result = post_to_instagram_detailed(item)
            job["ig_ok"] = ig_result.ok
            job["instagram_result"] = ig_result.to_dict()
            log("✓ Instagram OK" if ig_result.ok else "✗ Instagram falló")
        except Exception as exc:
            job["ig_ok"] = False
            job["instagram_result"] = {
                "status": "failed",
                "error_type": type(exc).__name__,
            }
            log(f"✗ Instagram: {exc}")

        # 3. Publicar en Facebook
        log("Publicando en Facebook…")
        try:
            from meta.fb_client import post_to_facebook_detailed
            fb_result = post_to_facebook_detailed(item)
            job["fb_ok"] = fb_result.ok
            job["facebook_result"] = fb_result.to_dict()
            log("✓ Facebook OK" if fb_result.ok else "✗ Facebook falló")
        except Exception as exc:
            job["fb_ok"] = False
            job["facebook_result"] = {
                "status": "failed",
                "error_type": type(exc).__name__,
            }
            log(f"✗ Facebook: {exc}")

        if job["ig_ok"] and job["fb_ok"]:
            job["status"] = "success"
        elif job["ig_ok"] or job["fb_ok"]:
            job["status"] = "degraded"
            job["error_type"] = "partial_external_publication"
        else:
            job["status"] = "failed"
            job["error_type"] = "all_social_channels_failed"

        # 4. Limpiar R2 si ninguno publicó correctamente
        if not job["ig_ok"] and not job["fb_ok"]:
            cleanup = r2_storage.delete(r2_key)
            if cleanup.ok:
                log("Video eliminado de R2 (publicación fallida).")
            else:
                job["cleanup_error"] = cleanup.error_type or "r2_delete_error"
                log(f"No se pudo eliminar el video temporal de R2: {job['cleanup_error']}")

        job["done"] = True

    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        job["done"] = True
        logger.exception("Error en publish_background job %s", job_id[:8])


def _custom_publish_background(job_id: str, item: dict) -> None:
    job = _custom_jobs[job_id]

    def log(msg: str) -> None:
        job["messages"].append(msg)
        logger.info("[custom-publish %s] %s", job_id[:8], msg)

    try:
        from pipeline.custom_post import publish_custom_post
        result = publish_custom_post(item, log=log)
        job.update(result)

        if result.get("web_ok"):
            try:
                from utils.manual_post_queue import record_published
                record_published(item, result.get("public_url", ""))
            except Exception:
                job["status"] = "degraded"
                job["history_error"] = "manual_history_write_failed"
                logger.exception("No se pudo registrar la publicacion en el historial")

        job["done"] = True

    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        job["done"] = True
        logger.exception("Error en custom_publish_background job %s", job_id[:8])


# ── HTTP Handler ──────────────────────────────────────────────

class VideoReelHandler(BaseHTTPRequestHandler):

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; "
            "media-src 'self' blob: https:; connect-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 500_000:
            raise ValueError("payload demasiado grande")
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def do_GET(self) -> None:
        try:
            validate_local_request_headers(self.headers.get("Host", ""))
        except ValueError as exc:
            self._json(403, {"error": str(exc)})
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/api/videos":
            self._json(200, load_video_state())
            return

        # ── Estudio Premium (Fase 3) ────────────────────────────
        if path == "/api/premium/packages":
            from utils.premium_post_queue import list_packages

            status = (query.get("status") or [None])[0]
            self._json(200, {"packages": list_packages(status=status)})
            return

        if path == "/api/premium/draft":
            from utils.premium_post_queue import get_package

            package_id = _safe_object_id((query.get("id") or [""])[0])
            if not package_id:
                self._json(400, {"error": "id inválido"})
                return
            package = get_package(package_id)
            if package is None:
                self._json(404, {"error": "paquete no encontrado"})
                return
            self._json(200, {"package": package})
            return

        if path.startswith("/api/premium/publish-status/"):
            job_id = _safe_object_id(path[len("/api/premium/publish-status/"):])
            if not job_id:
                self._json(400, {"error": "job_id inválido"})
                return
            job = _premium_jobs.get(job_id)
            if not job:
                self._json(404, {"error": "job not found"})
                return
            self._json(200, job)
            return

        if path == "/api/editorial/candidates":
            from utils.editorial_router import list_candidates

            status = (query.get("status") or [None])[0]
            self._json(200, {"candidates": list_candidates(channel="instagram", status=status)})
            return

        if path == "/api/media-library":
            from utils.media_library import search_library

            all_time = (query.get("all_time") or ["0"])[0] in {"1", "true"}
            rows = search_library(
                query=(query.get("query") or [None])[0],
                seccion=(query.get("seccion") or [None])[0],
                fuente=(query.get("fuente") or [None])[0],
                topic_key=(query.get("topic_key") or [None])[0],
                only_candidatas=(query.get("candidatas") or ["0"])[0] in {"1", "true"},
                only_publicadas=(query.get("publicadas") or ["0"])[0] in {"1", "true"},
                only_premium=(query.get("premium") or ["0"])[0] in {"1", "true"},
                only_automaticas=(query.get("automaticas") or ["0"])[0] in {"1", "true"},
                window_days=None if all_time else 10,
            )
            self._json(200, {"rows": rows})
            return

        if path.startswith("/api/media-library/thumb/"):
            from utils.media_library import get_asset_thumbnail_path

            asset_id = _safe_object_id(path[len("/api/media-library/thumb/"):])
            if not asset_id:
                self._json(400, {"error": "asset_id inválido"})
                return
            thumbnail_path = get_asset_thumbnail_path(asset_id)
            if not thumbnail_path:
                self._json(404, {"error": "miniatura no encontrada"})
                return
            try:
                with open(thumbnail_path, "rb") as thumbnail_file:
                    data = thumbnail_file.read()
                self._send(200, data, "image/jpeg")
            except OSError:
                self._json(404, {"error": "miniatura no encontrada"})
            return

        # Servir video renderizado: /api/preview/{video_id}.mp4
        if path.startswith("/api/preview/") and path.endswith(".mp4"):
            video_id = _safe_object_id(path[len("/api/preview/"):-4])
            if not video_id:
                self._json(400, {"error": "video_id inválido"})
                return
            video_path = _renders.get(video_id)
            if not video_path:
                # buscar en directorio de renders
                from utils.video_renderer import RENDERS_DIR
                candidate = os.path.join(RENDERS_DIR, f"{video_id}.mp4")
                if os.path.exists(candidate):
                    video_path = candidate
            if not video_path or not os.path.exists(video_path):
                self._json(404, {"error": "video not found"})
                return
            try:
                with open(video_path, "rb") as f:
                    data = f.read()
                self._send(200, data, "video/mp4")
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        # Estado de publicación: /api/publish-status/{job_id}
        if path.startswith("/api/publish-status/"):
            job_id = _safe_object_id(path[len("/api/publish-status/"):])
            if not job_id:
                self._json(400, {"error": "job_id inválido"})
                return
            job = _publish_jobs.get(job_id)
            if not job:
                self._json(404, {"error": "job not found"})
                return
            self._json(200, job)
            return

        # ── Publicaciones personalizadas ───────────────────────
        if path == "/api/custom/posts":
            self._json(200, load_post_state())
            return

        # Servir preview de imagen: /api/custom/preview/{preview_id}.jpg
        if path.startswith("/api/custom/preview/") and path.endswith(".jpg"):
            preview_id = _safe_object_id(path[len("/api/custom/preview/"):-4])
            if not preview_id:
                self._json(400, {"error": "preview_id inválido"})
                return
            data = _custom_previews.get(preview_id)
            if not data:
                self._json(404, {"error": "preview not found"})
                return
            self._send(200, data, "image/jpeg")
            return

        # Estado de publicación: /api/custom/publish-status/{job_id}
        if path.startswith("/api/custom/publish-status/"):
            job_id = _safe_object_id(path[len("/api/custom/publish-status/"):])
            if not job_id:
                self._json(400, {"error": "job_id inválido"})
                return
            job = _custom_jobs.get(job_id)
            if not job:
                self._json(404, {"error": "job not found"})
                return
            self._json(200, job)
            return

        # Servir archivo subido a mano: /api/uploads/{filename}
        if path.startswith("/api/uploads/"):
            filename = path[len("/api/uploads/"):]
            allowed_extensions = "|".join(
                re.escape(ext.lstrip("."))
                for extensions in _UPLOAD_EXTENSIONS.values()
                for ext in sorted(extensions)
            )
            if not re.fullmatch(
                rf"[a-f0-9]{{32}}\.(?:{allowed_extensions})",
                filename,
                re.IGNORECASE,
            ):
                self._json(400, {"error": "nombre invalido"})
                return
            root = os.path.realpath(UPLOADS_DIR)
            file_path = os.path.realpath(os.path.join(root, filename))
            if os.path.dirname(file_path) != root or not os.path.isfile(file_path):
                self._json(404, {"error": "not found"})
                return
            ext = os.path.splitext(filename)[1].lower()
            content_type = _UPLOAD_CONTENT_TYPES.get(ext, "application/octet-stream")
            try:
                with open(file_path, "rb") as f:
                    data = f.read()
                self._send(200, data, content_type)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return

        self._json(404, {"error": "not_found"})

    def _handle_upload(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._json(400, {"error": "se espera multipart/form-data"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 320 * 1024 * 1024:
            self._json(400, {"error": "archivo demasiado grande o vacio (max 300MB)"})
            return

        body = self.rfile.read(length)
        fields = _parse_multipart(content_type, body)
        file_field = fields.get("file")
        if not isinstance(file_field, tuple):
            self._json(400, {"error": "falta el archivo"})
            return

        content, filename, _file_content_type = file_field
        kind = str(fields.get("kind") or "image").strip().lower()
        if kind not in _UPLOAD_EXTENSIONS:
            kind = "image"

        ext = os.path.splitext(filename)[1].lower()
        if ext not in _UPLOAD_EXTENSIONS[kind]:
            self._json(400, {"error": f"extension no permitida para {kind}: {ext or '(sin extension)'}"})
            return
        if len(content) > _UPLOAD_MAX_BYTES[kind]:
            max_mb = _UPLOAD_MAX_BYTES[kind] // (1024 * 1024)
            self._json(400, {"error": f"archivo demasiado grande (max {max_mb}MB)"})
            return
        try:
            validate_upload_content(content, filename, kind)
        except InvalidUploadError as exc:
            self._json(400, {"error": str(exc)})
            return

        os.makedirs(UPLOADS_DIR, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}{ext}"
        dest = os.path.join(UPLOADS_DIR, stored_name)
        tmp_dest = f"{dest}.tmp"
        try:
            with open(tmp_dest, "xb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_dest, dest)
        finally:
            try:
                os.unlink(tmp_dest)
            except FileNotFoundError:
                pass

        server_host, server_port = self.server.server_address[:2]
        public_host = f"[{server_host}]" if ":" in server_host else server_host
        url = f"http://{public_host}:{server_port}/api/uploads/{stored_name}"
        self._json(
            200,
            {
                "ok": True,
                "url": url,
                "filename": filename,
                "stored_name": stored_name,
            },
        )

    def do_POST(self) -> None:
        try:
            validate_local_request_headers(
                self.headers.get("Host", ""),
                self.headers.get("Origin", ""),
            )
        except ValueError as exc:
            self._json(403, {"error": str(exc)})
            return
        path = urlparse(self.path).path

        if path == "/api/upload":
            try:
                self._handle_upload()
            except Exception as exc:
                logger.exception("Error en upload")
                self._json(400, {"error": str(exc)})
            return

        try:
            payload = self._read_body()

            # ── Cola y borradores (existentes) ────────────────
            if path == "/api/queue-video":
                item, added = enqueue_video(payload)
                self._json(200, {"ok": True, "added": added, "item": item})
                return

            if path == "/api/draft-video":
                item, added = save_video_draft(payload)
                self._json(200, {"ok": True, "added": added, "item": item})
                return

            # ── Analizar URL con IA ───────────────────────────
            if path == "/api/analyze-url":
                source_url = str(payload.get("source_url") or "").strip()
                if not source_url:
                    self._json(400, {"error": "source_url requerida"})
                    return
                try:
                    source_url = validate_public_http_url(source_url)
                except UnsafeURLError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                from openIA.reel_generator import analyze_url_for_reel
                data = analyze_url_for_reel(source_url)
                self._json(200, {"ok": True, **data})
                return

            # ── Renderizar video ──────────────────────────────
            if path == "/api/render-video":
                titulo = str(payload.get("titulo_reel") or "").strip()
                if not titulo:
                    self._json(400, {"error": "titulo_reel requerido"})
                    return
                try:
                    payload["source_url"], _source_local = _validated_optional_url(
                        payload.get("source_url")
                    )
                    payload["video_url"], local_video = _validated_optional_url(
                        payload.get("video_url"),
                        kind="video",
                    )
                    payload["imagen_url"], local_image = _validated_optional_url(
                        payload.get("imagen_url"),
                        kind="image",
                    )
                except UnsafeURLError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                if local_video:
                    payload["local_video_path"] = local_video
                if local_image:
                    payload["local_image_path"] = local_image
                from utils.video_renderer import render_video
                video_path, video_id, actual_duration, render_info = render_video(payload)
                _renders[video_id] = video_path
                size_mb = round(os.path.getsize(video_path) / 1_048_576, 1)
                self._json(200, {
                    "ok": True,
                    "video_id": video_id,
                    "preview_url": f"/api/preview/{video_id}.mp4",
                    "size_mb": size_mb,
                    "duration": actual_duration,
                    "source_used": render_info.get("source_used"),
                    "fallback_reason": render_info.get("fallback_reason"),
                })
                return

            # ── Publicar reel ─────────────────────────────────
            if path == "/api/publish-reel":
                video_id = _safe_object_id(str(payload.get("video_id") or "").strip())
                if not video_id:
                    self._json(400, {"error": "video_id inválido"})
                    return
                video_path = _renders.get(video_id)
                if not video_path:
                    from utils.video_renderer import RENDERS_DIR
                    candidate = os.path.join(RENDERS_DIR, f"{video_id}.mp4")
                    if os.path.exists(candidate):
                        video_path = candidate
                if not video_path or not os.path.exists(video_path):
                    self._json(404, {"error": "video no encontrado — re-renderizá primero"})
                    return

                import uuid as _uuid
                job_id = _uuid.uuid4().hex
                try:
                    source_url, _ = _validated_optional_url(payload.get("source_url"))
                    image_url, local_image = _validated_optional_url(
                        payload.get("imagen_url"),
                        kind="image",
                    )
                except UnsafeURLError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                item = {
                    "media_type": "video",
                    "titulo": payload.get("titulo_reel", ""),
                    "titulo_reel": payload.get("titulo_reel", ""),
                    "titulo_instagram": str(payload.get("titulo_reel", ""))[:80],
                    "texto_instagram": payload.get("caption", ""),
                    "caption": payload.get("caption", ""),
                    "seccion": payload.get("seccion", "sociedad"),
                    "share_to_feed": True,
                    "source_video_url": source_url,
                    "url": source_url,
                    "canonical_url": source_url,
                    "imagen_url": image_url,
                    "imagen": local_image,
                    "dedup_key": f"video:{job_id[:16]}",
                }

                _publish_jobs[job_id] = {
                    "status": "processing",
                    "done": False,
                    "ig_ok": False,
                    "fb_ok": False,
                    "messages": [],
                    "error": None,
                }
                t = threading.Thread(
                    target=_publish_background,
                    args=(job_id, video_path, item),
                    daemon=True,
                )
                t.start()
                self._json(200, {"ok": True, "job_id": job_id})
                return

            # ── Publicaciones personalizadas ───────────────────
            if path == "/api/custom/fetch-image":
                source_url = str(payload.get("source_url") or "").strip()
                if not source_url:
                    self._json(400, {"error": "source_url requerida"})
                    return
                try:
                    source_url = validate_public_http_url(source_url)
                except UnsafeURLError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                from pipeline.custom_post import fetch_image_from_url
                data = fetch_image_from_url(source_url)
                self._json(200, data)
                return

            if path == "/api/custom/preview-image":
                from pipeline.custom_post import build_custom_noticia, render_preview_image
                try:
                    item = build_custom_noticia(payload)
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                image_bytes = render_preview_image(item)
                import uuid as _uuid
                preview_id = _uuid.uuid4().hex
                _custom_previews[preview_id] = image_bytes
                self._json(200, {
                    "ok": True,
                    "preview_id": preview_id,
                    "preview_url": f"/api/custom/preview/{preview_id}.jpg",
                })
                return

            if path == "/api/custom/draft":
                item, added = save_post_draft(payload)
                self._json(200, {"ok": True, "added": added, "item": item})
                return

            if path == "/api/custom/publish":
                from pipeline.custom_post import build_custom_noticia
                try:
                    item = build_custom_noticia(payload)
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                    return

                import uuid as _uuid
                job_id = _uuid.uuid4().hex
                _custom_jobs[job_id] = {
                    "status": "processing",
                    "done": False,
                    "web_ok": False,
                    "ig_ok": False,
                    "fb_ok": False,
                    "public_url": "",
                    "messages": [],
                    "error": None,
                }
                t = threading.Thread(
                    target=_custom_publish_background,
                    args=(job_id, item),
                    daemon=True,
                )
                t.start()
                self._json(200, {"ok": True, "job_id": job_id})
                return

            # ── Estudio Premium (Fase 3) ────────────────────────
            if path == "/api/premium/generate":
                from openIA.premium_package_generator import (
                    PremiumGenerationError,
                    generate_premium_package_json,
                    validate_generated_payload,
                )
                from utils.premium_importer import import_chatgpt_package
                from utils.premium_post_queue import save_package

                raw_text = str(payload.get("raw_text") or "")
                if not raw_text.strip():
                    self._json(400, {"error": "raw_text requerido"})
                    return
                try:
                    generated_json = generate_premium_package_json(raw_text)
                except PremiumGenerationError as exc:
                    self._json(422, {"error": str(exc)})
                    return
                editorial_warnings = validate_generated_payload(
                    json.loads(generated_json),
                    raw_text,
                )
                package, errors, warnings = import_chatgpt_package(generated_json)
                warnings = list(warnings or []) + [
                    f"generación IA: {warning}" for warning in editorial_warnings
                ]
                if package is not None:
                    package = save_package(package)
                self._json(
                    200,
                    {
                        "package": package,
                        "errors": errors,
                        "warnings": warnings,
                        "generated_json": generated_json,
                    },
                )
                return

            if path == "/api/premium/asset-from-url":
                from utils.media_library import ingest_image_bytes

                image_url = str(payload.get("url") or "").strip()
                if not image_url:
                    self._json(400, {"error": "url requerida"})
                    return
                try:
                    image_bytes, normalized_url, filename = _download_premium_image(image_url)
                except UnsafeURLError as exc:
                    self._json(400, {"error": str(exc)})
                    return
                except ValueError as exc:
                    self._json(422, {"error": str(exc)})
                    return
                try:
                    asset = ingest_image_bytes(
                        image_bytes,
                        filename=filename,
                        origin="premium_link",
                        source_url=normalized_url,
                        titulo=str(payload.get("titulo") or "").strip() or None,
                        seccion=str(payload.get("seccion") or "").strip() or None,
                        source="manual_premium",
                    )
                except ValueError as exc:
                    self._json(422, {"error": str(exc)})
                    return
                self._json(200, _premium_asset_payload(asset))
                return

            if path == "/api/premium/asset-from-upload":
                from utils.media_library import ingest_image_bytes

                stored_name = str(payload.get("stored_name") or "").strip()
                upload_path = _owned_upload_name_path(stored_name, kind="image")
                if not upload_path:
                    upload_path = _owned_upload_path(
                        str(payload.get("upload_url") or ""),
                        kind="image",
                    )
                if not upload_path:
                    self._json(400, {"error": "archivo subido inválido o inexistente"})
                    return
                try:
                    if os.path.getsize(upload_path) > _PREMIUM_IMAGE_MAX_BYTES:
                        self._json(400, {"error": "archivo demasiado grande (max 20MB)"})
                        return
                    with open(upload_path, "rb") as uploaded_file:
                        image_bytes = uploaded_file.read()
                    asset = ingest_image_bytes(
                        image_bytes,
                        filename=os.path.basename(upload_path),
                        origin="premium_upload",
                        titulo=str(payload.get("titulo") or "").strip() or None,
                        seccion=str(payload.get("seccion") or "").strip() or None,
                        source="manual_premium",
                    )
                except OSError:
                    self._json(404, {"error": "archivo subido no encontrado"})
                    return
                except ValueError as exc:
                    self._json(422, {"error": str(exc)})
                    return
                self._json(200, _premium_asset_payload(asset))
                return

            if path == "/api/premium/import":
                from utils.premium_importer import import_chatgpt_package
                from utils.premium_post_queue import save_package

                raw_text = str(payload.get("raw_text") or "")
                package, errors, warnings = import_chatgpt_package(raw_text)
                if package is not None:
                    package = save_package(package)
                self._json(200, {"package": package, "errors": errors, "warnings": warnings})
                return

            if path == "/api/premium/draft":
                from utils.premium_contract import validate_package
                from utils.premium_post_queue import save_package

                package = payload.get("package")
                if not isinstance(package, dict):
                    self._json(400, {"error": "package requerido"})
                    return
                saved = save_package(package)
                errors, warnings = validate_package(saved)
                self._json(200, {"package": saved, "errors": errors, "warnings": warnings})
                return

            if path == "/api/premium/preview":
                import base64

                from utils.premium_post_queue import get_package
                from utils.premium_renderer import render_package_with_engine
                from utils.remotion_renderer import RemotionRenderError

                package_id = _safe_object_id(str(payload.get("id") or ""))
                if not package_id:
                    self._json(400, {"error": "id inválido"})
                    return
                package = get_package(package_id)
                if package is None:
                    self._json(404, {"error": "paquete no encontrado"})
                    return
                try:
                    images, warnings, engine = render_package_with_engine(package)
                except RemotionRenderError as exc:
                    self._json(409, {"error": str(exc)})
                    return
                self._json(
                    200,
                    {
                        "ok": True,
                        "images": [base64.b64encode(image).decode("ascii") for image in images],
                        "warnings": warnings,
                        "engine": engine,
                    },
                )
                return

            if path == "/api/premium/publish":
                from utils.premium_post_queue import get_package

                package_id = _safe_object_id(str(payload.get("id") or ""))
                if not package_id or get_package(package_id) is None:
                    self._json(404, {"error": "paquete no encontrado"})
                    return
                job_id = uuid.uuid4().hex
                _premium_jobs[job_id] = {"done": False, "status": "processing", "result": None, "error": None}
                t = threading.Thread(
                    target=_premium_publish_background,
                    args=(job_id, package_id),
                    daemon=True,
                )
                t.start()
                self._json(200, {"ok": True, "job_id": job_id})
                return

            if path == "/api/premium/retry":
                from utils.premium_publisher import retry_channel

                package_id = _safe_object_id(str(payload.get("id") or ""))
                channel = str(payload.get("channel") or "")
                if not package_id:
                    self._json(400, {"error": "id inválido"})
                    return
                try:
                    result = retry_channel(package_id, channel)
                except (KeyError, ValueError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(200, result)
                return

            if path == "/api/editorial/candidates/status":
                from utils.editorial_router import update_candidate_status

                candidate_id = str(payload.get("candidate_id") or "")
                new_status = str(payload.get("status") or "")
                try:
                    item = update_candidate_status(candidate_id, new_status, operator="manual_ui")
                except (KeyError, ValueError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(200, {"ok": True, "item": item})
                return

            if path == "/api/editorial/candidates/demote":
                from utils.editorial_router import demote_automatic_to_candidate

                identity = str(payload.get("identity") or "")
                reason = str(payload.get("reason") or "manual_ui_override")
                try:
                    result = demote_automatic_to_candidate(identity, reason=reason, operator="manual_ui")
                except (KeyError, ValueError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(200, {"ok": True, **result})
                return

            if path == "/api/editorial/candidates/add-published":
                from utils.editorial_router import add_published_to_candidates

                identity = str(payload.get("identity") or "")
                reason = str(payload.get("reason") or "reutilizar en carrusel premium")
                try:
                    result = add_published_to_candidates(identity, reason=reason, operator="manual_ui")
                except (KeyError, ValueError) as exc:
                    self._json(400, {"error": str(exc)})
                    return
                self._json(200, {"ok": True, **result})
                return

            self._json(404, {"error": "not_found"})

        except Exception as exc:
            logger.exception("Error en POST %s", path)
            self._json(400, {"error": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        return  # silenciar logs de HTTP en consola


# ── Entry point ───────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Video Reel Manager — La Voz Riojana")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    host = validate_bind_host(args.host)
    server = ThreadingHTTPServer((host, args.port), VideoReelHandler)
    url_host = f"[{host}]" if ":" in host else host
    url = f"http://{url_host}:{args.port}/"
    print(f"\n  Video Reel Manager · La Voz Riojana")
    print(f"  URL: {url}")
    print(f"  Ctrl+C para detener\n")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")


if __name__ == "__main__":
    main()
