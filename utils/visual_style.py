"""Flags del sistema visual compartido entre publicaciones manuales y automáticas."""
from __future__ import annotations

import os
from collections.abc import Mapping


AUTOMATIC_MANUAL_VISUAL_STYLE_ENV = "AUTOMATIC_MANUAL_VISUAL_STYLE_ENABLED"
REEL_CINEMATIC_VISUAL_STYLE_ENV = "REEL_CINEMATIC_VISUAL_STYLE_ENABLED"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def automatic_manual_visual_style_enabled(
    values: Mapping[str, str] | None = None,
) -> bool:
    """Indica si el lote automático adopta el paquete visual manual completo.

    El default es ``False`` para que un deploy de código no cambie producción
    hasta que el host active explícitamente el flag del workflow automático.
    """
    env = os.environ if values is None else values
    return str(env.get(AUTOMATIC_MANUAL_VISUAL_STYLE_ENV, "false")).strip().lower() in _TRUE_VALUES


def reel_cinematic_visual_style_enabled(
    values: Mapping[str, str] | None = None,
) -> bool:
    """Indica si el generador manual de Reels usa la composición cinemática v2.

    El default es ``False``: desplegar el código no cambia un render productivo
    hasta que el host active expresamente el flag exclusivo de este workflow.
    """
    env = os.environ if values is None else values
    return str(env.get(REEL_CINEMATIC_VISUAL_STYLE_ENV, "false")).strip().lower() in _TRUE_VALUES


def uses_manual_publication_visual_style(
    article: Mapping[str, object],
    values: Mapping[str, str] | None = None,
) -> bool:
    """True para Publicaciones manuales o para el automático habilitado."""
    if str(article.get("source") or "").strip() == "manual_custom_post":
        return True
    return automatic_manual_visual_style_enabled(values)
