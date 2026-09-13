"""Contrato normalizado de fuentes oficiales (Parte 50).

Toda estrategia de descubrimiento (RSS, sitemap, HTML index, JSON-LD) debe
devolver una lista de ``OfficialSourceItem``, nunca la página entera.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OfficialSourceItem:
    source_id: str
    title: str
    url: str
    published_at: str = ""
    updated_at: str = ""
    excerpt: str = ""
    body: str = ""
    category: str = ""
    entities: list[str] = field(default_factory=list)
    location: str = ""
    raw_metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "updated_at": self.updated_at,
            "excerpt": self.excerpt,
            "body": self.body,
            "category": self.category,
            "entities": list(self.entities),
            "location": self.location,
            "raw_metadata": dict(self.raw_metadata),
        }
