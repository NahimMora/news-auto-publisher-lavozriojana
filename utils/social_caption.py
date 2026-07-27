"""Construcción compartida del caption usado por Instagram y Facebook."""
from __future__ import annotations


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


def build_instagram_caption(noticia: dict) -> str:
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
