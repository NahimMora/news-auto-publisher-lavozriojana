"""SourceSelector (Parte 24): sólo fuentes plausibles, nunca todas por noticia.

Evita tráfico y procesamiento inútil. Las fuentes nacionales de seguridad
(Gendarmería, PFA, Prefectura) sólo se seleccionan cuando hay una localidad
riojana detectada en la noticia (Parte 19: nunca publicar automáticamente
hechos de todo el país).
"""
from __future__ import annotations

from pathlib import Path

from editorial_context import entities as ec_entities
from sources.registry import SourceDefinition, enabled_sources

# Categoría -> fuentes candidatas (ejemplos explícitos de la Parte 24/27-33).
CATEGORY_SOURCE_IDS: dict[str, tuple[str, ...]] = {
    "policiales": ("mpf_larioja", "justicia_larioja", "policia_larioja", "gendarmeria", "pfa"),
    "politica": (
        "gobierno_larioja", "legislatura_larioja", "secretaria_justicia_larioja",
        "hacienda_larioja", "mpf_larioja", "justicia_larioja",
    ),
    "economia": ("hacienda_larioja", "bcra", "indec", "arca", "anses", "energia_nacion", "senasa"),
    "salud": ("salud_larioja", "salud_nacion", "crilar"),
    "educacion": ("educacion_nacion", "legislatura_larioja"),
    "interior": ("vialidad_nacional", "gobierno_larioja", "agua_energia_larioja", "senasa"),
    "sociedad": ("gobierno_larioja", "smn_news", "smn_alerts", "estadisticas_larioja"),
    "cultura": ("turismo_larioja", "crilar"),
    # Parte 32/33: sin fuentes oficiales nacionales de deportes/espectáculos en esta etapa.
    "deportes": (),
    "espectaculos": (),
}

# Palabras clave -> fuentes adicionales, afinan más allá de la categoría (Parte 24).
KEYWORD_SOURCE_IDS: dict[str, tuple[str, ...]] = {
    "anses": ("anses",),
    "jubilacion": ("anses",),
    "jubilados": ("anses",),
    "bono": ("anses",),
    "inflacion": ("indec",),
    "indec": ("indec",),
    "banco central": ("bcra",),
    "bcra": ("bcra",),
    "tasas": ("bcra",),
    "impuesto": ("arca",),
    "afip": ("arca",),
    "arca": ("arca",),
    "clima": ("smn_news", "smn_alerts"),
    "alerta meteorologica": ("smn_alerts",),
    "temporal": ("smn_news", "smn_alerts"),
    "ruta": ("vialidad_nacional",),
    "vialidad": ("vialidad_nacional",),
    "gendarmeria": ("gendarmeria",),
    "senasa": ("senasa",),
}

# Fuentes nacionales de seguridad: sólo si hay señal riojana concreta (Parte 19).
REQUIRES_RIOJAN_LOCALITY = {"gendarmeria", "pfa", "prefectura", "seguridad_nacion"}


def select_sources(
    *,
    category: str = "",
    localities: list[str] | None = None,
    keywords_text: str = "",
    path: Path | str | None = None,
) -> list[SourceDefinition]:
    registry_by_id = {source.source_id: source for source in enabled_sources(path=path)}
    candidate_ids: set[str] = set(CATEGORY_SOURCE_IDS.get(category, ()))

    lowered_text = ec_entities.ascii_lower(keywords_text)
    for keyword, source_ids in KEYWORD_SOURCE_IDS.items():
        if keyword in lowered_text:
            candidate_ids.update(source_ids)

    has_riojan_locality = bool(
        [locality for locality in (localities or []) if locality not in {"la rioja", "rioja"}]
    ) or bool(localities)

    selected: list[SourceDefinition] = []
    for source_id in candidate_ids:
        source = registry_by_id.get(source_id)
        if source is None:
            continue
        if source_id in REQUIRES_RIOJAN_LOCALITY and not has_riojan_locality:
            continue
        selected.append(source)

    selected.sort(key=lambda source: (source.priority != "CRITICAL", source.priority != "HIGH", source.source_id))
    return selected
