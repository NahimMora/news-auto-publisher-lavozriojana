"""
Genera título y caption para Reels de Instagram/Facebook.
Módulo independiente del autopublicador de noticias.
"""
from __future__ import annotations

import json
import os

import requests
from bs4 import BeautifulSoup

_SECTIONS_REEL = [
    "politica", "policiales", "interior", "sociedad",
    "economia", "salud", "educacion", "deportes", "cultura",
]

_REEL_HASHTAGS: dict[str, str] = {
    "policiales":   "#PoliciaLaRioja #Seguridad",
    "deportes":     "#DeportesRioja #Deportes",
    "politica":     "#PoliticaRioja #LaRiojaGobierna",
    "economia":     "#EconomiaRioja #Economia",
    "salud":        "#SaludRioja #Salud",
    "educacion":    "#EducacionRioja #Educacion",
    "cultura":      "#CulturaRioja #Cultura",
    "espectaculos": "#EspectaculosRioja #Cultura",
    "interior":     "#InteriorRioja",
}

_SCRAPE_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LVRBot/1.0)"}


def scrape_url(url: str) -> dict:
    """Extrae título, imagen og y párrafos de cualquier URL."""
    r = requests.get(url, headers=_SCRAPE_HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = ""
    og_t = soup.find("meta", property="og:title")
    if og_t and og_t.get("content"):
        title = og_t["content"].strip()
    if not title:
        h1 = soup.select_one("h1")
        if h1:
            title = h1.get_text(strip=True)

    imagen_url = ""
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        imagen_url = og_img["content"].strip()

    parrafos: list[str] = []
    content = (
        soup.select_one("div.entry-content")
        or soup.select_one("div.post-content")
        or soup.select_one("article")
        or soup.select_one("main")
    )
    if content:
        for p in content.find_all("p"):
            text = p.get_text(separator=" ", strip=True)
            if len(text) >= 40:
                parrafos.append(text)

    return {"titulo": title, "imagen_url": imagen_url, "parrafos": parrafos, "url": url}


def generate_reel_meta(article: dict) -> dict:
    """
    Genera titulo_reel (≤80 chars, MAYÚSCULAS) y caption para IG/FB.
    Retorna {titulo_reel, caption, caption_base, seccion}.
    """
    import re as _re

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        titulo = article.get("titulo", "SIN TÍTULO")
        return {
            "titulo_reel": titulo[:80].upper(),
            "caption": titulo,
            "caption_base": titulo,
            "seccion": "sociedad",
        }

    from openai import OpenAI

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    titulo = article.get("titulo", "")
    texto = "\n\n".join(article.get("parrafos", [])[:4]) or titulo

    prompt = (
        "Sos el editor de La Voz Riojana, un medio digital de La Rioja, Argentina.\n"
        "La Voz Riojana NO es la fuente original de esta noticia: tiene permiso para distribuirla "
        "pero NO la redactó ni la investigó. Por lo tanto:\n"
        "- El título y caption deben informar el hecho sin atribuirse la primicia.\n"
        "- Usá lenguaje que cite o atribuya: 'se informó que', 'trascendió que', 'según fuentes', "
        "'se conoció que', 'fuentes indicaron que', etc.\n"
        "- NUNCA uses frases como 'informamos', 'te contamos', 'nuestra redacción' ni similares.\n"
        "- El tono es el de un medio local que redistribuye y amplifica noticias de la región.\n\n"
        "Dada la siguiente noticia, generá:\n"
        "1. titulo_reel: Título corto y llamativo para un Reel de Instagram "
        "(máximo 80 caracteres, en MAYÚSCULAS, sin punto final, directo al grano, en tercera persona).\n"
        "2. caption: Caption para Instagram y Facebook "
        "(2-3 oraciones, máximo 280 caracteres, tono periodístico, atribución de fuente, "
        "incluí un emoji apropiado al inicio).\n"
        f"3. seccion: La sección correcta (solo una de: {', '.join(_SECTIONS_REEL)}).\n\n"
        f"NOTICIA:\nTítulo: {titulo}\nTexto: {texto[:1500]}\n\n"
        "Respondé ÚNICAMENTE con un JSON así (sin explicaciones, sin markdown):\n"
        '{"titulo_reel": "...", "caption": "...", "seccion": "..."}'
    )

    client = OpenAI(api_key=api_key, timeout=float(os.getenv("OPENAI_TIMEOUT", "60")))
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=400,
    )
    raw = resp.choices[0].message.content.strip()
    match = _re.search(r"\{.*\}", raw, _re.DOTALL)
    data: dict = json.loads(match.group() if match else raw)

    seccion = str(data.get("seccion") or "sociedad")
    caption_base = str(data.get("caption") or titulo)
    hashtags = _REEL_HASHTAGS.get(seccion, "#RiojaHoy")
    caption_full = f"{caption_base}\n\n{hashtags} #LaVozRiojana #LaRioja #Noticias"

    return {
        "titulo_reel": str(data.get("titulo_reel") or titulo[:80]).upper(),
        "caption": caption_full[:2200],
        "caption_base": caption_base,
        "seccion": seccion,
    }


def analyze_url_for_reel(url: str) -> dict:
    """
    Pipeline completo: scrape URL → genera contenido IA para Reel.
    Retorna dict con titulo, imagen_url, parrafos, titulo_reel, caption, seccion.
    """
    article = scrape_url(url)
    reel = generate_reel_meta(article)
    return {**article, **reel}
