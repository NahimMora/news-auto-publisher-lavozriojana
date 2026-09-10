"""Paso B del retrieval: relation scoring explicable (sin embeddings, sin IA).

Fórmula determinística y testeable (Parte 7/10 del plan). Los pesos no son
sagrados: están pensados para ser ajustados con evidencia de tests, no como
requisito matemático.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from editorial_context import entities as ec_entities
from editorial_context.archive_index import ArchiveArticle

_GENERIC_TERM_WORDS = {
    "incendio", "accidente", "policia", "gobierno", "partido", "choque",
    "temporal", "operativo", "denuncia", "comunicado", "noticia", "ultimo",
    "momento", "provincia", "municipio", "informe", "reporte", "situacion",
    "caso", "hecho", "nota", "para", "con", "sus", "este", "esta", "fue",
    "son", "fueron", "fue", "fue", "por", "fue",
}
_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+")

# Categorías que requieren evidencia doble (entidad + término compartido) para
# no agrupar por la sola coincidencia de una persona/lugar (Parte 10, 27, 33).
STRICT_RELATION_CATEGORIES = {"policiales", "espectaculos", "deportes"}

DEFAULT_RELATION_THRESHOLD = 0.45
STRICT_RELATION_THRESHOLD = 0.55


@dataclass
class RelationScore:
    candidate: ArchiveArticle
    score: float
    reasons: list[str] = field(default_factory=list)
    matched_entities: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    matched_localities: list[str] = field(default_factory=list)
    time_distance_days: float | None = None
    confidence: str = "low"

    @property
    def relation_reason(self) -> str:
        return ";".join(self.reasons)

    def meets_category_bar(self, category: str) -> bool:
        threshold = STRICT_RELATION_THRESHOLD if category in STRICT_RELATION_CATEGORIES else DEFAULT_RELATION_THRESHOLD
        if self.score < threshold:
            return False
        if category in STRICT_RELATION_CATEGORIES:
            # Misma persona/equipo/artista sola no alcanza: hace falta además
            # un término temático compartido (misma causa, mismo torneo,
            # mismo evento concreto), no sólo la coincidencia de nombre.
            return bool(self.matched_entities) and bool(self.matched_terms)
        return bool(self.matched_entities or self.matched_localities)


def significant_terms(*texts: str, exclude: set[str] | None = None) -> set[str]:
    # Excluye tanto la entidad completa normalizada ("maria becerra") como
    # cada palabra que la compone ("maria", "becerra"): si no se excluyen
    # las palabras sueltas, el nombre de la entidad se filtra igual como
    # "término compartido" y rompe la exigencia de evidencia doble en
    # categorías estrictas (Parte 10/33: mismo famoso no alcanza).
    exclude_norm: set[str] = set()
    for term in (exclude or set()):
        normalized = ec_entities.normalize_entity(term)
        exclude_norm.add(normalized)
        exclude_norm.update(normalized.split())
    blob = " ".join(str(t or "") for t in texts)
    tokens = {
        ec_entities.normalize_entity(match.group(0))
        for match in _WORD_RE.finditer(blob)
        if len(match.group(0)) >= 5
    }
    return {
        token
        for token in tokens
        if token not in _GENERIC_TERM_WORDS and token not in exclude_norm
    }


def _parse_timestamp(value: str) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def score_candidate(
    *,
    probe_title: str,
    probe_excerpt: str = "",
    probe_entities: list[str] | None = None,
    probe_localities: list[str] | None = None,
    probe_category: str = "",
    probe_published_at: str = "",
    candidate: ArchiveArticle,
) -> RelationScore:
    if probe_entities is None:
        probe_entities = ec_entities.extract_entities(probe_title, probe_excerpt)
    if probe_localities is None:
        probe_localities = ec_entities.extract_localities(probe_title, probe_excerpt)
    probe_entities_norm = {ec_entities.normalize_entity(e) for e in probe_entities}
    probe_localities_norm = set(probe_localities)

    candidate_entities = candidate.entities or ec_entities.extract_entities(candidate.title, candidate.excerpt)
    candidate_localities = candidate.localities or ec_entities.extract_localities(candidate.title, candidate.excerpt)
    candidate_entities_norm = {ec_entities.normalize_entity(e) for e in candidate_entities}
    candidate_localities_norm = set(candidate_localities)

    matched_entities = sorted(probe_entities_norm & candidate_entities_norm)
    matched_localities = sorted(probe_localities_norm & candidate_localities_norm)
    specific_localities = [loc for loc in matched_localities if loc not in {"la rioja", "rioja"}]

    probe_terms = significant_terms(probe_title, probe_excerpt, exclude=probe_entities_norm)
    candidate_terms = significant_terms(candidate.title, candidate.excerpt, exclude=candidate_entities_norm)
    matched_terms = sorted(probe_terms & candidate_terms)

    score = 0.0
    reasons: list[str] = []

    if matched_entities:
        score += min(len(matched_entities), 2) * 0.35
        reasons.append(f"same_entity:{','.join(matched_entities[:3])}")

    if specific_localities:
        score += min(len(specific_localities), 2) * 0.15
        reasons.append(f"same_locality:{','.join(specific_localities[:2])}")
    elif matched_localities:
        score += 0.05
        reasons.append("same_province_wide_locality")

    if probe_category and probe_category == candidate.category:
        score += 0.10
        reasons.append(f"same_category:{probe_category}")

    if matched_terms:
        score += min(len(matched_terms), 3) * 0.05
        reasons.append(f"shared_significant_terms:{','.join(matched_terms[:3])}")

    time_distance_days: float | None = None
    probe_ts = _parse_timestamp(probe_published_at)
    candidate_ts = _parse_timestamp(candidate.published_at)
    if probe_ts is not None and candidate_ts is not None:
        time_distance_days = abs(probe_ts - candidate_ts) / 86400.0
        recency_bonus = max(0.0, 0.15 - (time_distance_days / 60.0) * 0.15)
        if recency_bonus > 0.0:
            score += recency_bonus
            reasons.append(f"date_distance:{time_distance_days:.1f}d")

    score = min(round(score, 4), 1.0)
    if score >= 0.6:
        confidence = "high"
    elif score >= 0.35:
        confidence = "medium"
    else:
        confidence = "low"

    return RelationScore(
        candidate=candidate,
        score=score,
        reasons=reasons,
        matched_entities=matched_entities,
        matched_terms=matched_terms,
        matched_localities=matched_localities,
        time_distance_days=time_distance_days,
        confidence=confidence,
    )


def rank_candidates(
    candidates: list[ArchiveArticle],
    *,
    probe_title: str,
    probe_excerpt: str = "",
    probe_entities: list[str] | None = None,
    probe_localities: list[str] | None = None,
    probe_category: str = "",
    probe_published_at: str = "",
) -> list[RelationScore]:
    scored = [
        score_candidate(
            probe_title=probe_title,
            probe_excerpt=probe_excerpt,
            probe_entities=probe_entities,
            probe_localities=probe_localities,
            probe_category=probe_category,
            probe_published_at=probe_published_at,
            candidate=candidate,
        )
        for candidate in candidates
    ]
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored
