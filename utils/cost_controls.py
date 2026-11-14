"""Controles de costo de IA (plan del 2026-11-14, decisiones del responsable).

* **Paparazzi por puntaje heurístico** (``PAPARAZZI_HEURISTIC_ENABLED``): antes
  de cualquier llamada a la IA, cada nota de farándula recibe un puntaje 0–10
  sin IA (figuras de primer nivel, hechos fuertes, relleno). Debajo de
  ``PAPARAZZI_HEURISTIC_MIN`` (5) o pasado ``PAPARAZZI_DAILY_MAX`` (10) por día
  no se procesa. Paparazzi sigue saliendo en la web: sólo baja el volumen.
* **Nacionales fuera de la web** (``NATIONAL_WEB_SKIP_ENABLED``): las notas
  nacionales o internacionales sin vínculo riojano (Infobae, internacionales,
  y las de Nueva Rioja que no nombran La Rioja ni una localidad riojana) no
  pasan por la redacción web; siguen compitiendo por Instagram. Paparazzi no
  entra en esta regla.
* **Caption bajo demanda** (``CAPTION_LAZY_ENABLED``): el caption con IA ya no
  se genera al reescribir cada nota; con ``IG_CAPTION_FROM_WEB_ENABLED`` casi
  siempre sale de la nota web sin IA. Se genera sólo si una red lo necesita y
  queda en ``data/caption_cache.json`` para que Instagram y Facebook no lo
  generen dos veces. Las notas con video lo siguen generando al reescribir
  (los Reels usan ese texto).

Todos apagados por defecto: el comportamiento no cambia hasta activarlos.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata

from utils.file_manager import load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_time import now_ar

logger = setup_logger("cost_controls", "cost_controls.log")

_TRUE = {"1", "true", "yes", "on", "si", "sí"}


def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in _TRUE


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def fold(text: object) -> str:
    raw = unicodedata.normalize("NFD", str(text or "").lower())
    return " " + re.sub(r"[^a-z0-9ñ ]+", " ", "".join(c for c in raw if unicodedata.category(c) != "Mn")) + " "


def _has(text: str, terms) -> list[str]:
    return [t for t in terms if f" {t} " in text or (t.endswith("*") and f" {t[:-1]}" in text)]


# ── Paparazzi: puntaje heurístico ────────────────────────────────────────
TOP_FIGURES = (
    "wanda nara", "icardi", "china suarez", "l gante", "tini", "lali", "susana gimenez", "mirtha legrand", "tinelli",
    "messi", "antonela roccuzzo", "pampita", "nicole neumann", "jorge rial", "moria casan", "yanina latorre",
    "angel de brito", "marley", "benjamin vicuna", "flor pena", "graciela alfano", "guillermina valdes", "cris morena",
    "shakira", "bizarrap", "emilia mernes", "duki", "nicki nicole", "charlotte caniggia", "mariana nannis", "darin",
    "francella", "juana viale", "luisana lopilato", "jimena baron", "fatima florez", "yuyito gonzalez", "milei",
    "karina la princesita", "maradona", "dalma maradona", "gianinna maradona", "furia", "gran hermano", "wos",
    "maria becerra", "rodrigo de paul", "la joaqui", "barby franco", "cinthia fernandez", "ricardo fort", "evangelina anderson",
    "martin demichelis", "zaira nara", "paula chaves", "pedro alfonso", "marcelo gallardo", "carmen barbieri", "mauro caiazza",
)
STRONG_EVENTS = (
    "murio", "fallecio", "muerte", "internado", "internada", "internacion", "accidente", "detenido", "detenida", "denuncia",
    "denuncio", "femicidio", "violencia", "juicio", "demanda", "escandalo", "allanaron", "allanamiento", "imputado",
    "separacion", "separaron", "se separo", "divorcio", "ruptura", "infidelidad", "engano", "embarazo", "embarazada",
    "boda", "casamiento", "se caso", "nacio", "bebe", "romance", "confirmo", "blanqueo", "pelea", "cruce", "polemica",
)
FILLER = (
    "horoscopo", "signos", "signo", "recomend*", "serie", "series", "pelicula", "peliculas", "que ver", "estrenos",
    "cartelera", "rating", "receta", "look", "outfit", "vestido", "moda", "tendencia", "tips", "en fotos", "fotos de",
    "cumpleanos", "aniversario", "sorteo", "programacion",
)


def paparazzi_score(noticia: dict) -> int:
    """Puntaje 0–10 sin IA para una nota de farándula."""
    title = fold(noticia.get("titulo"))
    body = fold(" ".join(str(p) for p in (noticia.get("parrafos") or [])[:3]))
    text = title + body
    score = 3
    figures = _has(text, TOP_FIGURES)
    if figures:
        score += 2 if len(figures) == 1 else 3
    events = _has(title, STRONG_EVENTS) or _has(body, STRONG_EVENTS)
    if events:
        score += 3 if _has(title, STRONG_EVENTS) else 1
    if _has(title, FILLER):
        score -= 3
    if noticia.get("video_url") or noticia.get("video_embed_url"):
        score += 1
    return max(0, min(10, score))


def paparazzi_enabled() -> bool:
    return _flag("PAPARAZZI_HEURISTIC_ENABLED")


def state_path() -> str:
    return str(data_dir() / "cost_controls.json")


def paparazzi_gate(noticia: dict, *, now=None) -> tuple[bool, str, int]:
    """(pasa, motivo, puntaje). Si pasa, suma al contador del día."""
    score = paparazzi_score(noticia)
    noticia["paparazzi_heuristic_score"] = score
    minimum = _int("PAPARAZZI_HEURISTIC_MIN", 5)
    if score < minimum:
        return False, f"paparazzi_low_heuristic:{score}", score
    day = now_ar(now).date().isoformat()
    cap = _int("PAPARAZZI_DAILY_MAX", 10)
    result = {"ok": False}

    def mutate(state):
        days = state.setdefault("paparazzi_daily", {})
        for old in [d for d in days if d < day][:-7]:
            days.pop(old, None)
        if days.get(day, 0) < cap:
            days[day] = days.get(day, 0) + 1
            result["ok"] = True
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)
    if not result["ok"]:
        return False, "paparazzi_daily_cap", score
    return True, "", score


# ── Nacionales fuera de la web ───────────────────────────────────────────
def national_web_skip_enabled() -> bool:
    return _flag("NATIONAL_WEB_SKIP_ENABLED")


_ALWAYS_LOCAL_SUFFIXES = ("_locales", "_interior")


def _riojan_places() -> set[str]:
    try:
        from utils.newscast_v5 import _geo

        geo = _geo()
        names = set((geo.get("places") or {}).keys()) | set((geo.get("aliases") or {}).keys())
        return {n for n in names if n and len(n) >= 4 and n not in {"capital", "la capital"}}
    except Exception:  # noqa: BLE001 — sin nomenclador, sólo cuentan las demás señales
        return set()


def is_national(noticia: dict) -> bool:
    """True sólo con evidencia de que la nota NO es riojana (conservador:
    ante cualquier señal riojana, es local). Paparazzi nunca es "nacional" acá."""
    source = str(noticia.get("source") or "").strip().lower()
    if source.startswith("paparazzi") or source.endswith(_ALWAYS_LOCAL_SUFFIXES) or source.startswith(("judicial_", "fenix", "mediosrioja", "tiempopopular")):
        return False
    always_national = source.startswith("infobae") or "internacional" in source
    if not always_national and not source.startswith("nuevarioja"):
        return False
    try:
        from utils.editorial_router import detect_riojan_link

        if detect_riojan_link(noticia)[0] and not always_national:
            return False
    except Exception:  # noqa: BLE001
        return False
    text = fold(" ".join([str(noticia.get("titulo") or ""), str(noticia.get("titulo_original") or ""),
                          " ".join(str(p) for p in (noticia.get("parrafos") or []))]))
    if " la rioja " in text or " riojan" in text:
        return False
    if any(f" {place} " in text for place in _riojan_places()):
        return False
    return True


# ── Caption bajo demanda ─────────────────────────────────────────────────
def lazy_caption_enabled() -> bool:
    return _flag("CAPTION_LAZY_ENABLED")


CAPTION_FIELDS = ("titulo_instagram", "texto_instagram", "cta")


def caption_cache_path() -> str:
    return str(data_dir() / "caption_cache.json")


def _caption_key(noticia: dict) -> str:
    return str(noticia.get("canonical_url") or noticia.get("url") or noticia.get("meta_queue_key") or noticia.get("titulo") or "")


def ensure_caption(noticia: dict, *, generator=None) -> dict:
    """Completa el caption de una nota diferida: primero el caché, si no la IA
    (una sola vez por nota). Devuelve la nota (modificada en el lugar)."""
    if not noticia.get("caption_deferred") or str(noticia.get("texto_instagram") or "").strip():
        return noticia
    key = _caption_key(noticia)
    cached = (load_json(caption_cache_path(), {}, expected_type=dict).get(key) or {}) if key else {}
    if cached.get("texto_instagram"):
        noticia.update({k: cached[k] for k in CAPTION_FIELDS if k in cached})
        return noticia
    if generator is None:
        from openIA.caption_generator import generate_caption as generator
    data = generator(noticia) or {}
    noticia.update(data)
    if key and data.get("texto_instagram") and not data.get("caption_fallback_used"):
        now = time.time()

        def mutate(state):
            for k in [k for k, v in state.items() if now - float(v.get("at") or 0) > 14 * 86400]:
                state.pop(k, None)
            state[key] = {**{k: data[k] for k in CAPTION_FIELDS if k in data}, "at": int(now)}
            return state

        update_json(caption_cache_path(), mutate, {}, expected_type=dict)
    logger.info("Caption generado bajo demanda: %s", str(noticia.get("titulo") or "")[:70])
    return noticia
