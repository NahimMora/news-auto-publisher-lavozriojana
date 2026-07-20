from __future__ import annotations

import unicodedata
from collections import defaultdict, deque


# Lower number = published earlier.
DEFAULT_CATEGORY_PRIORITY = {
    "policiales": 0,
    "interior": 1,
    "politica": 2,
    "sociedad": 3,
    "economia": 3,
    "salud": 4,
    "educacion": 4,
    "cultura": 5,
    "espectaculos": 5,
    "deportes": 9,
}

CATEGORY_ALIASES = {
    "locales": "interior",
    "policia": "policiales",
    "policial": "policiales",
    "politica riojana": "politica",
    "ultimo momento": "sociedad",
}

# Palabras que indican urgencia / "Último Momento".
# Modelo único compartido por la web (editorial_flags.py) y las redes
# sociales (social_queue.py / run_ig.py) para que "urgente" signifique
# lo mismo en todos los canales.
BREAKING_KEYWORDS = {
    "murio", "fallecio", "muertos", "muerta", "muerto",
    "accidente", "choque", "colision", "vuelco",
    "incendio", "explosion", "desborde", "inundacion", "tornado", "granizo",
    "detenido", "detenidos", "detenida", "allanamiento",
    "tiroteo", "disparo", "disparos", "asalto", "robo", "asaltaron",
    "asesinato", "femicidio", "homicidio",
    "alerta", "urgente", "emergencia", "catastrofe",
    "paro", "huelga", "corte", "caos", "colapso",
    "sismo", "terremoto", "heridos", "herido", "herida",
    "ataque", "agresion",
}

# Solo estas categorías pueden activar "Último Momento" (breaking).
BREAKING_CATEGORIES = {"policiales", "interior", "sociedad"}

# Marca interna de grupo para noticias de último momento: no pasa por
# CATEGORY_ALIASES a propósito, así nunca choca con una categoría real.
_BREAKING_GROUP = "__breaking__"


def normalize_category(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    category = " ".join(ascii_value.lower().split()) or "desconocido"
    return CATEGORY_ALIASES.get(category, category)


def item_category(item: dict) -> str:
    for field in ("categoria", "categorySlug", "seccion", "category", "section"):
        value = item.get(field)
        if value:
            return normalize_category(value)
    return "desconocido"


def priority_value(category: object) -> int:
    if category == _BREAKING_GROUP:
        return -1
    return DEFAULT_CATEGORY_PRIORITY.get(normalize_category(category), 6)


def is_breaking(titulo: object, category: object) -> bool:
    """True si el título contiene una keyword de urgencia y la categoría lo permite."""
    if normalize_category(category) not in BREAKING_CATEGORIES:
        return False
    normalized = unicodedata.normalize("NFKD", str(titulo or "").lower())
    ascii_titulo = normalized.encode("ascii", "ignore").decode("ascii")
    return any(kw in ascii_titulo for kw in BREAKING_KEYWORDS)


def item_is_breaking(item: dict) -> bool:
    return is_breaking(item.get("titulo", ""), item_category(item))


def group_key(item: dict) -> str:
    """Categoría efectiva para ordenar: último momento salta al frente de la cola."""
    return _BREAKING_GROUP if item_is_breaking(item) else item_category(item)


def priority_interleave(items: list[dict]) -> list[dict]:
    """
    Orders items by editorial category and round-robins inside priority groups.

    FIFO order is preserved inside each category. This keeps high-priority
    categories first while avoiding long blocks of the same section.
    Breaking ("Último Momento") items form their own top-priority group,
    regardless of their underlying category.
    """
    groups: dict[str, deque] = defaultdict(deque)
    for item in items:
        groups[group_key(item)].append(item)

    sorted_categories = sorted(
        groups.keys(),
        key=lambda category: (priority_value(category), category),
    )

    ordered: list[dict] = []
    while any(groups[category] for category in sorted_categories):
        for category in sorted_categories:
            if groups[category]:
                ordered.append(groups[category].popleft())
    return ordered


def split_priority_batch(
    items: list[dict],
    *,
    max_items: int | None = None,
    category_caps: dict[str, int] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Returns (selected, deferred) after applying priority order and per-category caps.

    category_caps values below 0 mean no cap for that category.
    max_items <= 0 is treated as no total cap.
    """
    ordered = priority_interleave(items)
    caps = {
        normalize_category(category): cap
        for category, cap in (category_caps or {}).items()
        if cap is not None and cap >= 0
    }
    total_cap = max_items if max_items and max_items > 0 else None
    counts: dict[str, int] = defaultdict(int)
    selected: list[dict] = []
    deferred: list[dict] = []

    for item in ordered:
        category = group_key(item)
        cap = caps.get(category)
        if cap is not None and counts[category] >= cap:
            deferred.append(item)
            continue
        if total_cap is not None and len(selected) >= total_cap:
            deferred.append(item)
            continue
        selected.append(item)
        counts[category] += 1

    return selected, deferred
