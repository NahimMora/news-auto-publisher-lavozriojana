from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps

from pipeline.node_webapp.editorial import clean_text, source_display_name
from utils import r2_storage
from utils.logging_setup import setup_logger

logger = setup_logger("node_webapp.media", "publish_web.log")

ROOT_DIR = Path(__file__).resolve().parents[2]
MEDIA_WORK_DIR = ROOT_DIR / "output" / "web_media"


@dataclass
class MediaResult:
    ok: bool
    main_image: dict | None = None
    og_image_url: str | None = None
    warnings: list[str] = field(default_factory=list)


def _is_http_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _media_work_dir() -> Path:
    MEDIA_WORK_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_WORK_DIR


def _sha1_file(path: Path, *extra: str) -> str:
    digest = hashlib.sha1()
    for value in extra:
        digest.update(str(value or "").encode("utf-8", errors="ignore"))
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date_parts(noticia: dict) -> tuple[str, str]:
    raw = str(noticia.get("fecha") or noticia.get("published_at") or "").strip()
    parsed: datetime | None = None
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is None:
        parsed = datetime.now(timezone.utc)
    return f"{parsed.year:04d}", f"{parsed.month:02d}"


def slugify(value: str, *, max_chars: int = 72) -> str:
    import unicodedata

    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_chars].strip("-") or "noticia"


def _download_remote_image(url: str) -> Path | None:
    if not _is_http_url(url):
        return None
    try:
        response = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
        if not content_type.startswith("image/"):
            logger.error("Remote image is not image/*: %s content_type=%s", url, content_type)
            return None
        ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(content_type, ".img")
        digest = hashlib.sha1((url + str(time.time())).encode("utf-8")).hexdigest()[:16]
        dest = _media_work_dir() / f"download_{digest}{ext}"
        dest.write_bytes(response.content)
        return dest
    except Exception as exc:
        logger.error("Could not download image %s: %s", url, exc)
        return None


def resolve_source_image(noticia: dict) -> tuple[Path | None, str]:
    for field_name in ("imagen_optimizada", "imagen"):
        raw = str(noticia.get(field_name) or "").strip()
        if raw:
            path = Path(raw)
            if path.exists() and path.is_file():
                return path, field_name
            logger.warning("Image field %s points to missing file: %s", field_name, raw)

    url = str(noticia.get("imagen_url") or "").strip()
    downloaded = _download_remote_image(url)
    if downloaded:
        return downloaded, "imagen_url"
    return None, "missing"


def convert_main_image_to_webp(source_path: Path, noticia: dict) -> tuple[Path, int, int, str]:
    digest = _sha1_file(source_path, str(noticia.get("canonical_url") or noticia.get("url") or ""))[:20]
    dest = _media_work_dir() / f"{digest}.webp"

    with Image.open(source_path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        width, height = img.size
        img.save(dest, "WEBP", quality=86, method=6)

    return dest, width, height, digest


def generate_og_image(source_path: Path, digest: str, title: str, noticia: dict | None = None) -> Path:
    from layout.image_generator import generate_post, FB_W, FB_H

    slug = slugify(title)
    dest = _media_work_dir() / f"og_{slug}_{digest[:10]}.jpg"
    with Image.open(source_path) as raw:
        raw = ImageOps.exif_transpose(raw).convert("RGBA")
        article = {
            "titulo": title,
            "seccion": (noticia or {}).get("seccion", ""),
            "imagen_url": "",
        }
        result = generate_post(article, FB_W, FB_H, preloaded_img=raw)
    result.save(dest, "JPEG", quality=88, optimize=True, progressive=True)
    return dest


def _response_is_public_image(response: requests.Response) -> bool:
    content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
    return response.status_code == 200 and content_type.startswith("image/")


def verify_public_image_url(url: str) -> bool:
    if not _is_http_url(url):
        return False

    enabled = os.getenv("WEB_PUBLIC_MEDIA_CHECK_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        logger.warning("Public image verification disabled; trusting URL: %s", url)
        return True

    attempts = int(os.getenv("WEB_PUBLIC_MEDIA_CHECK_ATTEMPTS", "3"))
    initial_delay = float(os.getenv("WEB_PUBLIC_MEDIA_CHECK_INITIAL_DELAY_SECONDS", "0"))
    retry_sleep = float(os.getenv("WEB_PUBLIC_MEDIA_CHECK_RETRY_SLEEP_SECONDS", "2"))

    if initial_delay > 0:
        time.sleep(initial_delay)

    for attempt in range(1, attempts + 1):
        try:
            head = requests.head(url, timeout=12, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            if _response_is_public_image(head):
                return True
            get = requests.get(
                url,
                timeout=12,
                stream=True,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            try:
                if _response_is_public_image(get):
                    return True
            finally:
                get.close()
        except Exception as exc:
            logger.warning("Public image check attempt %s/%s failed for %s: %s", attempt, attempts, url, exc)
        if attempt < attempts:
            time.sleep(retry_sleep)
    return False


def upload_main_image(noticia: dict) -> tuple[dict, Path, str]:
    source_path, source_kind = resolve_source_image(noticia)
    if not source_path:
        raise RuntimeError("missing_main_image")

    webp_path, width, height, digest = convert_main_image_to_webp(source_path, noticia)
    year, month = _date_parts(noticia)
    key = f"noticias/{year}/{month}/{digest}.webp"
    url, _object_key = r2_storage.upload_file(
        str(webp_path),
        key,
        "image/webp",
        cache_control="public, max-age=31536000, immutable",
    )
    if not verify_public_image_url(url):
        raise RuntimeError(f"main_image_not_public:{url}")

    title = clean_text(noticia.get("titulo") or noticia.get("titulo_original") or "Noticia", max_chars=150)
    source_name = source_display_name(noticia)
    main_image = {
        "url": url,
        "width": width,
        "height": height,
        "alt": title,
        "caption": clean_text(noticia.get("titulo_original") or title, max_chars=180),
        "credit": source_name,
    }
    logger.info("Main image uploaded source=%s key=%s size=%sx%s", source_kind, key, width, height)
    return main_image, webp_path, digest


def upload_og_image(source_webp_path: Path, digest: str, title: str, fallback_url: str, noticia: dict | None = None) -> str:
    if os.getenv("ENABLE_R2_OG_IMAGE", "true").lower() not in {"1", "true", "yes", "on"}:
        return fallback_url

    try:
        og_path = generate_og_image(source_webp_path, digest, title, noticia)
        slug = slugify(title)
        key = f"og/{slug}-{digest[:10]}.jpg"
        url, _object_key = r2_storage.upload_file(
            str(og_path),
            key,
            "image/jpeg",
            cache_control="public, max-age=31536000, immutable",
        )
        if verify_public_image_url(url):
            logger.info("OG image uploaded key=%s", key)
            return url
        logger.warning("OG image was uploaded but not publicly verified, using main image")
    except Exception as exc:
        logger.warning("OG image generation/upload failed, using main image: %s", exc)
    return fallback_url


def prepare_media(noticia: dict, title: str) -> MediaResult:
    try:
        main_image, webp_path, digest = upload_main_image(noticia)
        og_image_url = upload_og_image(webp_path, digest, title, main_image["url"], noticia)
        return MediaResult(ok=True, main_image=main_image, og_image_url=og_image_url)
    except Exception as exc:
        logger.error("Media preparation failed for %s: %s", clean_text(noticia.get("titulo"), max_chars=70), exc)
        return MediaResult(ok=False, warnings=[str(exc)])
