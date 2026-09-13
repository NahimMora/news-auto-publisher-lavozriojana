"""Source Registry configurable (Parte 17): contrato común, no scripts sueltos.

Los datos viven en ``config/official_sources.json`` (fuera de código) para
poder ajustar prioridad/enabled/poll_ttl sin tocar Python.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from utils.paths import ROOT_DIR

DEFAULT_REGISTRY_PATH = ROOT_DIR / "config" / "official_sources.json"

VALID_MODES = {"DISCOVERY", "ENRICHMENT", "BOTH", "REFERENCE_ONLY"}


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    name: str
    scheme: str
    host: str
    path: str
    source_type: str = ""
    scope: str = ""
    categories: tuple[str, ...] = ()
    priority: str = "MEDIUM"
    mode: str = "BOTH"
    enabled: bool = False
    discovery_strategy: str = "UNCONFIRMED"
    fetch_strategy: str = "none"
    poll_ttl: int = 3600
    request_delay: float = 1.0
    allowed_hosts: tuple[str, ...] = ()
    max_items_per_cycle: int = 10
    notes: str = ""

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.host}{self.path}"

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "scheme": self.scheme,
            "host": self.host,
            "path": self.path,
            "source_type": self.source_type,
            "scope": self.scope,
            "categories": list(self.categories),
            "priority": self.priority,
            "mode": self.mode,
            "enabled": self.enabled,
            "discovery_strategy": self.discovery_strategy,
            "fetch_strategy": self.fetch_strategy,
            "poll_ttl": self.poll_ttl,
            "request_delay": self.request_delay,
            "allowed_hosts": list(self.allowed_hosts),
            "max_items_per_cycle": self.max_items_per_cycle,
            "notes": self.notes,
            "url": self.url,
        }


def _source_from_raw(raw: dict) -> SourceDefinition:
    mode = str(raw.get("mode") or "BOTH").upper()
    if mode not in VALID_MODES:
        raise ValueError(f"mode inválido para {raw.get('source_id')}: {mode}")
    return SourceDefinition(
        source_id=str(raw["source_id"]),
        name=str(raw.get("name") or raw["source_id"]),
        scheme=str(raw.get("scheme") or "https"),
        host=str(raw["host"]),
        path=str(raw.get("path") or "/"),
        source_type=str(raw.get("source_type") or ""),
        scope=str(raw.get("scope") or ""),
        categories=tuple(raw.get("categories") or ()),
        priority=str(raw.get("priority") or "MEDIUM").upper(),
        mode=mode,
        enabled=bool(raw.get("enabled", False)),
        discovery_strategy=str(raw.get("discovery_strategy") or "UNCONFIRMED"),
        fetch_strategy=str(raw.get("fetch_strategy") or "none"),
        poll_ttl=int(raw.get("poll_ttl") or 3600),
        request_delay=float(raw.get("request_delay") or 1.0),
        allowed_hosts=tuple(raw.get("allowed_hosts") or (str(raw["host"]),)),
        max_items_per_cycle=int(raw.get("max_items_per_cycle") or 10),
        notes=str(raw.get("notes") or ""),
    )


def load_registry(path: Path | str | None = None) -> list[SourceDefinition]:
    resolved = Path(path) if path else DEFAULT_REGISTRY_PATH
    with open(resolved, "r", encoding="utf-8") as handle:
        raw_items = json.load(handle)
    if not isinstance(raw_items, list):
        raise ValueError(f"{resolved} debe contener una lista de fuentes")

    sources = [_source_from_raw(item) for item in raw_items]
    seen_ids = set()
    for source in sources:
        if source.source_id in seen_ids:
            raise ValueError(f"source_id duplicado en el registry: {source.source_id}")
        seen_ids.add(source.source_id)
    return sources


def get_source(source_id: str, *, path: Path | str | None = None) -> SourceDefinition | None:
    for source in load_registry(path):
        if source.source_id == source_id:
            return source
    return None


def enabled_sources(*, path: Path | str | None = None) -> list[SourceDefinition]:
    return [source for source in load_registry(path) if source.enabled]
