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
.premium-asset-card .asset-current{margin:7px 0;color:#9fb0c5}
.premium-asset-card .dropzone{padding:10px}
.premium-library-thumb{width:100%;height:120px;object-fit:cover;border-radius:6px;margin:7px 0;background:#161b24}
.premium-library-thumb.missing{display:none}
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
      <label>Título</label>
      <input id="custom_titulo" maxlength="240" oninput="updateChars('custom_titulo','ctc_titulo',240)">
      <div class="char-count" id="ctc_titulo">0/240</div>
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
      <h3>Asigná una imagen a cada slide</h3>
    </div>
    <p class="premium-help">En cada slide podés pegar un link, subir una imagen propia o usar una imagen seleccionada de la biblioteca.</p>
    <div id="premium_asset_slides_list"></div>
    <div class="field">
      <label>Buscar en la biblioteca</label>
      <input id="premium_library_query" placeholder="incendio, Chilecito...">
    </div>
    <div class="actions"><button class="secondary" onclick="searchPremiumLibrary()">Buscar</button></div>
    <div id="premium_library_results"></div>
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

<div class="app hidden" id="app_candidates">
<main style="width:100%">
  <div class="pipe-block" style="max-width:900px;margin:0 auto">
    <div class="block-title"><h3>Mover noticia por identidad</h3></div>
    <div class="field">
      <label>Identidad (meta_queue_key / dedup_key / canonical_url)</label>
      <input id="override_identity" placeholder="link:abc123...">
    </div>
    <div class="field"><label>Motivo</label><input id="override_reason" placeholder="Nota nacional sin vínculo riojano comprobado"></div>
    <div class="actions">
      <button class="secondary" onclick="demoteAutomaticToCandidate()">Quitar de automático → candidatas</button>
      <button class="secondary" onclick="addPublishedToCandidates()">Añadir a candidatas premium (ya publicada)</button>
    </div>
    <div class="status" id="st_override"></div>
  </div>
  <div class="pipe-block" style="max-width:900px;margin:0 auto">
    <div class="block-title"><h3>Candidatas de Instagram</h3></div>
    <div class="status" id="st_candidates"></div>
    <div id="candidates_list"></div>
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
      if (d.titulo_hint) setVal('custom_titulo', d.titulo_hint);
      return;
    }
    _customSetThumb(d.imagen_url);
    setVal('custom_imagen_manual', d.imagen_url);
    if (d.titulo_hint) setVal('custom_titulo', d.titulo_hint);
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
  updateChars('custom_titulo', 'ctc_titulo', 240);
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
let _selectedAssetId = '';
let _selectedAssetLabel = '';

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

function _assignPremiumAsset(slide, payload, label) {
  slide.asset_id = payload.asset_id;
  slide.asset_label = label || payload.titulo || payload.asset_id;
  renderPremiumSlides();
  document.getElementById('pbadge3').textContent = '✓';
  document.getElementById('pbadge3').classList.add('done');
  setStatus('st_premium_assets', `✓ Imagen asignada al slide: ${slide.asset_label}`, 'ok');
}

async function assignPremiumAssetFromUrl(slide, imageUrl) {
  if (!imageUrl.trim()) {
    setStatus('st_premium_assets', 'Pegá un link de imagen primero.', 'err');
    return;
  }
  setStatus('st_premium_assets', '⏳ Descargando y validando la imagen…');
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
    _assignPremiumAsset(slide, d, 'link externo');
  } catch (e) {
    setStatus('st_premium_assets', `✗ ${e.message}`, 'err');
  }
}

async function uploadPremiumSlideAsset(slide, file) {
  if (!file) return;
  setStatus('st_premium_assets', `⏳ Subiendo ${file.name}…`);
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
    _assignPremiumAsset(slide, promoted, file.name);
  } catch (e) {
    setStatus('st_premium_assets', `✗ ${e.message}`, 'err');
  }
}

function _wirePremiumDropzone(zone, input, slide) {
  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => uploadPremiumSlideAsset(slide, input.files[0]));
  zone.addEventListener('dragover', event => {
    event.preventDefault();
    zone.classList.add('dragover');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', event => {
    event.preventDefault();
    zone.classList.remove('dragover');
    uploadPremiumSlideAsset(slide, event.dataTransfer.files[0]);
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
    header.textContent = `#${index + 1} — ${slide.type}`;
    row.appendChild(header);

    const typeSelect = document.createElement('select');
    ['cover', 'image_text', 'full_image', 'key_points', 'quote', 'number', 'closing'].forEach(t => {
      const opt = document.createElement('option');
      opt.value = t; opt.textContent = t;
      if (t === slide.type) opt.selected = true;
      typeSelect.appendChild(opt);
    });
    typeSelect.addEventListener('change', () => { slide.type = typeSelect.value; renderPremiumSlides(); });
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
    btnRow.appendChild(_premiumButton('Duplicar', () => { duplicateSlideUI(slide.id); }));
    btnRow.appendChild(_premiumButton('Eliminar', () => { removeSlideUI(slide.id); }));
    row.appendChild(btnRow);
    editorList.appendChild(row);

    const assetCard = document.createElement('div');
    assetCard.className = 'item premium-asset-card';

    const assetHeader = document.createElement('b');
    assetHeader.textContent = `#${index + 1} — ${slide.type}`;
    assetCard.appendChild(assetHeader);

    if (slide.asset_id) {
      const preview = document.createElement('img');
      preview.className = 'premium-library-thumb';
      preview.src = `/api/media-library/thumb/${encodeURIComponent(slide.asset_id)}`;
      preview.alt = '';
      preview.addEventListener('error', () => preview.classList.add('missing'));
      assetCard.appendChild(preview);
    }

    const assetLabel = document.createElement('small');
    assetLabel.className = 'asset-current';
    assetLabel.textContent = slide.asset_id
      ? `Imagen asignada: ${slide.asset_label || slide.asset_id}`
      : 'Todavía no tiene imagen asignada';
    assetCard.appendChild(assetLabel);

    const urlInput = document.createElement('input');
    urlInput.type = 'url';
    urlInput.placeholder = 'https://…/imagen.jpg';
    assetCard.appendChild(urlInput);
    assetCard.appendChild(
      _premiumButton('Usar este link', () => assignPremiumAssetFromUrl(slide, urlInput.value)),
    );

    const uploadZone = document.createElement('div');
    uploadZone.className = 'dropzone';
    const uploadStrong = document.createElement('strong');
    uploadStrong.textContent = 'Subir desde mi galería';
    uploadZone.appendChild(uploadStrong);
    uploadZone.appendChild(document.createElement('br'));
    uploadZone.appendChild(document.createTextNode('Arrastrá una imagen o hacé click para elegirla'));
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/*';
    fileInput.style.display = 'none';
    uploadZone.appendChild(fileInput);
    _wirePremiumDropzone(uploadZone, fileInput, slide);
    assetCard.appendChild(uploadZone);

    const selectedButton = _premiumButton('Usar la seleccionada de biblioteca', () => {
      if (!_selectedAssetId) {
        setStatus('st_premium_assets', 'Primero elegí una imagen en la biblioteca.', 'err');
        return;
      }
      _assignPremiumAsset(
        slide,
        {asset_id: _selectedAssetId, titulo: _selectedAssetLabel},
        _selectedAssetLabel,
      );
    });
    selectedButton.classList.add('full-btn');
    assetCard.appendChild(selectedButton);
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

function addPremiumSlide(type) {
  _ensurePackage();
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
  const slides = _premiumPackage.slides;
  const i = slides.findIndex(s => s.id === id);
  if (i < 0) return;
  const clone = Object.assign({}, slides[i], {id: 'tmp_' + Math.random().toString(16).slice(2)});
  slides.splice(i + 1, 0, clone);
  renderPremiumSlides();
}

function removeSlideUI(id) {
  if (_premiumPackage.slides.length <= 2) { alert('El mínimo es 2 slides'); return; }
  _premiumPackage.slides = _premiumPackage.slides.filter(s => s.id !== id);
  renderPremiumSlides();
}

async function savePremiumDraft() {
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
    setStatus(
      'st_premium_draft',
      d.errors && d.errors.length ? `✗ ${_fmtErrList(d.errors)}` : '✓ Borrador guardado',
      d.errors && d.errors.length ? 'err' : 'ok',
    );
    loadPremiumDraftList();
  } catch (e) {
    setStatus('st_premium_draft', `✗ ${e.message}`, 'err');
  }
}

async function previewPremium() {
  if (!_premiumPackage || !_premiumPackage.id) { alert('Guardá el borrador primero'); return; }
  try {
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

async function pollPremiumJob(jobId) {
  try {
    const r = await fetch(`/api/premium/publish-status/${jobId}`);
    const job = await r.json();
    if (!job.done) { setTimeout(() => pollPremiumJob(jobId), 1500); return; }
    if (job.error) { setStatus('st_premium_publish', `✗ ${job.error}`, 'err'); return; }
    const results = (job.result && job.result.channel_results) || {};
    const parts = Object.entries(results).map(([ch, res]) => `${ch}: ${res.ok ? 'OK' : (res.error_type || 'fallo')}`);
    setStatus('st_premium_publish', `Estado: ${job.status} — ${parts.join(' · ')}`, job.status === 'published' ? 'ok' : 'warn');
    loadPremiumDraftList();
  } catch (e) {
    setStatus('st_premium_publish', `✗ ${e.message}`, 'err');
  }
}

async function searchPremiumLibrary() {
  const query = val('premium_library_query');
  setStatus('st_premium_assets', '⏳ Buscando en la biblioteca…');
  try {
    const r = await fetch(`/api/media-library?query=${encodeURIComponent(query)}`);
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'No se pudo buscar en la biblioteca');
    const container = document.getElementById('premium_library_results');
    container.textContent = '';
    const rows = (d.rows || []).slice(0, 20);
    rows.forEach(row => {
      const item = document.createElement('div');
      item.className = 'item';
      const title = document.createElement('b');
      title.textContent = row.titulo || '(sin título)';
      item.appendChild(title);
      if (row.thumbnail) {
        const thumbnail = document.createElement('img');
        thumbnail.className = 'premium-library-thumb';
        thumbnail.src = row.thumbnail;
        thumbnail.alt = '';
        thumbnail.addEventListener('error', () => thumbnail.classList.add('missing'));
        item.appendChild(thumbnail);
      }
      const meta = document.createElement('small');
      meta.textContent = `${row.resource_type} · ${row.estado || ''} · usado ${row.used_count || 0}x`;
      item.appendChild(meta);
      const btn = document.createElement('button');
      btn.className = 'secondary';
      btn.textContent = row.asset_id ? 'Seleccionar esta imagen' : 'Agregar y seleccionar';
      btn.disabled = !row.asset_id && !/^https?:\/\//i.test(String(row.thumbnail || ''));
      btn.addEventListener('click', async () => {
        try {
          let selected = row;
          if (!row.asset_id) {
            btn.disabled = true;
            btn.textContent = 'Agregando…';
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
          _selectedAssetId = selected.asset_id;
          _selectedAssetLabel = row.titulo || selected.titulo || selected.asset_id;
          setStatus(
            'st_premium_assets',
            `✓ Imagen seleccionada: ${_selectedAssetLabel}. Elegí el slide donde querés usarla.`,
            'ok',
          );
          btn.textContent = '✓ Seleccionada';
        } catch (e) {
          btn.disabled = false;
          btn.textContent = row.asset_id ? 'Seleccionar esta imagen' : 'Agregar y seleccionar';
          setStatus('st_premium_assets', `✗ ${e.message}`, 'err');
        }
      });
      item.appendChild(btn);
      container.appendChild(item);
    });
    setStatus(
      'st_premium_assets',
      rows.length ? `${rows.length} resultado(s). Elegí una imagen.` : 'No se encontraron imágenes.',
      rows.length ? '' : 'warn',
    );
  } catch (e) {
    setStatus('st_premium_assets', `✗ ${e.message}`, 'err');
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

// ══ Candidatas ═══════════════════════════════════════════════
async function loadCandidates() {
  try {
    const r = await fetch('/api/editorial/candidates?status=candidate');
    const d = await r.json();
    const container = document.getElementById('candidates_list');
    container.textContent = '';
    (d.candidates || []).forEach(c => {
      const item = document.createElement('div');
      item.className = 'item';
      const title = document.createElement('b');
      title.textContent = c.titulo || '(sin título)';
      item.appendChild(title);
      const meta = document.createElement('small');
      meta.textContent = `${c.seccion || ''} · ${c.topic_key || ''} · ${c.route_reason || ''}`;
      item.appendChild(meta);
      const btnRow = document.createElement('div');
      btnRow.className = 'actions';
      const promote = document.createElement('button');
      promote.className = 'primary';
      promote.textContent = 'Promover a automática';
      promote.addEventListener('click', () => setCandidateStatus(c.candidate_id, 'automatic'));
      const discard = document.createElement('button');
      discard.className = 'secondary';
      discard.textContent = 'Descartar';
      discard.addEventListener('click', () => setCandidateStatus(c.candidate_id, 'discarded'));
      btnRow.appendChild(promote);
      btnRow.appendChild(discard);
      item.appendChild(btnRow);
      container.appendChild(item);
    });
    setStatus('st_candidates', `${(d.candidates || []).length} candidatas`, '');
  } catch (e) {
    setStatus('st_candidates', `✗ ${e.message}`, 'err');
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

async function setCandidateStatus(candidateId, status) {
  try {
    const r = await fetch('/api/editorial/candidates/status', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({candidate_id: candidateId, status}),
    });
    const d = await r.json();
    if (!d.ok) { setStatus('st_candidates', `✗ ${d.error || 'error'}`, 'err'); return; }
    loadCandidates();
  } catch (e) {
    setStatus('st_candidates', `✗ ${e.message}`, 'err');
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
                package, errors, warnings = import_chatgpt_package(generated_json)
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
