"""Story Engine: agrupación conservadora de notas en historias (Partes 9/10).

Nunca agrupa por sola coincidencia de categoría o localidad genérica. Para
categorías sensibles (policiales, espectáculos, deportes) exige evidencia
doble: misma entidad Y mismo término temático compartido (ver
``retrieval.STRICT_RELATION_CATEGORIES``).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from editorial_context import archive_index as ai
from editorial_context import retrieval
from editorial_context.archive_index import ArchiveArticle
from editorial_context.retrieval import RelationScore
from utils.logging_setup import setup_logger

logger = setup_logger("editorial_context.story_engine", "editorial_context.log")


@dataclass
class StoryAssignment:
    story_key: str
    relations: list[RelationScore] = field(default_factory=list)
    created_new: bool = False

    @property
    def best_score(self) -> float:
        return max((item.score for item in self.relations), default=0.0)

    @property
    def has_high_confidence_relation(self) -> bool:
        return any(item.confidence == "high" for item in self.relations)


def story_key_from_seed(article_id: str) -> str:
    digest = hashlib.sha1(str(article_id).encode("utf-8")).hexdigest()[:12]
    return f"story:{digest}"


def assign_story(
    *,
    article_id: str,
    title: str,
    excerpt: str = "",
    category: str = "",
    entities: list[str] | None = None,
    localities: list[str] | None = None,
    published_at: str = "",
    candidates: list[ArchiveArticle] | None = None,
    path=None,
) -> StoryAssignment | None:
    """Evalúa si la noticia pertenece a una historia existente o inicia una nueva.

    Devuelve ``None`` cuando no hay evidencia suficiente: una noticia sin
    antecedentes no es un error, es el caso normal (Parte 53).
    """
    if candidates is None:
        candidates = ai.candidate_retrieval(
            title=title,
            excerpt=excerpt,
            entities=entities,
            localities=localities,
            category=category,
            exclude_article_id=article_id,
            path=path,
        )
    if not candidates:
        return None

    scored = retrieval.rank_candidates(
        candidates,
        probe_title=title,
        probe_excerpt=excerpt,
        probe_entities=entities,
        probe_localities=localities,
        probe_category=category,
        probe_published_at=published_at,
    )
    qualifying = [item for item in scored if item.meets_category_bar(category)]
    if not qualifying:
        return None

    existing_keys = [item.candidate.story_key for item in qualifying if item.candidate.story_key]
    if existing_keys:
        story_key = existing_keys[0]
        created_new = False
    else:
        seed = qualifying[0].candidate
        story_key = story_key_from_seed(seed.article_id)
        created_new = True
        if not seed.story_key:
            ai.set_story_key(seed.article_id, story_key, path=path)
        ai.add_story_relation(
            seed.article_id,
            story_key,
            relation_score=qualifying[0].score,
            relation_reason=qualifying[0].relation_reason,
            matched_entities=qualifying[0].matched_entities,
            matched_terms=qualifying[0].matched_terms,
            time_distance_days=qualifying[0].time_distance_days,
            confidence=qualifying[0].confidence,
            path=path,
        )
        logger.info(
            "Nueva historia %s creada a partir de %s (score=%.2f)",
            story_key,
            seed.article_id,
            qualifying[0].score,
        )

    ai.upsert_story(
        story_key,
        category=category,
        title_hint=title,
        anchor_entities=entities or [],
        anchor_terms=[],
        path=path,
    )
    ai.add_story_relation(
        article_id,
        story_key,
        relation_score=qualifying[0].score,
        relation_reason=qualifying[0].relation_reason,
        matched_entities=qualifying[0].matched_entities,
        matched_terms=qualifying[0].matched_terms,
        time_distance_days=qualifying[0].time_distance_days,
        confidence=qualifying[0].confidence,
        path=path,
    )

    return StoryAssignment(story_key=story_key, relations=qualifying, created_new=created_new)
