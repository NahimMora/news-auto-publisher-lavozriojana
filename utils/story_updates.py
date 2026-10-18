"""Seguimiento de noticias en desarrollo.

Si después de publicar una noticia en redes llega otra nota del mismo hecho
con una cifra distinta para lo mismo (desaparecidos, heridos, detenidos...),
se publica la actualización:

* Instagram: historia "Actualización" (dato anterior tachado, dato nuevo) y
  un comentario de la cuenta en la publicación original (la API no permite
  editar el texto de un post de Instagram);
* Facebook: la misma historia y el texto del post original con
  "🔄 Actualización HH:MM" arriba.

Reglas conservadoras, sin IA: el mismo hecho exige muchas palabras en común
y la cifra nueva tiene que estar escrita en el título de la nota nueva. Si
hay dudas (dos cifras para lo mismo, sustantivos distintos), no se publica.
"""
from __future__ import annotations

import re
import time
import unicodedata

from utils.file_manager import JsonStateError, load_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir

logger = setup_logger("story_updates", "social_formats.log")

_NUMBERS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "veinte": 20,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "cien": 100,
}
_NOUNS = {
    "muerto": "muertos", "fallecido": "fallecidos", "victima": "víctimas", "herido": "heridos", "lesionado": "lesionados",
    "desaparecido": "desaparecidos", "detenido": "detenidos", "aprehendido": "aprehendidos", "evacuado": "evacuados",
    "rescatado": "rescatados", "sobreviviente": "sobrevivientes", "hospitalizado": "hospitalizados", "internado": "internados",
    "demorado": "demorados", "imputado": "imputados", "afectado": "afectados", "caso": "casos", "contagio": "contagios",
}
_FACT = re.compile(r"\b(\d{1,4}|" + "|".join(_NUMBERS) + r")\s+(?:\w+\s+)?(" + "|".join(_NOUNS) + r")(?:e?s)?\b")
_STOP = {
    "tras", "para", "entre", "desde", "sobre", "contra", "durante", "luego", "donde", "cuando", "fueron", "estaba", "estan", "sigue",
    # Genéricas: dos choques distintos comparten "choque" y "heridos".
    "choque", "choco", "accidente", "siniestro", "vial", "rioja", "riojana", "riojano", "capital", "provincia", "policia",
    "barrio", "hombre", "mujer", "joven", "personas", "hallaron", "quedan", "otros", "otro",
}


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def facts(title: str) -> dict[str, int]:
    """{"desaparecidos": 3, ...}. Si un sustantivo aparece con dos cifras
    distintas en el mismo título, se descarta (ambiguo)."""
    found: dict[str, set[int]] = {}
    for number, noun in _FACT.findall(fold(title)):
        value = int(number) if number.isdigit() else _NUMBERS[number]
        found.setdefault(_NOUNS[noun], set()).add(value)
    return {noun: next(iter(values)) for noun, values in found.items() if len(values) == 1}


def _words(title: str) -> set[str]:
    nouns = set(_NOUNS) | set(_NOUNS.values())
    words = set()
    for w in re.findall(r"[a-zñ]{5,}", fold(title)):
        stem = w[:-2] if w.endswith("es") and w[:-2] in nouns else w[:-1] if w.endswith("s") and w[:-1] in nouns else w
        if w not in _STOP and stem not in nouns and w not in nouns:
            words.add(w)
    return words


def same_event(a: str, b: str) -> bool:
    """Mismo hecho: al menos dos palabras distintivas en común y que cubran
    la mayor parte del título más corto (sin genéricas ni las cifras)."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    shared = wa & wb
    return len(shared) >= 2 and len(shared) / min(len(wa), len(wb)) >= 0.6


def find_change(original: str, newer: str) -> tuple[str, int, int] | None:
    """(sustantivo, antes, ahora) si la nota nueva cambia una cifra."""
    if not same_event(original, newer):
        return None
    before, after = facts(original), facts(newer)
    for noun, old in before.items():
        new = after.get(noun)
        if new is not None and new != old:
            return noun, old, new
    return None


def phrase(noun: str, value: int) -> str:
    words = {1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete", 8: "ocho", 9: "nueve", 10: "diez"}
    count = words.get(value, str(value))
    if value == 1:
        singular = {"víctimas": "víctima"}.get(noun, noun[:-1] if noun.endswith("s") else noun)
        return f"Una {singular}" if singular.endswith("a") else f"Un {singular}"
    return f"{count[:1].upper()}{count[1:]} {noun}"


def update_candidates(*, now: float | None = None, lookback_hours: float = 48, state: dict | None = None) -> list[dict]:
    """Publicaciones de las últimas ``lookback_hours`` horas con una nota
    posterior del mismo hecho que cambia una cifra."""
    now = now or time.time()
    state = state or {}
    applied = state.get("updates") or {}
    try:
        ig_posted = load_json(str(data_dir() / "ig_posted.json"), {"posted": {}}, expected_type=dict).get("posted") or {}
        fb_posted = load_json(str(data_dir() / "fb_posted.json"), {"posted": {}}, expected_type=dict).get("posted") or {}
        web = load_json(str(data_dir() / "noticias_web_publicadas.json"), [], expected_type=list)
    except JsonStateError as exc:
        logger.warning("Estado ilegible para el seguimiento: %s", exc)
        return []
    fb_by_url = {str(r.get("canonical_url") or ""): r for r in fb_posted.values() if isinstance(r, dict) and r.get("external_id")}
    newer = sorted((r for r in web if isinstance(r, dict) and r.get("web_url")), key=lambda r: float(r.get("published_at_ts") or 0))
    out = []
    for key, record in ig_posted.items():
        if not isinstance(record, dict) or not record.get("external_id"):
            continue
        posted_at = float(record.get("posted_at") or 0)
        title = str(record.get("titulo") or "")
        if now - posted_at > lookback_hours * 3600 or not facts(title):
            continue
        done = applied.get(key) or {}
        if len(done.get("sources") or []) >= 3:
            continue
        for candidate in newer:
            if float(candidate.get("published_at_ts") or 0) <= posted_at:
                continue
            if candidate.get("canonical_url") == record.get("canonical_url") or candidate["web_url"] in (done.get("sources") or []):
                continue
            change = find_change(title, str(candidate.get("titulo") or ""))
            if change:
                fb = fb_by_url.get(str(record.get("canonical_url") or "")) or {}
                out.append({
                    "key": key, "ig_media_id": str(record["external_id"]), "fb_post_id": str(fb.get("external_id") or ""),
                    "original_title": title, "new_title": str(candidate.get("titulo") or ""), "web_url": candidate["web_url"],
                    "noun": change[0], "before": change[1], "after": change[2], "seccion": str(record.get("seccion") or ""),
                })
                break
    return out


def facebook_message(original: str, new_title: str, hhmm: str, link: str) -> str:
    """Texto editado: encabezado de actualización + texto original (sin
    encabezados de actualizaciones anteriores)."""
    body = re.sub(r"^(🔄 Actualización[^\n]*\n+)+", "", original or "")
    return f"🔄 Actualización {hhmm}: {new_title}. Nota actualizada: {link}\n\n{body}".strip()
