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
from datetime import datetime, timedelta, timezone

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


_EMOJI_PREFIX = re.compile(r"^[^\w¿¡\"«(]+", re.UNICODE)
_DECK_MAX_CHARS = 170


def reel_deck_from_caption(caption: str) -> str:
    """Primera oración del párrafo 📌 del caption (qué pasó), sin emojis.

    Es texto ya publicado en el mismo Reel: no se genera nada nuevo. Si la
    oración es demasiado larga para la pieza, no se recorta con "…": se
    omite la bajada."""
    for raw in str(caption or "").splitlines():
        line = raw.strip()
        if not line.startswith("📌"):
            continue
        text = _EMOJI_PREFIX.sub("", line).strip()
        match = re.search(r"^(.+?[.!?])(\s|$)", text)
        sentence = (match.group(1) if match else text).strip()
        return sentence if 20 <= len(sentence) <= _DECK_MAX_CHARS else ""
    return ""


def reel_credit(source_url: str, uploader: str = "") -> str:
    """Crédito verificable del video a partir de su URL de origen."""
    from urllib.parse import urlparse

    parsed = urlparse(str(source_url or ""))
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host in {"x.com", "twitter.com", "mobile.twitter.com"}:
        handle = uploader.strip().lstrip("@") or (parsed.path.strip("/").split("/") or [""])[0]
        return f"Video: X / @{handle}" if handle and handle != "i" else "Video: X"
    known = {"infobae.com": "Infobae", "paparazzi.com.ar": "Paparazzi"}
    for domain, label in known.items():
        if host == domain or host.endswith("." + domain):
            return f"Video: {label}"
    return ""


def reel_props_v2(
    item: Mapping[str, object],
    *,
    duration_frames: int,
    asset_type: str,
    asset_file: str,
    asset_size: tuple[int, int] | None = None,
) -> dict:
    # ``titulo_display`` conserva la caja original (nombres propios); el
    # ``titulo_reel`` histórico llega en MAYÚSCULAS.
    title = str(item.get("titulo_display") or item.get("titulo_reel") or item.get("titulo") or "").strip()
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
        "deck": str(item.get("reel_deck") or "").strip(),
        "credit": str(item.get("reel_credit") or "").strip(),
        "still": False,
    }


# Argentina no tiene horario de verano: UTC−3 fijo (sin depender de tzdata).
_AR_TZ = timezone(timedelta(hours=-3))
_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def date_label(now: datetime | None = None) -> str:
    """Fecha de publicación para la banda de pie ("sábado 18 de octubre")."""
    moment = (now or datetime.now(_AR_TZ)).astimezone(_AR_TZ)
    return f"{_DIAS[moment.weekday()]} {moment.day} de {_MESES[moment.month - 1]}"


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
        "dateLabel": date_label(),
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
