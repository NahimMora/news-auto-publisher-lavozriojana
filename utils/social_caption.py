"""Construcción compartida del caption usado por Instagram y Facebook."""
from __future__ import annotations

import os
import re


_SECTION_TAGS = {
    "policiales": "#PoliciaLaRioja #Seguridad",
    "deportes": "#DeportesRioja #Deportes",
    "cultura": "#CulturaRioja #Cultura",
    "espectaculos": "#Espectaculos #Famosos",
    "politica": "#PoliticaRioja #LaRiojaGobierna",
    "economia": "#EconomiaRioja #Economia",
    "salud": "#SaludRioja #Salud",
    "educacion": "#EducacionRioja #Educacion",
    "interior": "#InteriorRioja #LaRioja",
    "sociedad": "#LaRiojaHoy #Sociedad",
}


_SECTION_OPENERS = {
    "policiales": "🚨",
    "deportes": "⚽",
    "cultura": "🎭",
    "espectaculos": "🎬",
    "politica": "🏛️",
    "economia": "💰",
    "salud": "🩺",
    "educacion": "📚",
    "interior": "📍",
    "sociedad": "📰",
}
_WEB_BODY_MAX_CHARS = 1800


def _caption_from_web_enabled() -> bool:
    return os.getenv("IG_CAPTION_FROM_WEB_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on", "si", "sí",
    }


_LEAD_MAX_CHARS = 600
# Un "punto clave" de la web suele ser un chip de ≤32 caracteres (tag, nombre
# propio o categoría: "Policiales", "La Rioja"). En el caption sólo se listan
# los que son una oración con contenido propio.
_KEY_POINT_MIN_WORDS = 4
_TRUNCATION_MARKS = ("...", "…")
_CLOSING_LINE = "📲 Nota completa en lavozriojana.com"


def _is_truncated(text: str) -> bool:
    return text.endswith(_TRUNCATION_MARKS)


def _whole_sentences(text: str, max_chars: int) -> str:
    """Recorta a oraciones completas; nunca deja una palabra cortada con "...".

    ``clean_text`` de la web corta el lead con "..." en mitad de una palabra;
    en el caption se vuelve a la última oración terminada.
    """
    text = " ".join(str(text or "").split())
    truncated = _is_truncated(text)
    if truncated:
        text = text.rstrip(".… ")
    elif len(text) <= max_chars:
        return text
    # Fin de oración = signo seguido de espacio. Si el texto llegó truncado,
    # su final no cuenta: la última "oración" quedó cortada.
    window = text[: max_chars + 1]
    end = max(window.rfind(mark) for mark in (". ", "! ", "? "))
    if end > 0:
        return window[: end + 1]
    # Sin oración completa dentro del límite: corte en palabra entera.
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def _words(text: str) -> set[str]:
    return {word.casefold() for word in re.findall(r"\w+", text) if len(word) > 2}


def _sentence_points(web: dict, lead: str) -> list[str]:
    """Puntos con contenido propio; la lista sólo vale con dos o más."""
    lead_words = _words(lead)
    points: list[str] = []
    for raw in web.get("key_points") or []:
        point = " ".join(str(raw or "").split())
        words = _words(point)
        if (
            len(point.split()) < _KEY_POINT_MIN_WORDS
            or _is_truncated(point)
            or not words
            # Repite lo que ya dice el lead ("272 aniversario de Chepes").
            or len(words & lead_words) >= 0.8 * len(words)
        ):
            continue
        points.append(point)
    return points[:3] if len(points) >= 2 else []


def _normalize_question(cta: str) -> str:
    cta = " ".join(str(cta or "").split()).lstrip("❓💬 ")
    if cta.endswith("?") and not cta.startswith("¿"):
        cta = f"¿{cta}"
    return cta


def _caption_from_web(noticia: dict) -> str:
    """Caption armado con la versión editorial final de la web (sin llamar a IA).

    Reutiliza lo que ya produjo la redacción web —título social y lead
    verificados— para que Instagram/Facebook reflejen esas mejoras en vez del
    caption generado antes sobre el texto scrapeado (LVR-IMPROVEMENT-0001).

    Si la web publicó el fallback con el texto original (todas las revisiones
    rechazadas), devuelve vacío: ese lead es el primer párrafo crudo de la
    fuente y puede no tener relación con el título.
    """
    web = noticia.get("web_editorial")
    if not isinstance(web, dict) or web.get("source_fallback"):
        return ""
    title = str(web.get("social_title") or web.get("title") or "").strip()
    raw_lead = str(web.get("lead") or web.get("excerpt") or web.get("social_description") or "")
    lead = _whole_sentences(raw_lead, _LEAD_MAX_CHARS)
    if not title or not lead:
        return ""
    seccion = str(noticia.get("seccion") or "").lower()
    opener = _SECTION_OPENERS.get(seccion, "📰")
    parts = [f"{opener} {title}", lead]
    points = _sentence_points(web, lead)
    if points:
        parts.append("\n".join(f"▪️ {point}" for point in points))
    cta = _normalize_question(noticia.get("cta") or "")
    if cta:
        parts.append(f"💬 {cta}")
    parts.append(_CLOSING_LINE)
    return "\n\n".join(parts)[:_WEB_BODY_MAX_CHARS].rstrip()


def _hashtags(noticia: dict) -> str:
    """Hashtags sin repetir (``hashtag_localidad`` suele ser ``#LaRioja``)."""
    seccion = str(noticia.get("seccion") or "").lower()
    raw = " ".join(
        (
            str(noticia.get("hashtag_localidad") or "").strip(),
            _SECTION_TAGS.get(seccion, "#RiojaHoy"),
            "#LaVozRiojana #LaRioja #Noticias",
        )
    )
    tags: list[str] = []
    seen: set[str] = set()
    for tag in raw.split():
        key = tag.casefold()
        if tag.startswith("#") and key not in seen:
            seen.add(key)
            tags.append(tag)
    return " ".join(tags)


def build_instagram_caption(noticia: dict) -> str:
    cuerpo = _caption_from_web(noticia) if _caption_from_web_enabled() else ""
    if not cuerpo:
        cuerpo = str(noticia.get("texto_instagram") or "").strip()
    if not cuerpo:
        parrafos = noticia.get("parrafos") or []
        primero = noticia.get("excerpt") or (parrafos[0] if parrafos else "")
        cuerpo = f"{noticia.get('titulo', '')}\n\n{primero}"
    return f"{cuerpo}\n\n{_hashtags(noticia)}"[:2200]
