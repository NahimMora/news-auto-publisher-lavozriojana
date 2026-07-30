import os
import re
import unicodedata
from typing import Iterable


DEDUP_SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.5"))

_STOPWORDS = {
    "a",
    "al",
    "ante",
    "como",
    "con",
    "de",
    "del",
    "desde",
    "el",
    "en",
    "entre",
    "esta",
    "este",
    "fue",
    "hacia",
    "la",
    "las",
    "lo",
    "los",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "son",
    "sus",
    "tras",
    "una",
    "uno",
    "y",
}


def normalize_tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z0-9]+", ascii_text)
    return {word[:6] for word in words if len(word) >= 4 and word not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def text_candidates(item: dict) -> list[str]:
    candidates = []
    for field in (
        "titulo",
        "title",
        "titulo_original",
        "titulo_original_scrapeado",
        "titulo_instagram",
        "seoTitle",
        "ogTitle",
    ):
        value = str(item.get(field) or "").strip()
        if value:
            candidates.append(value)

    excerpt = str(item.get("excerpt") or "").strip()
    if excerpt:
        candidates.append(excerpt)

    parrafos = item.get("parrafos") or []
    if isinstance(parrafos, list) and parrafos:
        first = str(parrafos[0] or "").strip()
        if first:
            candidates.append(first)

    return candidates


def title_candidates(item: dict) -> list[str]:
    candidates = []
    for field in (
        "titulo",
        "title",
        "titulo_original",
        "titulo_original_scrapeado",
        "titulo_instagram",
        "seoTitle",
        "ogTitle",
    ):
        value = str(item.get(field) or "").strip()
        if value:
            candidates.append(value)
    return candidates


def item_similarity(a: dict, b: dict) -> float:
    # Si ambos elementos tienen título, la identidad editorial se decide por esos
    # títulos. Comparar cualquier excerpt contra cualquier excerpt con `max()` hacía
    # que boilerplate idéntico descartara noticias distintas.
    left_titles = title_candidates(a)
    right_titles = title_candidates(b)
    left_values = left_titles or text_candidates(a)
    right_values = right_titles or text_candidates(b)
    best = 0.0
    for left in left_values:
        left_tokens = normalize_tokens(left)
        if not left_tokens:
            continue
        for right in right_values:
            right_tokens = normalize_tokens(right)
            if not right_tokens:
                continue
            best = max(best, jaccard(left_tokens, right_tokens))
    return best


def duplicate_reason(
    item: dict,
    existing_items: Iterable[dict],
    *,
    key_fields: tuple[str, ...] = (),
    threshold: float | None = None,
) -> str | None:
    threshold = DEDUP_SIMILARITY_THRESHOLD if threshold is None else threshold
    for existing in existing_items:
        if not isinstance(existing, dict):
            continue
        for field in key_fields:
            key = item.get(field)
            if key and key == existing.get(field):
                return f"same_{field}"
        similarity = item_similarity(item, existing)
        if similarity >= threshold:
            return f"similar_title:{similarity:.2f}"
    return None
