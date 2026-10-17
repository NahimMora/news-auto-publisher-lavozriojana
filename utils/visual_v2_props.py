"""Adaptadores de datos del pipeline actual a las composiciones V2.

No reimplementan lógica editorial: reutilizan ``select_highlight_phrase`` y
``restore_deck_casing`` (openIA/caption_generator.py) y los campos que ya
produce el pipeline (``titulo``, ``titulo_instagram``, ``titulo_reel``,
``seccion``, ``deck``, ``locality``, ``highlight_terms``, ``breaking``).
Ningún campo se inventa: si el dato no existe, el prop queda vacío y la
composición V2 usa una variante compatible.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

_WORD = re.compile(r"[\w%$]+", re.UNICODE)


def _norm_words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFC", str(text or "")).casefold()
    return _WORD.findall(folded)


def phrase_in_title(phrase: str, title: str) -> bool:
    words = _norm_words(phrase)
    hay = _norm_words(title)
    if not words:
        return False
    return any(hay[i : i + len(words)] == words for i in range(len(hay) - len(words) + 1))


def highlight_terms_for(title: str, item: Mapping[str, object]) -> list[str]:
    """Destacados verificables: los del pipeline sólo si aparecen literalmente
    en ESTE titular (la cola guarda frases de otras versiones del título); si
    ninguno aparece, el selector local sobre el propio titular."""
    raw = item.get("highlight_terms") or item.get("highlightTerms") or []
    if isinstance(raw, str):
        raw = [raw]
    terms = [str(t).strip() for t in raw if str(t).strip()] if isinstance(raw, list) else []
    valid = [t for t in terms if phrase_in_title(t, title)]
    if valid:
        return valid[:2]
    from openIA.caption_generator import select_highlight_phrase

    phrase = select_highlight_phrase(title)
    return [phrase] if phrase and phrase_in_title(phrase, title) else []


def locality_for(item: Mapping[str, object]) -> str:
    web = item.get("web_editorial") if isinstance(item.get("web_editorial"), Mapping) else {}
    return str(item.get("locality") or web.get("locality") or "").strip()


def deck_for(item: Mapping[str, object]) -> str:
    from layout.image_generator import _deck_for_render

    return _deck_for_render(dict(item))


def reel_props_v2(
    item: Mapping[str, object],
    *,
    duration_frames: int,
    asset_type: str,
    asset_file: str,
    asset_size: tuple[int, int] | None = None,
) -> dict:
    title = str(item.get("titulo_reel") or item.get("titulo") or "").strip()
    width, height = asset_size or (0, 0)
    return {
        "titulo": title,
        "seccion": str(item.get("seccion") or "sociedad"),
        "assetType": asset_type if asset_file else "none",
        "assetFile": asset_file,
        "kenBurnsVariant": 0,
        "durationInFrames": int(duration_frames),
        "highlightTerms": highlight_terms_for(title, item),
        "assetWidth": int(width or 0),
        "assetHeight": int(height or 0),
        "locality": locality_for(item),
        "breaking": bool(item.get("breaking")),
        "hookStyle": "auto",
    }


def instagram_props_v2(
    article: Mapping[str, object],
    *,
    asset_file: str,
    asset_size: tuple[int, int] | None = None,
) -> dict:
    title = str(article.get("titulo") or "").strip()
    width, height = asset_size or (0, 0)
    props = {
        "titulo": title,
        "seccion": str(article.get("seccion") or ""),
        "assetFile": asset_file,
        "highlightTerms": highlight_terms_for(title, article),
        "locality": locality_for(article),
        "deck": deck_for(article),
        "assetWidth": int(width or 0),
        "assetHeight": int(height or 0),
        "breaking": bool(article.get("breaking")),
        "layout": "auto",
    }
    if width and height:
        props["assetOrientation"] = "landscape" if width > height else "portrait" if height > width else "square"
    return props


def og_props_v2(article: Mapping[str, object], *, asset_file: str) -> dict:
    title = str(article.get("titulo_instagram") or article.get("titulo") or "").strip()
    return {
        "titulo": title,
        "seccion": str(article.get("seccion") or ""),
        "assetFile": asset_file,
        "highlightTerms": highlight_terms_for(title, article),
        "locality": locality_for(article),
        "breaking": bool(article.get("breaking")),
    }
