"""Efemérides automáticas para el Reel "Un día como hoy" (criterio del responsable del 2026-11-15).

Fuente fija: la página de cada fecha de Wikipedia en español ("15 de
noviembre"), que trae acontecimientos, nacimientos, fallecimientos y
celebraciones (con una subsección Argentina y las jornadas de la ONU). De ahí
salen las candidatas del día; la IA sólo ELIGE con el criterio editorial y
redacta el guion con el texto del artículo enlazado. Todo lo que se dice o se
lee se controla contra ese artículo con el mismo control de la lista fija
(``format_reels.validate_ef``): si un dato no figura, no sale.

Prioridad: 1) La Rioja; 2) fechas patrias y memoria nacional (Soberanía, ARA
San Juan); 3) jornadas de servicio o concientización (25N); 4) cultura popular
(Día del Deportista, de la Música). Nunca: fundaciones de otras ciudades,
natalicios de figuras no riojanas sin peso nacional, crímenes policiales,
fechas partidarias.

La foto es la imagen principal del artículo en Wikimedia Commons, sólo con
licencia libre verificada por la API (dominio público, CC0, CC BY, CC BY-SA);
el crédito va en el texto del posteo.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date

from utils import nightly_newscast as nn
from utils.logging_setup import setup_logger
from utils.safe_http import safe_get

logger = setup_logger("efemerides_auto", "format_reels.log")

WIKI_API = "https://es.wikipedia.org/w/api.php"
UA = {"User-Agent": "LaVozRiojanaBot/1.0 (efemerides; +https://lavozriojana.com)"}
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
SECTIONS = {"acontecimientos": "hecho", "nacimientos": "nacimiento", "fallecimientos": "fallecimiento", "celebraciones": "celebracion"}
INTERNATIONAL = ("naciones unidas", "unesco", "organizacion mundial de la salud")
FREE_LICENSE = re.compile(r"^(public domain|dominio p[uú]blico|pd\b.*|cc0.*|cc[ -]by(-sa)?([ -][\d.]+.*)?)$", re.I)
GENERIC_LINK = re.compile(r"^(\d{1,4}|\d{1,2} de \w+|siglo .*|fallecidos en .*|argentina|rep[uú]blica argentina|buenos aires)$", re.I)


class NoEfemeride(Exception):
    """No hay una efeméride publicable para el día (no es un error de red)."""


@dataclass
class Item:
    id: str
    section: str          # hecho | nacimiento | fallecimiento | celebracion
    year: int | None
    text: str             # texto plano de la línea
    raw: str              # wikitexto de la línea (con destinos de enlaces)
    links: list[str] = field(default_factory=list)
    group: str = ""       # celebraciones: encabezado (Argentina, ONU, provincia)
    riojan: bool = False
    argentine: bool = False


@dataclass
class Photo:
    url: str
    width: int
    height: int
    credit: str
    file_page: str
    name: str = ""
    description: str = ""


@dataclass
class AutoEf:
    item: Item
    entry: dict
    cand: nn.Candidate
    photo: Photo
    scope: str            # riojana | nacional | internacional
    article_url: str


# ── API de Wikipedia ─────────────────────────────────────────────────────
def _api(params: dict, *, getter=None) -> dict:
    getter = getter or safe_get
    response = getter(WIKI_API, params={"format": "json", "formatversion": "2", **params}, headers=UA, timeout=30)
    if getattr(response, "status_code", 0) != 200:
        raise RuntimeError(f"Wikipedia respondió {getattr(response, 'status_code', '?')}")
    return response.json()


def day_title(day: date) -> str:
    return f"{day.day} de {MONTHS_ES[day.month - 1]}"


def day_wikitext(day: date, *, getter=None) -> str:
    data = _api({"action": "parse", "page": day_title(day), "prop": "wikitext"}, getter=getter)
    text = ((data.get("parse") or {}).get("wikitext")) or ""
    if not text:
        raise RuntimeError(f"la página '{day_title(day)}' vino vacía")
    return text


# ── Wikitexto → texto ────────────────────────────────────────────────────
_REF = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)


def plain(wikitext: str) -> str:
    s = _REF.sub("", wikitext)
    s = re.sub(r"\{\{\s*fecha\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,4})[^{}]*\}\}",
               lambda m: f"{int(m[1])} de {MONTHS_ES[int(m[2]) - 1]} de {m[3]}" if 1 <= int(m[2]) <= 12 else "", s, flags=re.I)
    prev = None
    while prev != s:
        prev, s = s, re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:Archivo|File|Imagen|Image|Categoría|Category):[^\[\]]*\]\]", "", s, flags=re.I)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\]", "", s)
    s = re.sub(r"<br\s*/?>", ". ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("'''", "").replace("''", "").replace("&nbsp;", " ").replace("―", ", ")
    s = re.sub(r"\.\s*\.", ".", s)
    return " ".join(s.split()).strip(" :")


def links(wikitext: str) -> list[str]:
    out = []
    for m in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]", _REF.sub("", wikitext)):
        title = m.group(1).strip()
        if re.match(r"(Archivo|File|Imagen|Image|Categoría|Category):", title, re.I) or GENERIC_LINK.match(title):
            continue
        if title not in out:
            out.append(title)
    return out


_YEAR = re.compile(r"^(?:\[\[(?:[^\]|]*\|)?)?(\d{1,4})(?:\]\])?\s*:\s*(.*)$")


def _riojan_text(raw: str) -> bool:
    folded = nn._fold(raw)
    if "rioja (espana)" in folded or "logrono" in folded:
        return False
    return any(k in folded for k in ("la rioja (argentina)", "provincia de la rioja", "ciudad de la rioja", "riojano", "riojana",
                                      "chacho", "facundo quiroga", "talampaya", "famatina", "chilecito", "los llanos"))


def parse_day(wikitext: str) -> list[Item]:
    """Líneas de la página del día, con sección, año y encabezado."""
    items: list[Item] = []
    section = ""
    skip_sub = False
    year_ctx: int | None = None
    stack: dict[int, str] = {}
    for line in wikitext.splitlines():
        h2 = re.match(r"^==\s*([^=].*?)\s*==\s*$", line)
        if h2:
            section = SECTIONS.get(nn._fold(h2.group(1)), "")
            skip_sub, year_ctx, stack = False, None, {}
            continue
        h3 = re.match(r"^===\s*(.*?)\s*===\s*$", line)
        if h3:
            skip_sub = "santoral" in nn._fold(h3.group(1))
            stack = {}
            continue
        bullet = re.match(r"^(\*+)\s*(.*)$", line)
        if not section or skip_sub or not bullet:
            continue
        depth, rest = len(bullet.group(1)), bullet.group(2).strip()
        if section == "celebracion":
            if rest.endswith(":") and "<br" not in rest:
                stack = {k: v for k, v in stack.items() if k < depth}
                stack[depth] = rest
                continue
            group = " > ".join(stack[k] for k in sorted(stack) if k < depth)
            text = plain(rest)
            if not text:
                continue
            # Las jornadas no tienen "año del hecho": la IA lo toma del texto
            # (año de la ley o de la proclamación) y se controla que figure.
            item = Item(id=f"c{len(items)}", section=section, year=None, text=text[:600], raw=rest,
                        links=links(rest), group=plain(re.sub(r"\{\{ARG\}\}", "Argentina", group, flags=re.I)))
            fg = nn._fold(group)
            item.argentine = "{{arg}}" in fg or "argentin" in fg
            item.riojan = item.argentine and ("la rioja" in fg or _riojan_text(rest))
            if item.argentine or not group or any(k in fg for k in INTERNATIONAL):
                items.append(item)
            continue
        m = _YEAR.match(rest)
        if m and depth == 1:
            year_ctx = int(m.group(1))
            rest = m.group(2)
        elif depth == 1:
            year_ctx = None
        if year_ctx is None or "a. c." in nn._fold(rest[:12]):
            continue
        text = plain(rest)
        if not text:
            continue
        item = Item(id=f"{section[0]}{len(items)}", section=section, year=year_ctx, text=text[:600], raw=rest, links=links(rest))
        item.riojan = _riojan_text(rest)
        item.argentine = item.riojan or "argentin" in nn._fold(rest)
        if item.argentine:
            items.append(item)
    return items


def _categories(titles: list[str], *, getter=None) -> dict[str, list[str]]:
    """Categorías visibles de cada artículo (siguiendo redirecciones)."""
    out: dict[str, list[str]] = {}
    for start in range(0, len(titles), 20):
        chunk = titles[start:start + 20]
        params = {"action": "query", "prop": "categories", "clshow": "!hidden", "cllimit": "max", "redirects": "1", "titles": "|".join(chunk)}
        alias: dict[str, str] = {}
        for _ in range(6):
            data = _api(params, getter=getter)
            query = data.get("query") or {}
            for r in (query.get("normalized") or []) + (query.get("redirects") or []):
                alias[r.get("to", "")] = alias.get(r.get("from", ""), r.get("from", ""))
            for page in query.get("pages") or []:
                original = alias.get(page.get("title", ""), page.get("title", ""))
                out.setdefault(original, []).extend(c.get("title", "") for c in page.get("categories") or [])
            cont = data.get("continue")
            if not cont:
                break
            params = {**params, **cont}
    return out


def riojan_categories(categories: list[str]) -> bool:
    from utils.newscast_v5 import _geo

    text = " | ".join(nn._fold(c) for c in categories)
    if "la rioja (argentina)" in text:
        return True
    geo = _geo()
    names = {n for n in set((geo.get("places") or {}).keys()) | set((geo.get("aliases") or {}).keys())
             if n and len(n) >= 6 and not n.startswith(("san ", "santa ", "villa ", "capital", "la capital"))}
    return any(re.search(rf"(personas|nacidos|fallecidos) (de|en) {re.escape(n)}\b", text) for n in names)


def candidates(day: date, *, getter=None) -> list[Item]:
    """Candidatas del día: hechos argentinos o riojanos, natalicios y muertes
    SÓLO de riojanos, celebraciones de Argentina y de la ONU."""
    items = parse_day(day_wikitext(day, getter=getter))
    people = [i for i in items if i.section in {"nacimiento", "fallecimiento"} and i.links]
    cats = _categories([i.links[0] for i in people], getter=getter) if people else {}
    out = []
    for item in items:
        if item.section in {"nacimiento", "fallecimiento"}:
            item.riojan = item.riojan or riojan_categories(cats.get(item.links[0], []) if item.links else [])
            if not item.riojan:
                continue
        out.append(item)
    return out


# ── Elección (IA, sólo elige) ────────────────────────────────────────────
NO_INVENT = ("No inventes datos, fechas, cifras, personas, armas, lugares ni hechos ajenos al texto que se te da; "
             "no completes con conocimiento propio.")

PICK_PROMPT = (
    "Sos el editor de efemérides de La Voz Riojana, un medio de La Rioja, Argentina. Elegís qué efeméride del día "
    "merece un Reel \"Un día como hoy\". " + NO_INVENT + " Criterio, en este orden de prioridad: "
    "1) todo lo de La Rioja (hechos, natalicios o muertes de riojanos, fechas provinciales); "
    "2) fechas patrias y memoria nacional argentina (batallas y gestas, Soberanía, tragedias nacionales como el ARA San Juan); "
    "3) jornadas de servicio o concientización con peso social (violencia contra la mujer, salud, derechos de la infancia); "
    "4) cultura popular argentina (Día del Deportista, Día de la Música, logros deportivos nacionales). "
    "NUNCA: fundaciones o aniversarios de otras ciudades o provincias, natalicios o muertes de figuras no riojanas, "
    "crímenes y casos policiales, fechas partidarias o de militancia política, aniversarios de dirigentes en actividad, "
    "días de productos o comerciales, fechas religiosas, nada de otros países. Si no hay nada de prioridad 1 a 4, devolvé lista vacía. "
    "Respondé SOLO este JSON: {\"elegidas\": [{\"id\": str, \"prioridad\": int, \"articulo\": str, \"motivo\": str}]} "
    "con hasta 3 candidatas, la mejor primero. articulo: el título EXACTO de uno de los enlaces de esa candidata, el que mejor "
    "cuenta el hecho (no el de un país ni un año)."
)


def choose(items: list[Item], *, completion=None) -> list[tuple[Item, str, int]]:
    from utils.ai_client import chat_completion

    if not items:
        return []
    completion = completion or chat_completion
    payload = [{"id": i.id, "tipo": i.section, "anio": i.year, "riojana": i.riojan, "grupo": i.group[:60], "texto": i.text[:320],
                "enlaces": i.links[:6]} for i in items[:60]]
    content = completion(
        messages=[{"role": "system", "content": PICK_PROMPT}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        model=os.getenv("FORMAT_REELS_SCRIPT_MODEL") or os.getenv("GEMINI_MODEL") or None,
        temperature=0.2, max_tokens=700, timeout=float(os.getenv("GEMINI_TIMEOUT", "90")), json_mode=True, stage="format_reels_ef_pick",
    )
    raw = json.loads(content or "{}")
    by_id = {i.id: i for i in items}
    out = []
    for row in (raw.get("elegidas") if isinstance(raw, dict) else None) or []:
        if not isinstance(row, dict) or row.get("id") not in by_id:
            continue
        item = by_id[row["id"]]
        prio = int(row.get("prioridad") or 4) if str(row.get("prioridad") or "").isdigit() else 4
        if not 1 <= prio <= 4:
            continue
        article = str(row.get("articulo") or "").strip()
        if article not in item.links:
            article = item.links[0] if item.links else ""
        out.append((item, article, prio))
    return out[:3]


# ── Artículo y foto ──────────────────────────────────────────────────────
def article(title: str, *, getter=None) -> tuple[str, str, str]:
    """``(título, texto plano, imagen principal)`` del artículo."""
    data = _api({"action": "query", "prop": "extracts|pageimages", "explaintext": "1", "exsectionformat": "plain", "piprop": "name",
                 "redirects": "1", "titles": title}, getter=getter)
    pages = (data.get("query") or {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        return "", "", ""
    page = pages[0]
    return page.get("title", title), (page.get("extract") or "")[:15000], page.get("pageimage") or ""


def _strip_html(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", text or "").split())


def photo(file_name: str, *, getter=None) -> tuple[Photo | None, str]:
    """Imagen de Commons con licencia libre verificada, o el motivo del rechazo."""
    if not file_name:
        return None, "el artículo no tiene imagen"
    data = _api({"action": "query", "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": "1280",
                 "titles": f"File:{file_name}"}, getter=getter)
    pages = (data.get("query") or {}).get("pages") or []
    info = ((pages[0].get("imageinfo") or [None])[0]) if pages else None
    if not info:
        return None, "no hay datos de la imagen"
    meta = info.get("extmetadata") or {}
    lic = _strip_html((meta.get("LicenseShortName") or {}).get("value", ""))
    if (meta.get("NonFree") or {}).get("value") or not FREE_LICENSE.match(lic) or re.search(r"\b(nc|nd)\b", lic, re.I):
        return None, f"licencia no libre: {lic or 'desconocida'}"
    artist = _strip_html((meta.get("Artist") or {}).get("value", ""))[:80]
    credit = f"{artist} ({lic}), vía Wikimedia Commons" if artist else f"{lic}, vía Wikimedia Commons"
    url = info.get("thumburl") or info.get("url") or ""
    if not url.startswith("https://"):
        return None, "imagen sin URL segura"
    description = _strip_html((meta.get("ImageDescription") or {}).get("value", "") or (meta.get("ObjectName") or {}).get("value", ""))
    return Photo(url=url, width=int(info.get("thumbwidth") or info.get("width") or 0), height=int(info.get("thumbheight") or info.get("height") or 0),
                 credit=credit, file_page=info.get("descriptionurl") or "", name=file_name, description=description[:300]), ""


# ── Guion (IA redacta, el control es el de la lista fija) ────────────────
SCRIPT_PROMPT = (
    "Escribís el guion de un Reel vertical \"Un día como hoy\" de La Voz Riojana (15 a 20 segundos, voz en off), a partir del "
    "texto de un artículo. " + NO_INVENT + " Usá SOLO datos que estén escritos en el texto; si no lo dice, no va. "
    "Tono periodístico, claro y sobrio, sin adjetivos de opinión que no estén en el texto; si es una tragedia, respetuoso y "
    "sin dramatizar. Español rioplatense. "
    "No uses 'hoy', 'ayer', 'mañana' ni 'anoche' salvo en el tramo de los años. Mayúsculas y minúsculas normales. "
    "Respondé SOLO este JSON: {\"foto_pertinente\": bool, \"anio\": int, \"gancho\": str, \"lugar\": str, "
    "\"quien\": {\"locucion\": str, \"apodo\": str, \"nombre\": str, \"chips\": [str], \"claves\": [str]} | null, "
    "\"donde\": {\"locucion\": str, \"chips\": [str], \"claves\": [str]} | null, "
    "\"anios\": {\"locucion\": str, \"claves\": [str]}, "
    "\"fecha_hoy\": {\"locucion\": str, \"sello\": str, \"detalle\": str, \"claves\": [str]} | null}. "
    "foto_pertinente: true sólo si el nombre del archivo y la descripción de la foto muestran al protagonista, el lugar o el "
    "objeto del hecho; false si es una imagen genérica del tema o de otra cosa. "
    "anio: el año del hecho (el que se te da; en una jornada, el año en que se creó, tal como figura en el texto). "
    "gancho: de 8 a 16 palabras. Para un hecho, natalicio o muerte empieza \"Un <día> de <mes> de <año>,\" (ej. \"Un 12 de "
    "noviembre de 1863, en Olta, asesinaban al Chacho Peñaloza.\"); para una jornada empieza \"Desde <año>, cada <día> de <mes>\" "
    "(ej. \"Desde 1999, cada 25 de noviembre el mundo dice basta a la violencia contra la mujer.\"). "
    "Si se te da una conmemoracion de la fecha (ley, día nacional), usala en fecha_hoy. "
    "lugar: la localidad o el lugar del hecho tal como figura en el texto (vacío si no hay uno). "
    "quien: el protagonista (persona, nave, institución): locucion de 6 a 12 palabras; apodo corto (máx. 24, puede ir vacío); "
    "nombre completo (máx. 40); chips: 2 o 3 rasgos cortos (máx. 26) que figuren en el texto. null si no hay protagonista. "
    "donde: dónde pasó: locucion de 6 a 12 palabras; chips: 1 a 3 lugares o datos cortos (máx. 28). null si no aplica. "
    "anios: locucion con el marcador literal {anios} donde va la cantidad de años (ej. \"Hoy se cumplen {anios} años.\"). "
    "fecha_hoy: cómo se recuerda la fecha (ley, día nacional, homenaje) sólo si el texto lo dice: locucion de 6 a 12 palabras, "
    "sello corto (máx. 24, ej. \"Día nacional\"), detalle opcional (máx. 30, ej. \"Ley 27.758\"). null si el texto no lo dice. "
    "Al menos dos de quien, donde y fecha_hoy. Total de palabras habladas entre 24 y 48 (gancho + locuciones): contalas antes de responder. "
    "Copiá nombres, cifras y fechas EXACTAMENTE como están en el texto, y escribí toda cantidad con números "
    "(\"44 tripulantes\", nunca \"cuarenta y cuatro\")."
)


def _source_text(item: Item, day: date, body: str, related: list[Item] | None = None) -> str:
    when = f"{day.day} de {MONTHS_ES[day.month - 1]}"
    head = f"{when} de {item.year}: {item.text}" if item.year and item.section != "celebracion" else f"Cada {when}: {item.text}"
    extra = "".join(f"\nCada {when}: {r.text}" for r in related or [])
    return f"{head}{extra}\n{body}"


def write_entry(item: Item, day: date, cand: nn.Candidate, *, pic: Photo | None = None, related: list[Item] | None = None,
                completion=None, attempts: int = 4) -> tuple[dict | None, list[str]]:
    from utils import format_reels as fr
    from utils.ai_client import chat_completion

    completion = completion or chat_completion
    payload = json.dumps({"fecha": f"{day.day} de {MONTHS_ES[day.month - 1]}", "anio": item.year, "efemeride": item.text,
                          "conmemoracion": [r.text for r in related or []],
                          "foto": {"archivo": pic.name, "descripcion": pic.description} if pic else None,
                          "texto": cand.body[:9000]}, ensure_ascii=False)
    feedback, warnings = "", []
    for attempt in range(1, attempts + 1):
        user = payload + (f"\n\nCorregí estos problemas del intento anterior sin agregar datos nuevos:\n{feedback}" if feedback else "")
        try:
            content = completion(
                messages=[{"role": "system", "content": SCRIPT_PROMPT}, {"role": "user", "content": user}],
                model=os.getenv("FORMAT_REELS_SCRIPT_MODEL") or os.getenv("GEMINI_MODEL") or None,
                temperature=0.3 if attempt == 1 else 0.5, max_tokens=1200, timeout=float(os.getenv("GEMINI_TIMEOUT", "90")),
                json_mode=True, stage="format_reels_ef_script",
            )
            raw = json.loads(content or "{}")
            raw = raw if isinstance(raw, dict) else {}
        except Exception as exc:  # noqa: BLE001 — red, cuota o JSON inválido: se reintenta
            warnings = [f"intento {attempt}: {type(exc).__name__}"]
            time.sleep(min(15, 4 * attempt))
            continue
        if pic and raw.get("foto_pertinente") is not True:
            return None, ["la foto no muestra el hecho"]
        year = item.year
        if year is None:
            year = raw.get("anio") if isinstance(raw.get("anio"), int) else None
            if year is None or str(year) not in cand.body:
                warnings = ["anio: el año tiene que figurar en el texto"]
                feedback = "\n".join(f"- {w}" for w in warnings)
                continue
        entry = {"fecha": f"{day.month:02d}-{day.day:02d}", "anio": year, "gancho": raw.get("gancho"), "lugar": raw.get("lugar") or ""}
        for key in ("quien", "donde", "anios", "fecha_hoy"):
            if isinstance(raw.get(key), dict):
                entry[key] = raw[key]
        plan, warnings = fr.validate_ef(entry, cand, day)
        if plan and not warnings:
            return entry, []
        logger.info("Guion EF automático, intento %s/%s con observaciones: %s", attempt, attempts, warnings[:5])
        feedback = "\n".join(f"- {w}" for w in warnings[:10])
    return None, warnings


def prepare(day: date, *, getter=None, completion=None) -> AutoEf:
    """Efeméride lista para renderizar. ``NoEfemeride`` si el día no tiene una
    publicable; ``RuntimeError``/``OSError`` ante fallas de red (se reintenta)."""
    items = candidates(day, getter=getter)
    picks = choose(items, completion=completion)
    celebrations = [i for i in items if i.section == "celebracion"]
    if not picks:
        raise NoEfemeride(f"ninguna de las {len(items)} candidatas cumple el criterio")
    reasons = []
    for item, title, prio in picks:
        if not title:
            reasons.append(f"{item.id}: sin artículo")
            continue
        real_title, body, image = article(title, getter=getter)
        if len(body) < 400:
            reasons.append(f"{item.id}: artículo corto o inexistente")
            continue
        pic, why = photo(image, getter=getter)
        if not pic:
            reasons.append(f"{item.id}: foto: {why}")
            continue
        url = "https://es.wikipedia.org/wiki/" + real_title.replace(" ", "_")
        # Conmemoraciones del día sobre el mismo tema (p. ej. la ley del Día del ARA San Juan).
        related = [c for c in celebrations if c is not item and set(c.links) & set(item.links)]
        cand = nn.Candidate(id="w1", title=real_title, section="cultura", source="wikipedia", web_url=url, published_at=0.0,
                            body=_source_text(item, day, body, related))
        entry, warnings = write_entry(item, day, cand, pic=pic, related=related, completion=completion)
        if not entry:
            reasons.append(f"{item.id}: guion: {(warnings or ['sin guion'])[0]}")
            continue
        scope = "riojana" if item.riojan else ("nacional" if item.argentine else "internacional")
        logger.info("Efeméride automática %s (%s, prioridad %s): %s", day.isoformat(), scope, prio, item.text[:90])
        return AutoEf(item=item, entry=entry, cand=cand, photo=pic, scope=scope, article_url=url)
    raise NoEfemeride("; ".join(reasons)[:300])
