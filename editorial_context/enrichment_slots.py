"""EnrichmentSlot: contexto/cambio/impacto/datos/próximo paso (Parte 14).

Nunca se completan por inferencia libre de Gemini: cada slot sólo queda
``available=True`` cuando hay un fragmento recuperado (archivo propio o
fuente oficial) con provenance que lo respalda. No hace falta completar los
cinco; ninguno lleva subtítulo técnico visible en la nota.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SLOT_CONTEXTO = "CONTEXTO"
SLOT_CAMBIO = "CAMBIO"
SLOT_IMPACTO = "IMPACTO"
SLOT_DATOS = "DATOS"
SLOT_PROXIMO_PASO = "PROXIMO_PASO"
SLOT_TYPES = (SLOT_CONTEXTO, SLOT_CAMBIO, SLOT_IMPACTO, SLOT_DATOS, SLOT_PROXIMO_PASO)

_DATA_PATTERN = re.compile(
    r"(\$\s?\d[\d.,]*|\d[\d.,]*\s?%|\b\d{1,3}(?:[.,]\d{3})+\b|\b\d+\s?(?:millones|mil|kg|km|horas|dias|d[ií]as|a[nñ]os)\b)",
    re.IGNORECASE,
)
_NEXT_STEP_CUES = (
    "a partir del", "a partir de", "comenzara", "comenzará", "se espera",
    "preve", "prevé", "vence el", "proxima", "próxima", "proximo", "próximo",
    "sera", "será", "entrara en vigencia", "entrará en vigencia",
)


@dataclass
class Snippet:
    text: str
    source_url: str = ""
    source_type: str = ""
    confidence: str = "medium"


@dataclass
class EnrichmentSlot:
    type: str
    available: bool = False
    value: str = ""
    source_refs: list[str] = field(default_factory=list)
    confidence: str = "low"
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "available": self.available,
            "value": self.value,
            "source_refs": list(self.source_refs),
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _empty_slot(slot_type: str, reason: str) -> EnrichmentSlot:
    return EnrichmentSlot(type=slot_type, available=False, reason=reason)


def _contexto_slot(archive_snippets: list[Snippet]) -> EnrichmentSlot:
    if not archive_snippets:
        return _empty_slot(SLOT_CONTEXTO, "sin_antecedente_en_archivo")
    best = archive_snippets[0]
    return EnrichmentSlot(
        type=SLOT_CONTEXTO,
        available=True,
        value=best.text,
        source_refs=[url for url in (best.source_url,) if url],
        confidence=best.confidence,
        reason="antecedente_propio",
    )


def _datos_slot(official_snippets: list[Snippet]) -> EnrichmentSlot:
    for snippet in official_snippets:
        match = _DATA_PATTERN.search(snippet.text)
        if match:
            return EnrichmentSlot(
                type=SLOT_DATOS,
                available=True,
                value=snippet.text,
                source_refs=[url for url in (snippet.source_url,) if url],
                confidence=snippet.confidence,
                reason="dato_numerico_en_fuente_oficial",
            )
    return _empty_slot(SLOT_DATOS, "sin_dato_numerico_verificable")


def _proximo_paso_slot(official_snippets: list[Snippet], archive_snippets: list[Snippet]) -> EnrichmentSlot:
    for snippet in (*official_snippets, *archive_snippets):
        lowered = snippet.text.lower()
        if any(cue in lowered for cue in _NEXT_STEP_CUES):
            return EnrichmentSlot(
                type=SLOT_PROXIMO_PASO,
                available=True,
                value=snippet.text,
                source_refs=[url for url in (snippet.source_url,) if url],
                confidence=snippet.confidence,
                reason="mencion_de_proximo_paso_en_fuente",
            )
    return _empty_slot(SLOT_PROXIMO_PASO, "sin_mencion_de_proximo_paso")


def _cambio_slot(current_text: str, archive_snippets: list[Snippet]) -> EnrichmentSlot:
    if not archive_snippets:
        return _empty_slot(SLOT_CAMBIO, "sin_antecedente_para_comparar")
    current_numbers = set(_DATA_PATTERN.findall(current_text))
    for snippet in archive_snippets:
        previous_numbers = set(_DATA_PATTERN.findall(snippet.text))
        diff = previous_numbers - current_numbers
        if diff:
            return EnrichmentSlot(
                type=SLOT_CAMBIO,
                available=True,
                value=f"antes: {'; '.join(sorted(diff))} | ahora: {'; '.join(sorted(current_numbers)) or 'ver nota'}",
                source_refs=[url for url in (snippet.source_url,) if url],
                confidence="medium",
                reason="valores_numericos_distintos_respecto_del_antecedente",
            )
    return _empty_slot(SLOT_CAMBIO, "sin_evidencia_determinista_de_cambio")


def build_enrichment_slots(
    *,
    current_text: str = "",
    archive_snippets: list[Snippet] | None = None,
    official_snippets: list[Snippet] | None = None,
) -> list[EnrichmentSlot]:
    """Evalúa los cinco tipos de valor extra (Parte 14). IMPACTO no tiene señal
    determinística confiable hoy: queda siempre ``available=False`` acá (la
    prosa editorial existente ya lo aborda con criterio humano/Gemini
    supervisado); se deja el slot para no cerrar la extensión futura.
    """
    archive_snippets = archive_snippets or []
    official_snippets = official_snippets or []
    return [
        _contexto_slot(archive_snippets),
        _cambio_slot(current_text, archive_snippets),
        _empty_slot(SLOT_IMPACTO, "sin_senal_deterministica_de_impacto"),
        _datos_slot(official_snippets),
        _proximo_paso_slot(official_snippets, archive_snippets),
    ]
