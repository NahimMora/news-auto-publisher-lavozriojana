"""Contrato versionado de publicaciones premium (Fase 3): social-only.

Nunca crea artículo web, nunca depende del CMS y Facebook nunca agrega un
link. El contrato es intencionalmente simple: reordenar/duplicar/eliminar
slides, sin posicionamiento libre pixel a pixel.
"""
from __future__ import annotations

import re
import time
import unicodedata
import uuid
from typing import Any

SCHEMA_VERSION = 1

SLIDE_TYPES = {
    "cover",
    "image_text",
    "full_image",
    "key_points",
    "quote",
    "number",
    "closing",
    "video",  # reservado a futuro; bloqueado en publish() de esta versión
}
IMAGE_REQUIRED_SLIDE_TYPES = {"cover", "image_text", "full_image"}
TEMPLATES = {"lvr_cronica", "lvr_datos", "lvr_visual"}
DESTINATIONS = {"instagram", "facebook"}

MIN_SLIDES = 2
MAX_SLIDES = 10
PRIMARY_MIN_SLIDES = 3
PRIMARY_MAX_SLIDES = 5

MAX_HIGHLIGHT_TERMS = 3
HIGHLIGHT_MAX_TITLE_FRACTION = 0.4


class SlideLimitError(ValueError):
    pass


def _ascii_lower(text: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def new_slide(slide_type: str, **fields: Any) -> dict:
    slide = {
        "id": f"slide_{uuid.uuid4().hex}",
        "type": slide_type,
        "text": "",
        "title": "",
        "items": [],
        "highlights": [],
        "asset_id": "",
        "source_ids": [],
    }
    slide.update(fields)
    return slide


def new_package(
    *,
    title: str = "",
    caption: str = "",
    section: str = "",
    template: str = "lvr_cronica",
    destination: tuple[str, ...] = ("instagram", "facebook"),
    source_item_ids: list[str] | None = None,
    sources: list[dict] | None = None,
) -> dict:
    now = int(time.time())
    return {
        "schema_version": SCHEMA_VERSION,
        "id": uuid.uuid4().hex,
        "workflow": "manual_premium",
        "status": "draft",
        "destination": list(destination),
        "publish_mode": "direct_media",
        "template": template,
        "title": title,
        "caption": caption,
        "section": section,
        "topic_key": "",
        "highlight_terms": [],
        "source_item_ids": list(source_item_ids or []),
        "slides": [],
        "sources": list(sources or []),
        "created_at_ts": now,
        "updated_at_ts": now,
    }


# ── Validación de highlight terms (contrato compartido con Fase 4) ──────

def validate_highlight_terms(title: str, terms: list[str]) -> list[str]:
    """Devuelve *warnings* (no bloqueantes) sobre highlight_terms.

    Reglas: 1-3 expresiones, coincidencia de palabra completa,
    aproximadamente no más del 40% del título.
    """
    warnings: list[str] = []
    if not terms:
        return warnings
    if len(terms) > MAX_HIGHLIGHT_TERMS:
        warnings.append(f"highlight_terms_excede_maximo:{len(terms)}>{MAX_HIGHLIGHT_TERMS}")

    title_norm = _ascii_lower(title)
    covered_chars = 0
    for term in terms:
        term_norm = _ascii_lower(term)
        if not term_norm or not re.search(rf"\b{re.escape(term_norm)}\b", title_norm):
            warnings.append(f"highlight_term_inexistente_en_titulo:{term}")
            continue
        covered_chars += len(term_norm)

    if title_norm and covered_chars / max(1, len(title_norm)) > HIGHLIGHT_MAX_TITLE_FRACTION:
        warnings.append("highlight_terms_exceden_40_por_ciento_del_titulo")
    return warnings


# ── Validación del paquete ────────────────────────────────────────────────

def validate_package(package: dict) -> tuple[list[str], list[str]]:
    """Devuelve (errors, warnings). No muta el paquete."""
    errors: list[str] = []
    warnings: list[str] = []

    if int(package.get("schema_version") or 0) != SCHEMA_VERSION:
        errors.append(f"schema_version_no_soportado:{package.get('schema_version')}")
    if package.get("workflow") != "manual_premium":
        errors.append("workflow_debe_ser_manual_premium")
    if package.get("publish_mode") != "direct_media":
        errors.append("publish_mode_debe_ser_direct_media")

    destination = package.get("destination")
    if not isinstance(destination, list) or not destination:
        errors.append("destination_vacio")
    else:
        invalid = [item for item in destination if item not in DESTINATIONS]
        if invalid:
            errors.append(f"destination_invalido:{invalid}")

    template = package.get("template")
    if template not in TEMPLATES:
        errors.append(f"template_invalido:{template}")

    if not str(package.get("title") or "").strip():
        errors.append("title_vacio")

    slides = package.get("slides")
    if not isinstance(slides, list):
        errors.append("slides_debe_ser_lista")
        slides = []
    count = len(slides)
    if count < MIN_SLIDES or count > MAX_SLIDES:
        errors.append(f"cantidad_de_slides_fuera_de_rango:{count} (permitido {MIN_SLIDES}-{MAX_SLIDES})")
    elif not (PRIMARY_MIN_SLIDES <= count <= PRIMARY_MAX_SLIDES):
        warnings.append(f"cantidad_de_slides_fuera_del_rango_principal:{count} (recomendado 3-5)")

    seen_ids = set()
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            errors.append(f"slide_{index}_invalido")
            continue
        slide_type = slide.get("type")
        if slide_type not in SLIDE_TYPES:
            errors.append(f"slide_{index}_tipo_invalido:{slide_type}")
        if slide_type == "video":
            warnings.append(f"slide_{index}_tipo_video_no_soportado_en_esta_version")
        slide_id = slide.get("id")
        if not slide_id:
            errors.append(f"slide_{index}_sin_id")
        elif slide_id in seen_ids:
            errors.append(f"slide_{index}_id_duplicado:{slide_id}")
        else:
            seen_ids.add(slide_id)
        if slide_type in IMAGE_REQUIRED_SLIDE_TYPES and not str(slide.get("asset_id") or "").strip():
            warnings.append(f"slide_{index}_sin_imagen_asignada")
        if not (slide.get("source_ids") or package.get("sources")):
            warnings.append(f"slide_{index}_sin_fuente")

    warnings.extend(validate_highlight_terms(package.get("title") or "", package.get("highlight_terms") or []))

    return errors, warnings


# ── Edición de slides (mover/duplicar/eliminar/cambiar tipo) ─────────────

def _find_slide_index(package: dict, slide_id: str) -> int:
    for index, slide in enumerate(package.get("slides") or []):
        if isinstance(slide, dict) and slide.get("id") == slide_id:
            return index
    raise KeyError(f"slide no encontrada: {slide_id}")


def add_slide(package: dict, slide_type: str, **fields: Any) -> dict:
    slides = package.setdefault("slides", [])
    if len(slides) >= MAX_SLIDES:
        raise SlideLimitError(f"no se pueden superar {MAX_SLIDES} slides")
    slides.append(new_slide(slide_type, **fields))
    package["updated_at_ts"] = int(time.time())
    return package


def remove_slide(package: dict, slide_id: str) -> dict:
    slides = package.get("slides") or []
    if len(slides) <= MIN_SLIDES:
        raise SlideLimitError(f"no se puede bajar de {MIN_SLIDES} slides")
    index = _find_slide_index(package, slide_id)
    del slides[index]
    package["updated_at_ts"] = int(time.time())
    return package


def duplicate_slide(package: dict, slide_id: str) -> dict:
    slides = package.setdefault("slides", [])
    if len(slides) >= MAX_SLIDES:
        raise SlideLimitError(f"no se pueden superar {MAX_SLIDES} slides")
    index = _find_slide_index(package, slide_id)
    clone = dict(slides[index])
    clone["id"] = f"slide_{uuid.uuid4().hex}"
    slides.insert(index + 1, clone)
    package["updated_at_ts"] = int(time.time())
    return package


def move_slide_up(package: dict, slide_id: str) -> dict:
    slides = package.get("slides") or []
    index = _find_slide_index(package, slide_id)
    if index > 0:
        slides[index - 1], slides[index] = slides[index], slides[index - 1]
        package["updated_at_ts"] = int(time.time())
    return package


def move_slide_down(package: dict, slide_id: str) -> dict:
    slides = package.get("slides") or []
    index = _find_slide_index(package, slide_id)
    if index < len(slides) - 1:
        slides[index + 1], slides[index] = slides[index], slides[index + 1]
        package["updated_at_ts"] = int(time.time())
    return package


def change_slide_type(package: dict, slide_id: str, new_type: str) -> dict:
    if new_type not in SLIDE_TYPES:
        raise ValueError(f"tipo de slide inválido: {new_type}")
    index = _find_slide_index(package, slide_id)
    package["slides"][index]["type"] = new_type
    package["updated_at_ts"] = int(time.time())
    return package
