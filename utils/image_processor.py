import io
import os
import tempfile
import requests
from PIL import Image
from utils.logging_setup import setup_logger
from utils.paths import photos_dir
from utils.safe_http import safe_get

logger = setup_logger("image_processor", "image_processor.log")

FOTOS_DIR = str(photos_dir())
os.makedirs(FOTOS_DIR, exist_ok=True)


def download_image(url: str, dest_path: str, timeout: int = 20) -> bool:
    tmp_path = ""
    try:
        r = safe_get(
            url,
            requester=requests.get,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
            stream=True,
        )
        r.raise_for_status()
        content_type = str(r.headers.get("Content-Type") or "").lower()
        if not content_type.startswith("image/"):
            raise ValueError("La respuesta remota no es image/*")
        max_bytes = int(os.getenv("IMAGE_DOWNLOAD_MAX_BYTES", str(20 * 1024 * 1024)))
        parent = os.path.dirname(os.path.abspath(dest_path))
        os.makedirs(parent, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".imagen-", suffix=".tmp", dir=parent)
        total = 0
        with os.fdopen(fd, "wb") as handle:
            for chunk in r.iter_content(64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("La imagen supera IMAGE_DOWNLOAD_MAX_BYTES")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, dest_path)
        tmp_path = ""
        return True
    except Exception as e:
        logger.error(f"Error descargando imagen {url}: {e}")
        return False
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


def process_image(source: str | bytes, dest_path: str, max_width: int | None = None) -> bool:
    """Redimensiona y guarda imagen JPEG. source puede ser ruta o bytes."""
    try:
        if isinstance(source, (bytes, bytearray)):
            img = Image.open(io.BytesIO(source))
        else:
            img = Image.open(source)

        img.verify()
        if isinstance(source, (bytes, bytearray)):
            img = Image.open(io.BytesIO(source))
        else:
            img = Image.open(source)
        img = img.convert("RGB")
        w, h = img.size
        max_pixels = int(os.getenv("IMAGE_MAX_PIXELS", "40000000"))
        if w <= 0 or h <= 0 or w * h > max_pixels:
            raise ValueError("Dimensiones de imagen inválidas o excesivas")
        min_width = int(os.getenv("IMAGE_MIN_WIDTH", "700"))
        max_width = max_width or int(os.getenv("IMAGE_MAX_WIDTH", "1400"))

        if w < min_width:
            scale = min_width / w
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


def optimize_image(path: str, max_kb: int | None = None, min_quality: int | None = None) -> bool:
    """Reduce calidad JPEG iterativamente hasta alcanzar max_kb."""
    try:
        img = Image.open(path).convert("RGB")
        max_kb = max_kb or int(os.getenv("IMAGE_MAX_FILESIZE_KB", "250"))
        min_quality = min_quality or int(os.getenv("IMAGE_MIN_QUALITY", "5"))
        quality = int(os.getenv("IMAGE_JPEG_QUALITY", "85"))
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
