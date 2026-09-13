"""Extracción determinística de entidades y localidades (sin IA, sin embeddings).

Duplica intencionalmente el concepto de localidades riojanas de
``utils/editorial_router.py::RIOJAN_LOCALITY_TERMS`` en vez de importarlo:
ese módulo resuelve routing/dedup de corto plazo y no debe acoplarse al
archivo de largo plazo (mismo patrón de duplicación deliberada que ya usa el
repo entre ``editorial_router`` y ``openIA/rewrite_news.py``).
"""
from __future__ import annotations

import re
import unicodedata

_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+")
_CONNECTOR_WORDS = {
    "de", "del", "la", "las", "los", "y", "e", "en", "san", "santa", "el", "un", "una", "al", "da",
}
_GENERIC_SINGLE_WORDS = {
    "gobierno", "policia", "provincia", "municipio", "ministerio", "hospital",
    "escuela", "hoy", "ayer", "manana", "noticia", "noticias", "informe",
    "operativo", "incendio", "accidente", "partido", "choque", "temporal",
    "denuncia", "comunicado", "ultimo", "momento", "situacion", "caso",
    "hecho", "nota",
}
_SENTENCE_END_CHARS = {".", "!", "?"}

RIOJAN_LOCALITY_TERMS = {
    "la rioja", "rioja", "riojano", "riojana", "riojanos", "riojanas",
    "chilecito", "famatina", "vinchina", "arauco", "chamical",
    "aimogasta", "chepes", "patquia", "tinogasta", "andalgala",
    "casa blanca", "nonogasta", "anguinan", "sierra negra",
    "villa union", "guandacol", "santa florentina", "villa famatina",
    "capital riojana", "general angel", "general lavalle",
}


def ascii_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def normalize_entity(text: str) -> str:
    return re.sub(r"\s+", " ", ascii_lower(text)).strip()


# Alias semántico: la misma normalización sirve de clave de entidad para el
# Context Store (Parte 15 del plan).
entity_key = normalize_entity


def extract_localities(*texts: str) -> list[str]:
    """Localidades riojanas detectadas (claves canónicas en minúsculas).

    Las localidades específicas van antes que el término genérico de
    provincia ("la rioja"/"rioja") para que el llamador pueda preferirlas
    como señal más informativa.
    """
    blob = ascii_lower(" ".join(str(t or "") for t in texts))
    found = [term for term in RIOJAN_LOCALITY_TERMS if f" {term} " in f" {blob} "]
    found.sort(key=lambda term: (term in {"la rioja", "rioja"}, term))
    return found


def _is_sentence_start(text: str, pos: int) -> bool:
    prefix = text[:pos].rstrip()
    if not prefix:
        return True
    return prefix[-1] in _SENTENCE_END_CHARS


def _strip_connectors(words: list[str]) -> list[str]:
    start = 0
    end = len(words)
    while start < end and words[start].lower() in _CONNECTOR_WORDS:
        start += 1
    while end > start and words[end - 1].lower() in _CONNECTOR_WORDS:
        end -= 1
    return words[start:end]


def extract_entities(*texts: str, max_entities: int = 20) -> list[str]:
    """Nombres propios y siglas (personas/instituciones/lugares), en orden de aparición.

    Heurística: corridas de palabras capitalizadas con conectores intermedios
    permitidos ("Ministerio de Salud", "Juan Pérez de la Torre") más siglas de
    2+ letras. Una sola palabra capitalizada (no sigla) al comienzo de una
    oración se descarta (suele ser el inicio de una frase, no una entidad;
    limitación conocida y aceptada, igual que en ``editorial_router``).
    """
    text = "\n".join(str(t or "") for t in texts if t)
    matches = list(_WORD_RE.finditer(text))

    entities: list[str] = []
    seen: set[str] = set()

    buffer: list[str] = []
    buffer_start_is_sentence_start = False
    buffer_has_acronym = False
    pending_connector: str | None = None

    def flush() -> None:
        nonlocal buffer, buffer_has_acronym, buffer_start_is_sentence_start
        trimmed = _strip_connectors(buffer)
        if trimmed:
            single_non_acronym_at_sentence_start = (
                len(trimmed) == 1
                and buffer_start_is_sentence_start
                and not buffer_has_acronym
            )
            key = normalize_entity(" ".join(trimmed))
            if (
                not single_non_acronym_at_sentence_start
                and key
                and key not in seen
                and not (len(trimmed) == 1 and key in _GENERIC_SINGLE_WORDS)
                and not (len(trimmed) == 1 and len(key) < 3)
            ):
                seen.add(key)
                entities.append(" ".join(trimmed))
        buffer = []
        buffer_has_acronym = False
        buffer_start_is_sentence_start = False

    prev_end = 0
    for match in matches:
        gap = text[prev_end:match.start()]
        prev_end = match.end()
        if any(ch.isdigit() for ch in gap):
            # Un numero entre dos palabras rompe la corrida: "Ruta 38 en
            # Chilecito" no debe fusionar "Ruta" con "Chilecito" como si
            # fueran un unico nombre propio compuesto.
            pending_connector = None
            flush()

        word = match.group(0)
        is_acronym = word.isupper() and len(word) >= 2
        is_capitalized = word[0].isupper() and not word.isupper()
        is_connector = word.lower() in _CONNECTOR_WORDS

        if is_acronym or is_capitalized:
            if pending_connector is not None:
                if buffer:
                    buffer.append(pending_connector)
                pending_connector = None
            if not buffer:
                buffer_start_is_sentence_start = _is_sentence_start(text, match.start())
            buffer.append(word)
            buffer_has_acronym = buffer_has_acronym or is_acronym
        elif is_connector and buffer:
            pending_connector = word
        else:
            pending_connector = None
            flush()

        if len(entities) >= max_entities:
            break

    flush()
    return entities[:max_entities]
