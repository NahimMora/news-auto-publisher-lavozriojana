"""ContextDepth: cuánto contexto agregar por nota (Parte 13).

Decisión 100% determinística (sin llamadas de IA extra, Parte 45). Default
``LIGHT``; sólo sube a ``STANDARD``/``STORY`` con evidencia suficiente y puede
bajar a ``NONE`` cuando no hay nada útil.
"""
from __future__ import annotations

from enum import Enum


class ContextDepth(str, Enum):
    NONE = "NONE"
    LIGHT = "LIGHT"
    STANDARD = "STANDARD"
    STORY = "STORY"


DEFAULT_DEPTH = ContextDepth.LIGHT

# Palabras aproximadas de contexto adicional permitidas en el cuerpo (Parte 13).
WORD_BUDGET = {
    ContextDepth.NONE: 0,
    ContextDepth.LIGHT: 120,
    ContextDepth.STANDARD: 220,
    # STORY: la redacción sigue enfocada en el hecho actual; el timeline vive
    # como UI separada, no agrega más palabras al cuerpo que STANDARD.
    ContextDepth.STORY: 220,
}

# Máximo de notas previas del archivo propio citadas en el cuerpo (Parte 35).
MAX_ARCHIVE_ITEMS = {
    ContextDepth.NONE: 0,
    ContextDepth.LIGHT: 1,
    ContextDepth.STANDARD: 3,
    ContextDepth.STORY: 3,
}


def decide_depth(
    *,
    best_archive_score: float = 0.0,
    archive_item_count: int = 0,
    has_official_context: bool = False,
    has_strong_story: bool = False,
) -> ContextDepth:
    """Regla explicable: no requiere que el archivo tenga match para publicar
    (Parte 53); simplemente decide cuánto contexto agregar si lo hay.
    """
    if has_strong_story:
        return ContextDepth.STORY
    if archive_item_count == 0 and not has_official_context:
        return ContextDepth.NONE
    if best_archive_score >= 0.6 or (archive_item_count >= 2 and best_archive_score >= 0.45):
        return ContextDepth.STANDARD
    if best_archive_score >= 0.35 or has_official_context:
        return ContextDepth.LIGHT
    return ContextDepth.NONE
