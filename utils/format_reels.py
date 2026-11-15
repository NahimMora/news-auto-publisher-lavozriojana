"""Reels de formato propio (Fase 2, criterios del responsable del 2026-11-14).

* **Último momento (UM)**: sólo una PRIMICIA (primera nota de ese hecho, de
  menos de ``FORMAT_REELS_UM_MAX_AGE_MINUTES``), urgente (``is_breaking``),
  riojana, con FOTO FUERTE y VIDEO REAL del lugar (nunca el estudio de una
  radio o un canal). Máximo ``FORMAT_REELS_UM_MAX_PER_DAY`` (2) por día.
* **Datos útiles (DU)**: sin tope diario, sólo notas riojanas con muchos datos
  concretos (al menos ``FORMAT_REELS_DU_MIN_CARDS`` tarjetas verificadas) y
  alto interés probable para el público riojano (puntaje de la IA ≥
  ``FORMAT_REELS_DU_MIN_INTEREST``).
* **Efemérides (EF, "Un día como hoy")**: a las 9 h, sólo los días que figuran
  en la lista fija ``config/efemerides_riojanas.json``, que revisa el
  responsable. El guion NO lo escribe la IA: sale de la lista (aprobada a mano)
  y se vuelve a controlar contra la nota fuente de lavozriojana.com; los años
  se calculan. Sólo salen las entradas con ``aprobada`` y
  ``foto_licencia_verificada`` en ``true``. Una por día. Si la lista no tiene
  nada para el día y ``FORMAT_REELS_EF_AUTO`` está encendido, la efeméride sale
  de la página de la fecha en Wikipedia (``utils/efemerides_auto.py``): la IA
  elige con el criterio editorial y redacta desde el artículo, y el guion pasa
  por el mismo control contra la fuente; la foto, sólo con licencia libre.

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
``FORMAT_REELS_DU_ENABLED``, ``FORMAT_REELS_EF_ENABLED``; ``FORMAT_REELS_FACEBOOK`` (default ``true``).
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
CLOSING = {"um": "Seguí a La Voz Riojana.", "du": "Compartilo y guardalo.", "ef": "Seguí a La Voz Riojana."}
BADGE = {"um": "ÚLTIMO MOMENTO", "du": "DATO ÚTIL", "ef": "UN DÍA COMO HOY"}
ACCENT = {"um": "#FF7A1A", "du": "#FFD15C", "ef": "#FFD15C"}
# Ritmo de la voz por formato (atempo de ffmpeg sobre la locución 3.x).
TEMPO_DEFAULT = {"um": "1.0", "du": "1.0", "ef": "1.12"}
DIRECTION = (
    "Sos el locutor de último momento de un medio de La Rioja, Argentina. Voz potente, enérgica y urgente, "
    "que atrape desde la primera palabra, como un flash informativo de radio. Ritmo rápido y decidido, sin atropellarte "
    "ni comerte sílabas, con pausas mínimas entre frases. Español argentino con tonada riojana bien reconocible pero "
    "natural: seseo, voseo, la 'll' y la 'y' como una 'ye' suave, nunca la 'sh' porteña. Golpeá la primera frase y "
    "remarcá cifras, lugares y lo que pasó. Nada de tono solemne, cansino ni de asistente virtual. Leé exactamente este "
    "texto, sin agregar, quitar ni cambiar palabras:\n\n"
)
EF_DIRECTION = (
    "Sos el locutor de efemérides de un medio de La Rioja, Argentina. Voz firme, clara y cálida, de narrador de historia "
    "que atrapa desde la primera palabra. Ritmo ágil, sin atropellarte ni comerte sílabas, con pausas mínimas entre frases. "
    "Si el hecho es una tragedia, tono respetuoso y sobrio, sin dramatizar. Español argentino con tonada riojana natural: "
    "seseo, voseo, la 'll' y la 'y' como una 'ye' suave, nunca la 'sh' porteña. Remarcá fechas, años, nombres y lugares. "
    "Leé exactamente este texto, sin agregar, quitar ni cambiar palabras:\n\n"
)
NO_INVENT = (
    "Usá SOLO datos que estén escritos en la nota: no inventes cifras, fechas, días, horarios, lugares, personas, "
    "armas, instituciones ni hechos, y no completes con conocimiento propio. Si la nota no lo dice, no va. "
    "No agregues 'hoy', 'ahora', 'mañana', 'ayer' ni 'anoche' si la nota no lo dice."
)

UM_PROMPT = (
    "Escribís el guion de un Reel vertical de ÚLTIMO MOMENTO de La Voz Riojana (15 a 22 segundos, voz en off). "
    + NO_INVENT
    + " Respondé SOLO este JSON: {\"gancho\": str, \"lugar\": str, \"tramos\": [{\"tipo\": \"mapa\"|\"sellos\"|\"cifra\"|\"balance\", "
    "\"locucion\": str, \"chips\": [str], \"sellos\": [str], \"valor\": str, \"etiqueta\": str, \"sello\": str, \"claves\": [str]}]}. "
    "gancho: titular hablado, corto y explosivo, de 3 a 7 palabras, puede ir entre signos de exclamación "
    "(ej.: \"¡Fuego en el camping de ATUR!\"). Se muestra entero y gigante. "
    "lugar: la localidad riojana del hecho tal como figura en la nota (vacío si no la dice). "
    "tramos: de 3 a 4, cada uno de un tipo distinto, en este orden si corresponden: mapa, sellos, cifra, balance. "
    "Cada locución tiene de 7 a 14 palabras y cuenta una parte del hecho. "
    "mapa: chips = exactamente 3 textos cortos: qué pasó (máx. 22 caracteres), cuándo (máx. 16, ej. \"Viernes\") y dónde "
    "(máx. 22, ej. \"Av. Santa Rosa\"); cada chip tiene una palabra que se dice en su locución. "
    "sellos: sellos = 2 o 3 palabras fuertes (máx. 20 caracteres) que se dicen en la locución (ej. \"Humo\", \"Vecinos alertados\"). "
    "cifra: sólo si la nota trae una cifra clave: valor = la cifra tal cual (ej. \"2\"), etiqueta = qué cuenta (máx. 26, ej. "
    "\"dotaciones de bomberos\"), sello = resultado corto (máx. 18, ej. \"Fuego controlado\") que se dice en la locución. "
    "balance: el cierre del hecho en 5 a 8 palabras (heridos, daños, cómo sigue), ej. \"No hubo heridos ni daños.\" "
    "claves: 2 o 3 palabras de la locución que se resaltan en el subtítulo. "
    "Escribí con mayúsculas y minúsculas normales (nada todo en mayúsculas). "
    "Total de palabras habladas (gancho + locuciones) entre 36 y 56: contalas antes de responder. "
    "Copiá cifras, horarios y fechas EXACTAMENTE como están en la nota. Español rioplatense, voseo. "
    "No digas 'último momento' ni el nombre del medio: eso ya está en pantalla."
)

DU_PROMPT = (
    "Evaluás si una nota de La Voz Riojana sirve para un Reel de DATOS ÚTILES (tarjetas con datos concretos que la gente "
    "guarda y comparte: fechas, plazos, montos, requisitos, modalidades, horarios, cantidades, cronogramas). "
    + NO_INVENT
    + " Respondé SOLO este JSON: {\"apta\": bool, \"interes\": int, \"motivo\": str, \"pregunta\": str, \"llamado\": str, "
    "\"tarjetas\": [{\"tipo\": \"fecha\"|\"lista\"|\"monto\"|\"cifra\"|\"texto\", \"rotulo\": str, \"resumen\": str, \"capsula\": str, "
    "\"valor\": str, \"unidad\": str, \"opciones\": [{\"icono\": str, \"texto\": str}], \"detalle\": str, \"locucion\": str, \"claves\": [str]}]}. "
    "apta: true sólo si la nota trae al menos 4 datos concretos, cortos y prácticos distintos. "
    "interes: 0 a 10, qué tan probable es que le sirva a mucha gente de La Rioja (10 = trámite, pago, inscripción o "
    "servicio masivo en la provincia; 0 = no le sirve a nadie de La Rioja). "
    "pregunta: de 3 a 7 palabras, a quién le sirve (ej. \"¿Vas a estudiar en la UNLaR?\"). llamado: 2 o 3 palabras (ej. \"Anotá esto.\"). "
    "tarjetas: 4 (5 sólo si hay un quinto dato fuerte), cada una de un tipo que muestre el dato de la forma más visual: "
    "fecha = una fecha o plazo (capsula opcional que la introduce, máx. 16, ej. \"Cierran el\"; valor = la fecha, ej. \"27 de diciembre\"); "
    "lista = 2 o 3 opciones cortas (máx. 16 cada una) con un emoji de ícono (ej. 🏫 Presencial, 💻 Virtual); "
    "monto = un precio o pago (valor con el signo, ej. \"$20.000\"); "
    "cifra = una cantidad (valor = número, unidad = qué cuenta, máx. 12, ej. \"106\" + \"carreras\"; capsula opcional, máx. 26); "
    "texto = un dato corto que no es nada de lo anterior (valor máx. 18). "
    "rotulo: qué es el dato, máx. 28 (ej. \"Cuánto cuesta\"). resumen: el dato en máx. 20 caracteres para la pila de tarjetas "
    "(ej. \"27 de diciembre\", \"Presencial o virtual\", \"$20.000\", \"106 carreras\"). detalle: aclaración opcional, máx. 40. "
    "locucion: cómo se dice el dato, de 6 a 12 palabras, nombrando el valor o las opciones. claves: 2 o 3 palabras de la locución. "
    "Escribí con mayúsculas y minúsculas normales (nada todo en mayúsculas). "
    "Copiá cifras, horarios y fechas EXACTAMENTE como están en la nota. "
    "Total de palabras habladas (pregunta + llamado + locuciones) entre 36 y 60: contalas antes de responder. "
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
    layout: str          # hook | mapchips | stamps | number | check | card | who | efmap | years | calendar | outro
    cap: str             # title | callout | marker | pill | chunk | pop | none
    cap_y: int
    text: str            # locución del tramo (lo que se dice)
    card: str = ""       # fecha | lista | monto | cifra | texto (DU)
    items: list[tuple[str, str]] = field(default_factory=list)  # (texto, ícono)
    keys: list[str] = field(default_factory=list)
    value: str = ""
    unit: str = ""
    label: str = ""
    pill: str = ""
    detail: str = ""
    head: str = ""
    index: int = 0
    cta_from: int = -1


@dataclass
class Plan:
    kind: str
    beats: list[Beat]
    place: str = ""
    interest: int = 0
    ef: dict | None = None  # EF: {"day", "month", "year", "now"}
    scope: str = "riojana"  # EF: riojana | nacional | internacional (cambia las etiquetas del posteo)
    credit: str = ""        # EF: crédito de la foto (licencia libre), va en el posteo

    @property
    def text(self) -> str:
        return " ".join(b.text for b in self.beats)


def _clean(text: object, limit: int = 400) -> str:
    return " ".join(str(text or "").split())[:limit]


def _sentence(text: str) -> str:
    """Primera letra en mayúscula y punto final."""
    text = text.strip()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text if re.search(r"[.!?]$", text) else text + "."


def _words(text: str) -> int:
    return len(text.split())


# Palabras de llamado y de rótulo (no son hechos): verbos en voseo, plazos y
# fórmulas como "Cierran el", "Elegí la que prefieras", "Tenés tiempo hasta".
_SCREEN_GENERIC = {"tenes", "podes", "elegi", "elegir", "elegis", "prefieras", "preferis", "opcion", "opciones", "plazo", "maximo",
                   "minimo", "cierran", "cierra", "cierre", "abren", "vence", "vencen", "tiempo", "anotate", "inscribite", "consulta",
                   "consultar", "recorda", "acordate", "importante", "atencion", "modalidad", "modalidades", "disponible", "disponibles",
                   "podras", "podran", "tenes", "tendras", "queres", "necesitas", "sirve", "servicio", "valido", "valida", "vigente"}
_SCREEN_STOP = _SCREEN_GENERIC | {"sobre", "desde", "hasta", "entre", "para", "porque", "donde", "cuando", "todos", "todas", "nuevo", "nueva",
                "nuevos", "nuevas", "fecha", "horario", "horarios", "lugar", "inicio", "final", "comienzo", "ultimo", "ultima",
                "datos", "costo", "precio", "como", "anotarte", "inscripcion", "inscripciones", "cabecera", "recorrido"}


def _screen_check(texts: list[str], cand: nn.Candidate, label: str) -> list[str]:
    """Lo que se lee en pantalla (chips, sellos, etiquetas, valores, detalles)
    no puede traer palabras con contenido que no estén en la nota: atrapa
    causas o hechos inventados ("desvío por obras" si la nota dice temporal)."""
    original = nn._fold(f"{cand.title} {cand.body} {' '.join(cand.localities)}")
    words_original = set(re.findall(r"[a-z0-9ñ]+", original))
    stems = {w[:5] for w in words_original if len(w) >= 5}
    out = []
    for text in texts:
        for word in re.findall(r"[a-z0-9ñ]+", nn._fold(text)):
            if len(word) < 5 or word.isdigit() or word in _SCREEN_STOP:
                continue
            if word not in words_original and word[:5] not in stems:
                out.append(f"{label}: '{word}' no está en la nota")
    return out


def _fact_check(texts: list[str], cand: nn.Candidate, label: str) -> list[str]:
    """Control factual del noticiero, sin el falso positivo de la mayúscula de
    comienzo de oración o de pregunta ("¿Cobrás Chachos?" → sólo "Chachos")."""
    from pipeline.node_webapp.editorial import _is_present

    text = ". ".join(t for t in texts if t)
    original = "\n".join([cand.title, cand.body, " ".join(cand.localities)])
    out = []
    folded_text, folded_original = f" {nn._fold(text)} ", f" {nn._fold(original)} "
    for word in ("hoy", "manana", "ayer", "anoche"):
        if re.search(rf"\b{word}\b", folded_text) and not re.search(rf"\b{word}\b", folded_original):
            out.append(f"{label}: dice '{word}' y la nota no lo dice")
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


def _items(raw: object, limit: int, n: int) -> list[str]:
    return [_clean(x, limit) for x in (raw or []) if _clean(x)][:n]


def _plain(x: str) -> str:
    return x.lower() if x.isupper() else x


UM_LAYOUT = {"mapa": ("mapchips", "callout", 1250), "sellos": ("stamps", "marker", 300), "cifra": ("number", "pill", 1300), "balance": ("check", "pop", 820)}


def validate_um(raw: dict, cand: nn.Candidate) -> tuple[Plan | None, list[str]]:
    warnings: list[str] = []
    hook = _clean(raw.get("gancho"), 90)
    if not 2 <= _words(hook) <= 8:
        warnings.append("gancho: tiene que tener de 3 a 7 palabras")
    if not re.search(r"[.!?]$", hook):
        hook += "."
    beats = [Beat("hook", "title", 0, hook)]
    used: set[str] = set()
    for i, t in enumerate((raw.get("tramos") or [])[:4]):
        if not isinstance(t, dict):
            continue
        kind = str(t.get("tipo") or "")
        speech = _sentence(_clean(t.get("locucion"), 200)) if _clean(t.get("locucion")) else ""
        tag = f"tramo {i + 1}"
        if kind not in UM_LAYOUT or not speech:
            warnings.append(f"{tag}: incompleto")
            continue
        if kind in used:
            warnings.append(f"{tag}: el tipo {kind} ya se usó; cada tramo de un tipo distinto")
            continue
        used.add(kind)
        layout, cap, cap_y = UM_LAYOUT[kind]
        beat = Beat(layout, cap, cap_y, speech, keys=_items(t.get("claves"), 30, 3))
        screen: list[str] = []
        if kind == "mapa":
            chips = _items(t.get("chips"), 24, 3)
            if len(chips) < 3:
                warnings.append(f"{tag}: el mapa necesita 3 chips (qué, cuándo, dónde)")
            beat.items = [(c, "pin" if k == 2 else "") for k, c in enumerate(chips)]
            screen = chips
        elif kind == "sellos":
            stamps = _items(t.get("sellos"), 22, 3)
            if len(stamps) < 2:
                warnings.append(f"{tag}: hacen falta 2 o 3 sellos")
            beat.items = [(x, "") for x in stamps]
            screen = stamps
        elif kind == "cifra":
            beat.value, beat.label, beat.detail = _clean(t.get("valor"), 10), _clean(t.get("etiqueta"), 28), _clean(t.get("sello"), 20)
            if not beat.value or not beat.label:
                warnings.append(f"{tag}: la cifra necesita valor y etiqueta")
            beat.items = [(beat.label, "")]
            screen = [beat.label, beat.detail]
        plain = [_plain(x) for x in screen]
        warnings += _fact_check([speech, *plain, beat.value], cand, tag)
        warnings += _screen_check(plain, cand, tag)
        beats.append(beat)
    if len(beats) < 4:
        warnings.append("hacen falta 3 o 4 tramos válidos")
    warnings += _fact_check([hook], cand, "gancho")
    spoken = sum(_words(b.text) for b in beats)
    if not 32 <= spoken <= 60:
        warnings.append(f"el guion tiene {spoken} palabras; tienen que ser entre 36 y 56")
    beats.append(Beat("outro", "none", 0, CLOSING["um"]))
    place = _clean(raw.get("lugar"), 40)
    if place and nn._fold(place) not in nn._fold(f"{cand.title} {cand.body} {' '.join(cand.localities)}"):
        place = ""
    # Sin lugar en el guion: la localidad que ya detectó el archivo editorial (nunca se adivina).
    place = place or (cand.localities[0] if cand.localities else "")
    return (Plan("um", beats, place=place) if len(beats) >= 5 else None), warnings


DU_CAPS = (("pill", 1330), ("marker", 1340), ("chunk", 1380), ("callout", 1440), ("pill", 1440))
DU_KINDS = {"fecha", "lista", "monto", "cifra", "texto"}


def validate_du(raw: dict, cand: nn.Candidate) -> tuple[Plan | None, list[str], bool]:
    """(plan, observaciones, apta). ``apta=False`` = la nota no califica (no se reintenta)."""
    interest = int(raw.get("interes") or 0) if str(raw.get("interes") or "0").lstrip("-").isdigit() else 0
    if not raw.get("apta") or interest < _int("FORMAT_REELS_DU_MIN_INTEREST", 7):
        return None, [f"no califica: apta={bool(raw.get('apta'))} interés={interest} ({_clean(raw.get('motivo'), 120)})"], False
    warnings: list[str] = []
    question, call = _clean(raw.get("pregunta"), 80), _clean(raw.get("llamado"), 30)
    if not 2 <= _words(question) <= 8 or not call or _words(call) > 4:
        warnings.append("gancho: pregunta de 3 a 7 palabras y llamado de 2 o 3")
    question = question if re.search(r"[.!?]$", question) else question + "?"
    call = _sentence(call) if call else ""
    hook = Beat("hook", "title", 0, f"{question} {call}".strip(), cta_from=_words(question) if call else -1)
    beats = [hook]
    cards: list[Beat] = []
    for i, t in enumerate((raw.get("tarjetas") or [])[:5]):
        if not isinstance(t, dict):
            continue
        tag = f"tarjeta {i + 1}"
        kind = str(t.get("tipo") or "")
        speech = _sentence(_clean(t.get("locucion"), 160)) if _clean(t.get("locucion")) else ""
        label, head = _clean(t.get("rotulo"), 30), _clean(t.get("resumen"), 22)
        if kind not in DU_KINDS or not speech or not label or not head:
            warnings.append(f"{tag}: incompleta")
            continue
        cap, cap_y = DU_CAPS[len(cards) % len(DU_CAPS)]
        beat = Beat("card", cap, cap_y, speech, card=kind, label=label, head=head, index=len(cards) + 1, keys=_items(t.get("claves"), 30, 3),
                    pill=_clean(t.get("capsula"), 28), detail=_clean(t.get("detalle"), 44))
        if kind == "lista":
            opts = [(_clean(o.get("texto"), 18), _clean(o.get("icono"), 4)) for o in (t.get("opciones") or []) if isinstance(o, dict) and _clean(o.get("texto"))][:3]
            if len(opts) < 2:
                warnings.append(f"{tag}: la lista necesita 2 o 3 opciones")
            beat.items = opts
            screen = [o[0] for o in opts]
        else:
            beat.value, beat.unit = _clean(t.get("valor"), 20), _clean(t.get("unidad"), 14) if kind == "cifra" else ""
            if not beat.value:
                warnings.append(f"{tag}: falta el valor")
            beat.items = [(beat.value, "")]
            screen = [beat.value, beat.unit]
        screen += [head, beat.pill, beat.detail]
        plain = [_plain(x) for x in screen if x]
        warnings += _fact_check([speech, *plain], cand, tag)
        warnings += _screen_check(plain, cand, tag)
        cards.append(beat)
    beats += cards
    if len(cards) < _int("FORMAT_REELS_DU_MIN_CARDS", 4):
        warnings.append(f"hay {len(cards)} tarjetas válidas; hacen falta al menos {_int('FORMAT_REELS_DU_MIN_CARDS', 4)}")
    warnings += _fact_check([question], cand, "gancho")
    spoken = sum(_words(b.text) for b in beats)
    if not 32 <= spoken <= 64:
        warnings.append(f"el guion tiene {spoken} palabras; tienen que ser entre 36 y 60")
    beats.append(Beat("outro", "none", 0, CLOSING["du"]))
    return (Plan("du", beats, interest=interest) if cards else None), warnings, True


# ── Efemérides (lista fija revisada por el responsable) ──────────────────
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
EF_LAYOUT = {"quien": ("who", "marker", 1350), "donde": ("efmap", "callout", 1390), "anios": ("years", "pill", 1260),
             "fecha_hoy": ("calendar", "chunk", 1300)}


def ef_list_path() -> str:
    return os.getenv("FORMAT_REELS_EF_LIST") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config",
                                                               "efemerides_riojanas.json")


def load_efemerides(path: str | None = None) -> list[dict]:
    """Entradas de la lista fija. Un archivo ilegible es un error (no una lista vacía)."""
    path = path or ef_list_path()
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    rows = data.get("efemerides") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("la lista de efemérides no tiene la clave 'efemerides'")
    return [r for r in rows if isinstance(r, dict)]


def ef_month_day(entry: dict) -> tuple[int, int] | None:
    m = re.fullmatch(r"(\d{2})-(\d{2})", str(entry.get("fecha") or ""))
    if not m or not (1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31):
        return None
    return int(m.group(1)), int(m.group(2))


def efemerides_for(day, rows: list[dict]) -> list[dict]:
    """Entradas de la fecha ``day`` (un ``date``)."""
    return [r for r in rows if ef_month_day(r) == (day.month, day.day)]


def ef_blockers(entry: dict) -> list[str]:
    """Lo que falta para que una entrada pueda salir (revisión humana y foto)."""
    out = []
    if entry.get("aprobada") is not True:
        out.append("la entrada no está aprobada")
    if entry.get("foto_licencia_verificada") is not True:
        out.append("la licencia de la foto no está verificada")
    if not str(entry.get("foto_url") or "").startswith("https://"):
        out.append("sin foto")
    if not str(entry.get("fuente_url") or "").startswith("https://lavozriojana.com/"):
        out.append("la fuente tiene que ser una nota de lavozriojana.com")
    if not ef_month_day(entry) or not isinstance(entry.get("anio"), int):
        out.append("fecha o año inválidos")
    return out


def validate_ef(entry: dict, cand: nn.Candidate, today) -> tuple[Plan | None, list[str]]:
    """Plan de la efeméride. Todo lo que se dice y se lee se controla contra la
    nota fuente; los años se calculan (no se copian de la nota)."""
    warnings: list[str] = []
    md = ef_month_day(entry)
    year = entry.get("anio")
    if not md or not isinstance(year, int) or not 0 < year < today.year:
        return None, ["fecha o año inválidos"]
    years = today.year - year
    hook = _sentence(_clean(entry.get("gancho"), 160))
    if not 4 <= _words(hook) <= 16:
        warnings.append("gancho: tiene que tener de 4 a 16 palabras")
    if str(year) not in hook:
        warnings.append("gancho: tiene que nombrar el año del hecho")
    beats = [Beat("hook", "title", 0, hook)]
    warnings += _fact_check([hook], cand, "gancho")
    place = _clean(entry.get("lugar"), 40)
    for kind in ("quien", "donde", "anios", "fecha_hoy"):
        t = entry.get(kind)
        if not isinstance(t, dict):
            if kind == "anios":
                warnings.append("anios: falta el tramo de los años")
            continue
        layout, cap, cap_y = EF_LAYOUT[kind]
        raw = _clean(t.get("locucion"), 200)
        if kind == "anios":
            if "{anios}" not in raw:
                warnings.append("anios: la locución tiene que llevar {anios}")
                continue
            speech = _sentence(raw.replace("{anios}", str(years)))
            beat = Beat(layout, cap, cap_y, speech, keys=_items(t.get("claves"), 30, 3), value=str(years), label="años",
                        items=[(str(years), "")])
            beats.append(beat)  # cifra calculada: no se controla contra la nota (la nota es de otro año)
            continue
        speech = _sentence(raw) if raw else ""
        if not speech:
            warnings.append(f"{kind}: falta la locución")
            continue
        beat = Beat(layout, cap, cap_y, speech, keys=_items(t.get("claves"), 30, 3))
        # Texto de pantalla más largo que su lugar: se pide de nuevo (cortarlo deja "DIÉSEL-ELÉCTRIC").
        limits = {"quien": [("apodo", 24), ("nombre", 40), ("chips", 26)], "donde": [("chips", 28)],
                  "fecha_hoy": [("sello", 24), ("detalle", 30)]}[kind]
        for field_name, limit in limits:
            values = t.get(field_name) if field_name == "chips" else [t.get(field_name)]
            for value in values if isinstance(values, list) else []:
                if len(_clean(value, 999)) > limit:
                    warnings.append(f"{kind}: '{_clean(value, 60)}' tiene más de {limit} caracteres")
        screen: list[str] = []
        if kind == "quien":
            beat.value, beat.label = _clean(t.get("apodo"), 24), _clean(t.get("nombre"), 40)
            beat.items = [(c, "") for c in _items(t.get("chips"), 26, 3)]
            screen = [beat.value, beat.label, *[c for c, _ in beat.items]]
        elif kind == "donde":
            beat.items = [(c, "") for c in _items(t.get("chips"), 28, 3)]
            if not beat.items:
                warnings.append("donde: hace falta al menos un chip")
            screen = [c for c, _ in beat.items]
        else:  # fecha_hoy
            beat.value = f"{md[1]} de {MONTHS_ES[md[0] - 1]}"
            beat.detail = _clean(t.get("detalle"), 30)
            sello = _clean(t.get("sello"), 24)
            if not sello:
                warnings.append("fecha_hoy: falta el sello")
            beat.items = [(sello, "")] if sello else []
            screen = [sello, beat.detail]
        plain = [_plain(x) for x in screen if x]
        warnings += _fact_check([speech, *plain], cand, kind)
        warnings += _screen_check(plain, cand, kind)
        beats.append(beat)
    if len(beats) < 3:
        warnings.append("hacen falta al menos dos tramos además del gancho")
    spoken = sum(_words(b.text) for b in beats)
    if not 24 <= spoken <= 60:
        warnings.append(f"el guion tiene {spoken} palabras; tienen que ser entre 24 y 60")
    beats.append(Beat("outro", "none", 0, CLOSING["ef"]))
    if place and nn._fold(place) not in nn._fold(f"{cand.title} {cand.body}"):
        warnings.append(f"lugar: '{place}' no está en la nota")
        place = ""
    ef = {"day": str(md[1]), "month": MONTHS_ES[md[0] - 1][:3].upper(), "year": str(year), "now": str(today.year)}
    return Plan("ef", beats, place=place, ef=ef), warnings


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
                timeout=float(os.getenv("GEMINI_TIMEOUT", "90")), json_mode=True, stage="format_reels_script",
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
    """Tramos con cuadros de inicio/fin según la locución real, palabras con
    su tiempo, ítems sincronizados con la palabra que los nombra."""
    counts = [_words(b.text) for b in plan.beats]
    if sum(counts) != len(tokens):
        raise ValueError(f"el alineamiento tiene {len(tokens)} palabras y el guion {sum(counts)}")
    starts, i = [], 0
    for n in counts:
        starts.append(i)
        i += n
    frame = lambda ms: int(round(ms / 1000 * FPS))  # noqa: E731
    froms = [0] + [max(0, frame(tokens[s].start_ms) - 3) for s in starts[1:]]
    end_voice = frame(voice_ms)
    total = max(end_voice + 30, froms[-1] + 72)
    beats = []
    for k, b in enumerate(plan.beats):
        f0, f1 = froms[k], (froms[k + 1] if k + 1 < len(froms) else total)
        s0, s1 = starts[k], starts[k] + counts[k]
        words = [{"t": tok.text, "s": int(tok.start_ms), "e": int(tok.end_ms)} for tok in tokens[s0:s1]]

        def when(text: str, j: int, n: int) -> int:
            ms = _key_time(text, tokens, s0, s1)
            at = frame(ms) if ms is not None else f0 + int((j + 1) * (f1 - f0) / (n + 1))
            return max(f0, min(at, f1 - 6))

        items = [{"text": text, "at": when(text, j, len(b.items)), "icon": icon} for j, (text, icon) in enumerate(b.items)]
        detail_at = when(b.detail or b.pill, 1, 2) if (b.detail or b.pill) else f0
        if b.layout == "number" and b.detail:
            detail_at = max(detail_at, items[0]["at"] + 8 if items else f0)
        keys = list(b.keys)
        for text, _icon in b.items:
            keys += [w for w in text.split() if len(_fold_word(w)) >= 4][:1]
        beats.append({"from": f0, "to": f1, "layout": b.layout, "card": b.card, "cap": b.cap, "capY": b.cap_y, "words": words,
                      "keys": keys, "ctaFrom": b.cta_from, "items": items, "value": b.value, "unit": b.unit, "label": b.label,
                      "pill": b.pill, "detail": b.detail, "detailAt": detail_at, "index": b.index})
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
        vision_model = os.getenv("NIGHTLY_NEWSCAST_VISION_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
        started_at = time.perf_counter()
        response = client.models.generate_content(
            model=vision_model,
            contents=[*parts, SCENE_PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
        )
        from utils.ai_client import record_usage

        record_usage(stage="vision:format_reels", model=vision_model, response=response, started_at=started_at, success=True)
        out = json.loads(response.text or "{}")
        kinds = ["?"] * len(paths)  # sin respuesta para un cuadro = no verificado
        for row in out.get("cuadros") or []:
            i = int(row.get("i", -1))
            if 0 <= i < len(paths):
                kinds[i] = str(row.get("tipo") or "otro")
        return kinds
    except Exception as exc:  # noqa: BLE001 — sin control visual no se aprueba el video
        logger.warning("Control visual del video falló: %s", type(exc).__name__)
        return []


def shot_cuts(video: str, *, threshold: float = 0.15) -> list[float]:
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
    step = max(1.0, length / 40)  # hasta 40 cuadros, al menos uno por segundo en tramos cortos
    times = [k * step + 0.5 for k in range(int(length / step))]
    check = [_frame_at(joined, t, os.path.join(work, f"chk{k:02d}.jpg")) for k, t in enumerate(times)]
    verdict = classify_frames([f for f in check if f])
    if not verdict or any(k != "lugar" for k in verdict):
        return "", f"la revisión final encontró estudio, placas o cuadros sin verificar ({''.join(k[0] for k in verdict) or 'sin control'})"
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
def opening_gap(tokens: list, *, max_start_ms: int = 900, max_gap_ms: int = 1200) -> None:
    """La voz 3.x a veces lee en voz alta la etiqueta de estilo antes del texto.
    Si después del recorte queda un arranque tardío o un hueco entre las
    primeras palabras, la locución no sirve: ``RuntimeError`` (no se publica)."""
    if not tokens:
        return
    if tokens[0].start_ms > max_start_ms:
        raise RuntimeError(f"la locución arranca a los {tokens[0].start_ms} ms: texto de más al comienzo")
    for a, b in zip(tokens[:4], tokens[1:5]):
        if b.start_ms - a.end_ms > max_gap_ms:
            raise RuntimeError(f"hueco de {b.start_ms - a.end_ms} ms al comienzo de la locución: la voz leyó texto de más")


@dataclass
class Rendered:
    video: str
    cover: str
    duration: float
    work: str


def render(plan: Plan, cand: nn.Candidate, media: dict, work: str) -> Rendered:
    """Voz, alineamiento, props y MP4 + portada. ``RuntimeError`` si algo falla."""
    from utils.newscast_align import align_clip
    from utils.newscast_v5 import locate
    from utils.remotion_renderer import REMOTION_DIR
    from utils.video_renderer import _npx_args

    public = os.path.join(REMOTION_DIR, "public")
    rel = os.path.relpath(work, public).replace("\\", "/")
    wav = os.path.join(work, "voz.wav")
    tempo = os.getenv(f"FORMAT_REELS_{plan.kind.upper()}_TEMPO") or os.getenv("FORMAT_REELS_TEMPO") or TEMPO_DEFAULT.get(plan.kind, "1.0")
    seconds = nn.synthesize(plan.text, wav, direction=EF_DIRECTION if plan.kind == "ef" else DIRECTION, tempo=tempo, voice=voice(),
                           model=os.getenv("FORMAT_REELS_TTS_MODEL", "gemini-3.8-flash-tts"))
    alignment = align_clip(wav, plan.text, int(seconds * 1000))
    if not alignment.ok:
        raise RuntimeError(f"la voz no alinea con el guion: {alignment.errors[:2]}")
    opening_gap(alignment.tokens)
    beats, total = timeline(plan, alignment.tokens, int(seconds * 1000))
    place = locate(plan.place) if plan.place else None
    props = {
        "kind": plan.kind, "badge": BADGE[plan.kind], "accent": ACCENT[plan.kind],
        "media": {"type": media["type"], "file": f"{rel}/{os.path.basename(media['file'])}", "width": media["width"], "height": media["height"]},
        "credit": media.get("credit", ""),
        "place": {"label": place.get("label") or plan.place, "x": float(place["x"]), "y": float(place["y"])} if place and "x" in place else None,
        "voiceFile": f"{rel}/voz.wav", "totalFrames": total,
        "heads": [b.head for b in plan.beats if b.layout == "card"], "music": True, "beats": beats, "ef": plan.ef,
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
    hook = plan.beats[0].text.rstrip(".")
    if plan.kind == "ef":
        body = " ".join(b.text for b in plan.beats[1:-1])
        if plan.scope == "riojana":
            tags = " ".join(t for t in ("#LaRioja", hashtag_place(plan.place), "#UnDíaComoHoy", "#HistoriaRiojana", "#LaVozRiojana") if t)
        elif plan.scope == "nacional":
            tags = "#UnDíaComoHoy #Efemérides #Argentina #LaRioja #LaVozRiojana"
        else:
            tags = "#UnDíaComoHoy #Efemérides #LaRioja #LaVozRiojana"
        credit = f"\n\n📷 Foto: {plan.credit}" if plan.credit else ""
        return f"📅 UN DÍA COMO HOY | {plan.beats[0].text}\n\n{body}{credit}\n\n{tags}"[:2200]
    if plan.kind == "um":
        body = " ".join(b.text for b in plan.beats[1:-1])
        tags = " ".join(t for t in ("#LaRioja", hashtag_place(plan.place), "#ÚltimoMomento", "#LaVozRiojana") if t)
        return f"🔴 ÚLTIMO MOMENTO | {hook}\n\n{body}\n\n📲 La nota completa, en lavozriojana.com\n\n{tags}"[:2200]
    lines = []
    for b in plan.beats:
        if b.layout != "card":
            continue
        shown = " / ".join(t for t, _ in b.items) if b.card == "lista" else " ".join(x for x in (b.pill, b.value, b.unit) if x)
        lines.append(f"• {b.label}: {shown}" + (f" ({b.detail})" if b.detail else ""))
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
