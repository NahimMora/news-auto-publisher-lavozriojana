"""Mismo hecho entre fuentes: duplicado o actualización.

Nueva Rioja y Tiempo Popular cuentan el mismo hecho con otras palabras
("Murió el joven que volcó en la Ruta 75" / "Falleció el joven de 25 años que
había volcado"), y el dedup por título no los reconoce. Antes de pagar la
reescritura, ``assess_same_event`` hace una sola llamada a Gemini contra las
notas encoladas en las últimas horas que comparten alguna palabra:

* ``new``: otro hecho; sigue como siempre.
* ``duplicate``: el mismo hecho sin nada nuevo; no se publica.
* ``update``: el mismo hecho con un dato nuevo importante (murió, detuvieron,
  apareció). Sale como ACTUALIZACIÓN y enlaza la publicación anterior.

Si Gemini no responde, la nota sigue como ``new`` (el comportamiento de
antes): nunca se descarta una nota por una falla de la evaluación.
Con ``SAME_EVENT_CHECK_ENABLED`` apagado no se evalúa nada.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field

from utils.file_manager import JsonStateError, load_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir

logger = setup_logger("same_event", "rewrite_news.log")

_TRUE = {"1", "true", "yes", "on"}
# Fuentes que no cubren hechos locales: no se comparan.
_NON_LOCAL_SOURCE_MARKERS = ("paparazzi", "infobae", "internacional")
_STOP = {
    "sobre", "contra", "desde", "hasta", "entre", "durante", "tras", "luego", "donde", "cuando", "porque", "fueron",
    "habia", "tiene", "tienen", "rioja", "riojana", "riojano", "riojanos", "provincia", "capital", "ciudad",
    "nuevo", "nueva", "nuevos", "nuevas", "este", "esta", "estos", "estas", "otro", "otra", "todos", "todas",
}

_PROMPT = """Sos editor de "La Voz Riojana", un medio digital de La Rioja, Argentina.

Recibís una NOTA NUEVA y una lista de notas que ya se publicaron o están por publicarse.

1) Decidí si la nota nueva cuenta EL MISMO HECHO que alguna de la lista: el mismo acontecimiento \
concreto sobre las mismas personas (el mismo accidente, el mismo crimen, el mismo operativo, la misma \
decisión). NO es el mismo hecho: un hecho distinto del mismo tipo (otro choque, otro robo, otra obra), \
ni otra historia dentro de un evento grande (las declaraciones de otra persona, otro protagonista o \
otro momento de una peregrinación, un partido, una elección o un temporal). Si no estás seguro, \
respondé null.

2) Si es el mismo hecho, decidí si la nota nueva trae un DATO NUEVO IMPORTANTE que la anterior no \
tenía: por ejemplo, la persona estaba grave o con muerte cerebral y ahora murió; fue detenida, \
apareció o fue identificada; cambió la cifra de víctimas; se conoció la causa; hubo una resolución \
judicial. Que la cuente otro medio, con otras palabras o con detalles menores NO es un dato nuevo.

3) Si es el mismo hecho, copiá en "ancla" el dato concreto que comparten las dos notas y que lo \
identifica: un lugar, una ruta con su número, un nombre propio o una institución, escrito igual que \
en el texto. Una palabra común ("vuelco", "joven", "choque") no sirve: si no hay un dato así, \
respondé null en "mismo_hecho".

4) Si hay dato nuevo, escribí la novedad en una frase de hasta 12 palabras, sólo con lo que dice el texto.

Evaluá sólo con el texto provisto; no inventes datos, armas, personas ni hechos ajenos al original.

Respondé ÚNICAMENTE con JSON: {{"mismo_hecho": <número de la lista o null>, "ancla": "<dato compartido o vacío>", "dato_nuevo": <true o false>, "novedad": "<frase o vacío>"}}

Notas publicadas o por publicarse:
{recientes}

NOTA NUEVA:
Título: {titulo}
Texto: {texto}
"""


@dataclass
class EventCheck:
    relation: str = "new"  # new | duplicate | update
    match: dict = field(default_factory=dict)
    novelty: str = ""
    error_type: str = ""
    # Gemini dijo "mismo hecho" pero el ancla no se pudo comprobar: la nota
    # sale igual (Web y redes), pero en una red donde la anterior ya salió no
    # se repite (ver ``drop_already_posted``).
    related: bool = False

    def related_payload(self) -> dict:
        """Lo que se guarda en la nota como ``event_related``."""
        return {
            "of_title": self.match.get("title", ""),
            "of_meta_key": self.match.get("meta_queue_key", ""),
            "of_canonical_url": self.match.get("canonical_url", ""),
        }

    def update_payload(self) -> dict:
        """Lo que se guarda en la nota como ``event_update``."""
        return {
            "of_title": self.match.get("title", ""),
            "of_meta_key": self.match.get("meta_queue_key", ""),
            "of_canonical_url": self.match.get("canonical_url", ""),
            "of_web_url": self.match.get("web_url", ""),
            "novedad": self.novelty,
        }


def enabled() -> bool:
    return os.getenv("SAME_EVENT_CHECK_ENABLED", "false").strip().lower() in _TRUE


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def _stems(text: str) -> set[str]:
    """Raíces de 4 letras de las palabras distintivas: "volcó"/"volcado" → "volc"."""
    return {w[:4] for w in re.findall(r"[a-zñ]{5,}", _fold(text)) if w not in _STOP}


def recent_candidates(noticia: dict, *, items: list | None = None, now: float | None = None) -> list[dict]:
    """Notas locales encoladas en las últimas ``SAME_EVENT_WINDOW_HOURS`` que
    comparten alguna raíz con la nota nueva, la más reciente primero."""
    hours = float(os.getenv("SAME_EVENT_WINDOW_HOURS", "36"))
    cutoff = (now or time.time()) - hours * 3600
    if items is None:
        try:
            items = load_json(str(data_dir() / "noticias_meta.json"), [], expected_type=list)
        except JsonStateError as exc:
            logger.warning("Cola Meta ilegible para comparar el mismo hecho: %s", exc)
            return []
    probe = " ".join(str(noticia.get(k) or "") for k in ("titulo_original", "titulo"))
    probe += " " + " ".join(str(p) for p in (noticia.get("parrafos") or [])[:1])
    probe_stems = _stems(probe)
    own_url = str(noticia.get("canonical_url") or noticia.get("url") or "")
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        queued = item.get("queued_at")
        source = str(item.get("source") or "").lower()
        if not isinstance(queued, (int, float)) or queued < cutoff or any(m in source for m in _NON_LOCAL_SOURCE_MARKERS):
            continue
        if own_url and own_url in (item.get("canonical_url"), item.get("url")):
            continue
        title = str(item.get("titulo_instagram") or item.get("titulo") or "").strip()
        original = str(item.get("titulo_original") or "").strip()
        if not title or not (probe_stems & _stems(f"{title} {original} {item.get('excerpt') or ''}")):
            continue
        rows.append({
            "title": title,
            "original": original,
            "excerpt": str(item.get("excerpt") or "")[:240],
            "meta_queue_key": str(item.get("meta_queue_key") or ""),
            "canonical_url": str(item.get("canonical_url") or item.get("url") or ""),
            "web_url": str(item.get("web_url") or ""),
            "queued_at": queued,
        })
    rows.sort(key=lambda r: r["queued_at"], reverse=True)
    return rows[: int(os.getenv("SAME_EVENT_MAX_CANDIDATES", "25"))]


def assess_same_event(noticia: dict, *, candidates: list[dict] | None = None, completion=None) -> EventCheck:
    """Una llamada a Gemini. Sin candidatas, sin credencial o sin respuesta
    válida: ``new``. Las notas no locales (paparazzi, Infobae, internacionales)
    no se evalúan: un evento grande tiene muchas historias distintas."""
    if any(m in str(noticia.get("source") or "").lower() for m in _NON_LOCAL_SOURCE_MARKERS):
        return EventCheck()
    candidates = recent_candidates(noticia) if candidates is None else candidates
    if not candidates:
        return EventCheck()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if completion is None and (not api_key or api_key == "PENDIENTE"):
        return EventCheck(error_type="credential_missing")
    if completion is None:
        from utils.ai_client import chat_completion as completion

    recientes = "\n".join(
        f"{i}. {c['title']}" + (f" — {c['excerpt']}" if c["excerpt"] else "")
        for i, c in enumerate(candidates, start=1)
    )
    parrafos = [str(p) for p in noticia.get("parrafos") or []]
    prompt = _PROMPT.format(
        recientes=recientes,
        titulo=str(noticia.get("titulo_original") or noticia.get("titulo") or ""),
        texto=" ".join(parrafos[:4])[:1800],
    )
    retry_count = int(os.getenv("GEMINI_RETRY_COUNT", "3"))
    retry_sleep = float(os.getenv("GEMINI_RETRY_SLEEP", "2"))
    for attempt in range(1, retry_count + 1):
        try:
            raw = completion(
                messages=[{"role": "user", "content": prompt}],
                model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
                api_key=api_key,
                temperature=0,
                max_tokens=120,
                timeout=float(os.getenv("GEMINI_TIMEOUT", "30")),
                json_mode=True,
            )
            return _parse(raw, candidates, str(noticia.get("titulo") or ""), probe_text=_probe_text(noticia))
        except Exception as exc:
            logger.warning("Evaluación de mismo hecho intento %s/%s: %s", attempt, retry_count, exc)
            if attempt < retry_count:
                time.sleep(retry_sleep)
    logger.error("Evaluación de mismo hecho falló; sigue como nota nueva: %s", str(noticia.get("titulo") or "")[:70])
    return EventCheck(error_type="gemini_failed")


def _probe_text(noticia: dict) -> str:
    parts = [noticia.get("titulo_original"), noticia.get("titulo"), *(noticia.get("parrafos") or [])[:4]]
    return " ".join(str(p) for p in parts if p)


def valid_anchor(anchor: str, probe_text: str, candidate: dict) -> bool:
    """El ancla tiene que estar escrita en las dos notas y ser un dato
    concreto: lleva un número ("Ruta 75") o una palabra con mayúscula que no
    sea la primera del texto ("Sanagasta", "Virgen India")."""
    anchor = re.sub(r"\s+", " ", str(anchor or "")).strip(" .,;:\"'")
    if len(anchor) < 4:
        return False
    other = " ".join(str(candidate.get(k) or "") for k in ("title", "original", "excerpt"))
    folded = _fold(anchor)
    if folded not in _fold(probe_text) or folded not in _fold(other):
        return False
    words = anchor.split()
    return any(c.isdigit() for c in anchor) or any(w[:1].isupper() and _fold(w) not in _STOP for w in words)


def _parse(raw: str, candidates: list[dict], titulo: str, *, probe_text: str = "") -> EventCheck:
    match = re.search(r"\{.*\}", str(raw or ""), re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        return EventCheck(error_type="invalid_model_response")
    index = data.get("mismo_hecho")
    if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= len(candidates):
        return EventCheck()
    found = candidates[index - 1]
    if not valid_anchor(str(data.get("ancla") or ""), probe_text or titulo, found):
        logger.info("Mismo hecho sin ancla comprobable (%r), sigue como nota nueva: %s", data.get("ancla"), titulo[:70])
        return EventCheck(match=found, related=True)
    novelty = re.sub(r"\s+", " ", str(data.get("novedad") or "")).strip(" .")
    if data.get("dato_nuevo") is True and novelty:
        logger.info("Actualización de \"%s\" (%s): %s", found["title"][:60], novelty[:80], titulo[:70])
        return EventCheck("update", found, novelty)
    logger.info("Mismo hecho que \"%s\", sin dato nuevo: %s", found["title"][:60], titulo[:70])
    return EventCheck("duplicate", found)


def superseded_keys(items: list) -> set[str]:
    """Notas reemplazadas por una actualización posterior que ya está lista
    (tiene URL web). Si la anterior todavía no salió en una red (las dos
    esperaban juntas el fin del horario de silencio), en esa red sale sólo
    la versión más nueva."""
    out: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        update = item.get("event_update")
        if not isinstance(update, dict) or not str(item.get("web_url") or item.get("noticia_url") or "").strip():
            continue
        for key in (update.get("of_meta_key"), update.get("of_canonical_url")):
            if key:
                out.add(str(key))
    return out


def is_superseded(noticia: dict, keys: set[str]) -> bool:
    return any(
        str(noticia.get(k) or "") in keys
        for k in ("meta_queue_key", "canonical_url", "url")
        if noticia.get(k)
    )


def drop_superseded(selected: list[dict], platform: str) -> tuple[list[dict], int]:
    """Saca de la tanda de ``platform`` las notas reemplazadas por una
    actualización ya lista y las marca como excluidas por política. Con el
    control apagado, o con la cola ilegible, la tanda queda igual."""
    if not enabled() or not selected:
        return selected, 0
    try:
        items = load_json(str(data_dir() / "noticias_meta.json"), [], expected_type=list)
    except JsonStateError as exc:
        logger.warning("Cola Meta ilegible; no se filtran versiones reemplazadas: %s", exc)
        return selected, 0
    keys = superseded_keys(items)
    if not keys:
        return selected, 0
    from utils.social_queue import mark_policy_excluded

    keep: list[dict] = []
    dropped = 0
    for noticia in selected:
        if is_superseded(noticia, keys):
            mark_policy_excluded(noticia, platform, "policy_superseded_by_update")
            logger.info("%s: sale sólo la actualización, no esta versión anterior: %s", platform, str(noticia.get("titulo") or "")[:70])
            dropped += 1
            continue
        keep.append(noticia)
    return keep, dropped


def _skip_platforms() -> set[str]:
    """``SAME_EVENT_SOCIAL_SKIP``: redes donde una nota ``event_related`` no se
    repite si la anterior ya salió ahí (vacío = ninguna)."""
    raw = os.getenv("SAME_EVENT_SOCIAL_SKIP", "")
    return {value.strip().lower() for value in raw.split(",") if value.strip()}


def _published_urls(platform: str) -> set[str]:
    name = {"instagram": "ig_posted.json", "facebook": "fb_posted.json"}.get(platform)
    if not name:
        return set()
    posted = load_json(str(data_dir() / name), {"posted": {}}, expected_type=dict).get("posted") or {}
    return {
        str(r.get(k))
        for r in posted.values()
        if isinstance(r, dict) and r.get("external_id")
        for k in ("canonical_url", "url")
        if r.get(k)
    }


def _related_chain(noticia: dict, index: dict[str, dict], hops: int = 3) -> list[str]:
    """URLs de las notas anteriores del mismo hecho: la ``event_related`` y,
    si esa tampoco salió, la que a su vez tenía como relacionada o como
    original de una actualización (hasta ``hops`` saltos)."""
    urls: list[str] = []
    current = noticia
    for _ in range(hops):
        link = current.get("event_related")
        if current is not noticia and not isinstance(link, dict):
            link = current.get("event_update")
        if not isinstance(link, dict):
            break
        url = str(link.get("of_canonical_url") or "")
        if not url or url in urls:
            break
        urls.append(url)
        current = index.get(url) or index.get(str(link.get("of_meta_key") or "")) or {}
        if not current:
            break
    return urls


def drop_already_posted(selected: list[dict], platform: str) -> tuple[list[dict], int]:
    """Saca de la tanda de ``platform`` las notas del mismo hecho que otra que
    ya salió en esa red, cuando el modelo las reconoció como el mismo hecho
    sin un ancla comprobable (``event_related``). La nota ya está en la Web y
    en las demás redes; acá sólo se evita repetir el tema (p. ej. cuatro posts
    sobre las licencias de conducir desde cuatro medios)."""
    if not enabled() or not selected or platform not in _skip_platforms():
        return selected, 0
    if not any(isinstance(n.get("event_related"), dict) for n in selected):
        return selected, 0
    try:
        published = _published_urls(platform)
        items = load_json(str(data_dir() / "noticias_meta.json"), [], expected_type=list)
    except JsonStateError as exc:
        logger.warning("Estado ilegible; no se filtran notas del mismo hecho para %s: %s", platform, exc)
        return selected, 0
    index: dict[str, dict] = {}
    for item in items:
        if isinstance(item, dict):
            for key in ("canonical_url", "url", "meta_queue_key"):
                if item.get(key):
                    index.setdefault(str(item[key]), item)
    from utils.social_queue import mark_policy_excluded

    keep: list[dict] = []
    dropped = 0
    for noticia in selected:
        if any(url in published for url in _related_chain(noticia, index)):
            mark_policy_excluded(noticia, platform, "policy_same_event_already_posted")
            logger.info("%s: el mismo hecho ya salió en esta red, no se repite: %s", platform, str(noticia.get("titulo") or "")[:70])
            dropped += 1
            continue
        keep.append(noticia)
    return keep, dropped


def original_published(noticia: dict, platform: str) -> bool:
    """True si la nota anterior de esta actualización ya salió en ``platform``
    (``instagram``/``facebook``). Sólo entonces la pieza dice ACTUALIZACIÓN."""
    update = noticia.get("event_update")
    if not isinstance(update, dict) or not update.get("of_canonical_url"):
        return False
    name = {"instagram": "ig_posted.json", "facebook": "fb_posted.json"}.get(platform)
    if not name:
        return False
    try:
        posted = load_json(str(data_dir() / name), {"posted": {}}, expected_type=dict).get("posted") or {}
    except JsonStateError:
        return False
    url = str(update["of_canonical_url"])
    return any(
        isinstance(r, dict) and r.get("external_id") and url in (r.get("canonical_url"), r.get("url"))
        for r in posted.values()
    )
