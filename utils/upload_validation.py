"""Validación de contenido de uploads, además de extensión y tamaño."""
from __future__ import annotations

import io
import os

from PIL import Image, UnidentifiedImageError


class InvalidUploadError(ValueError):
    pass


_IMAGE_FORMATS = {
    ".jpg": {"JPEG"},
    ".jpeg": {"JPEG"},
    ".png": {"PNG"},
    ".webp": {"WEBP"},
    ".gif": {"GIF"},
}

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}


def _validate_image(content: bytes, extension: str) -> None:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            image_format = str(image.format or "").upper()
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise InvalidUploadError("El archivo no contiene una imagen válida") from exc

    if image_format not in _IMAGE_FORMATS.get(extension, set()):
        raise InvalidUploadError(
            f"El contenido {image_format or 'desconocido'} no coincide con {extension}"
        )
    if width <= 0 or height <= 0 or width > 12000 or height > 12000:
        raise InvalidUploadError("Dimensiones de imagen fuera de rango")
    if width * height > 50_000_000:
        raise InvalidUploadError("La imagen excede 50 megapíxeles")


def _validate_video(content: bytes, extension: str) -> None:
    if extension == ".webm":
        valid = content.startswith(b"\x1a\x45\xdf\xa3")
    else:
        # ISO Base Media File Format (MP4/MOV/M4V): box `ftyp` al inicio.
        valid = len(content) >= 12 and content[4:8] == b"ftyp"
    if not valid:
        raise InvalidUploadError(f"El contenido no coincide con un video {extension}")


def validate_upload_content(content: bytes, filename: str, kind: str) -> None:
    if not isinstance(content, (bytes, bytearray)) or not content:
        raise InvalidUploadError("El archivo está vacío")
    extension = os.path.splitext(str(filename or ""))[1].lower()
    if kind == "image":
        if extension not in _IMAGE_FORMATS:
            raise InvalidUploadError(f"Extensión de imagen no permitida: {extension}")
        _validate_image(bytes(content), extension)
        return
    if kind == "video":
        if extension not in _VIDEO_EXTENSIONS:
            raise InvalidUploadError(f"Extensión de video no permitida: {extension}")
        _validate_video(bytes(content), extension)
        return
    raise InvalidUploadError(f"Tipo de upload desconocido: {kind}")
