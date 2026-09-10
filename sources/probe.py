"""Diagnóstico read-only por fuente (Parte 22): ``cli.py source-probe``.

Nunca escribe caché, métricas ni fetch-state local, y nunca publica nada:
sólo hace el GET real a la fuente y reporta qué encontró.
"""
from __future__ import annotations

from sources.registry import get_source
from sources.sync import sync_source


def probe_source(source_id: str) -> dict:
    source = get_source(source_id)
    if source is None:
        raise KeyError(f"source_id desconocido: {source_id}")
    report = sync_source(source, dry_run=True, force=True)
    return report.to_dict()
