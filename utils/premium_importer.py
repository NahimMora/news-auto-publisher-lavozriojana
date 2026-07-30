"""Importador del paquete preparado manualmente con ChatGPT.

Nunca pierde el contenido pegado: si el JSON es inválido, devuelve errores
por campo y el texto original queda intacto en la UI (responsabilidad del
llamador). Las sugerencias de imagen nunca se asignan en firme: quedan en
``suggested_assets`` para que el operador las confirme o cambie.
"""
from __future__ import annotations

import json

from utils.file_manager import JsonStateError
from utils.premium_contract import SLIDE_TYPES, new_package, new_slide, validate_package

REQUIRED_TOP_FIELDS = ("title", "slides")


def parse_chatgpt_payload(raw_text: str) -> tuple[dict | None, list[str]]:
    """Sólo parsea y valida forma; no crea el draft todavía."""
    errors: list[str] = []
    try:
        payload = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, [f"json_invalido:{exc}"]

    if not isinstance(payload, dict):
        return None, ["json_debe_ser_un_objeto"]

    for field in REQUIRED_TOP_FIELDS:
        if not payload.get(field):
            errors.append(f"campo_requerido_faltante:{field}")

    slides = payload.get("slides")
    if slides is not None and not isinstance(slides, list):
        errors.append("slides_debe_ser_lista")

    return payload, errors


def _suggest_assets(hint: str, *, limit: int = 3) -> list[dict]:
    if not hint or not hint.strip():
        return []
    try:
        from utils.media_library import search_library

        rows = search_library(query=hint, window_days=None)
    except JsonStateError:
        return []
    suggestions = []
    for row in rows[:limit]:
        suggestions.append(
            {
                "resource_id": row.get("resource_id"),
                "asset_id": row.get("asset_id"),
                "titulo": row.get("titulo"),
                "thumbnail": row.get("thumbnail"),
            }
        )
    return suggestions


def import_chatgpt_package(raw_text: str) -> tuple[dict | None, list[str], list[str]]:
    """Devuelve (draft_o_None, errors, warnings)."""
    payload, errors = parse_chatgpt_payload(raw_text)
    if payload is None:
        return None, errors, []
    if errors:
        return None, errors, []

    warnings: list[str] = []
    template = str(payload.get("suggested_template") or "lvr_cronica")

    package = new_package(
        title=str(payload.get("title") or ""),
        caption=str(payload.get("caption") or ""),
        section=str(payload.get("section") or ""),
        template=template,
        sources=list(payload.get("sources") or []),
    )
    package["import_unknowns"] = list(payload.get("unknowns") or [])

    slides = []
    for index, raw_slide in enumerate(payload.get("slides") or []):
        if not isinstance(raw_slide, dict):
            warnings.append(f"slide_{index}_ignorada_formato_invalido")
            continue
        slide_type = str(raw_slide.get("type") or "")
        if slide_type not in SLIDE_TYPES:
            warnings.append(f"slide_{index}_tipo_desconocido:{slide_type}, se usa image_text")
            slide_type = "image_text"

        asset_hint = str(raw_slide.get("asset_hint") or "").strip()
        title_hint = str(raw_slide.get("text") or payload.get("title") or "")
        suggestions = _suggest_assets(asset_hint or title_hint)
        if not suggestions:
            warnings.append(f"slide_{index}_sin_sugerencia_de_imagen")

        slide = new_slide(
            slide_type,
            text=str(raw_slide.get("text") or ""),
            highlights=list(raw_slide.get("highlights") or []),
            source_ids=list(raw_slide.get("source_ids") or []),
        )
        slide["suggested_assets"] = suggestions
        slide["asset_hint"] = asset_hint
        slides.append(slide)

    package["slides"] = slides
    if package.get("template") not in {"lvr_cronica", "lvr_datos", "lvr_visual"}:
        warnings.append(f"suggested_template_desconocido:{template}, se usa lvr_cronica")
        package["template"] = "lvr_cronica"

    contract_errors, contract_warnings = validate_package(package)
    return package, contract_errors, warnings + contract_warnings
