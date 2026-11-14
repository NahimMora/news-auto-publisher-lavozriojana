"""Reels de formato propio (Fase 2, criterios del responsable del 2026-11-14).

* **Último momento (UM)**: sólo una PRIMICIA (primera nota de ese hecho, de
  menos de ``FORMAT_REELS_UM_MAX_AGE_MINUTES``), urgente (``is_breaking``),
  riojana, con FOTO FUERTE y VIDEO REAL del lugar (nunca el estudio de una
  radio o un canal). Máximo ``FORMAT_REELS_UM_MAX_PER_DAY`` (2) por día.
* **Datos útiles (DU)**: sin tope diario, sólo notas riojanas con muchos datos
  concretos (al menos ``FORMAT_REELS_DU_MIN_CARDS`` tarjetas verificadas) y
  alto interés probable para el público riojano (puntaje de la IA ≥
  ``FORMAT_REELS_DU_MIN_INTEREST``).

El guion lo escribe Gemini y se controla contra la nota (cifras, nombres y
días que no figuran → se reintenta con esa devolución; nunca se relaja). La
voz es Gemini TTS (``FORMAT_REELS_VOICE``, Fenrir) y los subtítulos salen de
alinear el texto con la locución real (whisper.cpp): si no alinea, no sale.
Render: Remotion ``FormatReel``. Publicación: Reel en Instagram (+ video en
Facebook) con portada propia. Estado propio (``data/format_reels.json``):
cada nota se evalúa una sola vez por formato y un resultado ambiguo de Meta
no se reintenta.

Voz: ``FORMAT_REELS_TTS_MODEL`` (default ``gemini-3.8-flash-tts``: los modelos de voz 2.5
se dan de baja el 2026-11-17).

Interruptores (apagados por defecto): ``FORMAT_REELS_UM_ENABLED``,
``FORMAT_REELS_DU_ENABLED``; ``FORMAT_REELS_FACEBOOK`` (default ``true``).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

from utils import nightly_newscast as nn
from utils.editorial_priority import is_breaking
from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_time import now_ar

logger = setup_logger("format_reels", "format_reels.log")

FPS = 30
COMPOSITION = "FormatReel"
CLOSING = {"um": "Seguí a La Voz Riojana.", "du": "Compartilo y guardalo."}
BADGE = {"um": "ÚLTIMO MOMENTO", "du": "DATO ÚTIL"}
ACCENT = {"um": "#FF7A1A", "du": "#FFD15C"}
CARD_CAPTIONS = ("pill", "marker", "chunk", "callout", "pop")
DIRECTION = (
    "Sos el locutor de último momento de un medio de La Rioja, Argentina. Voz potente, enérgica y urgente, "
    "que atrape desde la primera palabra, como un flash informativo de radio. Ritmo rápido y decidido, sin atropellarte "
    "ni comerte sílabas, con pausas mínimas entre frases. Español argentino con tonada riojana bien reconocible pero "
    "natural: seseo, voseo, la 'll' y la 'y' como una 'ye' suave, nunca la 'sh' porteña. Golpeá la primera frase y "
    "remarcá cifras, lugares y lo que pasó. Nada de tono solemne, cansino ni de asistente virtual. Leé exactamente este "
    "texto, sin agregar, quitar ni cambiar palabras:\n\n"
)
NO_INVENT = (
    "Usá SOLO datos que estén escritos en la nota: no inventes cifras, fechas, días, horarios, lugares, personas, "
    "armas, instituciones ni hechos, y no completes con conocimiento propio. Si la nota no lo dice, no va."
)

UM_PROMPT = (
    "Escribís el guion de un Reel vertical de ÚLTIMO MOMENTO de La Voz Riojana (15 a 20 segundos, voz en off). "
    + NO_INVENT
    + " Respondé SOLO este JSON: {\"gancho\": str, \"lugar\": str, \"tramos\": [{\"tipo\": \"chips\"|\"sellos\"|\"cifra\", "
    "\"locucion\": str, \"items\": [str], \"valor\": str, \"etiqueta\": str, \"detalle\": str}]}. "
    "gancho: el titular hablado, completo, directo y con fuerza, de 4 a 10 palabras (se muestra entero y grande). "
    "lugar: la localidad riojana del hecho tal como figura en la nota (vacío si no la dice). "
    "tramos: 2 o 3, cada uno con una locución de 8 a 16 palabras que cuenta qué pasó, dónde, cómo sigue. "
    "chips: 2 o 3 items cortos (máx. 22 caracteres) con qué/cuándo/dónde, cada uno con una palabra que se dice en su locución. "
    "Escribí items, etiqueta y detalle en minúscula normal (con mayúscula sólo en nombres propios): en pantalla se pasan a mayúsculas. "
    "sellos: 2 o 3 palabras fuertes (máx. 22 caracteres) que se dicen en la locución. "
    "cifra: sólo si la nota trae una cifra clave; valor = la cifra tal cual (p. ej. \"2\" o \"$20.000\"), etiqueta = qué cuenta "
    "(máx. 26 caracteres), detalle = sello corto opcional (máx. 20). En cifra, items vacío. "
    "Total de palabras habladas (gancho + locuciones) entre 32 y 52: contalas antes de responder; si sobran, acortá. "
    "Copiá cifras, horarios y fechas EXACTAMENTE como están en la nota. Español rioplatense, voseo, frases cortas. "
    "No digas 'último momento' ni el nombre del medio: eso ya está en pantalla."
)

DU_PROMPT = (
    "Evaluás si una nota de La Voz Riojana sirve para un Reel de DATOS ÚTILES (tarjetas con datos concretos que la gente "
    "guarda y comparte: fechas, plazos, montos, requisitos, horarios, lugares, cómo hacer un trámite, cronogramas). "
    + NO_INVENT
    + " Respondé SOLO este JSON: {\"apta\": bool, \"interes\": int, \"motivo\": str, \"gancho\": str, "
    "\"tarjetas\": [{\"etiqueta\": str, \"valor\": str, \"detalle\": str, \"locucion\": str}]}. "
    "apta: true sólo si la nota trae al menos 4 datos concretos y prácticos distintos. "
    "interes: 0 a 10, qué tan probable es que le sirva a mucha gente de La Rioja (10 = trámite, pago, inscripción o "
    "servicio masivo en la provincia; 0 = no le sirve a nadie de La Rioja). "
    "gancho: pregunta o llamado corto de 4 a 9 palabras que se dice primero y se muestra entero (p. ej. "
    "\"¿Vas a estudiar en la UNLaR? Anotá esto.\"). "
    "Escribí etiquetas y valores en minúscula normal (mayúscula sólo en nombres propios). "
    "tarjetas: 4 o 5; etiqueta = qué es (máx. 28 caracteres), valor = el dato tal cual figura (máx. 24 caracteres), "
    "detalle = aclaración corta opcional (máx. 40), locucion = cómo se dice ese dato, de 4 a 9 palabras, que incluya el valor. "
    "Copiá cifras, horarios y fechas EXACTAMENTE como están en la nota. "
    "Total de palabras habladas (gancho + locuciones) entre 30 y 56: contalas antes de responder; si sobran, acortá. "
    "Español rioplatense, voseo."
)


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def enabled(kind: str) -> bool:
    return _flag(f"FORMAT_REELS_{kind.upper()}_ENABLED")


def voice() -> str:
    return os.getenv("FORMAT_REELS_VOICE", "Fenrir").strip() or "Fenrir"


# ── Estado ───────────────────────────────────────────────────────────────
def state_path() -> str:
    return str(data_dir() / "format_reels.json")


def load_state() -> dict:
    return load_json(state_path(), {}, expected_type=dict)


def mark(kind: str, url: str, **fields) -> None:
    def mutate(state):
        entry = state.setdefault("items", {}).setdefault(f"{kind}:{url}", {})
        entry.update(fields)
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)


def published_today(kind: str, state: dict, day: str) -> int:
    return sum(1 for key, v in (state.get("items") or {}).items()
               if key.startswith(f"{kind}:") and v.get("day") == day and (v.get("ig_id") or v.get("status") in {"ambiguous", "publishing"}))


# ── Selección ────────────────────────────────────────────────────────────
@dataclass
class Note:
    url: str
    title: str
    category: str
    localities: list[str]
    published_at: float
    source: str
    canonical: str = ""
    video_url: str = ""
    record: dict = field(default_factory=dict)


def _web_records() -> list[dict]:
    try:
        return [r for r in load_json(str(data_dir() / "noticias_web_publicadas.json"), [], expected_type=list) if isinstance(r, dict)]
    except JsonStateError as exc:
        logger.warning("Historial web ilegible: %s", exc)
        return []


def recent_notes(max_age_minutes: int, *, now: float | None = None) -> list[Note]:
    """Notas locales publicadas en la web en la ventana, más nuevas primero."""
    now = now or time.time()
    records = _web_records()
    fresh = [r for r in records if r.get("web_url") and 0 <= now - float(r.get("published_at_ts") or 0) <= max_age_minutes * 60
             and str(r.get("source") or "").startswith(nn.LOCAL_SOURCES)]
    info = nn._archive_info([r["web_url"] for r in fresh])
    videos = nn._video_index()
    out = []
    for r in sorted(fresh, key=lambda x: -float(x.get("published_at_ts") or 0)):
        video = ""
        for key in (r.get("canonical_url"), r.get("url")):
            if key and key in videos:
                video = videos[key]
                break
        meta = info.get(r["web_url"], {})
        out.append(Note(url=r["web_url"], title=str(r.get("titulo") or ""), category=meta.get("category", ""),
                        localities=meta.get("localities", []), published_at=float(r.get("published_at_ts") or 0),
                        source=str(r.get("source") or ""), canonical=str(r.get("canonical_url") or ""), video_url=video, record=r))
    return out


def is_scoop(note: Note, *, records: list[dict] | None = None, lookback_hours: int = 36) -> bool:
    """Primicia: ninguna nota anterior (de las últimas ``lookback_hours``) cuenta
    el mismo hecho. Un seguimiento o una actualización no es primicia."""
    from utils.story_updates import same_event

    records = records if records is not None else _web_records()
    for r in records:
        ts = float(r.get("published_at_ts") or 0)
        if r.get("web_url") == note.url or not (note.published_at - lookback_hours * 3600 <= ts < note.published_at):
            continue
        if same_event(str(r.get("titulo") or ""), note.title):
            return False
    return True


def clean_body(page: str) -> str:
    """Sólo la bajada, los puntos clave y el cuerpo de la nota (``.article-lead``,
    ``.lr-key-points``, ``.lr-article``). Las cajas de contexto, fuentes,
    relacionadas y la firma quedan afuera: traen datos de OTRAS notas."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page, "html.parser")
    parts: list[str] = []
    for node in soup.select(".article-lead, .lr-key-points, .lr-article"):
        for el in node.find_all(["p", "li"]) or [node]:
            text = " ".join(el.get_text(" ", strip=True).split())
            if len(text) >= 25 and text not in parts:
                parts.append(text)
    return "\n".join(parts)[:6000]


def fetch_note(web_url: str) -> dict | None:
    """Título, foto y cuerpo LIMPIO de una nota propia publicada."""
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
    data["body"] = clean_body(response.text)
    return data


def is_riojan(cand: nn.Candidate) -> bool:
    """Hecho riojano: la nota nombra La Rioja o una localidad del nomenclador
    riojano ("Capital" sola no alcanza: puede ser Capital Federal)."""
    from utils.newscast_v5 import _geo

    source = (cand.source or "").lower()
    if source.endswith(("_locales", "_interior")) or source.startswith("judicial_"):
        return True  # secciones locales y del interior de los medios riojanos, y el MPF
    text = " " + re.sub(r"[^a-z0-9ñ ]", " ", nn._fold(f"{cand.title} {cand.body[:2500]} {' '.join(cand.localities)}")) + " "
    if " la rioja " in text or " riojan" in text:
        return True
    # Localidades que el archivo editorial ya detectó o la sección Interior
    # (en lavozriojana.com es el interior riojano).
    if cand.localities or cand.section == "interior":
        return True
    geo = _geo()
    names = set((geo.get("places") or {}).keys()) | set((geo.get("aliases") or {}).keys())
    return any(f" {name} " in text for name in names if name and name not in {"capital", "la capital"} and len(name) >= 4)


# ── Guion ────────────────────────────────────────────────────────────────
@dataclass
class Beat:
    layout: str
    caption: str
    text: str            # locución del tramo (lo que se dice)
    title: str = ""
    items: list[str] = field(default_factory=list)
    value: str = ""
    label: str = ""
    detail: str = ""
    index: int = 0


@dataclass
class Plan:
    kind: str
    beats: list[Beat]
    place: str = ""
    interest: int = 0

    @property
    def text(self) -> str:
        return " ".join(b.text for b in self.beats)


def _clean(text: object, limit: int = 400) -> str:
    return " ".join(str(text or "").split())[:limit]


def _words(text: str) -> int:
    return len(text.split())


def _fact_check(texts: list[str], cand: nn.Candidate, label: str) -> list[str]:
    """Control factual del noticiero, sin el falso positivo de la mayúscula de
    comienzo de oración o de pregunta ("¿Cobrás Chachos?" → sólo "Chachos")."""
    from pipeline.node_webapp.editorial import _is_present

    text = ". ".join(t for t in texts if t)
    original = "\n".join([cand.title, cand.body, " ".join(cand.localities)])
    out = []
    for w in nn.factual_warnings(text, [cand], label):
        m = re.match(r".*: '(.+)' no aparece en las notas$", w)
        noun = m.group(1) if m else ""
        opener = rf"(^|[.!?¿¡:]\s*)"
        if noun and " " not in noun and re.search(opener + re.escape(noun) + r"\b", text) \
                and not re.search(rf"[^.!?¿¡:\s]\s+" + re.escape(noun) + r"\b", text):
            continue  # mayúscula sólo por abrir oración o pregunta
        if noun and " " in noun:
            words = noun.split()
            starts = re.search(opener + re.escape(words[0]) + r"\b", text)
            rest = " ".join(words[1:])
            if starts and rest and _is_present(rest, original):
                continue
        out.append(w)
    return out


def validate_um(raw: dict, cand: nn.Candidate) -> tuple[Plan | None, list[str]]:
    warnings: list[str] = []
    hook = _clean(raw.get("gancho"), 120).rstrip(".")
    if not 3 <= _words(hook) <= 11:
        warnings.append("gancho: tiene que tener de 4 a 10 palabras")
    beats = [Beat("hook", "title", hook + ".", title=hook)]
    captions = {"chips": "callout", "sellos": "marker", "cifra": "pill"}
    layouts = {"chips": "chips", "sellos": "stamps", "cifra": "number"}
    for i, t in enumerate((raw.get("tramos") or [])[:3]):
        if not isinstance(t, dict):
            continue
        kind = str(t.get("tipo") or "")
        speech = _clean(t.get("locucion"), 200)
        if kind not in layouts or not speech:
            warnings.append(f"tramo {i + 1}: incompleto")
            continue
        items = [_clean(x, 26) for x in (t.get("items") or []) if _clean(x)][:3]
        # En pantalla van en mayúsculas; el control se hace en minúscula si
        # llegaron todo en mayúsculas (si no, cada palabra parece un nombre propio).
        checked_items = [x.lower() if x.isupper() else x for x in items]
        beat = Beat(layouts[kind], captions[kind], speech if re.search(r"[.!?]$", speech) else speech + ".", items=items)
        if kind == "cifra":
            beat.value, beat.label, beat.detail = _clean(t.get("valor"), 12), _clean(t.get("etiqueta"), 30), _clean(t.get("detalle"), 22)
            if not beat.value or not beat.label:
                warnings.append(f"tramo {i + 1}: la cifra necesita valor y etiqueta")
            beat.items = [beat.detail] if beat.detail else []
        elif len(items) < 2:
            warnings.append(f"tramo {i + 1}: necesita 2 o 3 items")
        label_detail = [x.lower() if x.isupper() else x for x in (beat.label, beat.detail)]
        warnings += _fact_check([speech, ". ".join(checked_items), beat.value, *label_detail], cand, f"tramo {i + 1}")
        beats.append(beat)
    if len(beats) < 3:
        warnings.append("hacen falta 2 o 3 tramos válidos")
    layouts_used = [b.layout for b in beats[1:]]
    if len(layouts_used) != len(set(layouts_used)):
        warnings.append("cada tramo tiene que usar un tipo distinto (chips, sellos, cifra)")
    warnings += _fact_check([hook], cand, "gancho")
    spoken = sum(_words(b.text) for b in beats)
    if not 28 <= spoken <= 58:
        warnings.append(f"el guion tiene {spoken} palabras; tienen que ser entre 32 y 52")
    beats.append(Beat("outro", "none", CLOSING["um"]))
    place = _clean(raw.get("lugar"), 40)
    if place and nn._fold(place) not in nn._fold(f"{cand.title} {cand.body} {' '.join(cand.localities)}"):
        place = ""
    return (Plan("um", beats, place=place) if len(beats) >= 4 else None), warnings


def validate_du(raw: dict, cand: nn.Candidate) -> tuple[Plan | None, list[str], bool]:
    """(plan, observaciones, apta). ``apta=False`` = la nota no califica (no se reintenta)."""
    interest = int(raw.get("interes") or 0) if str(raw.get("interes") or "0").lstrip("-").isdigit() else 0
    if not raw.get("apta") or interest < _int("FORMAT_REELS_DU_MIN_INTEREST", 7):
        return None, [f"no califica: apta={bool(raw.get('apta'))} interés={interest} ({_clean(raw.get('motivo'), 120)})"], False
    warnings: list[str] = []
    hook = _clean(raw.get("gancho"), 100)
    if not 3 <= _words(hook) <= 10:
        warnings.append("gancho: tiene que tener de 4 a 9 palabras")
    beats = [Beat("hook", "title", hook if re.search(r"[.!?]$", hook) else hook + ".", title=hook)]
    cards = []
    for i, t in enumerate((raw.get("tarjetas") or [])[:5]):
        if not isinstance(t, dict):
            continue
        label, value, detail, speech = _clean(t.get("etiqueta"), 30), _clean(t.get("valor"), 26), _clean(t.get("detalle"), 44), _clean(t.get("locucion"), 140)
        if not (label and value and speech):
            warnings.append(f"tarjeta {i + 1}: incompleta")
            continue
        warnings += _fact_check([label, value, detail, speech], cand, f"tarjeta {i + 1}")
        cards.append(Beat("card", CARD_CAPTIONS[len(cards) % len(CARD_CAPTIONS)], speech if re.search(r"[.!?]$", speech) else speech + ".",
                          items=[value], value=value, label=label, detail=detail, index=len(cards) + 1))
    beats += cards
    if len(cards) < _int("FORMAT_REELS_DU_MIN_CARDS", 4):
        warnings.append(f"hay {len(cards)} tarjetas válidas; hacen falta al menos {_int('FORMAT_REELS_DU_MIN_CARDS', 4)}")
    warnings += _fact_check([hook], cand, "gancho")
    spoken = sum(_words(b.text) for b in beats)
    if not 26 <= spoken <= 62:
        warnings.append(f"el guion tiene {spoken} palabras; tienen que ser entre 30 y 56")
    beats.append(Beat("outro", "none", CLOSING["du"]))
    return (Plan("du", beats, interest=interest) if len(cards) >= 1 else None), warnings, True


def write_plan(kind: str, cand: nn.Candidate, *, completion=None, attempts: int = 4) -> tuple[Plan | None, list[str], bool]:
    """Pide el guion y lo controla; reintenta con la devolución. ``(plan, obs, califica)``."""
    from utils.ai_client import chat_completion

    completion = completion or chat_completion
    prompt = UM_PROMPT if kind == "um" else DU_PROMPT
    payload = json.dumps({"titulo": cand.title, "seccion": cand.section, "localidades": cand.localities, "nota": cand.body[:3500]}, ensure_ascii=False)
    feedback = ""
    warnings: list[str] = []
    for attempt in range(1, attempts + 1):
        user = payload + (f"\n\nCorregí estos problemas del intento anterior sin agregar datos nuevos:\n{feedback}" if feedback else "")
        try:
            content = completion(
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                model=os.getenv("FORMAT_REELS_SCRIPT_MODEL") or os.getenv("GEMINI_MODEL") or None,
                temperature=0.35 if attempt == 1 else 0.5, max_tokens=1600,
                timeout=float(os.getenv("GEMINI_TIMEOUT", "90")), json_mode=True, stage="format_reels",
            )
            raw = json.loads(content or "{}")
            raw = raw if isinstance(raw, dict) else {}
        except Exception as exc:  # noqa: BLE001 — red, cuota o JSON inválido: se reintenta
            warnings = [f"intento {attempt}: {type(exc).__name__}"]
            time.sleep(min(20, 4 * attempt))
            continue
        if kind == "um":
            plan, warnings = validate_um(raw, cand)
        else:
            plan, warnings, ok = validate_du(raw, cand)
            if not ok:
                return None, warnings, False
        if plan and not warnings:
            return plan, [], True
        logger.info("Guion %s, intento %s/%s con observaciones: %s", kind, attempt, attempts, warnings[:5])
        feedback = "\n".join(f"- {w}" for w in warnings[:10])
    return None, warnings, True


# ── Tiempos ──────────────────────────────────────────────────────────────
def _fold_word(word: str) -> str:
    return re.sub(r"[^\w$]", "", nn._fold(word))


def _key_time(item: str, tokens: list, start: int, end: int) -> int | None:
    """Milisegundo en que se dice una palabra del ítem dentro del tramo."""
    parts = [_fold_word(p) for p in item.split() if len(_fold_word(p)) >= 3 or any(ch.isdigit() for ch in p)]
    for tok in tokens[start:end]:
        word = _fold_word(tok.text)
        if any(p and (word.startswith(p[:6]) or p.startswith(word[:6]) and len(word) >= 3) for p in parts):
            return tok.start_ms
    return None


def timeline(plan: Plan, tokens: list, voice_ms: int) -> tuple[list[dict], int]:
    """Tramos con cuadros de inicio/fin según la locución real; ítems sincronizados."""
    counts = [_words(b.text) for b in plan.beats]
    if sum(counts) != len(tokens):
        raise ValueError(f"el alineamiento tiene {len(tokens)} palabras y el guion {sum(counts)}")
    starts, i = [], 0
    for n in counts:
        starts.append(i)
        i += n
    frame = lambda ms: int(round(ms / 1000 * FPS))  # noqa: E731
    froms = [0] + [frame(tokens[s].start_ms) - 3 for s in starts[1:]]
    end_voice = frame(voice_ms)
    total = max(end_voice + 30, froms[-1] + 72)
    beats = []
    for k, b in enumerate(plan.beats):
        f0, f1 = froms[k], (froms[k + 1] if k + 1 < len(froms) else total)
        s0, s1 = starts[k], starts[k] + counts[k]
        items = []
        for j, text in enumerate(b.items):
            ms = _key_time(text, tokens, s0, s1)
            at = frame(ms) if ms is not None else f0 + int((j + 1) * (f1 - f0) / (len(b.items) + 1))
            items.append({"text": text, "at": max(f0, min(at, f1 - 4))})
        beats.append({"from": f0, "to": f1, "layout": b.layout, "caption": b.caption, "title": b.title, "items": items,
                      "value": b.value, "label": b.label, "detail": b.detail, "index": b.index})
    return beats, total


# ── Medios ───────────────────────────────────────────────────────────────
SCENE_PROMPT = (
    "Te paso cuadros numerados (0, 1, 2...) de un video de una nota periodística, uno cada pocos segundos. "
    "Clasificá CADA cuadro y respondé SOLO este JSON: {\"cuadros\": [{\"i\": int, \"tipo\": \"lugar\"|\"estudio\"|\"placa\"|\"otro\"}]}. "
    "lugar: muestra el lugar o el hecho de la nota (calle, incendio, obra, operativo, paisaje, vehículos, gente en el lugar). "
    "estudio: estudio de radio o televisión, conductores, entrevista o periodista hablando a cámara. "
    "placa: flyer, captura, gráfico o pantalla con texto. otro: cualquier otra cosa."
)


def classify_frames(paths: list[str]) -> list[str]:
    """Tipo de cada cuadro ("lugar", "estudio", "placa", "otro"); lista vacía si falla."""
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY", "")
    if not key or key == "PENDIENTE" or not paths:
        return []
    try:
        parts = []
        for i, path in enumerate(paths):
            with open(path, "rb") as fh:
                parts += [f"cuadro {i}", types.Part.from_bytes(data=fh.read(), mime_type="image/jpeg")]
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=os.getenv("NIGHTLY_NEWSCAST_VISION_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash",
            contents=[*parts, SCENE_PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
        )
        out = json.loads(response.text or "{}")
        kinds = ["otro"] * len(paths)
        for row in out.get("cuadros") or []:
            i = int(row.get("i", -1))
            if 0 <= i < len(paths):
                kinds[i] = str(row.get("tipo") or "otro")
        return kinds
    except Exception as exc:  # noqa: BLE001 — sin control visual no se aprueba el video
        logger.warning("Control visual del video falló: %s", type(exc).__name__)
        return []


def shot_cuts(video: str, *, threshold: float = 0.3) -> list[float]:
    """Instantes de corte de toma (detección de escena de ffmpeg)."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", video, "-filter:v", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    return [float(m.group(1)) for m in re.finditer(r"pts_time:([\d.]+)", out.stderr)]


def _duration(path: str) -> float:
    try:
        return nn.media_duration(path)
    except (subprocess.SubprocessError, ValueError, OSError):
        return 0.0


def _frame_at(video: str, t: float, dest: str) -> str:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=480:-2", dest],
                   capture_output=True, timeout=60)
    return dest if os.path.isfile(dest) else ""


def scene_clip(video: str, work: str, *, min_seconds: float = 6.0, loop_to: float = 32.0) -> tuple[str, str]:
    """Sólo las tomas que muestran el lugar del hecho (nunca estudio, móvil
    hablado ni placas), unidas y repetidas hasta ``loop_to`` s. El resultado
    se vuelve a revisar segundo a segundo: un solo cuadro de estudio y no sale.
    Devuelve (ruta, motivo si no hay)."""
    total = _duration(video)
    if total < 3:
        return "", "video demasiado corto"
    bounds = [0.0] + [c for c in shot_cuts(video) if 0.3 < c < total - 0.3] + [total]
    shots = [(a, b) for a, b in zip(bounds, bounds[1:]) if b - a >= 1.2][:40]
    frames = [_frame_at(video, (a + b) / 2, os.path.join(work, f"shot{k:02d}.jpg")) for k, (a, b) in enumerate(shots)]
    pairs = [(shot, f) for shot, f in zip(shots, frames) if f]
    kinds = classify_frames([f for _, f in pairs])
    if not kinds:
        return "", "sin control visual del video"
    keep = [(a + 0.15, b - 0.15) for ((a, b), _), kind in zip(pairs, kinds) if kind == "lugar"]
    seconds = sum(b - a for a, b in keep)
    summary = "".join(k[0] for k in kinds)
    if seconds < min_seconds:
        return "", f"menos de {min_seconds:.0f} s del lugar del hecho ({seconds:.1f} s; tomas {summary})"
    parts = []
    for k, (a, b) in enumerate(keep):
        part = os.path.join(work, f"toma{k:02d}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.2f}", "-i", video, "-t", f"{b - a:.2f}", "-an", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", part], capture_output=True, timeout=300)
        if os.path.isfile(part):
            parts.append(part)
    listing = os.path.join(work, "tomas.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        fh.writelines(f"file '{os.path.basename(p)}'\n" for p in parts)
    joined = os.path.join(work, "escena_raw.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", joined],
                   capture_output=True, timeout=300, cwd=work)
    if not os.path.isfile(joined):
        return "", "no se pudieron unir las tomas"
    # Revisión final: un cuadro por segundo del material elegido.
    length = _duration(joined)
    check = [_frame_at(joined, t + 0.5, os.path.join(work, f"chk{int(t):02d}.jpg")) for t in range(int(length))]
    verdict = classify_frames([f for f in check if f])
    if not verdict or any(k in {"estudio", "placa"} for k in verdict):
        return "", f"la revisión final encontró estudio o placas ({''.join(k[0] for k in verdict) or 'sin control'})"
    out = os.path.join(work, "escena.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", joined, "-t", f"{loop_to:.1f}", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                   capture_output=True, timeout=300)
    if not os.path.isfile(out):
        return "", "no se pudo preparar el video"
    logger.info("Video: %d tomas del lugar (%.1f s) de %d (%s)", len(parts), seconds, len(kinds), summary)
    return out, ""


def strong_photo(path: str, size: tuple[int, int], *, policial: bool, checker=None) -> tuple[bool, str]:
    """Foto fuerte: grande, que no sea una placa con texto y, en policiales, sin una cara en primer plano."""
    if min(size) < 360 or max(size) < 640:
        return False, f"foto chica {size[0]}x{size[1]}"
    verdict = (checker or nn.check_photo)(path)
    if not verdict:
        return False, "sin control visual de la foto"
    if verdict.get("flyer"):
        return False, "la foto es una placa con texto"
    if policial and verdict.get("face"):
        return False, "cara en primer plano en policiales"
    return True, ""


# ── Render ───────────────────────────────────────────────────────────────
@dataclass
class Rendered:
    video: str
    cover: str
    duration: float
    work: str


def render(plan: Plan, cand: nn.Candidate, media: dict, work: str) -> Rendered:
    """Voz, alineamiento, props y MP4 + portada. ``RuntimeError`` si algo falla."""
    from utils.newscast_align import align_clip, build_cues
    from utils.newscast_v5 import locate
    from utils.remotion_renderer import REMOTION_DIR
    from utils.video_renderer import _npx_args

    public = os.path.join(REMOTION_DIR, "public")
    rel = os.path.relpath(work, public).replace("\\", "/")
    wav = os.path.join(work, "voz.wav")
    seconds = nn.synthesize(plan.text, wav, direction=DIRECTION, tempo=os.getenv("FORMAT_REELS_TEMPO", "1.08"), voice=voice(),
                           model=os.getenv("FORMAT_REELS_TTS_MODEL", "gemini-3.8-flash-tts"))
    alignment = align_clip(wav, plan.text, int(seconds * 1000))
    if not alignment.ok:
        raise RuntimeError(f"la voz no alinea con el guion: {alignment.errors[:2]}")
    beats, total = timeline(plan, alignment.tokens, int(seconds * 1000))
    cues = build_cues(alignment.tokens, max_words=4, max_chars=26, min_ms=500)
    place = locate(plan.place) if plan.place else None
    props = {
        "kind": plan.kind, "badge": BADGE[plan.kind], "accent": ACCENT[plan.kind],
        "media": {"type": media["type"], "file": f"{rel}/{os.path.basename(media['file'])}", "width": media["width"], "height": media["height"]},
        "credit": media.get("credit", ""),
        "place": {"label": place.get("label") or plan.place, "x": float(place["x"]), "y": float(place["y"])} if place and "x" in place else None,
        "voiceFile": f"{rel}/voz.wav", "totalFrames": total,
        "cues": [{"text": c["text"], "startMs": c["startMs"], "endMs": c["endMs"],
                  "words": [{"text": w["text"], "startMs": w["startMs"], "endMs": w["endMs"]} for w in c["words"]]} for c in cues],
        "beats": beats, "cards": [b.value for b in plan.beats if b.layout == "card"], "music": True,
    }
    props_path = os.path.join(work, "props.json")
    with open(props_path, "w", encoding="utf-8") as fh:
        json.dump(props, fh, ensure_ascii=False)
    video = os.path.join(work, "reel.mp4")
    result = subprocess.run(
        _npx_args(["remotion", "render", COMPOSITION, video, "--codec=h264", "--crf=19", "--timeout=120000", f"--props={props_path}"]),
        cwd=REMOTION_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200,
    )
    if result.returncode != 0 or not os.path.isfile(video):
        raise RuntimeError(f"remotion: {(result.stderr or result.stdout)[-300:]}")
    hook_end = beats[1]["from"] / FPS if len(beats) > 1 else 1.5
    cover = os.path.join(work, "portada.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.5, hook_end - 0.2):.2f}", "-i", video, "-frames:v", "1", "-q:v", "2", cover],
                   capture_output=True, timeout=60)
    return Rendered(video=video, cover=cover if os.path.isfile(cover) else "", duration=total / FPS, work=work)


def new_workdir(kind: str) -> str:
    from utils.remotion_renderer import REMOTION_DIR

    work = os.path.join(REMOTION_DIR, "public", "tmp", f"freel_{kind}_{int(time.time() * 1000)}")
    os.makedirs(work, exist_ok=True)
    return work


def cleanup(work: str) -> None:
    shutil.rmtree(work, ignore_errors=True)


# ── Publicación ──────────────────────────────────────────────────────────
def hashtag_place(place: str) -> str:
    return "#" + re.sub(r"[^\wÁÉÍÓÚÑáéíóúñ]", "", place.title()) if place else ""


def caption_for(plan: Plan, cand: nn.Candidate) -> str:
    hook = plan.beats[0].title
    if plan.kind == "um":
        body = " ".join(b.text for b in plan.beats[1:-1])
        tags = " ".join(t for t in ("#LaRioja", hashtag_place(plan.place), "#ÚltimoMomento", "#LaVozRiojana") if t)
        return f"🔴 ÚLTIMO MOMENTO | {hook}\n\n{body}\n\n📲 La nota completa, en lavozriojana.com\n\n{tags}"[:2200]
    lines = [f"• {b.label}: {b.value}" + (f" ({b.detail})" if b.detail else "") for b in plan.beats if b.layout == "card"]
    tags = "#LaRioja #DatoÚtil #LaVozRiojana"
    return (f"📌 DATO ÚTIL | {cand.title}\n\n" + "\n".join(lines) + "\n\n🔁 Guardalo y compartilo con quien le sirva.\n"
            f"📲 La nota completa, en lavozriojana.com\n\n{tags}")[:2200]


def publish(kind: str, url: str, rendered: Rendered, caption: str, *, title: str, section: str, locality: str) -> dict:
    """Reel en Instagram y, si corresponde, video en Facebook. Ambiguo = no se reintenta."""
    from meta import fb_client, ig_client
    from utils import r2_storage

    outcome = {"ig": "skipped", "fb": "skipped"}
    try:
        video_url, _ = r2_storage.upload_temp(rendered.video, ttl_hint="reel")
        cover_url = r2_storage.upload_temp(rendered.cover, ttl_hint="reel")[0] if rendered.cover else ""
    except RuntimeError as exc:
        logger.warning("No se pudo subir el Reel a R2: %s", exc)
        return {"ig": "r2_error", "fb": "skipped"}
    item = {"video_url": video_url, "texto_instagram": caption, "titulo": title, "seccion": section, "share_to_feed": True,
            "caption_complete": True, "locality": locality}
    if cover_url:
        item["cover_url"] = cover_url
    else:
        item["thumb_offset_ms"] = 1500
    mark(kind, url, status="publishing", day=now_ar().date().isoformat(), at=int(time.time()))
    result = ig_client.post_reel_video_to_instagram(item)
    if result.ok and result.external_id:
        outcome["ig"] = "success"
        mark(kind, url, status="completed", ig_id=result.external_id)
    else:
        ambiguous = (result.details or {}).get("publication_outcome") == "unknown"
        outcome["ig"] = "ambiguous" if ambiguous else (result.error_type or "failed")
        mark(kind, url, status="ambiguous" if ambiguous else "failed", error=outcome["ig"])
    if _flag("FORMAT_REELS_FACEBOOK", "true") and outcome["ig"] == "success":
        fb = fb_client.post_reel_video_to_facebook(item)
        outcome["fb"] = "success" if fb.ok and fb.external_id else (fb.error_type or "failed")
        if fb.ok and fb.external_id:
            mark(kind, url, fb_id=fb.external_id)
    logger.info("Reel %s %s → instagram=%s facebook=%s", kind.upper(), title[:60], outcome["ig"], outcome["fb"])
    return outcome
