"""Noticiero de la Noche: Reel locutado de las 21 con lo más importante del día
en La Rioja (``NightlyNewscastV2`` en Remotion).

Flujo: notas locales publicadas hoy en la web → guion de radio con Gemini
(agrupa los hechos del mismo tema, policiales primero) → control factual de
cifras y nombres contra el texto de cada nota → locución con tonada riojana
(Gemini TTS) → fotos procesadas de la web y video silenciado si la nota lo
trae → render en Remotion con sirena, música y cortinas → MP4 normalizado.

Todo queda detrás de ``NIGHTLY_NEWSCAST_ENABLED`` (apagado por defecto) y
sólo publica en Instagram/Facebook con ``NIGHTLY_NEWSCAST_PUBLISH=true``;
si no, deja el video y el texto listos en ``output/noticiero/<fecha>/``.
Estado propio en ``data/nightly_newscast_state.json``.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass, field
from datetime import date, datetime

from PIL import Image

from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir, output_dir
from utils.social_time import DIAS, MESES, now_ar

logger = setup_logger("nightly_newscast", "nightly_newscast.log")

STATE_PATH = str(data_dir() / "nightly_newscast_state.json")
FPS = 30
_TRUE = {"1", "true", "yes", "on", "si", "sí"}

LOCAL_SOURCES = ("nuevarioja", "tiempopopular", "fenix", "mediosrioja", "judicial_")
EXCLUDED_CATEGORIES = {"deportes", "espectaculos"}
CATEGORIES = ("policiales", "interior", "sociedad", "economia", "salud", "educacion", "cultura", "politica")
# Temas sensibles (víctimas, menores, delitos sexuales, suicidio). Por
# decisión editorial del 2026-10-31 no se descartan: entran marcados y el
# guion y el material visual se tratan con reglas reforzadas (sin nombres de
# víctimas ni caras). ``NIGHTLY_NEWSCAST_SENSITIVE=exclude`` vuelve al filtro.
SENSITIVE = ("abuso", "violacion", "femicidio", "suicid", "menor de edad", "intimo", "pornograf", "grooming", "corrupcion de menores")
SOURCE_NAMES = {
    "nuevarioja": "Nueva Rioja",
    "fenix": "Fénix",
    "mediosrioja": "Medios Rioja",
    "tiempopopular": "Tiempo Popular",
    "judicial_": "Poder Judicial",
}

HOOK_TAIL = "Son las nueve de la noche. Esto es lo que pasó hoy en La Rioja."
OUTRO_TEXT = (
    "Esto fue el noticiero de las nueve de La Voz Riojana. Seguinos para estar al último momento, "
    "y encontrá todas las notas en lavozriojana punto com. Hasta mañana."
)
VOICE_DIRECTION = (
    "Sos el locutor del noticiero de las nueve de la noche de una radio de La Rioja, Argentina. "
    "Hablá con tonada riojana: la erre fuerte arrastrada como en el noroeste, alargá apenas la sílaba "
    "anterior a la acentuada y usá la entonación cantada y tranquila del interior; la 'll' y la 'y' "
    "como una 'ye' suave, nunca la 'sh' porteña; seseo y voseo. Voz grave, cercana y con autoridad, "
    "como hablándole al vecino. Ritmo de radio, ágil pero sin apurarte, con pausas cortas en las comas. "
    "Subí apenas la intensidad en los datos fuertes. Nada de tono de asistente virtual ni de lectura plana. "
    "Leé exactamente este texto, sin agregar, quitar ni cambiar palabras:\n\n"
)

SCRIPT_PROMPT = """Sos el editor del noticiero de las 21 de La Voz Riojana, un medio de La Rioja, Argentina.
Recibís las notas locales publicadas hoy (id, sección, título y texto) y armás el guion de un Reel locutado de radio.

Devolvé SOLO este JSON:
{"gancho": {"locucion": "...", "titulares": ["...", "..."], "ids_imagen": ["..."]},
 "bloques": [{"ids": ["..."], "seccion": "...", "lugar": "...", "titulo": "...", "locucion": "..."}]}

Reglas editoriales (obligatorias):
- Usá SOLO datos que estén en los textos recibidos. No inventes datos, cifras, edades, horarios, armas, personas, causas ni hechos ajenos al original.
- Entre 5 y 6 bloques, elegidos por impacto para los riojanos. Policiales mandan: el primer bloque es el policial más fuerte del día y, si hay suficientes, al menos la mitad de los bloques son policiales. Dejá afuera trámites menores (procesamientos de rutina, denuncias sin detenidos) si hay hechos más fuertes.
- Un hecho no se repite: agrupá en un mismo bloque las notas del MISMO hecho o del mismo fenómeno (por ejemplo, varios incendios del día, o dos detenciones por drogas en el mismo penal) y poné todos sus ids. Si hay varios hechos del mismo tipo en el día (accidentes, incendios, estafas, detenciones por drogas), van juntos en un solo bloque. Nunca juntes hechos sin relación sólo para llenar un bloque.
- No sumes ni cuentes personas, heridos o hechos entre notas distintas ("tres heridos", "dos incendios"): contá cada hecho por separado con las cifras de su nota.
- Presunción de inocencia: "acusado", "investigado", "detenido"; nunca des por probado lo que la nota no da por probado. No nombres víctimas, menores ni datos que los identifiquen.
- Escribí para el oído: oraciones cortas, sujeto y verbo al principio, sin paréntesis ni comillas, sin siglas sin desarrollar. Tono serio y cercano, sin adjetivos de opinión (escándalo, brutal, polémico, terrible).
- No digas días de la semana ni fechas salvo que el texto los diga. Si el texto dice "anoche" o "esta madrugada", podés usarlo.
- Sin saludos ni despedidas: la apertura y el cierre los pone el sistema.
- "seccion": una de policiales, interior, sociedad, economia, salud, educacion, cultura, politica.
- "lugar": barrio o localidad DONDE OCURRIÓ el hecho tal como figura en el texto (máximo 22 caracteres); no el lugar de origen de las personas ni una calle suelta. Si el bloque junta hechos de lugares distintos o no figura, "".
- "titulo": titular de pantalla, sin punto final, máximo 60 caracteres.
- "locucion" de cada bloque: 2 oraciones, máximo 38 palabras. La primera dice el hecho; la segunda, el dato que importa.
- "gancho.locucion": una sola oración de máximo 22 palabras con los 2 o 3 hechos de mayor impacto (no accidentes menores), como el arranque de un noticiero de radio ("Cayó..., ... y ..."). No agregues "esto es lo que pasó hoy": lo agrega el sistema.
- "gancho.titulares": 3 frases de pantalla de máximo 30 caracteres, una por hecho fuerte, en el mismo orden.
- "gancho.ids_imagen": los ids de las notas de esos hechos fuertes, en el mismo orden.
"""


def flag(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# ── Estado ───────────────────────────────────────────────────────────────
def load_state() -> dict:
    return load_json(STATE_PATH, {}, expected_type=dict)


def mark_day(day: str, **fields) -> None:
    def mutate(state):
        entry = state.setdefault(day, {})
        entry.update(fields)
        entry["updated_at"] = int(time.time())
        return state

    update_json(STATE_PATH, mutate, {}, expected_type=dict)


def note_attempt(day: str) -> int:
    attempts = {"n": 0}

    def mutate(state):
        entry = state.setdefault(day, {})
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        attempts["n"] = entry["attempts"]
        return state

    update_json(STATE_PATH, mutate, {}, expected_type=dict)
    return attempts["n"]


def date_label(day: date) -> str:
    return f"{DIAS[day.weekday()]} {day.day} de {MESES[day.month - 1]}".upper()


# ── Selección ────────────────────────────────────────────────────────────
@dataclass
class Candidate:
    id: str
    title: str
    section: str
    source: str
    web_url: str
    published_at: float
    body: str
    photo_url: str = ""
    video_url: str = ""
    localities: list[str] = field(default_factory=list)
    sensitive: bool = False
    photo_path: str = ""      # foto ya procesada (biblioteca), si existe
    library_key: str = ""

    @property
    def source_name(self) -> str:
        for prefix, name in SOURCE_NAMES.items():
            if self.source.startswith(prefix):
                return name
        return ""


def _fold(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def is_sensitive(text: str) -> bool:
    return any(word in _fold(text) for word in SENSITIVE)


def _archive_info(urls: list[str]) -> dict[str, dict]:
    import sqlite3

    path = str(data_dir() / "derived" / "editorial_context.sqlite3")
    if not urls or not os.path.isfile(path):
        return {}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return {}
    try:
        marks = ",".join("?" for _ in urls)
        rows = conn.execute(
            f"select canonical_url, category, localities_json from archive_articles where canonical_url in ({marks})", urls
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    out = {}
    for url, category, localities in rows:
        try:
            locs = [str(x) for x in json.loads(localities or "[]")][:3]
        except (TypeError, ValueError):
            locs = []
        out[url] = {"category": (category or "").lower(), "localities": locs}
    return out


def _video_index() -> dict[str, str]:
    """URL de origen → video de la nota (MP4 directo o YouTube incrustado)."""
    try:
        meta = load_json(str(data_dir() / "noticias_meta.json"), [], expected_type=list)
    except JsonStateError:
        return {}
    out = {}
    for item in meta:
        if not isinstance(item, dict):
            continue
        video = str(item.get("video_url") or item.get("video_embed_url") or "").strip()
        if not video:
            continue
        for key in (item.get("canonical_url"), item.get("url")):
            if key:
                out[str(key)] = video
    return out


def parse_article_body(page: str) -> str:
    """Párrafos del cuerpo de una nota de lavozriojana.com (sin relacionadas)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page, "html.parser")
    container = soup.select_one(".article-content-wrap") or soup.find("article") or soup
    paragraphs = []
    for p in container.find_all("p"):
        text = " ".join(p.get_text(" ", strip=True).split())
        if len(text) >= 60:
            paragraphs.append(text)
    return "\n".join(paragraphs[:10])


def fetch_article_full(web_url: str) -> dict | None:
    """Título, foto original y cuerpo de una nota propia publicada."""
    import requests

    from utils.article_media import _UA, parse_article_page
    from utils.safe_http import UnsafeURLError, safe_get

    if not web_url.startswith("https://lavozriojana.com/"):
        return None
    try:
        response = safe_get(web_url, headers=_UA, timeout=30)
    except (UnsafeURLError, requests.RequestException) as exc:
        logger.warning("No se pudo leer la nota %s: %s", web_url, type(exc).__name__)
        return None
    if response.status_code != 200:
        return None
    data = parse_article_page(response.text)
    data["body"] = parse_article_body(response.text)
    return data


def collect_candidates(*, now: float | None = None, fetch=fetch_article_full, limit: int = 24) -> list[Candidate]:
    """Notas locales publicadas en la web dentro de la ventana del día, sin
    deportes/espectáculos; los temas sensibles entran marcados (salvo
    ``NIGHTLY_NEWSCAST_SENSITIVE=exclude``), policiales primero."""
    now = now or time.time()
    window = _env_int("NIGHTLY_NEWSCAST_WINDOW_HOURS", 15) * 3600
    exclude_sensitive = os.getenv("NIGHTLY_NEWSCAST_SENSITIVE", "include").strip().lower() == "exclude"
    try:
        records = load_json(str(data_dir() / "noticias_web_publicadas.json"), [], expected_type=list)
    except JsonStateError as exc:
        logger.warning("Historial web ilegible: %s", exc)
        return []
    fresh = [
        r for r in records
        if isinstance(r, dict) and r.get("web_url") and 0 <= now - float(r.get("published_at_ts") or 0) <= window
        and str(r.get("source") or "").startswith(LOCAL_SOURCES)
        and not (exclude_sensitive and is_sensitive(str(r.get("titulo") or "")))
    ]
    info = _archive_info([r["web_url"] for r in fresh])
    videos = _video_index()
    ranked = []
    for r in fresh:
        category = info.get(r["web_url"], {}).get("category", "")
        if category in EXCLUDED_CATEGORIES:
            continue
        ranked.append((0 if category == "policiales" else 1, -float(r.get("published_at_ts") or 0), r, category))
    ranked.sort(key=lambda x: (x[0], x[1]))
    out: list[Candidate] = []
    seen: set[str] = set()
    # Policiales mandan en el pool, pero sin tapar el resto del día (la
    # jerarquía final la decide la cartera editorial de V3 por importancia).
    max_policiales = max(1, int(limit * float(os.getenv("NIGHTLY_NEWSCAST_POOL_POLICIAL_SHARE", "0.5"))))
    policiales = 0
    for _prio, _ts, r, category in ranked:
        if len(out) >= limit:
            break
        if r["web_url"] in seen or (category == "policiales" and policiales >= max_policiales):
            continue
        seen.add(r["web_url"])
        article = fetch(r["web_url"])
        if not article or not article.get("title") or not article.get("body"):
            continue
        section = category or _fold(article.get("section") or "")
        if section in EXCLUDED_CATEGORIES:
            continue
        video = ""
        for key in (r.get("canonical_url"), r.get("url")):
            if key and key in videos:
                video = videos[key]
                break
        policiales += int(section == "policiales")
        out.append(Candidate(
            id=f"n{len(out) + 1}",
            title=article["title"],
            section=section,
            source=str(r.get("source") or ""),
            web_url=r["web_url"],
            published_at=float(r.get("published_at_ts") or 0),
            body=article["body"],
            photo_url=article.get("photo_url") or "",
            video_url=video,
            localities=info.get(r["web_url"], {}).get("localities", []),
            sensitive=is_sensitive(f"{r.get('titulo') or ''} {article['title']} {article['body'][:600]}"),
        ))
    return out


# ── Guion ────────────────────────────────────────────────────────────────
@dataclass
class Script:
    hook: str
    teasers: list[str]
    hook_ids: list[str]
    blocks: list[dict]


def _payload(candidates: list[Candidate]) -> str:
    return json.dumps(
        [{"id": c.id, "seccion": c.section, "titulo": c.title, "lugares": c.localities, "sensible": c.sensitive, "texto": c.body[:1400]} for c in candidates],
        ensure_ascii=False,
    )


def _only_at_sentence_start(word: str, text: str) -> bool:
    """La palabra aparece sólo al comienzo de una oración (mayúscula de
    posición, no nombre propio)."""
    hits = list(re.finditer(rf"\b{re.escape(word)}\b", text))
    return bool(hits) and all(re.search(r"(^|[.!?:;\n]\s*)$", text[: m.start()]) for m in hits)


_ARTICLE = re.compile(r"^(El|La|Los|Las|Un|Una)\s+\S+$")


def factual_warnings(text: str, sources: list[Candidate], label: str) -> list[str]:
    """Cifras y nombres propios del guion que no figuran en las notas. Una
    cifra que surge de sumar notas distintas tampoco figura: se rechaza."""
    from pipeline.node_webapp.editorial import _extract_numbers, _extract_proper_nouns, _is_present

    original = "\n".join(f"{c.title}\n{c.body}\n{' '.join(c.localities)}" for c in sources)
    known_numbers = _extract_numbers(original)
    warnings = []
    for number in sorted(_extract_numbers(text, include_uno=False) - known_numbers):
        warnings.append(f"{label}: la cifra '{number}' no está en las notas")
    for noun in sorted(_extract_proper_nouns(text)):
        if noun in {"La Voz Riojana", "La Rioja", "Rioja", "Riojana"}:
            continue
        if " " not in noun and _only_at_sentence_start(noun, text):
            continue
        # "La Justicia", "El Gobierno" al abrir la oración: mayúscula de posición.
        if _ARTICLE.match(noun) and _only_at_sentence_start(noun, text):
            continue
        if not _is_present(noun, original):
            warnings.append(f"{label}: '{noun}' no aparece en las notas")
    for day_name in (_fold(d) for d in DIAS):
        if re.search(rf"\b{day_name}\b", _fold(text)) and day_name not in _fold(original):
            warnings.append(f"{label}: menciona '{day_name}' y la nota no lo dice")
    return warnings


def place_label(raw: str, sources: list[Candidate]) -> str:
    """Lugar del hecho para el rótulo: tiene que figurar en las notas, no
    puede ser el origen de una persona ("oriunda de Patquía") ni una calle
    suelta, y si el bloque junta hechos de lugares distintos queda vacío."""
    lugar = " ".join(raw.split())[:24]
    if not lugar or _fold(lugar).startswith(("calle ", "pasaje ")):
        return ""
    folded = _fold(lugar)
    texts = [_fold(f"{s.title} {s.body} {' '.join(s.localities)}") for s in sources]
    if not all(folded in t for t in texts):
        return ""
    if any(re.search(rf"(oriund[oa]s?|nacid[oa]s?|vecin[oa]s?) de {re.escape(folded)}", t) for t in texts):
        return ""
    if folded in {"la rioja", "rioja", "provincia", "interior", "interior provincial", "argentina"}:
        return ""
    # Mayúsculas tal como figuran en la nota ("chilecito" → "Chilecito").
    for s in sources:
        raw_text = f"{s.title} {s.body} {' '.join(s.localities)}"
        for match in re.finditer(r"[\wÁÉÍÓÚÑáéíóúñü ]+", raw_text):
            chunk = match.group(0)
            idx = _fold(chunk).find(folded)
            if idx >= 0 and len(_fold(chunk)) == len(chunk):
                return chunk[idx: idx + len(lugar)].strip() or lugar
    return lugar


def validate_script(raw: dict, candidates: list[Candidate]) -> tuple[Script | None, list[str]]:
    by_id = {c.id: c for c in candidates}
    warnings: list[str] = []
    blocks = []
    used: set[str] = set()
    for i, b in enumerate(raw.get("bloques") or []):
        if not isinstance(b, dict):
            continue
        ids = [x for x in (b.get("ids") or []) if x in by_id and x not in used]
        locucion = " ".join(str(b.get("locucion") or "").split())
        titulo = " ".join(str(b.get("titulo") or "").split()).rstrip(".")
        seccion = _fold(str(b.get("seccion") or ""))
        if not ids or not locucion or not titulo:
            warnings.append(f"bloque {i + 1}: incompleto o con notas repetidas")
            continue
        if seccion not in CATEGORIES:
            seccion = by_id[ids[0]].section if by_id[ids[0]].section in CATEGORIES else "sociedad"
        if len(locucion.split()) > 45:
            warnings.append(f"bloque {i + 1}: la locución supera 45 palabras")
        if len(titulo) > 70:
            warnings.append(f"bloque {i + 1}: el título supera 70 caracteres")
        sources = [by_id[x] for x in ids]
        tag = f"bloque {i + 1}:"
        block_warnings = [w for w in warnings if w.startswith(tag)]
        block_warnings += factual_warnings(f"{titulo}. {locucion}", sources, f"bloque {i + 1}")
        warnings = [w for w in warnings if not w.startswith(tag)] + block_warnings
        lugar = place_label(str(b.get("lugar") or ""), sources)
        used.update(ids)
        blocks.append({"ids": ids, "seccion": seccion, "lugar": lugar, "titulo": titulo, "locucion": locucion, "_warnings": block_warnings})
    hook = raw.get("gancho") or {}
    hook_text = " ".join(str(hook.get("locucion") or "").split())
    teasers = [" ".join(str(t).split())[:34] for t in (hook.get("titulares") or []) if str(t).strip()][:4]
    hook_ids = [x for x in (hook.get("ids_imagen") or []) if x in by_id][:4]
    chosen = [by_id[x] for b in blocks for x in b["ids"]]
    if not hook_text:
        warnings.append("gancho: falta la locución")
    else:
        warnings += factual_warnings(hook_text + ". " + ". ".join(teasers), chosen or candidates, "gancho")
    if len(blocks) < _env_int("NIGHTLY_NEWSCAST_MIN_BLOCKS", 4):
        warnings.append(f"hay {len(blocks)} bloques válidos; se necesitan al menos {_env_int('NIGHTLY_NEWSCAST_MIN_BLOCKS', 4)}")
    blocks = blocks[: _env_int("NIGHTLY_NEWSCAST_MAX_BLOCKS", 6)]
    # Policiales mandan: si hay alguno, abre el noticiero.
    policiales = [b for b in blocks if b["seccion"] == "policiales"]
    if policiales and blocks and blocks[0]["seccion"] != "policiales":
        blocks.remove(policiales[0])
        blocks.insert(0, policiales[0])
    if not hook_ids:
        hook_ids = [b["ids"][0] for b in blocks[:3]]
    if not hook_text or not blocks:
        return None, warnings
    return Script(hook=hook_text, teasers=teasers, hook_ids=hook_ids, blocks=blocks), warnings


def write_script(candidates: list[Candidate], *, completion=None, attempts: int = 3) -> tuple[Script | None, list[str]]:
    """Pide el guion y lo revisa; ante datos que no figuran en las notas,
    reintenta con esa devolución. Nunca relaja el control factual."""
    from utils.ai_client import chat_completion

    completion = completion or chat_completion
    model = os.getenv("NIGHTLY_NEWSCAST_SCRIPT_MODEL") or os.getenv("GEMINI_MODEL") or None
    feedback = ""
    warnings: list[str] = []
    last: Script | None = None
    for attempt in range(1, attempts + 1):
        user = _payload(candidates)
        if feedback:
            user += "\n\nCorregí estos problemas del intento anterior (sin agregar datos nuevos):\n" + feedback
        try:
            content = completion(
                messages=[{"role": "system", "content": SCRIPT_PROMPT}, {"role": "user", "content": user}],
                model=model,
                temperature=0.4 if attempt == 1 else 0.55,
                max_tokens=3000,
                timeout=float(os.getenv("GEMINI_TIMEOUT", "90")),
                json_mode=True,
                stage="nightly_newscast",
            )
            raw = json.loads(content or "{}")
        except Exception as exc:  # noqa: BLE001 — red, cuota o JSON inválido: se reintenta
            logger.warning("Guion del noticiero, intento %s/%s falló: %s", attempt, attempts, type(exc).__name__)
            warnings = [f"intento {attempt}: {type(exc).__name__}"]
            time.sleep(min(30, 4 * attempt))
            continue
        script, warnings = validate_script(raw if isinstance(raw, dict) else {}, candidates)
        if script and not warnings:
            return _strip(script), []
        logger.info("Guion del noticiero, intento %s/%s con observaciones: %s", attempt, attempts, warnings[:6])
        feedback = "\n".join(f"- {w}" for w in warnings[:12])
        last = script
    # Último recurso: sacar los bloques con observaciones. El gancho tiene
    # que estar limpio y tienen que quedar bloques suficientes; nunca sale
    # un dato sin verificar.
    if last is not None and not any(w.startswith("gancho") or w.startswith("hay ") for w in warnings):
        clean = [b for b in last.blocks if not b["_warnings"]]
        kept_ids = {x for b in clean for x in b["ids"]}
        if len(clean) >= _env_int("NIGHTLY_NEWSCAST_MIN_BLOCKS", 4) and set(last.hook_ids) <= kept_ids:
            dropped = [w for b in last.blocks for w in b["_warnings"]]
            logger.info("Guion del noticiero: salen %d bloques con observaciones: %s", len(last.blocks) - len(clean), dropped[:6])
            last.blocks = clean
            return _strip(last), []
    return None, warnings


def _strip(script: Script) -> Script:
    script.blocks = [{k: v for k, v in b.items() if k != "_warnings"} for b in script.blocks]
    return script


# ── Locución ─────────────────────────────────────────────────────────────
class TTSQuotaError(RuntimeError):
    """Gemini TTS respondió 429: cupo diario agotado."""


def cached_voice(text: str, dest_wav: str) -> float:
    """Locución de un texto fijo (el cierre): se genera una vez por voz,
    modelo y texto, y se reutiliza todas las noches."""
    import hashlib

    from utils.remotion_renderer import REMOTION_DIR

    key = hashlib.sha1("|".join([
        os.getenv("NIGHTLY_NEWSCAST_TTS_MODEL", "gemini-2.5-pro-preview-tts"), os.getenv("NIGHTLY_NEWSCAST_VOICE", "Orus"),
        os.getenv("NIGHTLY_NEWSCAST_TEMPO", "0.97"), VOICE_DIRECTION, text,
    ]).encode("utf-8")).hexdigest()[:12]
    cache_dir = os.path.join(REMOTION_DIR, "public", "tmp", "newscast_cache")
    os.makedirs(cache_dir, exist_ok=True)
    cached = os.path.join(cache_dir, f"voz_{key}.wav")
    if not os.path.isfile(cached):
        synthesize(text, cached)
    shutil.copyfile(cached, dest_wav)
    return media_duration(dest_wav)


def synthesize(text: str, dest_wav: str, *, retries: int = 3, direction: str | None = None, tempo: str | None = None) -> float:
    """Locución con tonada riojana (Gemini TTS). Devuelve la duración en s.
    ``direction``/``tempo`` permiten otra dirección de voz (V3) sin tocar la de V2."""
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY", "")
    if not key or key == "PENDIENTE":
        raise RuntimeError("GEMINI_API_KEY no configurada")
    model = os.getenv("NIGHTLY_NEWSCAST_TTS_MODEL", "gemini-2.5-pro-preview-tts")
    voice = os.getenv("NIGHTLY_NEWSCAST_VOICE", "Orus")
    client = genai.Client(api_key=key)
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
    )
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.models.generate_content(model=model, contents=(direction or VOICE_DIRECTION) + text, config=config)
            data = response.candidates[0].content.parts[0].inline_data.data
            pcm = base64.b64decode(data) if isinstance(data, str) else data
            if not pcm:
                raise RuntimeError("audio vacío")
            break
        except Exception as exc:  # noqa: BLE001 — red o error transitorio: backoff y reintento
            last = exc
            if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
                # Cupo diario agotado: reintentar sólo gasta más cupo.
                raise TTSQuotaError("Cupo diario de locución agotado") from exc
            logger.warning("Locución, intento %s/%s falló: %s", attempt, retries, type(exc).__name__)
            time.sleep(min(60, 6 * attempt))
    else:
        raise RuntimeError(f"No se pudo generar la locución: {type(last).__name__}")
    raw = dest_wav + ".raw.wav"
    with wave.open(raw, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    # Sin silencios en las puntas y un leve empuje de ritmo de radio.
    trim = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05"
    tempo = tempo or os.getenv("NIGHTLY_NEWSCAST_TEMPO", "0.97")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", raw, "-af", f"{trim},areverse,{trim},areverse,atempo={tempo},highpass=f=70",
         "-ar", "48000", dest_wav],
        check=True, capture_output=True, timeout=120,
    )
    os.remove(raw)
    return media_duration(dest_wav)


def media_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return float(out.stdout.strip())


def frames(seconds: float) -> int:
    return int(math.ceil(seconds * FPS))


# ── Medios ───────────────────────────────────────────────────────────────
def prepare_photo(url: str, dest: str) -> tuple[int, int] | None:
    from utils.story_publisher import download_image

    path = download_image(url)
    if not path:
        return None
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((1600, 1600))
            image.save(dest, "JPEG", quality=90)
            return image.size
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def prepare_video(url: str, dest: str, max_seconds: int = 20, max_width: int = 1080) -> tuple[int, int] | None:
    """Video de la nota, silenciado y recortado, listo para Remotion. V3 pide
    ``max_width=1920`` para recortar en vertical sin ampliar un 1080p."""
    from utils.video_renderer import get_source_video

    source, result = get_source_video({"video_url": url})
    if not source:
        if not result.ok:
            logger.info("Video de la nota no disponible (%s)", result.error_type)
        return None
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", source, "-t", str(max_seconds), "-an",
             "-vf", f"scale='min({max_width},iw)':-2,fps=30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-g", "15", "-pix_fmt", "yuv420p", "-movflags", "+faststart", dest],
            check=True, capture_output=True, timeout=600,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("No se pudo preparar el video: %s", type(exc).__name__)
        return None
    finally:
        try:
            os.unlink(source)
        except OSError:
            pass
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", dest],
        capture_output=True, text=True, timeout=60,
    )
    try:
        w, h = (int(x) for x in out.stdout.strip().split(","))
        return w, h
    except ValueError:
        return None


PHOTO_CHECK_PROMPT = (
    "Mirá esta foto de una nota periodística y respondé SOLO este JSON: "
    '{"persona_primer_plano": true|false, "placa_con_texto": true|false}. '
    "persona_primer_plano: hay una cara de persona que ocupa una parte importante de la imagen "
    "(fichaje policial, retrato, primer plano). placa_con_texto: es un flyer, afiche, captura o "
    "gráfico donde el texto es protagonista, no una foto de un lugar o hecho."
)


def check_photo(path: str) -> dict:
    """Control visual de una foto (Gemini). Ante un fallo, no bloquea."""
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY", "")
    if not key or key == "PENDIENTE":
        return {}
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=os.getenv("NIGHTLY_NEWSCAST_VISION_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash",
            contents=[types.Part.from_bytes(data=data, mime_type="image/jpeg"), PHOTO_CHECK_PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
        )
        out = json.loads(response.text or "{}")
        return {"face": bool(out.get("persona_primer_plano")), "flyer": bool(out.get("placa_con_texto"))}
    except Exception as exc:  # noqa: BLE001 — sin control visual se sigue; el operador revisa en la prueba
        logger.warning("Control visual de la foto falló: %s", type(exc).__name__)
        return {}


def usable_media(items: list[dict], *, policial: bool) -> list[dict]:
    """Ninguna cara en primer plano en Policiales (fichajes, retratos de
    acusados); las placas con texto van al final."""
    kept = [m for m in items if not (policial and m.get("face"))]
    return sorted(kept, key=lambda m: (m.get("type") != "video", bool(m.get("flyer"))))


def _clean(item: dict) -> dict:
    return {k: item[k] for k in ("type", "file", "width", "height")}


# ── Armado y render ──────────────────────────────────────────────────────
@dataclass
class Edition:
    day: date
    video_path: str
    caption: str
    script: Script
    blocks: list[dict]
    folder: str
    cover_path: str = ""          # V5: portada 1080×1920 para cover_url
    caption_complete: bool = False  # V5: el caption ya trae sus hashtags


def caption_for(day: date, blocks: list[dict], candidates: dict[str, Candidate]) -> str:
    numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]
    lines = [f"🎙️ Noticiero de la Noche · {date_label(day).capitalize()}", ""]
    tags = ["#LaRioja", "#LaVozRiojana", "#Noticias"]
    for n, b in zip(numbers, blocks):
        lines.append(f"{n} {b['titulo']}")
        if b.get("lugar"):
            tag = "#" + re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ0-9]", "", b["lugar"].title())
            if len(tag) > 2 and tag not in tags:
                tags.append(tag)
    lines += ["", "👉 Seguinos para estar al último momento.", "📲 Notas completas en lavozriojana.com", "", " ".join(tags[:8])]
    return "\n".join(lines)


def build_edition(day: date, candidates: list[Candidate], script: Script) -> Edition:
    from utils.remotion_renderer import REMOTION_DIR
    from utils.video_renderer import _npx_args

    by_id = {c.id: c for c in candidates}
    stamp = f"newscast_{day.isoformat()}_{int(time.time())}"
    work = os.path.join(REMOTION_DIR, "public", "tmp", stamp)
    os.makedirs(work, exist_ok=True)
    rel = f"tmp/{stamp}"
    folder = str(output_dir() / "noticiero" / day.isoformat())
    os.makedirs(folder, exist_ok=True)
    try:
        photos: dict[str, dict] = {}

        def photo(cid: str) -> dict | None:
            if cid in photos:
                return photos[cid]
            c = by_id[cid]
            name = f"{cid}.jpg"
            size = prepare_photo(c.photo_url, os.path.join(work, name)) if c.photo_url else None
            if size:
                photos[cid] = {"type": "image", "file": f"{rel}/{name}", "width": size[0], "height": size[1], **check_photo(os.path.join(work, name))}
            else:
                photos[cid] = None
            return photos[cid]

        max_videos = _env_int("NIGHTLY_NEWSCAST_MAX_VIDEOS", 3)
        video_owner: dict[int, str] = {}
        blocks_props = []
        for i, b in enumerate(script.blocks):
            media = []
            sources = [by_id[x] for x in b["ids"]]
            owner = next((s for s in sources if s.video_url), None)
            if owner and max_videos > 0:
                name = f"v{i}.mp4"
                size = prepare_video(owner.video_url, os.path.join(work, name))
                if size:
                    media.append({"type": "video", "file": f"{rel}/{name}", "width": size[0], "height": size[1]})
                    video_owner[i] = owner.id
                    max_videos -= 1
            for s in sources[:4]:
                item = photo(s.id)
                if item:
                    media.append(item)
            # Temas sensibles: mismas reglas que policiales (ninguna cara).
            media = [_clean(m) for m in usable_media(media, policial=b["seccion"] == "policiales" or any(s.sensitive for s in sources))]
            voice = os.path.join(work, f"b{i}.wav")
            seconds = synthesize(b["locucion"], voice)
            names = sorted({s.source_name for s in sources if s.source_name})
            blocks_props.append({
                "seccion": b["seccion"], "lugar": b["lugar"], "titulo": b["titulo"],
                "credit": ("Con información de " + " y ".join(names)) if names else "",
                "voiceFile": f"{rel}/b{i}.wav", "voiceFrames": frames(seconds), "media": media,
            })
        hook_voice = os.path.join(work, "hook.wav")
        hook_seconds = synthesize(f"{script.hook} {HOOK_TAIL}", hook_voice)
        # Gancho: fotos de los hechos fuertes y después del resto, sin caras ni
        # placas con texto (abre con sirena y luces de patrullero).
        def apt(cid: str) -> dict | None:
            m = photo(cid)
            return m if m and not m.get("face") and not m.get("flyer") else None

        def video_still(cid: str) -> dict | None:
            """Cuadro del video de ESA nota, si lo trae."""
            for i, b in enumerate(script.blocks):
                if video_owner.get(i) == cid:
                    clip = os.path.join(work, f"v{i}.mp4")
                    still = os.path.join(work, f"v{i}_still.jpg")
                    if os.path.isfile(clip) and not os.path.isfile(still):
                        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-i", clip, "-frames:v", "1", still],
                                       capture_output=True, timeout=60)
                    if os.path.isfile(still):
                        with Image.open(still) as image:
                            w, h = image.size
                        return {"type": "image", "file": f"{rel}/v{i}_still.jpg", "width": w, "height": h}
            return None

        # Cada titular con una imagen de SU nota: foto apta, cuadro del video o,
        # si no hay nada, campo de marca (file vacío). Nunca la foto de otra nota.
        aligned: list[dict] = []
        for cid in script.hook_ids[: len(script.teasers)]:
            pick = apt(cid) or video_still(cid)
            aligned.append(pick or {"type": "image", "file": "", "width": 0, "height": 0})
        rest = [m for m in (apt(x) for b in script.blocks for x in b["ids"]) if m and m not in aligned]
        hook_media = [_clean(m) for m in [*aligned, *rest][:8]]
        outro_voice = os.path.join(work, "outro.wav")
        outro_seconds = cached_voice(OUTRO_TEXT, outro_voice)
        props = {
            "dateLabel": date_label(day),
            "hook": {"voiceFile": f"{rel}/hook.wav", "voiceFrames": frames(hook_seconds), "teasers": script.teasers, "media": hook_media},
            "blocks": blocks_props,
            "outro": {"voiceFile": f"{rel}/outro.wav", "voiceFrames": frames(outro_seconds)},
        }
        props_path = os.path.join(work, "props.json")
        with open(props_path, "w", encoding="utf-8") as fh:
            json.dump(props, fh, ensure_ascii=False)
        raw_video = os.path.join(tempfile.gettempdir(), f"lvr_{stamp}.mp4")
        result = subprocess.run(
            _npx_args(["remotion", "render", os.getenv("NIGHTLY_NEWSCAST_ENTRY", "src/index.ts"), "NightlyNewscastV2", raw_video, "--codec=h264", "--crf=19", "--timeout=120000",
                       f"--concurrency={os.getenv('NIGHTLY_NEWSCAST_RENDER_CONCURRENCY', '2')}", f"--props={props_path}"]),
            cwd=REMOTION_DIR, capture_output=True, text=True, timeout=int(os.getenv("NIGHTLY_NEWSCAST_RENDER_TIMEOUT", "1800")),
        )
        if result.returncode != 0 or not os.path.isfile(raw_video):
            raise RuntimeError(f"Render del noticiero falló: {(result.stderr or result.stdout)[-500:]}")
        final = os.path.join(folder, f"noticiero-{day.isoformat()}.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", raw_video, "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=9",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", final],
            check=True, capture_output=True, timeout=600,
        )
        os.unlink(raw_video)
        caption = caption_for(day, script.blocks, by_id)
        with open(os.path.join(folder, "texto.txt"), "w", encoding="utf-8") as fh:
            fh.write(caption)
        with open(os.path.join(folder, "guion.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "gancho": f"{script.hook} {HOOK_TAIL}", "titulares": script.teasers,
                "bloques": [{**b, "notas": [by_id[x].web_url for x in b["ids"]]} for b in script.blocks],
                "cierre": OUTRO_TEXT,
            }, fh, ensure_ascii=False, indent=2)
        return Edition(day=day, video_path=final, caption=caption, script=script, blocks=script.blocks, folder=folder)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── Publicación ──────────────────────────────────────────────────────────
def publish(edition: Edition, *, instagram: bool, facebook: bool) -> dict:
    """Sube el Reel a Instagram y Facebook. Un resultado ambiguo no se
    reintenta: queda marcado para revisión manual."""
    from meta import fb_client, ig_client
    from utils import r2_storage

    day = edition.day.isoformat()
    outcome = {"ig": "skipped", "fb": "skipped"}
    record = load_state().get(day) or {}
    try:
        url, _key = r2_storage.upload_temp(edition.video_path, ttl_hint="reel")
    except RuntimeError as exc:
        logger.warning("No se pudo subir el noticiero a R2: %s", exc)
        return {"ig": "r2_error", "fb": "skipped"}
    item = {"video_url": url, "texto_instagram": edition.caption, "titulo": "Noticiero de la Noche", "seccion": "", "share_to_feed": True, "thumb_offset_ms": 6000}
    # V5: portada propia (cover_url tiene prioridad sobre thumb_offset en
    # Meta), caption con sus propios hashtags y ubicación del medio (La Rioja,
    # no la del hecho) vía utils/ig_location (sólo si IG_LOCATION_ENABLED).
    if edition.cover_path and os.path.isfile(edition.cover_path):
        try:
            item["cover_url"], _cover_key = r2_storage.upload_temp(edition.cover_path, ttl_hint="reel")
        except RuntimeError as exc:
            logger.warning("Portada del noticiero sin subir (se usa el cuadro de 6 s): %s", exc)
    if edition.caption_complete:
        item["caption_complete"] = True
        item["locality"] = os.getenv("NIGHTLY_NEWSCAST_LOCATION", "La Rioja")
    if instagram and not record.get("ig_id") and not record.get("ambiguous"):
        result = ig_client.post_reel_video_to_instagram(item)
        if result.ok and result.external_id:
            outcome["ig"] = "success"
            mark_day(day, ig_id=result.external_id)
        else:
            ambiguous = (result.details or {}).get("publication_outcome") == "unknown"
            outcome["ig"] = "ambiguous" if ambiguous else (result.error_type or "failed")
            if ambiguous:
                mark_day(day, ambiguous="instagram")
    if facebook and not record.get("fb_id") and outcome["ig"] != "ambiguous" and not record.get("ambiguous"):
        result = fb_client.post_reel_video_to_facebook(item)
        if result.ok and result.external_id:
            outcome["fb"] = "success"
            mark_day(day, fb_id=result.external_id)
        else:
            outcome["fb"] = result.error_type or "failed"
    logger.info("Noticiero %s → instagram=%s facebook=%s", day, outcome["ig"], outcome["fb"])
    return outcome


def wait_until_hour(hour: int, *, now_fn=now_ar, sleep=time.sleep, max_wait: int = 3600) -> None:
    """Espera a la hora de salida (el render arranca antes)."""
    moment = now_fn()
    target = moment.replace(hour=hour, minute=0, second=0, microsecond=0)
    delay = (target - moment).total_seconds()
    if 0 < delay <= max_wait:
        logger.info("Noticiero listo; espera %d s hasta las %02d:00", int(delay), hour)
        sleep(delay)


def due(day: str, *, publish_enabled: bool) -> bool:
    """¿Falta generar (o publicar) la edición del día?"""
    record = load_state().get(day) or {}
    if record.get("ambiguous") or int(record.get("attempts") or 0) >= _env_int("NIGHTLY_NEWSCAST_MAX_ATTEMPTS", 2):
        return False
    if publish_enabled:
        return not record.get("ig_id")
    return not record.get("video")


def today() -> date:
    return now_ar().date()


def edition_day(moment: datetime | None = None) -> str:
    return (moment or now_ar()).date().isoformat()
