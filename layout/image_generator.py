"""
Genera imagenes de posts para Instagram (1080x1350) y Facebook/OG (1200x630)
con el estilo definido en instagram_layout_designer.py.
"""
import os
import io
import tempfile
import time
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from utils.logging_setup import setup_logger
from utils.safe_http import safe_get

logger = setup_logger("image_generator", "image_generator.log")

BASE_DIR     = os.path.dirname(os.path.dirname(__file__))
LOGO_PATH    = os.path.join(BASE_DIR, "data", "media", "logo.png")
POSTS_DIR    = os.path.join(BASE_DIR, "data", "media", "posts")
FB_ICON_PATH = os.path.join(BASE_DIR, "data", "media", "fb_icon_base.png")
IG_ICON_PATH = os.path.join(BASE_DIR, "data", "media", "ig_icon_base.png")

# ── Resoluciones ─────────────────────────────────────────────
IG_W, IG_H = 1080, 1350   # 4:5 Instagram
FB_W, FB_H = 1200, 630    # 1.91:1 Facebook/OG

# ── Paleta por sección (solo rojo bordo y azul) ───────────────
ROJO  = "#8B1A1A"   # rojo bordo
AZUL  = "#1a4f8b"   # azul oscuro

SECTION_COLORS = {
    # Categorías IA
    "politica":     AZUL,
    "policiales":   ROJO,
    "interior":     AZUL,
    "sociedad":     AZUL,
    "economia":     AZUL,
    "salud":        AZUL,
    "educacion":    AZUL,
    "deportes":     AZUL,
    "cultura":      ROJO,
    "espectaculos": ROJO,
    # Compat. con secciones del scraper
    "locales":      ROJO,
}

def section_color(seccion: str) -> str:
    return SECTION_COLORS.get(seccion.lower().strip(), ROJO)

# ── Config visual (espeja defaults del diseñador) ─────────────
CFG = {
    "content_top":  0.55,
    "grad_op":      1.0,
    "grad_soft":    0.43,
    "bg_dark":      0.10,
    "logo_w":       0.16,
    "logo_inset":   0.022,
    "img_blend":    0.09,
    "footer_h":     0.07,
    "social_color": (227, 0, 0),
    "pad":          0.052,
    "leftbar_w":    0.011,
    "title_w":      0.95,
    "content_gap":  0.018,
    "wm_opacity":   0.095,
    "wm_size":      0.38,
    "wm_vpos":      0.27,
}

# ── Fuentes ───────────────────────────────────────────────────
# Archivo (variable, SIL OFL) es la tipografía del sistema "Editorial
# Cinemática Riojana" — ver remotion/src/shared/designSystem.ts y
# docs/DECISIONS.md. Este fallback Pillow (única pieza de emergencia,
# nunca el motor real) la usa primero; sólo si el .ttf no está presente o
# PIL no puede leerlo cae a Arial. Eliminar Arial del sistema visual
# aplica también acá, sin rediseñar el resto de este layout.
_FONT_CACHE: dict = {}
_ARCHIVO_VF_PATH = os.path.join(BASE_DIR, "layout", "fonts", "Archivo[wdth,wght].ttf")

def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    f = None
    if os.path.exists(_ARCHIVO_VF_PATH):
        try:
            f = ImageFont.truetype(_ARCHIVO_VF_PATH, size)
            try:
                f.set_variation_by_axes([900 if bold else 400])
            except Exception:
                pass  # build de FreeType sin soporte de variable fonts: se usa la instancia default.
        except Exception:
            f = None
    if f is None:
        # Fallback de emergencia si el .ttf de Archivo no está disponible.
        paths = (
            [r"C:\Windows\Fonts\arialbd.ttf",
             r"C:\Windows\Fonts\arial.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
            if bold else
            [r"C:\Windows\Fonts\arial.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
        )
        for p in paths:
            if os.path.exists(p):
                try:
                    f = ImageFont.truetype(p, size)
                    break
                except Exception:
                    pass
    _FONT_CACHE[key] = f or ImageFont.load_default()
    return _FONT_CACHE[key]


# ── Imagen remota ─────────────────────────────────────────────
def _download(url: str) -> Image.Image | None:
    if not url:
        return None
    try:
        r = safe_get(
            url,
            requester=requests.get,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        logger.warning(f"No se pudo descargar imagen: {e}")
        return None


# ── Cover crop ────────────────────────────────────────────────
def _cover(img: Image.Image, w: int, h: int, vpos: float = 0.5) -> Image.Image:
    """object-fit:cover — recorta ambos lados, mantiene aspecto."""
    ia = img.width / img.height
    ta = w / h
    if ia > ta:                          # más ancha → recorta lados
        nw = int(h * ia)
        img = img.resize((nw, h), Image.LANCZOS)
        x = (nw - w) // 2
        img = img.crop((x, 0, x + w, h))
    else:                                # más alta → recorta arriba/abajo
        nh = int(w / ia)
        img = img.resize((w, nh), Image.LANCZOS)
        y = int((nh - h) * vpos)
        img = img.crop((0, y, w, y + h))
    return img


# ── Fondo blur ────────────────────────────────────────────────
def _blur_bg(img: Image.Image, w: int, h: int, bg_dark: float) -> Image.Image:
    bg = _cover(img.copy(), w, h, 0.5)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=36))
    dark = Image.new("RGBA", (w, h), (0, 0, 0, int(255 * (1 - max(0.05, 1 - bg_dark)))))
    return Image.alpha_composite(bg, dark)


# ── Gradiente inferior ────────────────────────────────────────
def _gradient(w: int, h: int, grad_op: float, grad_soft: float) -> Image.Image:
    g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    for y in range(h):
        fb = (h - y) / h          # 1.0=arriba, 0=abajo
        if fb > 0.50:
            continue
        elif fb >= grad_soft:
            # de grad_soft→50%: alpha baja de 0.70 → 0.01
            t = (fb - grad_soft) / (0.50 - grad_soft)
            a = grad_op * 0.70 * (1 - t) + 0.01 * t
        else:
            # de 0→grad_soft: alpha baja de 1.0 → 0.70
            t = fb / grad_soft if grad_soft else 0
            a = grad_op * (1.0 - 0.30 * t)
        d.line([(0, y), (w - 1, y)], fill=(0, 0, 0, max(0, min(255, int(255 * a)))))
    return g


# ── Fades top/bottom imagen ───────────────────────────────────
def _fades(w: int, img_h: int, blend: float, bg_dark: float):
    fh = min(max(1, int(img_h * blend)), img_h // 2)
    amax = int(min(bg_dark + 0.40, 0.95) * 255)

    def build(direction):
        im = Image.new("RGBA", (w, fh), (0, 0, 0, 0))
        d  = ImageDraw.Draw(im)
        for y in range(fh):
            t = y / fh
            a = int(amax * (t if direction == "up" else 1 - t))
            d.line([(0, y), (w - 1, y)], fill=(0, 0, 0, a))
        return im

    return build("down"), build("up")


# ── Iconos sociales desde SVG pre-renderizados ───────────────
_ICON_CACHE: dict = {}

def _svg_icon(base_path: str, sz: int, color: tuple) -> Image.Image | None:
    """
    Carga el PNG base del SVG y lo coloriza con `color`.
    Soporta fondo transparente (usa canal alpha) y fondo blanco (invierte rojo).
    """
    key = (base_path, sz, color)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    try:
        base = Image.open(base_path).convert("RGBA").resize((sz, sz), Image.LANCZOS)
    except (FileNotFoundError, OSError):
        logger.warning("Ícono social ausente o inválido: %s", base_path)
        return None
    r, g, b, a = base.split()

    # Detectar si el fondo es transparente o blanco
    min_alpha = a.getextrema()[0]
    if min_alpha < 10:
        # Fondo transparente: usar alpha original como máscara
        mask = a
    else:
        # Fondo blanco: invertir canal rojo (blanco→0, negro→255)
        mask = r.point(lambda x: 255 - x)

    colored = Image.new("RGBA", base.size, (*color, 255))
    colored.putalpha(mask)
    _ICON_CACHE[key] = colored
    return colored


# ── Auto-ajuste de fuente para título ─────────────────────────
def _fit_title(draw: ImageDraw.Draw, text: str,
               max_w: int, max_h: int, min_fs: int, max_fs: int):
    def wrap(txt, font, mw):
        words = txt.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            bb = draw.textbbox((0, 0), test, font=font)
            if bb[2] <= mw:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    lo, hi = min_fs, max_fs
    best_f = _font(min_fs)
    best_l = wrap(text, best_f, max_w)

    for _ in range(22):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        f = _font(mid)
        ls = wrap(text, f, max_w)
        bb = draw.textbbox((0, 0), "Ag", font=f)
        if (bb[3] - bb[1]) * 1.25 * len(ls) <= max_h:
            best_f, best_l = f, ls
            lo = mid + 1
        else:
            hi = mid - 1

    return best_f, best_l



# ── Generador principal ───────────────────────────────────────
def _hex(color: str):
    c = color.lstrip("#")
    return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))


def generate_post(article: dict, width: int, height: int, preloaded_img: "Image.Image | None" = None) -> Image.Image:
    c = CFG
    color_hex = article.get("color") or section_color(article.get("seccion", ""))
    brand = _hex(color_hex)

    img_h       = int(height * c["content_top"])
    pad         = int(width  * c["pad"])
    inset       = int(width  * c["logo_inset"])
    footer_h    = int(height * c["footer_h"])
    lbar_w      = int(width  * c["leftbar_w"])
    lbar_off    = lbar_w + int(pad * 0.5)
    cgap        = int(height * c["content_gap"])
    soc         = c["social_color"]

    # 1. Fondo blur
    src = preloaded_img.convert("RGBA") if preloaded_img else _download(article.get("imagen_url", ""))
    canvas = _blur_bg(src, width, height, c["bg_dark"]) if src else \
             Image.new("RGBA", (width, height), (18, 20, 35, 255))

    # 2. Imagen principal (cover, centrada)
    if src:
        crop = _cover(src.convert("RGBA"), width, img_h, 0.5)
        canvas.paste(crop, (0, 0), crop)

        # Fades top/bottom: overlay oscuro sobre los bordes de la imagen
        ft, fb = _fades(width, img_h, c["img_blend"], c["bg_dark"])
        top_ov = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        top_ov.paste(ft, (0, 0))
        canvas = Image.alpha_composite(canvas, top_ov)

        bot_ov = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        bot_ov.paste(fb, (0, img_h - fb.height))
        canvas = Image.alpha_composite(canvas, bot_ov)

    # 3. Gradiente
    canvas = Image.alpha_composite(canvas, _gradient(width, height, c["grad_op"], c["grad_soft"]))
    draw   = ImageDraw.Draw(canvas)

    # 4. Barra lateral color
    draw.rectangle([(0, img_h), (lbar_w, height)], fill=(*brand, 255))

    # 5. Watermark logo centro
    try:
        logo_full = Image.open(LOGO_PATH).convert("RGBA")
        wm_w = int(width * c["wm_size"])
        wm_h = int(logo_full.height * wm_w / logo_full.width)
        wm   = logo_full.resize((wm_w, wm_h), Image.LANCZOS)
        wm_a = wm.split()[3].point(lambda p: int(p * c["wm_opacity"]))
        wm.putalpha(wm_a)
        wx   = (width - wm_w) // 2
        wy   = int(height * c["wm_vpos"]) - wm_h // 2
        canvas.paste(wm, (wx, wy), wm)
    except Exception:
        pass

    # 6. Logo arriba izquierda
    try:
        logo_full = Image.open(LOGO_PATH).convert("RGBA")
        lw = int(width * c["logo_w"])
        lh = int(logo_full.height * lw / logo_full.width)
        logo_img = logo_full.resize((lw, lh), Image.LANCZOS)
        canvas.paste(logo_img, (inset, inset), logo_img)
    except Exception:
        pass

    # 7. Badge sección
    badge_text = article.get("seccion", "").upper()
    bfs        = int(width * 0.030)
    bfont      = _font(bfs)
    bpx        = int(width  * 0.034)
    bpy        = int(height * 0.011)
    bb         = draw.textbbox((0, 0), badge_text, font=bfont)
    bw, bh     = bb[2] - bb[0] + bpx * 2, bb[3] - bb[1] + bpy * 2
    bx         = pad + lbar_off
    by         = img_h + cgap
    draw.rounded_rectangle([(bx, by), (bx + bw, by + bh)],
                            radius=bh // 2, fill=(*brand, 255))
    draw.text((bx + bpx, by + bpy), badge_text, font=bfont, fill=(255, 255, 255, 255))

    # 8. Título auto-tamaño
    ty      = by + bh + int(height * 0.010)
    avail_w = int(width * c["title_w"]) - lbar_off - pad
    max_th  = height - ty - footer_h - int(pad * 0.4)
    tf, tls = _fit_title(draw, article.get("titulo", ""),
                         avail_w, max_th,
                         int(width * 0.022), int(width * 0.080))
    tx      = pad + lbar_off
    bb      = draw.textbbox((0, 0), "Ag", font=tf)
    line_h  = int((bb[3] - bb[1]) * 1.22)
    for line in tls:
        draw.text((tx + 2, ty + 2), line, font=tf, fill=(0, 0, 0, 160))
        draw.text((tx,     ty    ), line, font=tf, fill=(255, 255, 255, 255))
        ty += line_h

    # 9. Footer
    fy    = height - footer_h
    fpad  = int(width * 0.038)
    icsz  = int(footer_h * 0.58)
    icy   = fy + (footer_h - icsz) // 2
    gap   = int(icsz * 0.35)

    fb_icon = _svg_icon(FB_ICON_PATH, icsz, brand)
    ig_icon = _svg_icon(IG_ICON_PATH, icsz, brand)
    if fb_icon:
        canvas.paste(fb_icon, (fpad, icy), fb_icon)
    if ig_icon:
        canvas.paste(ig_icon, (fpad + icsz + gap, icy), ig_icon)

    url_text = "www.lavozriojana.com"
    ufs      = max(8, int(footer_h * 0.33))
    ufont    = _font(ufs)
    ubb      = draw.textbbox((0, 0), url_text, font=ufont)
    uw       = ubb[2] - ubb[0]
    uh       = ubb[3] - ubb[1]
    draw.text((width - fpad - uw, fy + (footer_h - uh) // 2),
              url_text, font=ufont, fill=(255, 255, 255, 230))

    return canvas.convert("RGB")


# ── API pública ───────────────────────────────────────────────
def generate_instagram(article: dict) -> Image.Image:
    return generate_post(article, IG_W, IG_H)


def generate_facebook(article: dict) -> Image.Image:
    return generate_post(article, FB_W, FB_H)


def _image_orientation(img: "Image.Image") -> str:
    if img.width > img.height:
        return "landscape"
    if img.height > img.width:
        return "portrait"
    return "square"


def _materialize_image_for_remotion(
    article: dict, *, preloaded_img: "Image.Image | None" = None,
) -> tuple[str | None, str | None, "callable"]:
    """Resuelve la imagen del artículo a un archivo local que Remotion pueda
    leer, junto con su orientación (barata de calcular, ya la tenemos en
    memoria) y un callable de limpieza. Nunca borra un archivo que no creó
    esta función (p.ej. ``article['imagen']`` local ya existente)."""
    noop = lambda: None  # noqa: E731

    if preloaded_img is not None:
        orientation = _image_orientation(preloaded_img)
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        preloaded_img.convert("RGB").save(tmp_path, "JPEG", quality=92)
        return tmp_path, orientation, (lambda: os.unlink(tmp_path))

    local_path = str(article.get("imagen") or "").strip()
    if local_path and os.path.isfile(local_path):
        orientation = None
        try:
            with Image.open(local_path) as opened:
                orientation = _image_orientation(opened)
        except (OSError, ValueError):
            pass
        return local_path, orientation, noop

    image = _download(article.get("imagen_url", ""))
    if image is None:
        return None, None, noop
    orientation = _image_orientation(image)
    fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    image.convert("RGB").save(tmp_path, "JPEG", quality=92)
    return tmp_path, orientation, (lambda: os.unlink(tmp_path))


def _generate_instagram_remotion(article: dict, *, preloaded_img: "Image.Image | None" = None) -> bytes:
    """Renderiza la card automática con la composición Remotion
    ``AutomaticInstagramCard`` (sistema "Editorial Cinemática Riojana", ver
    docs/DECISIONS.md). Lanza ``RemotionRenderError`` si falla — el llamador
    (``generate_instagram_with_engine``) decide si cae a Pillow."""
    from utils.remotion_renderer import render_still

    local_path, orientation, cleanup = _materialize_image_for_remotion(article, preloaded_img=preloaded_img)
    try:
        props = {
            "titulo": article.get("titulo", ""),
            "seccion": article.get("seccion", ""),
            "assetFile": "",
            "highlightTerms": list(article.get("highlight_terms") or article.get("highlightTerms") or []),
        }
        if orientation:
            props["assetOrientation"] = orientation
        asset_paths = {"assetFile": local_path} if local_path else {}
        png_bytes, _metadata = render_still("AutomaticInstagramCard", props, asset_paths=asset_paths)
    finally:
        cleanup()

    with Image.open(io.BytesIO(png_bytes)) as opened:
        buffer = io.BytesIO()
        opened.convert("RGB").save(buffer, format="JPEG", quality=90, optimize=True)
        return buffer.getvalue()


def generate_instagram_with_engine(
    article: dict, preloaded_img: "Image.Image | None" = None,
) -> tuple[bytes, str]:
    """Punto de entrada real de la card automática de Instagram (Editorial
    Cinemática Riojana). Resuelve ``resolve_engine("automatic")`` e intenta
    Remotion primero; cae a ``generate_post``/Pillow (sin tocar esa función)
    si Remotion no está disponible o el render falla. Nunca en silencio —
    mismo patrón que ``utils.premium_renderer.render_package_with_engine``.
    Devuelve ``(jpeg_bytes, engine_used)``."""
    from utils.remotion_renderer import RemotionRenderError, resolve_engine

    engine = resolve_engine("automatic")

    if engine == "remotion_unavailable":
        raise RemotionRenderError(
            "el motor de automatic exige Remotion pero no está disponible en este entorno"
        )

    if engine == "remotion":
        try:
            return _generate_instagram_remotion(article, preloaded_img=preloaded_img), "remotion"
        except RemotionRenderError as exc:
            logger.warning("Remotion falló para la card automática, cae a Pillow: %s", exc)

    img = generate_post(article, IG_W, IG_H, preloaded_img=preloaded_img)
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, "JPEG", quality=90, optimize=True)
    return buffer.getvalue(), "pillow"


def save_for_article(article: dict, article_id: str) -> dict:
    """Genera y guarda imágenes IG + FB. Retorna {'ig': path, 'fb': path}."""
    os.makedirs(POSTS_DIR, exist_ok=True)
    result = {}

    for name, fn in [("ig", generate_instagram), ("fb", generate_facebook)]:
        path = os.path.join(POSTS_DIR, f"{article_id}_{name}.jpg")
        try:
            img = fn(article)
            img.save(path, "JPEG", quality=90, optimize=True)
            result[name] = path
            logger.info(f"Imagen {name.upper()} guardada: {path}")
        except Exception as e:
            logger.error(f"Error generando imagen {name}: {e}")

    return result
