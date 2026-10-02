"""Construcción compartida del caption usado por Instagram y Facebook."""
from __future__ import annotations

import os


_SECTION_TAGS = {
    "policiales": "#PoliciaLaRioja #Seguridad",
    "deportes": "#DeportesRioja #Deportes",
    "cultura": "#CulturaRioja #Cultura",
    "espectaculos": "#EspectaculosRioja #Cultura",
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


def _caption_from_web(noticia: dict) -> str:
    """Caption armado con la versión editorial final de la web (sin llamar a IA).

    Reutiliza lo que ya produjo la redacción web —título, bajada y puntos clave
    verificados— para que Instagram/Facebook reflejen esas mejoras en vez del
    caption generado antes sobre el texto scrapeado (LVR-IMPROVEMENT-0001).
    """
    web = noticia.get("web_editorial")
    if not isinstance(web, dict):
        return ""
    title = str(web.get("social_title") or web.get("title") or "").strip()
    lead = str(web.get("lead") or web.get("excerpt") or web.get("social_description") or "").strip()
    if not title or not lead:
        return ""
    seccion = str(noticia.get("seccion") or "").lower()
    opener = _SECTION_OPENERS.get(seccion, "📰")
    parts = [f"{opener} {title}", lead]
    points = [
        str(point).strip()
        for point in (web.get("key_points") or [])
        if str(point).strip() and str(point).strip() not in lead
    ][:3]
    if points:
        parts.append("\n".join(f"▪️ {point}" for point in points))
    cta = str(noticia.get("cta") or "").strip()
    if cta:
        parts.append(f"💬 {cta}")
    return "\n\n".join(parts)[:_WEB_BODY_MAX_CHARS].rstrip()


def build_instagram_caption(noticia: dict) -> str:
    cuerpo = _caption_from_web(noticia) if _caption_from_web_enabled() else ""
    if not cuerpo:
        cuerpo = str(noticia.get("texto_instagram") or "").strip()
    if not cuerpo:
        parrafos = noticia.get("parrafos") or []
        primero = noticia.get("excerpt") or (parrafos[0] if parrafos else "")
        cuerpo = f"{noticia.get('titulo', '')}\n\n{primero}"
    localidad = str(noticia.get("hashtag_localidad") or "").strip()
    seccion = str(noticia.get("seccion") or "").lower()
    tags = (
        f"{_SECTION_TAGS.get(seccion, '#RiojaHoy')} "
        "#LaVozRiojana #LaRioja #Noticias"
    )
    if localidad:
        tags = f"{localidad} {tags}"
    return f"{cuerpo}\n\n{tags}"[:2200]
