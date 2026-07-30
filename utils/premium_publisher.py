"""Orquestador social-only de publicaciones premium (Fase 3).

Nunca crea artículo web, nunca llama al publisher del CMS, nunca produce
``web_url`` ni depende de una publicación web exitosa. Instagram siempre
publica como carrusel (2-10 slides); Facebook usa media directa sin link.

Resultados parciales: si un canal publica y el otro falla, el paquete queda
``degraded`` conservando el ID del canal exitoso (nunca se reintenta) y
permitiendo reintentar sólo el canal fallido. Un resultado ambiguo
(``network_error``, outcome desconocido) nunca se reintenta automáticamente.
"""
from __future__ import annotations

import os
import time

from utils.logging_setup import setup_logger
from utils.premium_contract import validate_package
from utils.premium_post_queue import get_package, update_package_fields
from utils.premium_renderer import render_package_with_engine

logger = setup_logger("premium_publisher", "premium_publisher.log")


def _dry_run_enabled() -> bool:
    return str(os.getenv("PREMIUM_PUBLISH_DRY_RUN", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "si",
        "sí",
    }


def _channel_result_from_operation(operation) -> dict:
    outcome = operation.details.get("publication_outcome")
    ambiguous = operation.error_type in {"network_error", "server_error"} and outcome in {None, "unknown"}
    return {
        "ok": operation.ok,
        "external_id": operation.external_id,
        "deduplicated": operation.deduplicated,
        "error_type": operation.error_type,
        "retryable": operation.retryable,
        "requires_reconciliation": ambiguous,
        "next_retry_at": operation.next_retry_at,
        "updated_at_ts": int(time.time()),
    }


def _publish_instagram(package: dict, slide_images: list[bytes]) -> dict:
    from meta.ig_client import post_premium_carousel_to_instagram

    operation = post_premium_carousel_to_instagram(package, slide_images)
    return _channel_result_from_operation(operation)


def _publish_facebook(package: dict, slide_images: list[bytes]) -> dict:
    from meta.fb_client import post_premium_direct_media_to_facebook

    operation = post_premium_direct_media_to_facebook(package, slide_images)
    return _channel_result_from_operation(operation)


_PUBLISHERS = {"instagram": _publish_instagram, "facebook": _publish_facebook}


def _render_for_publish(package: dict) -> tuple[list[bytes], list[str], str | None]:
    """Envuelve ``render_package_with_engine``: si el modo es
    ``STATIC_RENDER_ENGINE=remotion`` explícito y no está disponible, se
    reporta como fallo en vez de dejar propagar la excepción."""
    from utils.remotion_renderer import RemotionRenderError

    try:
        images, warnings, engine = render_package_with_engine(package)
        return images, warnings, engine
    except RemotionRenderError as exc:
        logger.error("Render Remotion obligatorio no disponible: %s", exc)
        return [], [f"render_engine_unavailable:{exc}"], None


def _overall_status(channel_results: dict[str, dict]) -> str:
    oks = [result.get("ok") for result in channel_results.values()]
    if all(oks):
        return "published"
    if any(oks):
        return "degraded"
    return "failed"


def publish_package(package_id: str) -> dict:
    package = get_package(package_id)
    if package is None:
        raise KeyError(f"paquete no encontrado: {package_id}")

    errors, _warnings = validate_package(package)
    video_slides = [slide for slide in package.get("slides") or [] if slide.get("type") == "video"]
    if video_slides:
        errors.append("slides_de_video_no_soportados_en_esta_version")
    if errors:
        update_package_fields(package_id, status="failed", validation_errors=errors)
        return {"status": "failed", "errors": errors, "channel_results": {}}

    if _dry_run_enabled():
        logger.info("PREMIUM_PUBLISH_DRY_RUN activo: no se llama a ninguna API real")
        channel_results = {
            channel: {"ok": True, "external_id": f"dry-run-{channel}", "deduplicated": False}
            for channel in package.get("destination") or []
        }
        update_package_fields(package_id, status="published", channel_results=channel_results, dry_run=True)
        return {"status": "published", "channel_results": channel_results, "dry_run": True}

    slide_images, render_warnings, engine_used = _render_for_publish(package)
    if engine_used is None:
        update_package_fields(package_id, status="failed", validation_errors=render_warnings)
        return {"status": "failed", "errors": render_warnings, "channel_results": {}}
    missing_required = [w for w in render_warnings if w.endswith("_sin_imagen")]
    if missing_required:
        update_package_fields(package_id, status="failed", validation_errors=missing_required)
        return {"status": "failed", "errors": missing_required, "channel_results": {}}

    existing_results = dict(package.get("channel_results") or {})
    channel_results: dict[str, dict] = {}
    for channel in package.get("destination") or []:
        prior = existing_results.get(channel)
        if isinstance(prior, dict) and prior.get("ok"):
            channel_results[channel] = prior  # nunca se reintenta un canal ya exitoso
            continue
        publisher = _PUBLISHERS.get(channel)
        if publisher is None:
            channel_results[channel] = {"ok": False, "error_type": "unknown_channel"}
            continue
        channel_results[channel] = publisher(package, slide_images)

    status = _overall_status(channel_results)
    update_package_fields(
        package_id,
        status=status,
        channel_results=channel_results,
        render_warnings=render_warnings,
        render_engine=engine_used,
    )
    return {
        "status": status,
        "channel_results": channel_results,
        "render_warnings": render_warnings,
        "render_engine": engine_used,
    }


def retry_channel(package_id: str, channel: str, *, force: bool = False) -> dict:
    """Reintenta sólo el canal indicado. Se niega si ya fue exitoso o si
    quedó en un estado ambiguo sin confirmación explícita del operador."""
    package = get_package(package_id)
    if package is None:
        raise KeyError(f"paquete no encontrado: {package_id}")
    if channel not in (package.get("destination") or []):
        raise ValueError(f"canal no forma parte del paquete: {channel}")

    existing_results = dict(package.get("channel_results") or {})
    prior = existing_results.get(channel)
    if isinstance(prior, dict):
        if prior.get("ok"):
            return {"status": "no_work", "reason": "already_published", "channel_results": existing_results}
        if prior.get("requires_reconciliation") and not force:
            return {
                "status": "blocked",
                "reason": "ambiguous_outcome_requires_manual_reconciliation",
                "channel_results": existing_results,
            }

    if _dry_run_enabled():
        existing_results[channel] = {"ok": True, "external_id": f"dry-run-{channel}", "deduplicated": False}
    else:
        slide_images, render_warnings, engine_used = _render_for_publish(package)
        if engine_used is None:
            return {"status": "blocked", "reason": "render_engine_unavailable", "channel_results": existing_results}
        publisher = _PUBLISHERS.get(channel)
        if publisher is None:
            raise ValueError(f"canal desconocido: {channel}")
        existing_results[channel] = publisher(package, slide_images)
        existing_results[channel]["render_warnings"] = render_warnings

    status = _overall_status(existing_results)
    update_package_fields(package_id, status=status, channel_results=existing_results)
    return {"status": status, "channel_results": existing_results}
