import io
import os
import requests
from PIL import Image
from utils.logging_setup import setup_logger

logger = setup_logger("image_processor")

FOTOS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "FotosLVR")
os.makedirs(FOTOS_DIR, exist_ok=True)


def download_image(url: str, dest_path: str, timeout: int = 20) -> bool:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        logger.error(f"Error descargando imagen {url}: {e}")
        return False


def process_image(source: str | bytes, dest_path: str, max_width: int = 1400) -> bool:
    """Redimensiona y guarda imagen JPEG. source puede ser ruta o bytes."""
    try:
        if isinstance(source, (bytes, bytearray)):
            img = Image.open(io.BytesIO(source))
        else:
            img = Image.open(source)

        img = img.convert("RGB")
        w, h = img.size

        if w < 700:
            scale = 700 / w
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            w, h = img.size

        if w > max_width:
            scale = max_width / w
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        img.save(dest_path, "JPEG", quality=82, optimize=True)
        return True
    except Exception as e:
        logger.error(f"Error procesando imagen: {e}")
        return False


def optimize_image(path: str, max_kb: int = 50, min_quality: int = 5) -> bool:
    """Reduce calidad JPEG iterativamente hasta alcanzar max_kb."""
    try:
        img = Image.open(path).convert("RGB")
        quality = 85
        while quality >= min_quality:
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality, optimize=True)
            size_kb = buf.tell() / 1024
            if size_kb <= max_kb:
                with open(path, "wb") as f:
                    f.write(buf.getvalue())
                return True
            quality -= 5
        # Guardar con calidad mínima si sigue siendo grande
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=min_quality, optimize=True)
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        return True
    except Exception as e:
        logger.error(f"Error optimizando imagen {path}: {e}")
        return False


def apply_watermark(image_path: str, watermark_path: str, dest_path: str,
                    position: str = "bottom-right", opacity: float = 0.85,
                    scale: float = 0.18) -> bool:
    """
    Superpone el logo del medio sobre la imagen.
    position: 'bottom-right' | 'bottom-left' | 'bottom-center'
    """
    try:
        from PIL import ImageEnhance
        base = Image.open(image_path).convert("RGBA")
        logo = Image.open(watermark_path).convert("RGBA")

        bw, bh = base.size
        lw = int(bw * scale)
        lh = int(logo.height * lw / logo.width)
        logo = logo.resize((lw, lh), Image.LANCZOS)

        # Aplicar opacidad al logo
        r, g, b, a = logo.split()
        a = a.point(lambda x: int(x * opacity))
        logo.putalpha(a)

        margin = int(bw * 0.02)
        if position == "bottom-right":
            pos = (bw - lw - margin, bh - lh - margin)
        elif position == "bottom-left":
            pos = (margin, bh - lh - margin)
        else:  # bottom-center
            pos = ((bw - lw) // 2, bh - lh - margin)

        base.paste(logo, pos, logo)
        base.convert("RGB").save(dest_path, "JPEG", quality=85, optimize=True)
        return True
    except Exception as e:
        logger.error(f"Error aplicando watermark: {e}")
        return False
