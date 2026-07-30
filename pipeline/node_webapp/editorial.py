from __future__ import annotations

import html
import json
import os
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from utils.logging_setup import setup_logger

logger = setup_logger("node_webapp.editorial", "publish_web.log")


CATEGORY_SLUGS = {
    "politica": "politica",
    "policiales": "policiales",
    "interior": "interior",
    "sociedad": "sociedad",
    "economia": "economia",
    "salud": "salud",
    "educacion": "educacion",
    "deportes": "deportes",
    "cultura": "cultura",
    "espectaculos": "espectaculos",
}

CATEGORY_NAMES = {
    "politica": "Política",
    "policiales": "Policiales",
    "interior": "Interior",
    "sociedad": "Sociedad",
    "economia": "Economía",
    "salud": "Salud",
    "educacion": "Educación",
    "deportes": "Deportes",
    "cultura": "Cultura",
    "espectaculos": "Espectáculos",
}

_SOURCE_LABELS = {
    "tiempopopular": "Tiempo Popular",
    "tiempopopular.com.ar": "Tiempo Popular",
}

_CATEGORY_TAGS = {
    "politica": "Politica",
    "policiales": "Policiales",
    "interior": "Interior",
    "sociedad": "Sociedad",
    "economia": "Economia",
    "salud": "Salud",
    "educacion": "Educacion",
    "deportes": "Deportes",
    "cultura": "Cultura",
    "espectaculos": "Espectaculos",
}

_TOPIC_TAGS = (
    "La Rioja",
    "Chilecito",
    "Aimogasta",
    "Famatina",
    "Vinchina",
    "Arauco",
    "Chamical",
    "Chepes",
    "Villa Union",
    "Educacion",
    "Salud",
    "Vialidad Provincial",
    "Gobierno de La Rioja",
    "Seleccion Argentina",
    "Mundial 2026",
    "Futbol",
    "Copa del Mundo",
    "Tenis",
    "Atletismo",
    "Seguridad vial",
    "Obras viales",
    "Consumos problematicos",
)

_LOW_QUALITY_TAGS = {
    "noticia",
    "noticias",
    "actualidad",
    "informacion",
    "hecho",
    "hechos",
    "general",
}

_ALLOWED_TAGS = {"p", "div", "span", "h2", "ul", "ol", "li", "strong", "em"}
_ALLOWED_CLASS_ATTRS = {
    "p": {"lr-lead", "lr-source"},
    "div": {"lr-key-points"},
}

_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "setiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}\s+de\s+(?:"
    + "|".join(_MONTHS)
    + r")|(?:lunes|martes|miercoles|mi[e\u00e9]rcoles|jueves|viernes|sabado|s[a\u00e1]bado|domingo)\s+\d{1,2}\s+de\s+(?:"
    + "|".join(_MONTHS)
    + r"))\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)*(?:\s?(?:%|km|kilometros|metros|anos|a\u00f1os|minutos|horas))?\b", re.IGNORECASE)
_SPANISH_NUMBER_WORDS = {
    "cero": "0",
    "uno": "1",
    "dos": "2",
    "tres": "3",
    "cuatro": "4",
    "cinco": "5",
    "seis": "6",
    "siete": "7",
    "ocho": "8",
    "nueve": "9",
    "diez": "10",
    "once": "11",
    "doce": "12",
    "trece": "13",
    "catorce": "14",
    "quince": "15",
    "dieciseis": "16",
    "diecisiete": "17",
    "dieciocho": "18",
    "diecinueve": "19",
    "veinte": "20",
    "treinta": "30",
    "cuarenta": "40",
    "cincuenta": "50",
    "sesenta": "60",
    "setenta": "70",
    "ochenta": "80",
    "noventa": "90",
    "cien": "100",
    "ciento": "100",
    "mil": "1000",
}
_CAP_WORD = r"(?:[A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1][a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1]+|[A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1]{2,})"
_PROPER_RE = re.compile(
    rf"\b{_CAP_WORD}(?:[ \t]+(?:de|del|la|las|los|y|e|en|san|santa|general)?[ \t]*{_CAP_WORD})*\b"
)
_HTML_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"\b[\w\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1]+\b")

_SAFE_H2 = (
    "Que se sabe",
    "Los detalles",
    "El contexto",
)

_H2_POOL: dict[str, list[str]] = {
    "politica": [
        "Qué dijo el gobierno", "La posición oficial", "Cómo afecta a La Rioja",
        "Los principales puntos", "El trasfondo político", "Qué implica la medida",
        "Reacciones y declaraciones", "El panorama actual", "Qué se viene",
    ],
    "policiales": [
        "Cómo ocurrió", "Lo que se sabe hasta ahora", "El operativo policial",
        "La investigación en curso", "Los detalles del hecho", "Qué dijo la fiscalía",
        "El estado de los implicados", "Las primeras pericias", "La secuencia de los hechos",
    ],
    "deportes": [
        "Así fue el partido", "Los goles y las jugadas", "El rendimiento del equipo",
        "Las declaraciones del DT", "Los números del encuentro", "Qué viene para el equipo",
        "El detalle del marcador", "La figura del partido", "Cómo se dio el resultado",
    ],
    "economia": [
        "Qué implica para los riojanos", "Los números clave", "El impacto económico",
        "Qué dicen los especialistas", "La situación actual", "Las principales medidas",
        "Cómo afecta al bolsillo", "El contexto económico", "Los sectores involucrados",
    ],
    "salud": [
        "Qué recomiendan los médicos", "Los síntomas a tener en cuenta", "Cómo prevenirlo",
        "El sistema de salud riojano", "La situación sanitaria", "Qué dice el ministerio",
        "Los casos registrados", "Las medidas de prevención", "A quiénes afecta más",
    ],
    "educacion": [
        "Qué cambia para los estudiantes", "Los alcances del programa", "Cómo se aplica",
        "Las instituciones involucradas", "El calendario académico", "Qué dicen los docentes",
        "Los objetivos del proyecto", "Quiénes pueden acceder", "El impacto en las escuelas",
    ],
    "cultura": [
        "De qué se trata la propuesta", "Dónde y cuándo", "Quiénes participan",
        "La propuesta cultural", "Los artistas convocados", "El programa completo",
        "Cómo sumarse", "El espíritu de la iniciativa", "La agenda cultural",
    ],
    "espectaculos": [
        "De qué se trata", "Los protagonistas", "Cuándo y dónde verlo",
        "La historia detrás", "Qué dicen los artistas", "El detrás de escena",
        "Los detalles del evento", "La propuesta artística", "Qué esperar",
    ],
    "sociedad": [
        "Qué está pasando", "El impacto en la comunidad", "Quiénes están involucrados",
        "Las causas del problema", "Qué piden los vecinos", "La situación en La Rioja",
        "Cómo afecta a la gente", "Los testimonios", "Qué se puede hacer",
    ],
    "interior": [
        "Qué ocurrió en la región", "El contexto local", "Las localidades afectadas",
        "Qué dice la autoridad local", "El impacto en la comunidad", "Cómo llegó la información",
        "Los vecinos y el hecho", "La situación en el interior", "Qué se sabe desde allí",
    ],
}


@dataclass
class EditorialSection:
    heading: str = ""
    paragraphs: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)


@dataclass
class EditorialResult:
    title: str
    excerpt: str
    lead: str
    source_paragraph: str
    sections: list[EditorialSection] = field(default_factory=list)
    closing_paragraph: str = ""
    key_points: list[str] = field(default_factory=list)
    seo_title: str = ""
    meta_description: str = ""
    social_title: str = ""
    social_description: str = ""
    focus_keyword: str = ""
    tags: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    content_html: str = ""
    fallback_used: bool = False
    warnings: list[str] = field(default_factory=list)
    attempt_count: int = 0
    final_attempt_used: bool = False
    revision_history: list[dict] = field(default_factory=list)


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_html(value: str) -> str:
    text = html.unescape(_HTML_RE.sub(" ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def clean_text(value: object, *, max_chars: int | None = None) -> str:
    text = strip_html(str(value or ""))
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if max_chars and len(text) > max_chars:
        cut = text[: max_chars - 1].rstrip(" ,.;:")
        text = cut + "..."
    return text


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def get_original_paragraphs(noticia: dict) -> list[str]:
    paragraphs: list[str] = []
    for item in noticia.get("parrafos") or []:
        if isinstance(item, str):
            text = clean_text(item)
            if text:
                paragraphs.append(text)
        elif isinstance(item, dict):
            for child in item.get("items") or item.get("paragraphs") or []:
                text = clean_text(child)
                if text:
                    paragraphs.append(text)
    return paragraphs


def category_to_slug(category: str) -> str:
    slug = normalize(category)
    return CATEGORY_SLUGS.get(slug, "sociedad")


def category_to_name(slug: str) -> str:
    return CATEGORY_NAMES.get(slug, "Sociedad")


def news_category(noticia: dict) -> str:
    return clean_text(noticia.get("categoria") or noticia.get("seccion") or "")


def source_display_name(noticia: dict) -> str:
    for raw in (noticia.get("source"), noticia.get("fuente")):
        if raw:
            norm = normalize(str(raw)).replace(" ", "")
            for key, label in _SOURCE_LABELS.items():
                if key.replace(".", "") in norm:
                    return label
            return clean_text(str(raw)).replace("_", " ").title()

    url = str(noticia.get("canonical_url") or noticia.get("url") or "").strip()
    host = urlparse(url).netloc.lower().replace("www.", "")
    if host:
        return _SOURCE_LABELS.get(host, host)
    return "la fuente original"


def _original_text(noticia: dict) -> str:
    parts = [
        str(noticia.get("titulo") or ""),
        str(noticia.get("titulo_original") or ""),
        news_category(noticia),
        source_display_name(noticia),
    ]
    parts.extend(get_original_paragraphs(noticia))
    return "\n".join(p for p in parts if p)


def _result_text(result: EditorialResult, *, include_seo: bool = True) -> str:
    parts = [
        result.title,
        result.excerpt,
        result.lead,
        result.source_paragraph,
        result.closing_paragraph,
    ]
    for section in result.sections:
        parts.append(section.heading)
        parts.extend(section.paragraphs)
        parts.extend(section.items)
    if include_seo:
        parts.extend(
            [
                result.seo_title,
                result.meta_description,
                result.social_title,
                result.social_description,
                result.focus_keyword,
                "\n".join(result.tags),
            ]
        )
    return "\n".join(p for p in parts if p)


def _result_factual_text(result: EditorialResult) -> str:
    """Body text where facts must trace back to the source.

    Excludes headings, tags, key_points, and SEO/social fields: those are
    editorial framing the AI is meant to phrase freely, not verbatim claims,
    so checking them for invented numbers/dates/proper nouns only produces
    false positives against creative (but accurate) wording.
    """
    parts = [
        result.title,
        result.excerpt,
        result.lead,
        result.source_paragraph,
        result.closing_paragraph,
    ]
    for section in result.sections:
        parts.extend(section.paragraphs)
        parts.extend(section.items)
    return "\n".join(p for p in parts if p)


def _extract_numbers(text: str) -> set[str]:
    numbers = {
        re.sub(r"\s+", "", m.group(0)).lower()
        for m in _NUMBER_RE.finditer(text or "")
    }
    # El modelo puede expresar "tres autos" como "3 autos". Ambos representan
    # el mismo dato factual y no deben disparar reintentos editoriales falsos.
    normalized_words = re.findall(r"\b[a-z]+\b", normalize(text or ""))
    numbers.update(
        _SPANISH_NUMBER_WORDS[word]
        for word in normalized_words
        if word in _SPANISH_NUMBER_WORDS
    )
    return numbers


def _extract_dates(text: str) -> set[str]:
    return {normalize(m.group(0)) for m in _DATE_RE.finditer(text or "")}


_CONNECTOR_SPLIT_RE = re.compile(
    r"\s+(?:de|del|la|las|los|y|e|en|san|santa|general)\s+", re.IGNORECASE
)
_ACRONYM_RE = re.compile(r"\b[A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d1]{2,}\b")

_PROPER_NOUN_STOPWORDS = {
    "El",
    "La",
    "Los",
    "Las",
    "Un",
    "Una",
    "En",
    "De",
    "Del",
    "Segun",
    "Seg\u00fan",
    "Que",
    "Qu\u00e9",
    "Como",
    "Con",
    "Para",
    "Por",
    "Este",
    "Esta",
    "Tambien",
    "Tambi\u00e9n",
    "Ademas",
    "Adem\u00e1s",
    "Ambos",
    "Ante",
    "Durante",
    "Detencion",
    "Detenci\u00f3n",
    "Fallecimiento",
    "Tragico",
    "Tr\u00e1gico",
}
_PROPER_NOUN_MONTHS = {m.title() for m in _MONTHS}
_ACRONYM_STOPWORDS = {
    "de",
    "del",
    "la",
    "las",
    "los",
    "y",
    "e",
    "en",
    "san",
    "santa",
    "general",
    "el",
}


def _extract_proper_nouns(text: str) -> set[str]:
    out: set[str] = set()
    for match in _PROPER_RE.finditer(text or ""):
        # Split on connector words so a generic word glued to a real entity
        # (e.g. "Funcionamiento de RIOJA BUS") is judged as two candidates
        # instead of one phrase that must match the source verbatim.
        for chunk in _CONNECTOR_SPLIT_RE.split(match.group(0)):
            candidate = clean_text(chunk).strip(" .,:;")
            if not candidate or candidate in _PROPER_NOUN_STOPWORDS or candidate in _PROPER_NOUN_MONTHS:
                continue
            if len(candidate) <= 2:
                continue
            out.add(candidate)
    return out


def _strip_leading_proper_stopwords(value: str) -> str:
    words = value.split()
    while len(words) > 1 and words[0] in _PROPER_NOUN_STOPWORDS:
        words.pop(0)
    return " ".join(words)


def _acronyms_in(text: str) -> set[str]:
    return {normalize(m.group(0)).replace(" ", "").upper() for m in _ACRONYM_RE.finditer(text or "")}


def _acronym_expansion_matches(candidate: str, acronyms: set[str]) -> bool:
    if not acronyms:
        return False
    words = [w for w in re.split(r"\s+", candidate) if w]
    meaningful = [w for w in words if normalize(w) not in _ACRONYM_STOPWORDS]
    if len(meaningful) < 2:
        return False
    initials = normalize("".join(w[0] for w in meaningful)).replace(" ", "").upper()
    if not initials:
        return False
    return any(acronym.startswith(initials) or initials.startswith(acronym) for acronym in acronyms)


def _is_present(candidate: str, original: str) -> bool:
    candidate_norm = normalize(candidate)
    original_norm = normalize(original)
    return bool(candidate_norm and candidate_norm in original_norm)


def _match_starts_sentence(text: str, match: re.Match) -> bool:
    prefix = text[: match.start()].rstrip()
    return not prefix or prefix[-1] in ".!?\n"


def _html_warnings(content_html: str) -> list[str]:
    warnings: list[str] = []
    soup = BeautifulSoup(content_html or "", "html.parser")
    for tag in soup.find_all(True):
        if tag.name not in _ALLOWED_TAGS:
            warnings.append(f"disallowed_html_tag:{tag.name}")
            continue
        attrs = dict(tag.attrs)
        classes = attrs.pop("class", [])
        if isinstance(classes, str):
            classes = [classes]
        allowed_classes = _ALLOWED_CLASS_ATTRS.get(tag.name, set())
        for class_name in classes:
            if class_name not in allowed_classes:
                warnings.append(f"disallowed_html_class:{tag.name}.{class_name}")
        for attr in attrs:
            warnings.append(f"disallowed_html_attr:{tag.name}.{attr}")
    return warnings


def _similarity_warnings(result: EditorialResult, noticia: dict) -> list[str]:
    original_paragraphs = [normalize(p) for p in get_original_paragraphs(noticia) if len(p) >= 80]
    output_paragraphs: list[str] = []
    if result.lead:
        output_paragraphs.append(result.lead)
    for section in result.sections:
        output_paragraphs.extend(section.paragraphs)
    if result.closing_paragraph:
        output_paragraphs.append(result.closing_paragraph)

    warnings: list[str] = []
    for paragraph in output_paragraphs:
        norm = normalize(paragraph)
        if len(norm) < 80:
            continue
        if any(SequenceMatcher(None, norm, original).ratio() >= 0.965 for original in original_paragraphs):
            warnings.append("linear_paraphrase_detected")
            break

    original = normalize(" ".join(get_original_paragraphs(noticia)))[:7000]
    output = normalize(" ".join(output_paragraphs))[:7000]
    if len(original) >= 250 and len(output) >= 250:
        ratio = SequenceMatcher(None, output, original).ratio()
        if ratio >= 0.92:
            warnings.append(f"copy_paste_similarity:{ratio:.2f}")
    return warnings


def _judicial_warnings(result: EditorialResult, noticia: dict) -> list[str]:
    category = category_to_slug(news_category(noticia))
    original = normalize(_original_text(noticia))
    output = normalize(_result_text(result))
    if category != "policiales" and not any(
        marker in original
        for marker in ("denuncia", "investigacion", "investigacion judicial", "imputacion", "fiscalia")
    ):
        return []

    risky_claims = (
        "es culpable",
        "fue culpable",
        "autor del hecho",
        "autora del hecho",
        "cometio el delito",
        "cometio el crimen",
        "asesino a",
        "robo a",
    )
    return [
        f"unsafe_judicial_claim:{claim}"
        for claim in risky_claims
        if claim in output and claim not in original
    ]


def validate_editorial_result(
    result: EditorialResult,
    noticia: dict,
    *,
    check_similarity: bool = True,
) -> list[str]:
    original = _original_text(noticia)
    output = _result_factual_text(result)
    warnings: list[str] = []

    original_numbers = _extract_numbers(original)
    for number in sorted(_extract_numbers(output)):
        if number not in original_numbers:
            warnings.append(f"invented_number:{number}")

    original_dates = _extract_dates(original)
    for date in sorted(_extract_dates(output)):
        if date not in original_dates:
            warnings.append(f"invented_date:{date}")

    allowed_names = {
        source_display_name(noticia),
        "La Voz Riojana",
        "Redaccion La Voz Riojana",
        "Redacci\u00f3n La Voz Riojana",
    }

    def _name_is_allowed(name: str, acronyms: set[str]) -> bool:
        if _is_present(name, original):
            return True
        if any(_is_present(name, allowed) or _is_present(allowed, name) for allowed in allowed_names):
            return True
        # A name that just spells out an acronym already present in the
        # source (e.g. "Agencia Estatal de Meteorolog\u00eda" for "AEMET") is a
        # clarification, not an invented fact.
        return _acronym_expansion_matches(name, acronyms)

    original_acronyms = _acronyms_in(original)
    seen_warnings: set[str] = set()
    for match in _PROPER_RE.finditer(output):
        whole = clean_text(match.group(0)).strip(" .,:;")
        # Una sola palabra con mayúscula al comienzo de oración puede ser un
        # verbo o sustantivo editorial ("Avanza", "Están", "Fallecimiento").
        # Los nombres de varias palabras, acrónimos y entidades dentro de la
        # oración continúan sujetos a la validación factual.
        if (
            len(whole.split()) == 1
            and not whole.isupper()
            and _match_starts_sentence(output, match)
        ):
            continue
        if whole and _name_is_allowed(whole, original_acronyms):
            continue
        for chunk in _CONNECTOR_SPLIT_RE.split(match.group(0)):
            name = _strip_leading_proper_stopwords(
                clean_text(chunk).strip(" .,:;")
            )
            if not name or name in _PROPER_NOUN_STOPWORDS or name in _PROPER_NOUN_MONTHS:
                continue
            if len(name) <= 2 or name in seen_warnings:
                continue
            if _name_is_allowed(name, original_acronyms):
                continue
            seen_warnings.add(name)
            warnings.append(f"invented_proper_noun:{name}")

    warnings.extend(_judicial_warnings(result, noticia))
    warnings.extend(_html_warnings(result.content_html))
    if check_similarity:
        warnings.extend(_similarity_warnings(result, noticia))
    return warnings


def _paragraph_excerpt(paragraphs: list[str], title: str, *, max_chars: int = 210) -> str:
    source = paragraphs[0] if paragraphs else title
    return clean_text(source, max_chars=max_chars)


def _source_paragraph(noticia: dict, paragraphs: list[str]) -> str:
    source = source_display_name(noticia)
    detail = clean_text(paragraphs[0] if paragraphs else noticia.get("titulo", ""), max_chars=180)
    if detail:
        return f"Seg\u00fan public\u00f3 {source}, {detail}"
    return f"Seg\u00fan public\u00f3 {source}, la informacion surge de la publicacion original."


def _pick_h2(seccion: str, used: set[str]) -> str:
    pool = _H2_POOL.get(normalize(seccion), []) + list(_SAFE_H2)
    available = [h for h in pool if h not in used]
    if not available:
        available = pool or list(_SAFE_H2)
    choice = random.choice(available)
    used.add(choice)
    return choice


def _group_sections(paragraphs: list[str], seccion: str = "") -> list[EditorialSection]:
    if not paragraphs:
        return []
    body = paragraphs[1:] if len(paragraphs) > 1 else paragraphs
    if not body:
        body = paragraphs
    used: set[str] = set()
    if len(body) <= 3:
        return [EditorialSection(heading=_pick_h2(seccion, used), paragraphs=body)]
    sections: list[EditorialSection] = []
    chunk_size = max(2, (len(body) + 1) // 2)
    for index in range(0, len(body), chunk_size):
        chunk = body[index : index + chunk_size]
        if chunk:
            sections.append(EditorialSection(heading=_pick_h2(seccion, used), paragraphs=chunk))
    return sections


def _derive_key_points(noticia: dict, tags: list[str]) -> list[str]:
    candidates: list[str] = []
    for tag in tags:
        if len(tag.split()) <= 3:
            candidates.append(tag)
    hashtag = str(noticia.get("hashtag_localidad") or "").replace("#", "").strip()
    if hashtag:
        candidates.append(hashtag)
    category_tag = _CATEGORY_TAGS.get(category_to_slug(news_category(noticia)))
    if category_tag:
        candidates.append(category_tag)
    for name in sorted(_extract_proper_nouns(_original_text(noticia))):
        if 1 <= len(name.split()) <= 3:
            candidates.append(name)

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = clean_text(candidate, max_chars=32).strip(" #.,;:")
        norm = normalize(clean)
        if not norm or norm in seen or norm in _LOW_QUALITY_TAGS:
            continue
        seen.add(norm)
        out.append(clean)
        if len(out) >= 4:
            break
    return out


def _clean_tags(candidates: list[str], noticia: dict, *, max_tags: int = 6) -> list[str]:
    evidence = normalize(_original_text(noticia))
    category_slug = category_to_slug(news_category(noticia))
    out: list[str] = []
    seen: set[str] = set()

    def add(tag: str, *, require_evidence: bool = True) -> None:
        clean = clean_text(tag, max_chars=40).strip(" #.,;:")
        norm = normalize(clean)
        if not norm or norm in seen or norm in _LOW_QUALITY_TAGS:
            return
        if require_evidence and norm not in evidence:
            return
        seen.add(norm)
        out.append(clean)

    for tag in candidates:
        add(tag)
        if len(out) >= max_tags:
            return out[:max_tags]

    category_tag = _CATEGORY_TAGS.get(category_slug)
    if category_tag:
        add(category_tag, require_evidence=False)

    hashtag = str(noticia.get("hashtag_localidad") or "").replace("#", "").strip()
    if hashtag:
        add(hashtag, require_evidence=False)

    for tag in _TOPIC_TAGS:
        add(tag)
        if len(out) >= max_tags:
            break
    return out[:max_tags]


def render_editorial_html(result: EditorialResult) -> str:
    blocks: list[str] = []

    def esc(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return html.escape(text, quote=True)

    if result.lead:
        blocks.append(f'<p class="lr-lead">{esc(result.lead)}</p>')
    if result.source_paragraph:
        blocks.append(f'<p class="lr-source">{esc(result.source_paragraph)}</p>')
    if result.key_points:
        chips = "".join(f"<span>{esc(point)}</span>" for point in result.key_points[:4] if clean_text(point))
        if chips:
            blocks.append(f'<div class="lr-key-points">{chips}</div>')
    for section in result.sections:
        if section.heading:
            blocks.append(f"<h2>{esc(section.heading)}</h2>")
        for paragraph in section.paragraphs:
            if paragraph:
                blocks.append(f"<p>{esc(paragraph)}</p>")
        if section.items:
            items = "".join(f"<li>{esc(item)}</li>" for item in section.items if clean_text(item))
            if items:
                blocks.append(f"<ul>{items}</ul>")
    if result.closing_paragraph:
        blocks.append(f"<p>{esc(result.closing_paragraph)}</p>")

    result.content_html = "\n".join(blocks)
    return result.content_html


def build_fallback_editorial(noticia: dict, warnings: list[str] | None = None) -> EditorialResult:
    paragraphs = get_original_paragraphs(noticia)
    title = clean_text(noticia.get("titulo") or noticia.get("titulo_original") or "Noticia", max_chars=150)
    tags = _clean_tags([], noticia)
    result = EditorialResult(
        title=title,
        excerpt=_paragraph_excerpt(paragraphs, title),
        lead=paragraphs[0] if paragraphs else title,
        source_paragraph=_source_paragraph(noticia, paragraphs),
        sections=_group_sections(paragraphs, noticia.get("seccion", "")),
        closing_paragraph="",
        key_points=[],
        seo_title=clean_text(title, max_chars=70),
        meta_description=_paragraph_excerpt(paragraphs, title, max_chars=160),
        social_title=clean_text(title, max_chars=90),
        social_description=_paragraph_excerpt(paragraphs, title, max_chars=160),
        focus_keyword=tags[0] if tags else clean_text(title.split(":")[0], max_chars=40),
        tags=tags,
        quality_score=0.0,
        fallback_used=True,
        warnings=list(warnings or []),
    )
    result.key_points = _derive_key_points(noticia, result.tags)
    render_editorial_html(result)
    return result


def _normalize_sections(raw_sections: object) -> list[EditorialSection]:
    sections: list[EditorialSection] = []
    if not isinstance(raw_sections, list):
        return sections
    for raw in raw_sections:
        if isinstance(raw, str):
            text = clean_text(raw)
            if text:
                sections.append(EditorialSection(paragraphs=[text]))
            continue
        if not isinstance(raw, dict):
            continue
        paragraphs = [clean_text(p) for p in raw.get("paragraphs") or raw.get("parrafos") or []]
        items = [clean_text(i) for i in raw.get("items") or raw.get("bullets") or []]
        section = EditorialSection(
            heading=clean_text(raw.get("heading") or raw.get("title") or raw.get("titulo"), max_chars=90),
            paragraphs=[p for p in paragraphs if p],
            items=[i for i in items if i],
        )
        if section.heading or section.paragraphs or section.items:
            sections.append(section)
    return sections


def _quality_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score > 1.0:
        score = score / 10.0
    return max(0.0, min(1.0, score))


def _result_from_ai_payload(data: dict, noticia: dict) -> EditorialResult:
    paragraphs = get_original_paragraphs(noticia)
    title = clean_text(data.get("title") or noticia.get("titulo") or "", max_chars=150)
    tags = _clean_tags([str(t) for t in data.get("tags") or []], noticia)
    result = EditorialResult(
        title=title,
        excerpt=clean_text(data.get("excerpt") or _paragraph_excerpt(paragraphs, title), max_chars=240),
        lead=clean_text(data.get("lead") or (paragraphs[0] if paragraphs else title), max_chars=420),
        source_paragraph=clean_text(data.get("source_paragraph") or "", max_chars=260),
        sections=_normalize_sections(data.get("sections")),
        closing_paragraph=clean_text(data.get("closing_paragraph") or "", max_chars=420),
        key_points=[clean_text(kp, max_chars=32) for kp in data.get("key_points") or [] if clean_text(kp)],
        seo_title=clean_text(data.get("seo_title") or title, max_chars=90),
        meta_description=clean_text(data.get("meta_description") or data.get("seo_description") or "", max_chars=180),
        social_title=clean_text(data.get("social_title") or data.get("og_title") or title, max_chars=120),
        social_description=clean_text(
            data.get("social_description") or data.get("og_description") or "", max_chars=180
        ),
        focus_keyword=clean_text(data.get("focus_keyword") or "", max_chars=50),
        tags=tags,
        quality_score=_quality_score(data.get("quality_score")),
    )
    if not result.source_paragraph:
        result.source_paragraph = _source_paragraph(noticia, paragraphs)
    if not result.sections:
        result.sections = _group_sections(paragraphs, noticia.get("seccion", ""))
    if not result.meta_description:
        result.meta_description = _paragraph_excerpt(paragraphs, title, max_chars=160)
    if not result.social_description:
        result.social_description = result.meta_description
    if not result.focus_keyword:
        result.focus_keyword = tags[0] if tags else clean_text(title.split(":")[0], max_chars=40)
    repaired_points = _derive_key_points(noticia, result.tags)
    result.key_points = [kp for kp in result.key_points if normalize(kp) in normalize(_original_text(noticia))]
    if len(result.key_points) < 2:
        result.key_points = repaired_points
    render_editorial_html(result)
    return result


_SYSTEM_PROMPT = """
Sos editor web de La Voz Riojana. Devolve solo JSON valido, sin markdown.
No escribas HTML. No inventes cifras, fechas, nombres, instituciones, lugares ni contexto.
Si el texto habla de denuncias, investigacion, imputacion o causa judicial, no afirmes culpabilidad.

Campos obligatorios:
title, excerpt, lead, source_paragraph, sections, closing_paragraph, key_points,
seo_title, meta_description, social_title, social_description, focus_keyword,
quality_score, tags.

sections debe ser una lista de objetos con heading, paragraphs y opcionalmente items.
Los headings deben ser concretos y estar basados en la noticia.
key_points y tags deben salir de datos visibles en la noticia.
""".strip()


def _feedback_for_warnings(warnings: list[str], *, min_score: float) -> str:
    directives: list[str] = []
    factual_prefixes = ("invented_number", "invented_date", "invented_proper_noun")

    if any(w.startswith(factual_prefixes) for w in warnings):
        invented = ", ".join(
            warning.split(":", 1)[1]
            for warning in warnings
            if warning.startswith(factual_prefixes) and ":" in warning
        )
        directives.append(
            "Elimina o reemplaza estos datos no comprobados por expresiones literales de la fuente: "
            f"{invented}."
        )
    if any("linear_paraphrase" in w or "copy_paste_similarity" in w for w in warnings):
        directives.append(
            "Reorganiza el contenido por ejes, cambia el orden y la estructura de las oraciones, "
            "y condensa repeticiones sin alterar los hechos."
        )
    if any(w.startswith("quality_score_below_threshold") for w in warnings):
        directives.append(
            f"Mejora claridad, estructura, SEO y precision hasta superar {min_score:.2f}, "
            "sin agregar datos."
        )
    if any(w.startswith("disallowed_html_") for w in warnings):
        directives.append("Devuelve texto JSON sin HTML, atributos, scripts ni etiquetas.")
    if any(w.startswith("unsafe_judicial_claim") for w in warnings):
        directives.append(
            "No afirmes culpabilidad: atribui denuncias e investigaciones y usa lenguaje condicional."
        )
    if "revision_no_material_change" in warnings:
        directives.append(
            "El intento anterior no tuvo cambios materiales: modifica de forma visible los campos "
            "observados, en especial titulo, lead, secciones y metadatos señalados."
        )
    if not directives:
        directives.append("Corregi todos los puntos observados sin inventar datos.")

    return " ".join(directives) + f" Warnings exactos: {'; '.join(warnings)}"


def _quality_warnings(result: EditorialResult, *, min_score: float) -> list[str]:
    if result.quality_score < min_score:
        return [f"quality_score_below_threshold:{result.quality_score:.2f}"]
    return []


def _editorial_feedback_snapshot(result: EditorialResult) -> dict:
    return {
        "title": result.title,
        "excerpt": result.excerpt,
        "lead": result.lead,
        "source_paragraph": result.source_paragraph,
        "sections": [
            {
                "heading": section.heading,
                "paragraphs": list(section.paragraphs),
                "items": list(section.items),
            }
            for section in result.sections
        ],
        "closing_paragraph": result.closing_paragraph,
        "seo_title": result.seo_title,
        "meta_description": result.meta_description,
        "social_title": result.social_title,
        "social_description": result.social_description,
        "focus_keyword": result.focus_keyword,
        "quality_score": result.quality_score,
        "tags": list(result.tags),
    }


def _changed_revision_fields(previous: dict | None, current: dict) -> list[str]:
    if not previous:
        return []
    changed: list[str] = []
    for key in sorted(set(previous) | set(current)):
        before = json.dumps(previous.get(key), ensure_ascii=False, sort_keys=True)
        after = json.dumps(current.get(key), ensure_ascii=False, sort_keys=True)
        if normalize(before) != normalize(after):
            changed.append(key)
    return changed


_MATERIAL_REVISION_FIELDS = {
    "title",
    "excerpt",
    "lead",
    "source_paragraph",
    "sections",
    "closing_paragraph",
    "seo_title",
    "meta_description",
    "social_title",
    "social_description",
}


def _hard_editorial_warnings(warnings: list[str]) -> list[str]:
    prefixes = (
        "invented_number:",
        "invented_date:",
        "invented_proper_noun:",
        "unsafe_judicial_claim:",
        "disallowed_html_",
    )
    return [warning for warning in warnings if warning.startswith(prefixes)]


def _call_ai_enricher(
    noticia: dict,
    *,
    feedback: str | None = None,
    previous_attempt: dict | None = None,
) -> dict:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        raise RuntimeError("OPENAI_API_KEY no configurada")

    model = os.getenv("EDITORIAL_ENRICHER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    timeout = float(os.getenv("OPENAI_TIMEOUT", "60"))
    retry_count = _env_int("OPENAI_RETRY_COUNT", 3)
    retry_sleep = _env_float("OPENAI_RETRY_SLEEP", 2.0)
    client = OpenAI(api_key=api_key, timeout=timeout)

    user_payload = {
        "titulo": noticia.get("titulo") or noticia.get("titulo_original") or "",
        "seccion": news_category(noticia),
        "source": source_display_name(noticia),
        "url": noticia.get("canonical_url") or noticia.get("url") or "",
        "parrafos": get_original_paragraphs(noticia)[:12],
    }
    if feedback:
        user_payload["revision_feedback"] = feedback
    if previous_attempt:
        user_payload["previous_attempt"] = previous_attempt

    last_error: Exception | None = None
    for attempt in range(1, retry_count + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                # Una revisión necesita variación estructural real. La validación
                # factual posterior sigue siendo autoritativa.
                temperature=0.55 if feedback else 0.35,
                max_tokens=1800,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content or "{}")
        except Exception as exc:
            last_error = exc
            logger.warning("Editorial AI attempt %s/%s failed: %s", attempt, retry_count, exc)
            if attempt < retry_count:
                time.sleep(retry_sleep)
    raise RuntimeError(f"Editorial AI failed: {last_error}")


def prepare_editorial(noticia: dict) -> EditorialResult:
    enabled = os.getenv("ENABLE_EDITORIAL_NEWS_ENRICHER", "true").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        result = build_fallback_editorial(noticia, ["editorial_enricher_disabled"])
        _log_diagnostics(result)
        return result

    max_revisions = max(0, _env_int("EDITORIAL_ENRICHER_MAX_REVISIONS", 1))
    min_score = _env_float("EDITORIAL_ENRICHER_MIN_SCORE", 0.86)
    attempts = 1 + max_revisions
    feedback: str | None = None
    last_warnings: list[str] = []
    previous_attempt: dict | None = None
    revision_history: list[dict] = []

    for attempt in range(1, attempts + 1):
        try:
            data = _call_ai_enricher(
                noticia,
                feedback=feedback,
                previous_attempt=previous_attempt,
            )
            result = _result_from_ai_payload(data, noticia)
        except Exception as exc:
            last_warnings = [f"editorial_ai_error:{exc}"]
            break

        current_attempt = _editorial_feedback_snapshot(result)
        changed_fields = _changed_revision_fields(previous_attempt, current_attempt)
        material_changed_fields = [
            field for field in changed_fields if field in _MATERIAL_REVISION_FIELDS
        ]
        warnings = validate_editorial_result(result, noticia, check_similarity=True)
        warnings.extend(_quality_warnings(result, min_score=min_score))
        if previous_attempt is not None and not material_changed_fields:
            warnings.append("revision_no_material_change")
        revision_history.append(
            {
                "attempt": attempt,
                "warnings": list(warnings),
                "changed_fields": changed_fields,
                "material_changed_fields": material_changed_fields,
            }
        )
        result.attempt_count = attempt
        result.revision_history = list(revision_history)
        if not warnings:
            _log_diagnostics(result)
            return result

        last_warnings = warnings
        if attempt < attempts:
            feedback = _feedback_for_warnings(warnings, min_score=min_score)
            previous_attempt = current_attempt
            logger.warning(
                "Editorial attempt %s/%s rejected for %s: %s; retrying with feedback",
                attempt,
                attempts,
                result.title[:70],
                warnings,
            )
            continue

        final_action = os.getenv("EDITORIAL_FINAL_ATTEMPT_ACTION", "publish_last_safe").strip().lower()
        hard_warnings = _hard_editorial_warnings(warnings)
        if final_action == "publish_last_safe" and not hard_warnings:
            result.fallback_used = True
            result.final_attempt_used = True
            result.warnings = list(warnings)
            logger.warning(
                "Editorial final seguro usado para %s tras %s intentos: %s",
                result.title[:70],
                attempts,
                warnings,
            )
            _log_diagnostics(result)
            return result

        logger.warning(
            "Editorial fallback para %s tras %s intentos; bloqueos duros=%s warnings=%s",
            result.title[:70],
            attempts,
            hard_warnings,
            warnings,
        )

    result = build_fallback_editorial(noticia, last_warnings or ["editorial_enrichment_failed"])
    result.attempt_count = len(revision_history)
    result.revision_history = list(revision_history)
    _log_diagnostics(result)
    return result


def _log_diagnostics(result: EditorialResult) -> None:
    h2 = [section.heading for section in result.sections if section.heading]
    html_preview = strip_html(result.content_html)[:240]
    logger.info(
        "Editorial diagnostics fallback=%s score=%.2f warnings=%s tags=%s h2=%s source=%s chips=%s html_preview=%s",
        result.fallback_used,
        result.quality_score,
        result.warnings,
        result.tags,
        h2,
        bool(result.source_paragraph),
        result.key_points,
        html_preview,
    )
