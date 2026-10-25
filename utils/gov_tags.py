"""Etiquetas de Instagram para el Gobierno de La Rioja.

Si una nota local nombra un ministerio, secretaría u organismo del directorio
(``config/gov_directory.json``), la publicación de Instagram etiqueta a la
cuenta institucional y a su responsable (``user_tags``) y los menciona con @
en el caption. Facebook no recibe etiquetas: su API no permite mencionar
páginas ajenas y el caption de Facebook se arma sin estas menciones.

Reglas (deterministas, sin IA; nunca se adivina una cuenta):

* sólo cuentas del directorio, verificadas por el operador;
* sólo notas locales (Nueva Rioja, Tiempo Popular, Fénix, judiciales) y nunca
  de las secciones de ``GOV_TAGS_EXCLUDED_SECTIONS`` (policiales por defecto:
  etiquetar a un funcionario en una nota de delito se lee como acusación);
* "Ministerio de Salud de la Nación" o "nacional" no cuentan, y si la nota
  habla del Gobierno nacional ningún ministerio cuenta (sí los nombres);
* un nombre propio sólo cuenta si el texto también nombra un cargo
  (ministro, secretaria, gobernador...): evita homónimos;
* tope por publicación y por 24 h.

Apagado por defecto: ``GOV_TAGS_ENABLED``.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from functools import lru_cache

from utils.logging_setup import setup_logger

logger = setup_logger("gov_tags", "gov_tags.log")

DIRECTORY_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "gov_directory.json")

_LOCAL_SOURCES = ("nuevarioja", "tiempopopular", "fenix", "judicial_")
_NOT_LOCAL_SOURCES = ("nuevarioja_internacionales",)
_ROLE_WORDS = (
    "ministr", "secretari", "subsecretari", "gobernador", "vicegobernador", "jefe de gabinete",
    "funcionari", "titular", "presidente", "presidenta", "director", "coordinador",
)
_NATIONAL = re.compile(r"^\s*(de la nacion|nacional|de nacion)\b")
_NATIONAL_CONTEXT = ("gobierno nacional", "de la nacion", "gobierno de milei", "casa rosada")
_HANDLE = re.compile(r"^[a-z0-9._]{1,30}$")
_TRUE = {"1", "true", "yes", "on", "si", "sí"}


def enabled() -> bool:
    return str(os.getenv("GOV_TAGS_ENABLED", "false")).strip().lower() in _TRUE


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(text or "")) if unicodedata.category(c) != "Mn"
    ).lower()


@lru_cache(maxsize=1)
def _directory(path: str = DIRECTORY_PATH) -> tuple[dict, ...]:
    try:
        with open(path, encoding="utf-8") as handle:
            entries = json.load(handle).get("entries") or []
    except (OSError, ValueError) as exc:
        logger.error("Directorio de etiquetas ilegible (%s): no se etiqueta", type(exc).__name__)
        return ()
    valid = []
    for entry in entries:
        handles = [h for h in (entry.get("institution"), entry.get("person")) if h]
        if any(not _HANDLE.match(str(h)) for h in handles):
            logger.error("Cuenta inválida en el directorio (%s): se ignora la entrada", entry.get("area"))
            continue
        valid.append(entry)
    return tuple(valid)


def _is_local(noticia: dict) -> bool:
    source = str(noticia.get("source") or "")
    return source.startswith(_LOCAL_SOURCES) and not source.startswith(_NOT_LOCAL_SOURCES)


def _excluded_section(noticia: dict) -> bool:
    excluded = {
        _fold(s).strip()
        for s in os.getenv("GOV_TAGS_EXCLUDED_SECTIONS", "policiales").split(",")
        if s.strip()
    }
    return _fold(noticia.get("seccion") or "").strip() in excluded


def _text(noticia: dict) -> str:
    parts = [noticia.get("titulo"), noticia.get("titulo_instagram"), noticia.get("texto_instagram"), noticia.get("excerpt")]
    parts.extend((noticia.get("parrafos") or [])[:6])
    return _fold(" \n ".join(str(p) for p in parts if p))


def _mentions(text: str, alias: str, *, provincial: bool) -> bool:
    pattern = re.compile(r"(?<![a-z0-9])" + re.escape(_fold(alias)) + r"(?![a-z0-9])")
    for match in pattern.finditer(text):
        if provincial and _NATIONAL.match(text[match.end():match.end() + 20]):
            continue
        return True
    return False


def handles_for(noticia: dict) -> list[str]:
    """Cuentas a etiquetar para ``noticia`` (institución primero), sin topes."""
    if not _is_local(noticia) or _excluded_section(noticia):
        return []
    text = _text(noticia)
    if not text:
        return []
    has_role = any(word in text for word in _ROLE_WORDS)
    national = any(cue in text for cue in _NATIONAL_CONTEXT)
    found: list[str] = []
    for entry in _directory():
        area_hit = not national and any(
            _mentions(text, alias, provincial=True) for alias in entry.get("aliases") or []
        )
        person_hit = has_role and any(
            _mentions(text, alias, provincial=False) for alias in entry.get("person_aliases") or []
        )
        if not (area_hit or person_hit):
            continue
        # Pedido editorial: si aparece el área, se etiqueta al área y a su responsable.
        for handle in (entry.get("institution"), entry.get("person")):
            if handle and handle not in found:
                found.append(handle)
    return found


def tags_used_last_24h(records: list[dict], *, now: float | None = None) -> int:
    cutoff = (now or time.time()) - 86400
    total = 0
    for record in records:
        try:
            posted_at = float(record.get("posted_at") or 0)
        except (TypeError, ValueError):
            continue
        if posted_at >= cutoff:
            total += len(record.get("gov_tags") or [])
    return total


def select_tags(noticia: dict, *, used_last_24h: int = 0) -> list[str]:
    """Cuentas a etiquetar respetando ``GOV_TAGS_MAX_PER_POST`` y ``GOV_TAGS_DAILY_MAX``."""
    if not enabled():
        return []
    handles = handles_for(noticia)
    if not handles:
        return []
    per_post = max(0, _int("GOV_TAGS_MAX_PER_POST", 4))
    room = max(0, _int("GOV_TAGS_DAILY_MAX", 20) - used_last_24h)
    selected = handles[: min(per_post, room)]
    if len(selected) < len(handles):
        logger.info("Etiquetas recortadas por tope: %s de %s", len(selected), len(handles))
    return selected


def caption_line(handles: list[str]) -> str:
    return " ".join(f"@{h}" for h in handles)


def image_user_tags(handles: list[str]) -> str:
    """``user_tags`` para imagen: Meta pide coordenadas; van en la franja inferior."""
    count = len(handles)
    tags = [
        {"username": h, "x": round((i + 1) / (count + 1), 3), "y": 0.92}
        for i, h in enumerate(handles)
    ]
    return json.dumps(tags)


def reel_user_tags(handles: list[str]) -> str:
    return json.dumps([{"username": h} for h in handles])
