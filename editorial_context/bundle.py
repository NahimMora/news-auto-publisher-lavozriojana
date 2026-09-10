"""EditorialContextBundle: lo único que ve la redacción existente (Partes 34-37).

``build_context_bundle`` es el único punto de entrada que
``pipeline/node_webapp/publisher.py`` necesita llamar antes de
``prepare_editorial``. Todo lo demás (archive, story, depth, slots) es un
detalle de implementación de este módulo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from editorial_context import archive_index as ai
from editorial_context import context_depth as cd
from editorial_context import entities as ec_entities
from editorial_context import enrichment_slots as es
from editorial_context import metrics as ec_metrics
from editorial_context import retrieval
from editorial_context import story_engine
from editorial_context import timeline as tl
from utils.logging_setup import setup_logger

# Import diferido dentro de _gather_official_snippets para evitar acoplar
# este módulo a sources/ cuando sólo se usa el motor de archivo propio.

logger = setup_logger("editorial_context.bundle", "editorial_context.log")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# Límites de tamaño (Parte 35). No son requisitos matemáticos: ajustables por env.
ARCHIVE_CONTEXT_MAX_ITEMS = _env_int("ARCHIVE_CONTEXT_MAX_ITEMS", 3)
RELATED_ARTICLES_MAX_ITEMS = _env_int("RELATED_ARTICLES_MAX_ITEMS", 5)
TIMELINE_MAX_ITEMS = _env_int("TIMELINE_MAX_ITEMS", 5)
ARCHIVE_CONTEXT_MAX_CHARS = _env_int("ARCHIVE_CONTEXT_MAX_CHARS", 3500)
OFFICIAL_CONTEXT_MAX_CHARS = _env_int("OFFICIAL_CONTEXT_MAX_CHARS", 4500)
ANTECEDENT_SNIPPET_MAX_CHARS = 280
OFFICIAL_SNIPPET_MAX_ITEMS = _env_int("OFFICIAL_SNIPPET_MAX_ITEMS", 3)
OFFICIAL_SNIPPET_TEXT_MAX_CHARS = 400
OFFICIAL_ITEMS_PER_SOURCE_SCANNED = 10


@dataclass
class ContextSnippet:
    """Provenance auditable de cada fragmento usado (Parte 37)."""

    text: str
    source_type: str  # "own_archive" | "official_source"
    source_id: str = ""
    source_url: str = ""
    post_id: str = ""
    published_at: str = ""
    relation_score: float = 0.0


@dataclass
class EditorialContextBundle:
    context_depth: str = "NONE"
    archive_snippets: list[ContextSnippet] = field(default_factory=list)
    official_snippets: list[ContextSnippet] = field(default_factory=list)
    enrichment_slot_dicts: list[dict] = field(default_factory=list)
    related_articles: list[dict] = field(default_factory=list)
    story_key: str = ""
    timeline: list[dict] = field(default_factory=list)
    factual_basis_text: str = ""

    def archive_context_text(self) -> str:
        if self.context_depth == "NONE" or not self.archive_snippets:
            return ""
        text = " ".join(s.text for s in self.archive_snippets[:ARCHIVE_CONTEXT_MAX_ITEMS])
        return text[:ARCHIVE_CONTEXT_MAX_CHARS]

    def official_context_text(self) -> str:
        if self.context_depth == "NONE" or not self.official_snippets:
            return ""
        text = " ".join(s.text for s in self.official_snippets)
        return text[:OFFICIAL_CONTEXT_MAX_CHARS]

    def enrichment_hints(self) -> list[dict]:
        if self.context_depth == "NONE":
            return []
        return [slot for slot in self.enrichment_slot_dicts if slot.get("available")]

    def to_prompt_fragment(self) -> dict:
        """Lo único que Gemini recibe además de la noticia (Parte 34/36):
        fragmentos ya seleccionados y acotados, nunca el archivo completo."""
        fragment: dict = {}
        archive_text = self.archive_context_text()
        official_text = self.official_context_text()
        hints = self.enrichment_hints()
        if archive_text:
            fragment["archive_context"] = archive_text
        if official_text:
            fragment["official_context"] = official_text
        if hints:
            fragment["enrichment_hints"] = [{"type": h["type"], "value": h["value"]} for h in hints]
        if fragment:
            fragment["context_depth"] = self.context_depth
        return fragment

    def to_dict(self) -> dict:
        return {
            "context_depth": self.context_depth,
            "story_key": self.story_key,
            "timeline": list(self.timeline),
            "related_articles": list(self.related_articles),
            "enrichment_slots": list(self.enrichment_slot_dicts),
            "archive_snippet_count": len(self.archive_snippets),
            "official_snippet_count": len(self.official_snippets),
        }


def _summarize_antecedent(article: ai.ArchiveArticle) -> str:
    """Extrae el antecedente, no copia el artículo entero (Parte 36)."""
    text = (article.excerpt or article.title or "").strip()
    return text[:ANTECEDENT_SNIPPET_MAX_CHARS]


def _gather_official_snippets(
    *,
    category: str,
    entities: list[str],
    localities: list[str],
    title: str,
    excerpt: str,
    path: Path | str | None = None,
) -> tuple[list[ContextSnippet], int]:
    """SourceSelector + caché local (Parte 24/57): nunca consulta la red acá
    (eso lo hace ``editorial_context/refresh_context.py`` una vez por ciclo,
    Parte 56); sólo filtra lo ya cacheado por relevancia real al hecho
    puntual (entidad/término/localidad compartidos), no por sola coincidencia
    de fuente/categoría."""
    from sources import cache as source_cache
    from sources import selector as source_selector

    sources = source_selector.select_sources(
        category=category, localities=localities, keywords_text=" ".join([title, excerpt])
    )
    if not sources:
        return [], 0

    probe_entities_norm = {ec_entities.normalize_entity(e) for e in entities}
    probe_terms = retrieval.significant_terms(title, excerpt, exclude=probe_entities_norm)
    probe_localities = set(localities)

    snippets: list[ContextSnippet] = []
    for source in sources:
        for item in source_cache.recent_items_for_source(
            source.source_id, limit=OFFICIAL_ITEMS_PER_SOURCE_SCANNED, path=path
        ):
            item_title = str(item.get("title") or "")
            item_excerpt = str(item.get("excerpt") or "")
            item_entities_norm = {
                ec_entities.normalize_entity(e) for e in ec_entities.extract_entities(item_title, item_excerpt)
            }
            item_terms = retrieval.significant_terms(item_title, item_excerpt, exclude=item_entities_norm)
            item_localities = set(ec_entities.extract_localities(item_title, item_excerpt))

            relevant = bool(
                (probe_entities_norm & item_entities_norm)
                or (probe_terms & item_terms)
                or (probe_localities & item_localities - {"la rioja", "rioja"})
            )
            if not relevant:
                continue
            snippets.append(
                ContextSnippet(
                    text=(item_excerpt or item_title)[:OFFICIAL_SNIPPET_TEXT_MAX_CHARS],
                    source_type="official_source",
                    source_id=source.source_id,
                    source_url=str(item.get("url") or ""),
                    published_at=str(item.get("published_at") or ""),
                )
            )
            if len(snippets) >= OFFICIAL_SNIPPET_MAX_ITEMS:
                break
        if len(snippets) >= OFFICIAL_SNIPPET_MAX_ITEMS:
            break

    return snippets, len(sources)


def build_context_bundle(
    *,
    article_id: str,
    title: str,
    excerpt: str = "",
    category: str = "",
    published_at: str = "",
    official_snippets: list[ContextSnippet] | None = None,
    official_source_lookup_count: int = 0,
    path: Path | str | None = None,
) -> EditorialContextBundle:
    """Punto de entrada único. Nunca lanza: una falla acá degrada a NONE
    (Parte 60, "si falla el archivo, la nota puede continuar sin contexto").

    ``official_snippets=None`` (default) hace que este módulo los reúna solo
    vía ``SourceSelector`` + caché local; pasar una lista explícita (incluso
    vacía) omite ese paso automático (útil para tests o para un caller que ya
    los resolvió por su cuenta)."""
    try:
        return _build_context_bundle(
            article_id=article_id,
            title=title,
            excerpt=excerpt,
            category=category,
            published_at=published_at,
            official_snippets=official_snippets,
            official_source_lookup_count=official_source_lookup_count,
            path=path,
        )
    except Exception:
        logger.exception("Fallo construyendo EditorialContextBundle para %s; se continua sin contexto", article_id)
        return EditorialContextBundle()


def _build_context_bundle(
    *,
    article_id: str,
    title: str,
    excerpt: str,
    category: str,
    published_at: str,
    official_snippets: list[ContextSnippet] | None,
    official_source_lookup_count: int,
    path: Path | str | None,
) -> EditorialContextBundle:
    entities_found = ec_entities.extract_entities(title, excerpt)
    localities_found = ec_entities.extract_localities(title, excerpt)

    if official_snippets is None:
        official_snippets, official_source_lookup_count = _gather_official_snippets(
            category=category,
            entities=entities_found,
            localities=localities_found,
            title=title,
            excerpt=excerpt,
            path=path,
        )

    candidates = ai.candidate_retrieval(
        title=title,
        excerpt=excerpt,
        entities=entities_found,
        localities=localities_found,
        category=category,
        exclude_article_id=article_id,
        path=path,
    )

    ranked = (
        retrieval.rank_candidates(
            candidates,
            probe_title=title,
            probe_excerpt=excerpt,
            probe_entities=entities_found,
            probe_localities=localities_found,
            probe_category=category,
            probe_published_at=published_at,
        )
        if candidates
        else []
    )
    relevant = [item for item in ranked if item.meets_category_bar(category)]

    story_assignment = None
    if candidates:
        story_assignment = story_engine.assign_story(
            article_id=article_id,
            title=title,
            excerpt=excerpt,
            category=category,
            entities=entities_found,
            localities=localities_found,
            published_at=published_at,
            candidates=candidates,
            path=path,
        )

    story_key = story_assignment.story_key if story_assignment else ""
    timeline_items = tl.build_timeline(story_key, exclude_article_id=article_id, path=path) if story_key else []
    has_strong_story = bool(timeline_items)

    archive_snippets = [
        ContextSnippet(
            text=_summarize_antecedent(item.candidate),
            source_type="own_archive",
            source_url=item.candidate.canonical_url,
            post_id=item.candidate.post_id,
            published_at=item.candidate.published_at,
            relation_score=item.score,
        )
        for item in relevant[:ARCHIVE_CONTEXT_MAX_ITEMS]
    ]

    best_score = relevant[0].score if relevant else 0.0
    depth = cd.decide_depth(
        best_archive_score=best_score,
        archive_item_count=len(relevant),
        has_official_context=bool(official_snippets),
        has_strong_story=has_strong_story,
    )

    slots = es.build_enrichment_slots(
        current_text=" ".join([title, excerpt]),
        archive_snippets=[
            es.Snippet(text=s.text, source_url=s.source_url, confidence="medium") for s in archive_snippets
        ],
        official_snippets=[
            es.Snippet(text=s.text, source_url=s.source_url, confidence="medium") for s in official_snippets
        ],
    )

    factual_basis_text = " ".join([s.text for s in archive_snippets] + [s.text for s in official_snippets])

    bundle = EditorialContextBundle(
        context_depth=depth.value,
        archive_snippets=archive_snippets,
        official_snippets=official_snippets,
        enrichment_slot_dicts=[slot.to_dict() for slot in slots],
        related_articles=[
            {
                "article_id": item.candidate.article_id,
                "title": item.candidate.title,
                "url": item.candidate.canonical_url,
                "score": item.score,
            }
            for item in relevant[:RELATED_ARTICLES_MAX_ITEMS]
        ],
        story_key=story_key,
        timeline=[
            {"article_id": i.article_id, "title": i.title, "published_at": i.published_at, "url": i.url}
            for i in timeline_items[:TIMELINE_MAX_ITEMS]
        ],
        factual_basis_text=factual_basis_text,
    )

    ec_metrics.record_bundle_event(
        article_id=article_id,
        category=category,
        context_depth=bundle.context_depth,
        archive_lookup_count=1,
        archive_match_count=len(relevant),
        story_assigned=bool(story_key),
        timeline_shown=has_strong_story,
        official_source_lookup_count=official_source_lookup_count,
        official_source_hit_count=len(official_snippets),
        context_chars=len(bundle.archive_context_text()) + len(bundle.official_context_text()),
        related_articles_count=len(bundle.related_articles),
        path=path,
    )
    return bundle
