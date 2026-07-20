"""
Genera video MP4 9:16 (1080×1920) para Reels de Instagram/Facebook.

Arquitectura de composición (ffmpeg filter_complex):
  1. Canvas negro 1080×1920
  2. Video fuente (o imagen con Ken Burns) escalado a 1080×760 → pegado en y=285
  3. Overlay PNG RGBA (layout LVR) superpuesto: el área de video es transparente,
     los demás bloques (superior, rojo titular, footer, CTA) son opacos.

Resultado: el video/imagen queda DENTRO del layout, con branding aplicado encima.

Requisitos:
  - ffmpeg en PATH
  - yt-dlp en PATH (opcional, para YouTube/Instagram/X/Facebook)
"""
from __future__ import annotations

import io
import os
import subprocess
import uuid
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from utils.logging_setup import setup_logger

logger = setup_logger("video_renderer")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
RENDERS_DIR = os.path.join(BASE_DIR, "output", "renders")
LOGO_PATH    = os.path.join(BASE_DIR, "data", "media", "logo.png")
FB_ICON_PATH = os.path.join(BASE_DIR, "data", "media", "fb_icon_base.png")
IG_ICON_PATH = os.path.join(BASE_DIR, "data", "media", "ig_icon_base.png")

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

# Extensiones y dominios que yt-dlp puede descargar
_VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")
_VIDEO_HOSTS = {
    "youtube.com", "youtu.be",
    "instagram.com", "x.com", "twitter.com",
    "tiktok.com", "vimeo.com",
    "facebook.com", "fb.watch",
}


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
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        logger.warning("No se pudo descargar imagen: %s", e)
        return None


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


def _is_ytdlp_url(url: str) -> bool:
    host = urlparse(url).netloc.lower().replace("www.", "")
    return host in _VIDEO_HOSTS or any(host.endswith(f".{h}") for h in _VIDEO_HOSTS)


def _download_direct_video(url: str, dest: str) -> bool:
    """Descarga un MP4/MOV directo con requests."""
    try:
        r = requests.get(url, timeout=90, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        return os.path.getsize(dest) > 0
    except Exception as e:
        logger.warning("Error descargando MP4 directo: %s", e)
        return False


def _download_ytdlp(url: str, dest: str) -> bool:
    """Descarga un video via yt-dlp."""
    if not check_ytdlp():
        logger.warning("yt-dlp no disponible — instalalo con: pip install yt-dlp")
        return False
    try:
        result = subprocess.run(
            ["yt-dlp", "-f", "best[ext=mp4][height<=1080]/best[ext=mp4]/best",
             "-o", dest, "--no-playlist", "--no-warnings", url],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0:
            return True
        logger.warning("yt-dlp falló (code %s): %s", result.returncode, result.stderr[-300:])
        return False
    except Exception as e:
        logger.warning("Error con yt-dlp: %s", e)
        return False


def get_source_video(item: dict) -> str | None:
    """
    Intenta descargar el video fuente definido en el item.
    Busca en: video_url → source_url (si es YouTube/IG/MP4 directo).
    Retorna ruta a archivo temporal o None.
    """
    os.makedirs(RENDERS_DIR, exist_ok=True)
    candidates = [
        str(item.get("video_url") or "").strip(),
        str(item.get("source_video_url") or "").strip(),
    ]
    # Si source_url parece video, también intentarlo
    source_url = str(item.get("source_url") or "").strip()
    if source_url and (_is_direct_video(source_url) or _is_ytdlp_url(source_url)):
        candidates.append(source_url)

    for url in candidates:
        if not url:
            continue
        dest = os.path.join(RENDERS_DIR, f"_src_{uuid.uuid4().hex[:10]}.mp4")
        ok = False
        if _is_direct_video(url):
            logger.info("Descargando MP4 directo: %s", url[:80])
            ok = _download_direct_video(url, dest)
        elif _is_ytdlp_url(url):
            logger.info("Descargando con yt-dlp: %s", url[:80])
            ok = _download_ytdlp(url, dest)
        if ok:
            return dest
        try:
            os.remove(dest)
        except Exception:
            pass

    return None


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
        min_alpha = min(a.getdata())
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

    # Bloque superior rojo
    canvas.paste(Image.new("RGBA", (W2, top_h2), (*_ROJO, 255)), (0, 0))
    # Bloque titular rojo
    canvas.paste(Image.new("RGBA", (W2, headline_h2), (*_ROJO, 255)), (0, headline_y2))
    # Footer + área inferior: todo #111111
    canvas.paste(Image.new("RGBA", (W2, H2 - footer_y2), (*_FOOTER_BG, 255)), (0, footer_y2))

    draw = ImageDraw.Draw(canvas)

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
    """
    # El source_video se escala a 1080×760 con crop centrado
    # [bg]→[vid]→[combined]→overlay PNG→[out]
    vid_scale = (
        f"[0:v]scale=1080:760:force_original_aspect_ratio=increase,"
        f"crop=1080:760[vid]"
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
        "-r", "30",
        "-c:a", "aac",        # codificar audio como AAC
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error (video): {result.stderr[-800:]}")


def _ffmpeg_compose_image(image_jpg: str, overlay_png: str, output: str, duration: int) -> None:
    """
    Compone: canvas negro 9:16 + imagen con Ken Burns (zoom suave) en área _IMG_Y + overlay PNG.
    Pre-escala la imagen a 2× para que zoompan tenga calidad.
    """
    frames = duration * 30  # 30 fps
    # Escalar imagen al doble del área de video para que el zoom tenga resolución
    img_scale = (
        f"[0:v]scale=2160:-2:force_original_aspect_ratio=increase,"
        f"zoompan=z='min(zoom+0.0004,1.06)'"
        f":x='iw/2-(iw/zoom/2)'"
        f":y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s=1080x760:fps=30[vid]"
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


def render_video(item: dict) -> tuple[str, str, int]:
    """
    Genera el MP4 del reel.

    Flujo:
      1. Intentar descargar video fuente (video_url / source_url de YT/IG/MP4)
      2a. Si hay video: usa su duración real → composición ffmpeg (video + overlay)
      2b. Si hay imagen del artículo: Ken Burns + overlay con duración del item
      2c. Sin ninguno: solo overlay sobre negro con duración del item

    Retorna (ruta_mp4, video_id, duracion_segundos).
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

    video_id = uuid.uuid4().hex[:12]
    output_path = os.path.join(RENDERS_DIR, f"{video_id}.mp4")
    overlay_path = os.path.join(RENDERS_DIR, f"_ovl_{video_id}.png")
    temp_files: list[str] = [overlay_path]

    try:
        # Generar overlay PNG
        logger.info("Generando overlay PNG del layout LVR…")
        overlay_img = render_overlay(item)
        overlay_img.save(overlay_path, "PNG")

        # Intentar obtener video fuente
        source_video = get_source_video(item)
        if source_video:
            temp_files.append(source_video)
            # Usar duración real del video descargado
            real_dur = get_video_duration(source_video)
            duration = max(3, min(90, int(real_dur))) if real_dur else fallback_duration
            logger.info(
                "Componiendo con video fuente: %s (%.1fs)",
                os.path.basename(source_video), duration,
            )
            _ffmpeg_compose_video(source_video, overlay_path, output_path, duration)
        else:
            duration = fallback_duration
            # Fallback: imagen del artículo con Ken Burns
            imagen_url = str(item.get("imagen_url") or "")
            src_img = _download_image(imagen_url)
            if src_img:
                img_path = os.path.join(RENDERS_DIR, f"_img_{video_id}.jpg")
                temp_files.append(img_path)
                src_img.convert("RGB").save(img_path, "JPEG", quality=92)
                logger.info("Componiendo con imagen + Ken Burns: %s", imagen_url[:60])
                _ffmpeg_compose_image(img_path, overlay_path, output_path, duration)
            else:
                logger.info("Sin imagen ni video — generando solo overlay sobre negro")
                _ffmpeg_overlay_only(overlay_path, output_path, duration)

        size_mb = os.path.getsize(output_path) / 1_048_576
        logger.info("Video renderizado: %s (%.1f MB, %ds)", output_path, size_mb, duration)
        return output_path, video_id, duration

    finally:
        for f in temp_files:
            try:
                os.unlink(f)
            except Exception:
                pass
