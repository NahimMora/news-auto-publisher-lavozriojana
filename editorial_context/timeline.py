"""Timeline navegable de una historia (Partes 11/12).

Nunca se muestra "por mostrar": exige al menos dos antecedentes reales y al
menos una relación de confianza alta dentro de la historia.
"""
from __future__ import annotations

from dataclasses import dataclass

from editorial_context.archive_index import get_story_articles, get_story_relations

MAX_TIMELINE_ITEMS = 5
MIN_PRIOR_ITEMS_FOR_TIMELINE = 2


@dataclass
class TimelineItem:
    article_id: str
    title: str
    published_at: str
    url: str


def build_timeline(
    story_key: str, *, exclude_article_id: str | None = None, path=None
) -> list[TimelineItem]:
    """Máximo ``MAX_TIMELINE_ITEMS``, orden cronológico, sin repetir la nota actual."""
    if not story_key:
        return []

    relations = get_story_relations(story_key, path=path)
    if not any(row.get("confidence") == "high" for row in relations):
        return []

    articles = get_story_articles(story_key, exclude_article_id=exclude_article_id, limit=200, path=path)
    if len(articles) < MIN_PRIOR_ITEMS_FOR_TIMELINE:
        return []

    articles_sorted = sorted(articles, key=lambda item: item.published_at or "")
    tail = articles_sorted[-MAX_TIMELINE_ITEMS:]
    return [
        TimelineItem(
            article_id=article.article_id,
            title=article.title,
            published_at=article.published_at,
            url=article.canonical_url,
        )
        for article in tail
    ]
