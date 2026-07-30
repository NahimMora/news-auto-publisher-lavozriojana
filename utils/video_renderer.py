"""
Genera video MP4 9:16 (1080×1920) para Reels de Instagram/Facebook.

Arquitectura de composición:
  1. Camino normal: todo el reel (bloque superior, panel de video/imagen que crece y se
     compacta, blur-fill, caption animado, footer, logo) se renderiza en una sola pasada
     con la composición "Main" de Remotion — ver _render_remotion_main().
  2. Fallback si Remotion/Node no está disponible o falla: layout estático clásico
     (overlay PNG con PIL) compuesto con ffmpeg filter_complex — ver
     _ffmpeg_compose_video/_ffmpeg_compose_image/_ffmpeg_overlay_only.
  3. Outro de branding (Remotion, cacheado) concatenado al final — ver _append_outro().

Resultado: el video/imagen queda DENTRO del layout, con branding aplicado encima.

Requisitos:
  - ffmpeg en PATH
  - yt-dlp en PATH (opcional, para YouTube/Instagram/X/Facebook)
  - Node.js + `npm i` en remotion/ (opcional: sin esto, cae al layout estático y sin outro)
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import uuid
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from utils.logging_setup import setup_logger
from utils.operation_result import OperationResult
from utils.paths import output_dir
from utils.safe_http import safe_get, validate_public_http_url
from utils.stage_result import StageStatus

logger = setup_logger("video_renderer", "video_renderer.log")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
RENDERS_DIR = str(output_dir() / "renders")
LOGO_PATH    = os.path.join(BASE_DIR, "data", "media", "logo.png")
FB_ICON_PATH = os.path.join(BASE_DIR, "data", "media", "fb_icon_base.png")
IG_ICON_PATH = os.path.join(BASE_DIR, "data", "media", "ig_icon_base.png")

# Proyecto Remotion (branding animado: outro). Ver remotion/README interno.
REMOTION_DIR = os.path.join(BASE_DIR, "remotion")
OUTRO_PATH = os.path.join(BASE_DIR, "data", "media", "outro.mp4")

# Calidad de encoding — configurable por env sin tocar código.
_ENCODE_PRESET = os.getenv("VIDEO_ENCODE_PRESET", "medium")
_ENCODE_CRF = os.getenv("VIDEO_ENCODE_CRF", "19")

# Resolución reel 9:16
W, H = 1080, 1920

# Colores
_ROJO = (179, 0, 0)
_NEGRO = (11, 11, 11)
_FOOTER_BG = (17, 17, 17)
_WHITE = (255, 255, 255)
_GOLD = (246, 195, 67)

# Layout — espeja DEFAULT_REEL_LAYOUT de manual_video_queue.py
_TOP_H = 285        # área superior (sobre el video)
_IMG_Y = 285        # y donde empieza el video
_IMG_H = 760        # alto del área de video
_HEADLINE_Y = 1045  # inicio del bloque titular
_HEADLINE_H = 500   # alto del bloque titular
_FOOTER_Y = 1545    # inicio del footer
_FOOTER_H = 90      # alto del footer
# y=1635..1920: área CTA inferior (285 px)

_FONT_CACHE: dict = {}

# Extensión de archivo de video directo. Para todo lo demás (YouTube, Instagram, X,
# TikTok, Facebook, Vimeo y +1800 sitios más) se intenta yt-dlp directamente — su
# propio extractor genérico falla rápido y controlado si no hay video, así que no hace
# falta mantener una lista de hosts reconocidos.
_VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")

# Frases de stderr de yt-dlp que indican que hace falta sesión autenticada
# (login/cookies), a diferencia de un extractor roto o un error de red.
_YTDLP_AUTH_MARKERS = (
    "login required", "sign in", "rate-limit reached or login",
    "you need to log in", "private", "requested content is not available",
)


# ── Helpers ───────────────────────────────────────────────────

def check_ffmpeg() -> bool:
    try:
        return subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_ytdlp() -> bool:
    try:
        return subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=10).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def new_render_id() -> str:
    """ID hex sin truncar: video_reel_manager._safe_object_id exige 16-64 chars al
    validarlo de vuelta en /api/preview y /api/publish-reel."""
    return uuid.uuid4().hex


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    paths = (
        [r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\arialbd.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        [r"C:\Windows\Fonts\arial.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    f = None
    for p in paths:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, size)
                break
            except Exception:
                continue
    _FONT_CACHE[key] = f or ImageFont.load_default()
    return _FONT_CACHE[key]


def _download_image(url: str) -> Image.Image | None:
    if not url:
        return None
    try:
        r = safe_get(
            url,
            requester=requests.get,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        logger.warning("No se pudo descargar imagen: %s", e)
        return None


def _gradient_fill(
    draw: ImageDraw.Draw, box: tuple[int, int, int, int],
    top_color: tuple, bottom_color: tuple,
) -> None:
    """Rellena un rectángulo con degradado vertical sutil (profundidad en vez de color plano)."""
    x0, y0, x1, y1 = box
    height = max(1, y1 - y0)
    for i in range(height):
        t = i / height
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        draw.line([(x0, y0 + i), (x1, y0 + i)], fill=(r, g, b, 255))


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int, draw: ImageDraw.Draw) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        test = f"{cur} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _badge_text_fit(
    text: str, draw: ImageDraw.Draw, inner: int
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """
    Devuelve (font, líneas) que entran en un cuadrado de `inner` px.
    Prueba dividir el texto en más líneas hasta que quepan anchura y altura.
    """
    for n_lines in range(1, 6):
        chunk = max(1, -(-len(text) // n_lines))  # ceil division
        lines = [text[i:i + chunk] for i in range(0, len(text), chunk)]
        lo, hi = 14, 52
        best_f, best_l = _font(14), lines
        for _ in range(20):
            if lo > hi:
                break
            mid = (lo + hi) // 2
            f = _font(mid)
            bb_ref = draw.textbbox((0, 0), "Ag", font=f)
            lh = int((bb_ref[3] - bb_ref[1]) * 1.15)
            max_lw = max(draw.textbbox((0, 0), ln, font=f)[2] for ln in lines)
            if lh * len(lines) <= inner and max_lw <= inner:
                best_f, best_l = f, lines
                lo = mid + 1
            else:
                hi = mid - 1
        # Verificar que best_f satisface las restricciones
        bb_ref = draw.textbbox((0, 0), "Ag", font=best_f)
        lh = int((bb_ref[3] - bb_ref[1]) * 1.15)
        max_lw = max(draw.textbbox((0, 0), ln, font=best_f)[2] for ln in best_l)
        if lh * len(best_l) <= inner and max_lw <= inner:
            return best_f, best_l
    return _font(14), [text[:4]]


def _auto_font(
    text: str, draw: ImageDraw.Draw,
    max_w: int, max_h: int,
    min_fs: int = 42, max_fs: int = 100,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    lo, hi = min_fs, max_fs
    best_f = _font(min_fs)
    best_l = _wrap_text(text, best_f, max_w, draw)
    for _ in range(22):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        f = _font(mid)
        ls = _wrap_text(text, f, max_w, draw)
        bb = draw.textbbox((0, 0), "Ag", font=f)
        lh = int((bb[3] - bb[1]) * 1.28)
        if lh * len(ls) <= max_h:
            best_f, best_l = f, ls
            lo = mid + 1
        else:
            hi = mid - 1
    return best_f, best_l


# ── Detección y descarga de video fuente ──────────────────────

def _is_direct_video(url: str) -> bool:
    return urlparse(url).path.lower().endswith(_VIDEO_EXTS)


def _download_direct_video(url: str, dest: str) -> OperationResult:
    """Descarga un MP4/MOV directo con requests."""
    try:
        r = safe_get(
            url,
            requester=requests.get,
            timeout=90,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        max_bytes = int(os.getenv("VIDEO_DOWNLOAD_MAX_BYTES", str(250 * 1024 * 1024)))
        total = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("El video supera VIDEO_DOWNLOAD_MAX_BYTES")
                f.write(chunk)
        if os.path.getsize(dest) > 0:
            return OperationResult(StageStatus.SUCCESS, details={"path": dest})
        return OperationResult(
            StageStatus.FAILED,
            error_type="empty_download",
            details={"message": "La descarga terminó vacía"},
        )
    except ValueError as exc:
        logger.warning("Video directo excede el tamaño máximo: %s", exc)
        return OperationResult(
            StageStatus.FAILED, error_type="file_too_large", details={"message": str(exc)}
        )
    except requests.RequestException as exc:
        logger.warning("Error de red descargando MP4 directo: %s", exc)
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="network_error",
            retryable=True,
            details={"message": str(exc)},
        )
    except Exception as exc:
        logger.warning("Error descargando MP4 directo: %s", exc)
        return OperationResult(
            StageStatus.FAILED, error_type="download_error", details={"message": str(exc)}
        )


def _classify_ytdlp_failure(stderr: str) -> tuple[str, bool]:
    """Devuelve (error_type, retryable) a partir del stderr de yt-dlp."""
    lowered = stderr.lower()
    if any(marker in lowered for marker in _YTDLP_AUTH_MARKERS):
        return "auth_required", False
    if "unsupported url" in lowered or "no extractor" in lowered:
        return "unsupported_url", False
    if "http error 429" in lowered or "429" in lowered:
        return "rate_limit", True
    return "extractor_error", False


def _download_ytdlp(url: str, dest: str) -> OperationResult:
    """Descarga un video via yt-dlp."""
    if not check_ytdlp():
        logger.warning("yt-dlp no disponible — instalalo con: pip install yt-dlp")
        return OperationResult(
            StageStatus.FAILED,
            error_type="not_installed",
            details={"message": "yt-dlp no está en PATH; instalalo con pip install yt-dlp"},
        )
    try:
        validate_public_http_url(url)
        max_size = str(os.getenv("VIDEO_DOWNLOAD_MAX_BYTES", str(250 * 1024 * 1024)))
        cmd = [
            "yt-dlp", "-f", "best[ext=mp4][height<=1080]/best[ext=mp4]/best",
            "-o", dest, "--no-playlist", "--no-warnings", "--ignore-config",
            "--max-filesize", max_size,
        ]
        cookies_file = str(os.getenv("YTDLP_COOKIES_FILE", "")).strip()
        if cookies_file and os.path.isfile(cookies_file):
            cmd.extend(["--cookies", cookies_file])
        cmd.append(url)
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=int(os.getenv("YTDLP_TIMEOUT_SECONDS", "180")),
        )
        if result.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0:
            return OperationResult(StageStatus.SUCCESS, details={"path": dest})
        stderr_tail = result.stderr[-500:] if result.stderr else ""
        logger.warning("yt-dlp falló (code %s): %s", result.returncode, stderr_tail[-300:])
        error_type, retryable = _classify_ytdlp_failure(stderr_tail)
        status = StageStatus.DEGRADED if retryable else StageStatus.FAILED
        return OperationResult(
            status, error_type=error_type, retryable=retryable,
            details={"message": stderr_tail[-300:]},
        )
    except subprocess.TimeoutExpired:
        logger.warning("Timeout ejecutando yt-dlp para %s", url[:80])
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="network_error",
            retryable=True,
            details={"message": "yt-dlp superó el timeout configurado"},
        )
    except Exception as exc:
        logger.warning("Error con yt-dlp: %s", exc)
        return OperationResult(
            StageStatus.FAILED, error_type="download_error", details={"message": str(exc)}
        )


def get_source_video(item: dict) -> tuple[str | None, OperationResult]:
    """
    Intenta descargar el video fuente definido en el item.
    Busca en: video_url → source_url (si es YouTube/IG/TikTok/X/MP4 directo/otro sitio
    soportado por yt-dlp).

    Retorna (ruta_o_None, OperationResult). Cuando no hay ningún candidato de video en
    el item, el OperationResult es SUCCESS sin path — no es un fallo, simplemente no se
    pidió video. Cuando hubo un candidato pero la descarga falló, el OperationResult
    trae el motivo (`error_type`) para que el llamador pueda mostrarlo.
    """
    os.makedirs(RENDERS_DIR, exist_ok=True)
    local_video = str(item.get("local_video_path") or "").strip()
    if local_video:
        allowed_root = os.path.realpath(str(output_dir() / "uploads"))
        candidate = os.path.realpath(local_video)
        if (
            os.path.dirname(candidate) == allowed_root
            and os.path.isfile(candidate)
            and candidate.lower().endswith(_VIDEO_EXTS)
        ):
            return candidate, OperationResult(StageStatus.SUCCESS, details={"source": "upload"})
        logger.warning("Ruta de video local rechazada por estar fuera de uploads")
    candidates = [
        str(item.get("video_url") or "").strip(),
        str(item.get("source_video_url") or "").strip(),
    ]
    # source_url se agrega siempre como último candidato: yt-dlp se intenta igual (su
    # extractor genérico falla rápido y controlado si la página no tiene video
    # embebido) — cubre "y más" plataformas sin mantener una lista fija de hosts.
    source_url = str(item.get("source_url") or "").strip()
    if source_url:
        candidates.append(source_url)

    last_failure: OperationResult | None = None
    for url in candidates:
        if not url:
            continue
        dest = os.path.join(RENDERS_DIR, f"_src_{uuid.uuid4().hex[:10]}.mp4")
        if _is_direct_video(url):
            logger.info("Descargando MP4 directo: %s", url[:80])
            result = _download_direct_video(url, dest)
        else:
            logger.info("Descargando con yt-dlp: %s", url[:80])
            result = _download_ytdlp(url, dest)
        if result.ok:
            return dest, result
        last_failure = result
        try:
            os.remove(dest)
        except Exception:
            pass

    if last_failure is not None:
        return None, last_failure
    return None, OperationResult(StageStatus.SUCCESS, details={"source": "no_video_candidate"})


# ── Íconos para el footer ─────────────────────────────────────

_ICON_CACHE: dict = {}


def _icon_colored(path: str, size: int, color: tuple) -> Image.Image | None:
    """
    Carga un ícono PNG (fondo blanco o transparente) y lo coloriza con `color`.
    Mismo algoritmo que layout/image_generator.py → _svg_icon.
    """
    key = (path, size, color)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    try:
        base = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
        r, g, b, a = base.split()
        min_alpha = a.getextrema()[0]
        if min_alpha < 10:
            mask = a                           # fondo transparente: usar alpha original
        else:
            mask = r.point(lambda x: 255 - x) # fondo blanco: invertir canal rojo
        colored = Image.new("RGBA", base.size, (*color, 255))
        colored.putalpha(mask)
        _ICON_CACHE[key] = colored
        return colored
    except Exception:
        return None


def _paste_icon(canvas: Image.Image, path: str, x: int, y: int, size: int,
                color: tuple = (255, 255, 255)) -> None:
    icon = _icon_colored(path, size, color)
    if icon:
        canvas.paste(icon, (x, y), icon)


# ── Overlay PNG con layout LVR ────────────────────────────────

def render_overlay(item: dict) -> Image.Image:
    """
    Genera el overlay RGBA 1080×1920 con el layout LVR.
    Renderiza a 2× internamente y reduce con Lanczos para mejor calidad de texto.
    El área de video es completamente transparente — el video se ve a través.
    """
    titulo = str(item.get("titulo_reel") or item.get("titulo") or "").upper()
    seccion = str(item.get("seccion") or "sociedad").upper()

    # ── Super-sampling 2× → reduce con Lanczos al final
    SC = 2
    W2, H2 = W * SC, H * SC
    top_h2     = _TOP_H      * SC
    img_y2     = _IMG_Y      * SC
    headline_y2 = _HEADLINE_Y * SC
    headline_h2 = _HEADLINE_H * SC
    footer_y2  = _FOOTER_Y   * SC
    footer_h2  = _FOOTER_H   * SC
    pad2 = 60 * SC

    canvas = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Bloque superior — degradado oscuro (espeja GRADIENT_TOP de Overlay.tsx en Remotion)
    _gradient_fill(draw, (0, 0, W2, top_h2), (163, 0, 0), (61, 0, 0))
    # Bloque titular — degradado oscuro, más profundo hacia abajo (espeja GRADIENT_HEADLINE)
    _gradient_fill(draw, (0, headline_y2, W2, headline_y2 + headline_h2), (138, 0, 0), (61, 0, 0))
    # Footer + área inferior — degradado casi negro (espeja GRADIENT_BG_DARK)
    _gradient_fill(draw, (0, footer_y2, W2, H2), (22, 22, 22), (5, 5, 5))

    # ── Línea divisora blanca
    draw.rectangle([(0, img_y2 - 8), (W2, img_y2)], fill=(*_WHITE, 255))

    # ── Badge sección: rectángulo adaptativo al texto
    badge_fs = 44 * SC
    badge_font = _font(badge_fs, bold=True)
    sec_bb = draw.textbbox((0, 0), seccion, font=badge_font)
    sec_w = sec_bb[2] - sec_bb[0]
    sec_h = sec_bb[3] - sec_bb[1]
    bpad_x = 38 * SC
    bpad_y = 30 * SC
    badge_w = sec_w + bpad_x * 2
    badge_h = sec_h + bpad_y * 2

    bx = pad2
    by_top = headline_y2 - badge_h // 2
    by_bot = by_top + badge_h

    draw.rounded_rectangle(
        [(bx, by_top), (bx + badge_w, by_bot)],
        radius=14 * SC, fill=_WHITE,
    )
    draw.text(
        (bx + bpad_x, by_top + bpad_y),
        seccion, font=badge_font, fill=_ROJO,
    )

    # ── Título auto-size (debajo del badge)
    title_top2   = by_bot + 28 * SC
    title_bottom2 = footer_y2 - 44 * SC
    avail_w2 = W2 - pad2 * 2
    avail_h2 = title_bottom2 - title_top2
    tf, tls = _auto_font(titulo, draw, avail_w2, avail_h2, min_fs=42 * SC, max_fs=110 * SC)
    bb_ref = draw.textbbox((0, 0), "Ag", font=tf)
    lh = int((bb_ref[3] - bb_ref[1]) * 1.22)
    ty = title_top2
    for line in tls:
        draw.text(
            (pad2, ty), line, font=tf, fill=_WHITE,
            stroke_width=4, stroke_fill=(0, 0, 0, 150),
        )
        ty += lh

    # ── Footer: URL izquierda · íconos + handle derecha
    footer_fs = 34 * SC
    footer_font = _font(footer_fs, bold=True)
    url_text = "www.lavozriojana.com"
    url_bb = draw.textbbox((0, 0), url_text, font=footer_font)
    url_h = url_bb[3] - url_bb[1]
    fy = footer_y2 + (footer_h2 - url_h) // 2

    draw.text((pad2, fy), url_text, font=footer_font, fill=_WHITE)

    # Íconos + handle alineados a la derecha
    icon_size = int(footer_h2 * 0.78)   # proporcional al alto del footer
    icon_gap  = 14 * SC
    handle_text = "@lavozriojana"
    hbb = draw.textbbox((0, 0), handle_text, font=footer_font)
    handle_w = hbb[2] - hbb[0]
    handle_h = hbb[3] - hbb[1]

    right_block_w = icon_size + icon_gap + icon_size + icon_gap + handle_w
    rx = W2 - pad2 - right_block_w
    icon_y = footer_y2 + (footer_h2 - icon_size) // 2

    _paste_icon(canvas, FB_ICON_PATH, rx, icon_y, icon_size)
    rx += icon_size + icon_gap
    _paste_icon(canvas, IG_ICON_PATH, rx, icon_y, icon_size)
    rx += icon_size + icon_gap
    handle_y = footer_y2 + (footer_h2 - handle_h) // 2
    draw.text((rx, handle_y), handle_text, font=footer_font, fill=_WHITE)

    # ── Logo en esquina superior-derecha del área de video
    logo_size = 150 * SC
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        lw2 = logo_size
        lh2 = int(logo.height * lw2 / logo.width)
        logo = logo.resize((lw2, lh2), Image.LANCZOS)
        canvas.paste(logo, (W2 - lw2 - 24 * SC, img_y2 + 20 * SC), logo)
    except Exception:
        lvr_font = _font(36 * SC, bold=True)
        lvr_bb = draw.textbbox((0, 0), "LVR", font=lvr_font)
        lvr_w2 = lvr_bb[2] - lvr_bb[0] + 28 * SC
        lvr_h2 = lvr_bb[3] - lvr_bb[1] + 16 * SC
        lvr_x = W2 - lvr_w2 - 24 * SC
        lvr_y = img_y2 + 20 * SC
        draw.rounded_rectangle(
            [(lvr_x, lvr_y), (lvr_x + lvr_w2, lvr_y + lvr_h2)],
            radius=10 * SC, fill=(*_WHITE, 235),
        )
        draw.text(
            (lvr_x + 14 * SC, lvr_y + 8 * SC), "LVR",
            font=lvr_font, fill=_ROJO,
        )

    # Reducir a resolución final con Lanczos (anti-aliasing)
    return canvas.resize((W, H), Image.LANCZOS)


# ── Composición ffmpeg ────────────────────────────────────────

def _ffmpeg_compose_video(source_video: str, overlay_png: str, output: str, duration: int) -> None:
    """
    Compone: canvas negro 9:16 + source_video (en área _IMG_Y) + overlay PNG encima.
    El overlay tiene transparencia en el área de video → el video se ve a través.
    Fallback clásico (PIL + ffmpeg) cuando Remotion no está disponible — ver
    _render_remotion_main(), que reemplaza esto en el camino normal.
    """
    # El source_video se escala a 1080×760 con crop centrado + viñeta sutil (dirige el ojo al centro)
    # [bg]→[vid]→[combined]→overlay PNG→[out]
    vid_scale = (
        f"[0:v]scale=1080:760:force_original_aspect_ratio=increase,"
        f"crop=1080:760,vignette=PI/6[vid]"
    )
    filter_graph = (
        f"color=c=0x0B0B0B:s=1080x1920:d={duration}[bg];"
        f"{vid_scale};"
        f"[bg][vid]overlay=0:{_IMG_Y}[combined];"
        f"[combined][1:v]overlay=0:0:format=auto:shortest=1[out]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", source_video,
        "-loop", "1", "-i", overlay_png,
        "-filter_complex", filter_graph,
        "-map", "[out]",
        "-map", "0:a?",       # pasar audio del video fuente si existe
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", _ENCODE_PRESET,
        "-crf", _ENCODE_CRF,
        "-r", "30",
        "-c:a", "aac",        # codificar audio como AAC
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error (video): {result.stderr[-800:]}")


def _ease_zoom_expr(frames: int, max_zoom: float = 1.06) -> str:
    """Zoom ease-out (arranca rápido, desacelera) en vez del incremento lineal anterior."""
    delta = max_zoom - 1.0
    return f"1+{delta}*(1-pow(1-on/{frames},2))"


def _ffmpeg_compose_image(
    image_jpg: str, overlay_png: str, output: str, duration: int, variant: int = 0,
) -> None:
    """
    Compone: canvas negro 9:16 + imagen con Ken Burns (zoom ease-out + paneo sutil) en área
    _IMG_Y + overlay PNG. `variant` (0/1/2) alterna la dirección del paneo entre notas —
    determinístico por nota (ver render_video) para que no todas usen el mismo movimiento.
    Pre-escala la imagen a 2× para que zoompan tenga calidad. Fallback clásico (PIL +
    ffmpeg) cuando Remotion no está disponible — ver _render_remotion_main().
    """
    frames = duration * 30  # 30 fps
    zoom_expr = _ease_zoom_expr(frames)
    pan_w = f"iw*0.035*(1-on/{frames})"
    pan_h = f"ih*0.035*(1-on/{frames})"
    if variant == 1:
        x_expr, y_expr = f"iw/2-(iw/zoom/2)-{pan_w}", "ih/2-(ih/zoom/2)"
    elif variant == 2:
        x_expr, y_expr = "iw/2-(iw/zoom/2)", f"ih/2-(ih/zoom/2)-{pan_h}"
    else:
        x_expr, y_expr = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"

    # Escalar imagen al doble del área de video para que el zoom tenga resolución
    img_scale = (
        f"[0:v]scale=2160:-2:force_original_aspect_ratio=increase,"
        f"zoompan=z='{zoom_expr}'"
        f":x='{x_expr}'"
        f":y='{y_expr}'"
        f":d={frames}:s=1080x760:fps=30,"
        f"vignette=PI/6[vid]"
    )
    filter_graph = (
        f"color=c=0x0B0B0B:s=1080x1920:d={duration}[bg];"
        f"{img_scale};"
        f"[bg][vid]overlay=0:{_IMG_Y}[combined];"
        f"[combined][1:v]overlay=0:0:format=auto:shortest=1[out]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_jpg,
        "-loop", "1", "-i", overlay_png,
        "-filter_complex", filter_graph,
        "-map", "[out]",
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", _ENCODE_PRESET,
        "-crf", _ENCODE_CRF,
        "-r", "30",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error (imagen Ken Burns): {result.stderr[-800:]}")


def _ffmpeg_overlay_only(overlay_png: str, output: str, duration: int) -> None:
    """Fallback sin imagen: solo el layout LVR sobre fondo negro."""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", overlay_png,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", _ENCODE_PRESET,
        "-crf", _ENCODE_CRF,
        "-r", "30",
        "-pix_fmt", "yuv420p",
        "-vf", "scale=1080:1920",
        "-movflags", "+faststart",
        output,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error (solo overlay): {result.stderr[-800:]}")


# ── Punto de entrada ──────────────────────────────────────────

def get_video_duration(path: str) -> float | None:
    """Retorna la duración en segundos usando ffprobe, o None si falla."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-select_streams", "v:0",
        "-show_entries", "stream=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            return float(result.stdout.strip())
        except (ValueError, AttributeError):
            pass
    return None


def _npx_args(args: list[str]) -> list[str]:
    """En Windows, npx es un .cmd — subprocess sin shell no lo ejecuta directamente."""
    if os.name == "nt":
        return ["cmd", "/c", "npx", *args]
    return ["npx", *args]


def _ensure_outro() -> str | None:
    """
    Devuelve la ruta del outro de branding (Remotion), renderizándolo una única vez y
    cacheándolo en OUTRO_PATH. Si Remotion/Node no está disponible en este entorno,
    devuelve None — el llamador debe omitir el outro sin romper el render principal.
    """
    if os.path.isfile(OUTRO_PATH) and os.path.getsize(OUTRO_PATH) > 0:
        return OUTRO_PATH
    if not os.path.isdir(REMOTION_DIR):
        logger.info("Carpeta remotion/ no encontrada — se omite el outro")
        return None
    try:
        os.makedirs(os.path.dirname(OUTRO_PATH), exist_ok=True)
        result = subprocess.run(
            _npx_args(["remotion", "render", "Outro", OUTRO_PATH, "--codec=h264"]),
            cwd=REMOTION_DIR, capture_output=True, text=True, timeout=180,
        )
        if result.returncode == 0 and os.path.isfile(OUTRO_PATH):
            logger.info("Outro de Remotion renderizado y cacheado en %s", OUTRO_PATH)
            return OUTRO_PATH
        logger.warning("No se pudo renderizar el outro con Remotion: %s", result.stderr[-400:])
        return None
    except Exception as exc:
        logger.warning("Error renderizando outro con Remotion: %s", exc)
        return None


def _append_outro(main_path: str, video_id: str) -> bool:
    """
    Concatena el outro de branding al final de `main_path` (in-place). Devuelve True si se
    agregó, False si se omitió (Remotion no disponible o falló la composición) — en ese
    caso `main_path` queda intacto, el render principal nunca se rompe por esto.
    """
    outro_path = _ensure_outro()
    if not outro_path:
        return False
    combined_path = os.path.join(RENDERS_DIR, f"_final_{video_id}.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-i", main_path,
        "-i", outro_path,
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", _ENCODE_PRESET,
        "-crf", _ENCODE_CRF,
        "-r", "30",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        combined_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("No se pudo agregar el outro (se publica sin outro): %s", result.stderr[-400:])
        try:
            os.remove(combined_path)
        except Exception:
            pass
        return False
    os.remove(main_path)
    os.replace(combined_path, main_path)
    return True


def _render_remotion_main(
    item: dict, video_id: str, duration: int,
    asset_path: str | None, asset_type: str, ken_burns_variant: int,
) -> str | None:
    """
    Renderiza la composición "Main" de Remotion, que reemplaza todo el compositing de
    ffmpeg: bloque superior, panel de video/imagen (creciente + fondo blur-fill), caption
    animado (título/sección, se encoge y termina flotando sobre el video), footer con
    íconos, logo. Devuelve la ruta del mp4 generado, o None si Remotion no está disponible
    o falla — el llamador debe caer al pipeline clásico (PIL + ffmpeg).

    `asset_path` es la ruta local ya descargada del video/imagen (o None si el item no
    trae ninguno — asset_type se fuerza a "none" en ese caso). Remotion solo puede leer
    assets dentro de remotion/public/, así que se copia ahí bajo public/tmp/ con el
    video_id como nombre, y se borra al terminar (no queda nada del contenido de terceros
    dando vueltas en el repo).
    """
    if not os.path.isdir(REMOTION_DIR):
        return None

    titulo = str(item.get("titulo_reel") or item.get("titulo") or "").upper()
    seccion = str(item.get("seccion") or "sociedad").upper()
    frames = max(1, duration * 30)

    asset_file = ""
    tmp_asset_path: str | None = None
    effective_type = asset_type
    if asset_path:
        ext = ".mp4" if asset_type == "video" else ".jpg"
        asset_file = f"tmp/{video_id}{ext}"
        tmp_asset_path = os.path.join(REMOTION_DIR, "public", "tmp", f"{video_id}{ext}")
        os.makedirs(os.path.dirname(tmp_asset_path), exist_ok=True)
        shutil.copy2(asset_path, tmp_asset_path)
    else:
        effective_type = "none"

    props_path = os.path.join(RENDERS_DIR, f"_mainprops_{video_id}.json")
    output_path = os.path.join(RENDERS_DIR, f"_main_{video_id}.mp4")
    try:
        with open(props_path, "w", encoding="utf-8") as f:
            json.dump({
                "titulo": titulo,
                "seccion": seccion,
                "assetType": effective_type,
                "assetFile": asset_file,
                "kenBurnsVariant": ken_burns_variant,
                "durationInFrames": frames,
            }, f)
        result = subprocess.run(
            _npx_args([
                "remotion", "render", "Main", output_path,
                "--codec=h264", f"--props={props_path}",
            ]),
            cwd=REMOTION_DIR, capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0 and os.path.isfile(output_path):
            return output_path
        logger.warning("No se pudo renderizar Main con Remotion: %s", result.stderr[-500:])
        return None
    except Exception as exc:
        logger.warning("Error renderizando Main con Remotion: %s", exc)
        return None
    finally:
        try:
            os.remove(props_path)
        except Exception:
            pass
        if tmp_asset_path:
            try:
                os.remove(tmp_asset_path)
            except Exception:
                pass


def render_video(item: dict) -> tuple[str, str, int, dict]:
    """
    Genera el MP4 del reel.

    Flujo:
      1. Intentar descargar video fuente (video_url / source_url de YT/IG/TikTok/X/MP4)
      2a. Si hay video: usa su duración real
      2b. Si hay imagen del artículo: Ken Burns con esa duración
      2c. Sin ninguno: solo el layout de branding, sin panel de video/imagen
      3. Renderiza todo con Remotion (composición "Main" — panel de video/imagen que
         crece, caption animado, blur-fill, footer, logo). Si Remotion/Node no está
         disponible o falla, cae al pipeline clásico (overlay estático PIL + ffmpeg).
      4. Concatena el outro de branding al final.

    Retorna (ruta_mp4, video_id, duracion_segundos, info) donde `info` incluye
    `source_used` ("video" | "image_fallback" | "overlay_only"), `engine`
    ("remotion" | "ffmpeg_fallback"), `outro_added` (True si se pudo concatenar el outro)
    y, cuando el video fuente se pidió pero no se pudo descargar, `fallback_reason` con el
    motivo (`error_type` de la descarga) y un mensaje corto para mostrarle al operador.
    Lanza RuntimeError si ffmpeg no está disponible.
    """
    if not check_ffmpeg():
        raise RuntimeError(
            "ffmpeg no está disponible. "
            "Instalalo en https://ffmpeg.org/download.html "
            "y agregá la carpeta bin al PATH."
        )

    fallback_duration = max(3, min(90, int(item.get("duration_seconds") or 15)))
    os.makedirs(RENDERS_DIR, exist_ok=True)

    video_id = new_render_id()
    output_path = os.path.join(RENDERS_DIR, f"{video_id}.mp4")
    temp_files: list[str] = []

    # Variante de paneo Ken Burns determinística por nota (no aleatoria, para reproducibilidad)
    titulo_for_variant = str(item.get("titulo_reel") or item.get("titulo") or "")
    ken_burns_variant = sum(ord(c) for c in titulo_for_variant) % 3 if titulo_for_variant else 0

    try:
        # Obtener video o imagen fuente — la duración real hace falta antes de renderizar
        # (tanto Remotion como el fallback ffmpeg necesitan saber cuántos frames/segundos).
        source_video, source_result = get_source_video(item)
        info: dict = {}
        asset_path: str | None = None
        asset_type = "none"
        if source_video:
            info["source_used"] = "video"
            if (
                os.path.dirname(os.path.realpath(source_video)) == os.path.realpath(RENDERS_DIR)
                and os.path.basename(source_video).startswith("_src_")
            ):
                temp_files.append(source_video)
            real_dur = get_video_duration(source_video)
            duration = max(3, min(90, int(real_dur))) if real_dur else fallback_duration
            asset_path = source_video
            asset_type = "video"
        else:
            duration = fallback_duration
            if not source_result.ok:
                info["fallback_reason"] = {
                    "error_type": source_result.error_type,
                    "message": source_result.details.get("message"),
                }
                logger.warning(
                    "No se pudo obtener video fuente (%s); se usa fallback de imagen",
                    source_result.error_type,
                )
            imagen_url = str(item.get("imagen_url") or "")
            local_image = str(item.get("local_image_path") or "").strip()
            if local_image:
                allowed_root = os.path.realpath(str(output_dir() / "uploads"))
                candidate = os.path.realpath(local_image)
                if os.path.dirname(candidate) == allowed_root and os.path.isfile(candidate):
                    try:
                        src_img = Image.open(candidate).convert("RGBA")
                    except OSError:
                        src_img = None
                else:
                    src_img = None
            else:
                src_img = _download_image(imagen_url)
            if src_img:
                img_path = os.path.join(RENDERS_DIR, f"_img_{video_id}.jpg")
                temp_files.append(img_path)
                src_img.convert("RGB").save(img_path, "JPEG", quality=92)
                asset_path = img_path
                asset_type = "image"
                info["source_used"] = "image_fallback"
            else:
                info["source_used"] = "overlay_only"

        logger.info("Renderizando reel (%ds, asset=%s)…", duration, asset_type)
        main_path = _render_remotion_main(item, video_id, duration, asset_path, asset_type, ken_burns_variant)

        if main_path:
            os.replace(main_path, output_path)
            info["engine"] = "remotion"
            logger.info("Reel renderizado con Remotion (Main)")
        else:
            info["engine"] = "ffmpeg_fallback"
            logger.info("Remotion no disponible/falló — usando pipeline clásico (PIL + ffmpeg)")
            overlay_img = render_overlay(item)
            overlay_path = os.path.join(RENDERS_DIR, f"_ovl_{video_id}.png")
            temp_files.append(overlay_path)
            overlay_img.save(overlay_path, "PNG")
            if asset_type == "video":
                logger.info("Componiendo con video fuente: %s (%.1fs)", os.path.basename(asset_path), duration)
                _ffmpeg_compose_video(asset_path, overlay_path, output_path, duration)
            elif asset_type == "image":
                logger.info("Componiendo con imagen + Ken Burns")
                _ffmpeg_compose_image(asset_path, overlay_path, output_path, duration, variant=ken_burns_variant)
            else:
                logger.info("Sin imagen ni video — generando solo overlay sobre negro")
                _ffmpeg_overlay_only(overlay_path, output_path, duration)

        info["outro_added"] = _append_outro(output_path, video_id)

        size_mb = os.path.getsize(output_path) / 1_048_576
        logger.info("Video renderizado: %s (%.1f MB, %ds)", output_path, size_mb, duration)
        return output_path, video_id, duration, info

    finally:
        for f in temp_files:
            try:
                os.unlink(f)
            except Exception:
                pass
