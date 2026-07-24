"""Política explícita y medible para contenido generado mediante fallback."""
from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass

from utils.editorial_priority import item_category, item_is_breaking


@dataclass(frozen=True)
class FallbackDecision:
    allowed: bool
    degraded: bool
    strict: bool
    reason: str | None
    fallbacks: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "degraded": self.degraded,
            "strict": self.strict,
            "reason": self.reason,
            "fallbacks": list(self.fallbacks),
        }


_JUDICIAL_TERMS = {
    "fiscal",
    "fiscalia",
    "juez",
    "jueza",
    "justicia",
    "judicial",
    "imputado",
    "imputada",
    "procesado",
    "procesada",
    "causa",
}
_MINOR_TERMS = {
    "menor",
    "menores",
    "nino",
    "nina",
    "adolescente",
    "adolescentes",
}


def _normalized_text(item: dict) -> str:
    body = " ".join(str(value or "") for value in item.get("parrafos") or [])
    raw = f"{item.get('titulo', '')} {body}".lower()
    normalized = unicodedata.normalize("NFKD", raw)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _strict_reason(item: dict) -> str | None:
    category = item_category(item)
    tokens = set(_normalized_text(item).split())
    if tokens & _MINOR_TERMS:
        return "sensitive_minors"
    if category == "policiales":
        return "strict_category_policiales"
    if tokens & _JUDICIAL_TERMS:
        return "sensitive_judicial"
    if item_is_breaking(item):
        return "sensitive_breaking"
    return None


def evaluate_fallback_policy(
    item: dict,
    fallbacks: dict[str, object] | None,
    *,
    mode: str | None = None,
) -> FallbackDecision:
    used = tuple(sorted(name for name, value in (fallbacks or {}).items() if bool(value)))
    strict_reason = _strict_reason(item)
    strict = strict_reason is not None
    if not used:
        return FallbackDecision(
            allowed=True,
            degraded=False,
            strict=strict,
            reason=None,
            fallbacks=(),
        )

    selected_mode = str(
        mode or os.getenv("OPENAI_FALLBACK_MODE", "allow_non_sensitive")
    ).strip().lower()
    if selected_mode == "block":
        return FallbackDecision(False, True, strict, "fallback_blocked_by_policy", used)
    if selected_mode == "allow_non_sensitive" and strict:
        return FallbackDecision(False, True, True, strict_reason, used)
    if selected_mode not in {"allow_non_sensitive", "allow_all"}:
        return FallbackDecision(False, True, strict, "invalid_fallback_policy", used)
    return FallbackDecision(True, True, strict, None, used)


def evaluate_web_fallback(item: dict, fallback_used: bool) -> FallbackDecision:
    mode = os.getenv("WEB_EDITORIAL_FALLBACK_MODE", "allow_non_sensitive")
    return evaluate_fallback_policy(
        item,
        {"web_editorial": bool(fallback_used)},
        mode=mode,
    )
