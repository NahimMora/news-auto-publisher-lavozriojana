"""Router editorial determinístico: automatic | candidate | suppressed.

Separa selección automática de oportunidad editorial premium sin llamadas
adicionales a IA. Fase 1 sólo restringe la selección automática de
Instagram; Web y Facebook conservan su comportamiento actual (ver
docs/DECISIONS.md).

Contrato por noticia (``editorial_route`` + campos hermanos, ver spec):

    {
      "editorial_route": "automatic|candidate|suppressed",
      "route_by_channel": {"web": ..., "facebook": ..., "instagram": ...},
      "route_reason": "...",
      "topic_key": "...",
      "topic_post_number": 1,
      "material_update": false,
      "breaking": false,
      "routed_at_ts": 0,
    }

Dos funciones separan lógica pura de I/O para poder testear y para que el
modo report-only nunca toque estado productivo:

- ``evaluate_routing``: pura, recibe un snapshot en memoria de publicaciones
  recientes del mismo ``topic_key`` y devuelve la decisión.
- ``apply_routing`` / ``report_routing``: envoltorios de I/O. El primero lee
  y actualiza ``data/topic_publication_state.json`` bajo lock y persiste
  candidatas/eventos; el segundo sólo lee (``load_json``) y nunca escribe.
"""
from __future__ import annotations

import copy
import hashlib
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any

from utils.editorial_priority import item_is_breaking, normalize_category
from utils.file_manager import JsonStateError, load_json, update_json, update_json_files
from utils.logging_setup import setup_logger
from utils.news_dedup import duplicate_reason
from utils.paths import data_dir

logger = setup_logger("editorial_router", "editorial_router.log")

TOPIC_WINDOW_SECONDS = 12 * 3600
TOPIC_AUTOMATIC_CAP = 2

# "automatic" y "candidate" son simétricos con route_by_channel: una
# candidata puede promoverse a automática (si la noticia real todavía no se
# publicó) y una automática pendiente puede degradarse a candidata. Ninguna
# transición reescribe jamás una publicación ya confirmada (ver
# demote_automatic_to_candidate / add_published_to_candidates).
CANDIDATE_STATUSES = {"candidate", "automatic", "discarded"}
_ALLOWED_CANDIDATE_TRANSITIONS = {
    ("candidate", "automatic"),
    ("candidate", "discarded"),
    ("discarded", "candidate"),
    ("automatic", "candidate"),
}


def _routing_state_path() -> str:
    return str(data_dir() / "topic_publication_state.json")


def _candidates_path() -> str:
    return str(data_dir() / "editorial_candidates.json")


def _events_path() -> str:
    return str(data_dir() / "editorial_routing_events.json")


def _meta_queue_path() -> str:
    return str(data_dir() / "noticias_meta.json")


def _social_queue_path() -> str:
    return str(data_dir() / "noticias_sociales_pendientes.json")


def _ig_posted_path() -> str:
    return str(data_dir() / "ig_posted.json")


def _record_routing_event(*, status: str, reason: str, item: dict, metadata: dict | None = None) -> dict:
    """Journal propio del router (distinto de queue_events.json, reservado a
    terminales/degradaciones de colas de publicación)."""
    event = {
        "event_id": uuid.uuid4().hex,
        "stage": "editorial_router",
        "status": str(status),
        "reason": str(reason),
        "timestamp": int(time.time()),
        "item": copy.deepcopy(item or {}),
        "metadata": copy.deepcopy(metadata or {}),
    }

    def append(events):
        if not isinstance(events, list):
            raise ValueError("editorial_routing_events.json debe contener una lista")
        events.append(event)
        return events

    update_json(_events_path(), append, [], expected_type=list)
    return event


# ── Normalización de texto ──────────────────────────────────────────────

def _ascii_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


# ── Señal de vínculo riojano (determinística, sin IA) ───────────────────
# Nombres planos derivados de openIA/rewrite_news.py:LOCALITY_HASHTAGS.
# Duplicados acá a propósito: ese módulo carga OpenAI/dotenv al importarse y
# utils/ no debe depender de openIA/.
RIOJAN_LOCALITY_TERMS = {
    "la rioja", "rioja", "riojano", "riojana", "riojanos", "riojanas",
    "chilecito", "famatina", "vinchina", "arauco", "chamical",
    "aimogasta", "chepes", "patquia", "tinogasta", "andalgala",
    "casa blanca", "nonogasta", "anguinan", "sierra negra",
    "villa union", "guandacol", "santa florentina", "villa famatina",
    "capital riojana", "general angel", "general lavalle",
}


def detect_riojan_link(noticia: dict) -> tuple[bool, str]:
    """True si existe evidencia determinística de vínculo con La Rioja."""
    hashtag = str(noticia.get("hashtag_localidad") or "").strip()
    if hashtag:
        return True, f"hashtag_localidad:{hashtag}"

    category = normalize_category(noticia.get("seccion") or noticia.get("categoria"))
    if category == "interior":
        return True, "category:interior"

    text_parts = [
        noticia.get("titulo_original"),
        noticia.get("titulo"),
        noticia.get("excerpt"),
    ]
    parrafos = noticia.get("parrafos") or []
    if isinstance(parrafos, list) and parrafos:
        text_parts.append(parrafos[0])
    text = _ascii_lower(" ".join(str(part or "") for part in text_parts))

    for term in sorted(RIOJAN_LOCALITY_TERMS, key=len, reverse=True):
        if _ascii_lower(term) in text:
            return True, f"keyword:{term}"

    return False, "no_riojan_link_detected"


# ── topic_key ────────────────────────────────────────────────────────────
# Palabras genéricas que NO deben, por sí solas, agrupar acontecimientos
# distintos (instrucción explícita: incendio/accidente/policía/gobierno/
# partido son ejemplos dados).
GENERIC_TOPIC_WORDS = {
    "incendio", "accidente", "policia", "gobierno", "partido",
    "choque", "temporal", "operativo", "denuncia", "comunicado",
    "noticia", "ultimo", "momento", "provincia", "municipio",
    "informe", "reporte", "situacion", "caso", "hecho", "nota",
}

_CONNECTOR_WORDS = {"de", "del", "la", "las", "los", "y", "e", "en", "san", "santa", "el", "un", "una"}
_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+")


def _entity_tokens(titulo: str) -> list[str]:
    """Palabras capitalizadas que NO son inicio de oración, más siglas.

    Evita el falso positivo conocido (LVR-075) de tratar la mayúscula de
    inicio de oración como una entidad: sólo cuentan como "entidad" las
    palabras capitalizadas en posición >0, o siglas de 2+ letras en
    cualquier posición.
    """
    words = _WORD_RE.findall(titulo or "")
    tokens: list[str] = []
    for index, word in enumerate(words):
        if word.lower() in _CONNECTOR_WORDS:
            continue
        if word.isupper() and len(word) >= 2:
            tokens.append(_ascii_lower(word))
        elif index > 0 and word[0].isupper() and not word.isupper():
            tokens.append(_ascii_lower(word))
    return [token for token in tokens if len(token) >= 3 and token not in GENERIC_TOPIC_WORDS]


def _fallback_tokens(titulo: str) -> list[str]:
    from utils.news_dedup import normalize_tokens

    tokens = normalize_tokens(titulo)
    return sorted(token for token in tokens if token not in GENERIC_TOPIC_WORDS)[:4]


def _date_bucket(noticia: dict) -> str:
    fecha = str(noticia.get("fecha") or "").strip()
    if fecha:
        return fecha[:10]
    queued_at = noticia.get("queued_at") or noticia.get("web_queued_at")
    try:
        ts = int(queued_at)
    except (TypeError, ValueError):
        ts = int(time.time())
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def compute_topic_key(noticia: dict) -> str:
    """Fingerprint determinístico y económico de "mismo acontecimiento".

    Limitación conocida: dos títulos sobre el mismo hecho que no comparten
    ninguna entidad capitalizada (p. ej. uno omite el nombre propio que el
    otro incluye) pueden recibir topic_key distintos. Es una limitación
    aceptada de un enfoque sin embeddings/IA (ver docs/KNOWN_ISSUES.md).
    """
    titulo = str(noticia.get("titulo_original") or noticia.get("titulo") or "")
    entity_tokens = _entity_tokens(titulo)
    if not entity_tokens:
        entity_tokens = _fallback_tokens(titulo)

    _, locality_reason = detect_riojan_link(noticia)
    locality = locality_reason.split(":", 1)[1] if ":" in locality_reason else ""
    category = normalize_category(noticia.get("seccion") or noticia.get("categoria"))
    bucket = _date_bucket(noticia)

    basis = "|".join(
        [
            ",".join(sorted(set(entity_tokens))[:6]),
            _ascii_lower(locality),
            category,
            bucket,
        ]
    )
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return f"topic:{digest}"


# ── Actualización material (determinística, sin IA) ─────────────────────
MATERIAL_UPDATE_KEYWORDS = {
    "victima", "victimas", "evacuado", "evacuados", "evacuada", "evacuadas",
    "resuelto", "resolucion", "detenido", "detenidos", "detencion",
    "hallado", "hallados", "hallazgo", "confirmado", "confirmo oficialmente",
    "nueva alerta", "reabre", "reapertura", "cierre", "cerrado",
    "resultado definitivo", "condenado", "imputado", "liberado",
    "identificado", "identificada",
}


def _is_material_update_title(titulo: str) -> bool:
    text = _ascii_lower(titulo)
    return any(keyword in text for keyword in MATERIAL_UPDATE_KEYWORDS)


# ── Duplicado técnico ─────────────────────────────────────────────────────

def _is_technical_duplicate(noticia: dict, recent_entries: list[dict]) -> str | None:
    candidates = [
        {"titulo": entry.get("titulo"), "canonical_url": entry.get("canonical_url"), "url": entry.get("url")}
        for entry in recent_entries
    ]
    probe = {
        "titulo": noticia.get("titulo_original") or noticia.get("titulo"),
        "canonical_url": noticia.get("canonical_url"),
        "url": noticia.get("url"),
    }
    return duplicate_reason(
        probe,
        candidates,
        key_fields=("canonical_url", "url"),
        threshold=0.85,
    )


# ── Decisión pura ─────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    editorial_route: str
    route_by_channel: dict[str, str]
    route_reason: str
    topic_key: str
    topic_post_number: int
    material_update: bool
    breaking: bool
    routed_at_ts: int
    locality_signal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "editorial_route": self.editorial_route,
            "route_by_channel": dict(self.route_by_channel),
            "route_reason": self.route_reason,
            "topic_key": self.topic_key,
            "topic_post_number": self.topic_post_number,
            "material_update": self.material_update,
            "breaking": self.breaking,
            "routed_at_ts": self.routed_at_ts,
        }


def evaluate_routing(
    noticia: dict,
    *,
    recent_topic_entries: list[dict] | None = None,
    now_ts: int | None = None,
) -> RoutingDecision:
    """Decisión pura. ``recent_topic_entries`` son entradas ya podadas a la
    ventana de 12h para el ``topic_key`` de esta noticia y el canal
    Instagram, más antiguas primero. No hace I/O.
    """
    now_ts = int(now_ts if now_ts is not None else time.time())
    recent_topic_entries = recent_topic_entries or []
    topic_key = compute_topic_key(noticia)
    breaking = item_is_breaking(noticia)

    duplicate = _is_technical_duplicate(noticia, recent_topic_entries)
    if duplicate:
        reasons = [f"suppressed:{duplicate}"]
        return RoutingDecision(
            editorial_route="suppressed",
            route_by_channel={"web": "automatic", "facebook": "automatic", "instagram": "suppressed"},
            route_reason=";".join(reasons),
            topic_key=topic_key,
            topic_post_number=len(recent_topic_entries) + 1,
            material_update=False,
            breaking=breaking,
            routed_at_ts=now_ts,
            locality_signal="",
        )

    topic_post_number = len(recent_topic_entries) + 1
    material_update = topic_post_number > 1 and _is_material_update_title(
        str(noticia.get("titulo_original") or noticia.get("titulo") or "")
    )

    riojan_link, locality_reason = detect_riojan_link(noticia)
    reasons = [locality_reason]

    if not riojan_link:
        instagram_route = "candidate"
        reasons.append("gate:no_riojan_link")
    else:
        if breaking:
            instagram_route = "automatic"
            reasons.append(f"topic_post_number={topic_post_number}")
            reasons.append("exception:breaking")
        elif material_update:
            instagram_route = "automatic"
            reasons.append(f"topic_post_number={topic_post_number}")
            reasons.append("exception:material_update")
        elif topic_post_number <= TOPIC_AUTOMATIC_CAP:
            instagram_route = "automatic"
            reasons.append(f"topic_post_number={topic_post_number}")
        else:
            instagram_route = "candidate"
            reasons.append(f"topic_cap_exceeded:topic_post_number={topic_post_number}")

    route_by_channel = {
        "web": "automatic",
        "facebook": "automatic",
        "instagram": instagram_route,
    }
    editorial_route = "candidate" if instagram_route == "candidate" else "automatic"

    return RoutingDecision(
        editorial_route=editorial_route,
        route_by_channel=route_by_channel,
        route_reason=";".join(reasons),
        topic_key=topic_key,
        topic_post_number=topic_post_number,
        material_update=material_update,
        breaking=breaking,
        routed_at_ts=now_ts,
        locality_signal=locality_reason,
    )


# ── Envoltorios de I/O ──────────────────────────────────────────────────

def _identity(noticia: dict) -> str:
    return str(
        noticia.get("meta_queue_key")
        or noticia.get("web_queue_key")
        or noticia.get("dedup_key")
        or noticia.get("canonical_url")
        or noticia.get("url")
        or noticia.get("titulo")
        or ""
    )


# ── Búsqueda de la noticia real por identidad (para overrides manuales) ──

def _matches_identity(item: dict, identity: str) -> bool:
    if not identity:
        return False
    for field in ("meta_queue_key", "dedup_key", "web_queue_key", "canonical_url", "url"):
        value = item.get(field)
        if value and str(value) == identity:
            return True
    return False


def _find_meta_item(identity: str) -> dict | None:
    items = load_json(_meta_queue_path(), [], expected_type=list)
    for item in items:
        if isinstance(item, dict) and _matches_identity(item, identity):
            return item
    return None


def _social_queue_instagram_state(identity: str) -> str | None:
    items = load_json(_social_queue_path(), [], expected_type=list)
    for item in items:
        if not (isinstance(item, dict) and _matches_identity(item, identity)):
            continue
        explicit = str(item.get("instagram_state") or "").strip().lower()
        if explicit:
            return explicit
        return "completed" if item.get("instagram_done") else "pending"
    return None


def _find_posted_record(identity: str) -> dict | None:
    try:
        ig_state = load_json(_ig_posted_path(), {"posted": {}}, expected_type=dict)
    except JsonStateError:
        return None
    posted = ig_state.get("posted")
    if not isinstance(posted, dict):
        return None
    direct = posted.get(identity)
    if isinstance(direct, dict):
        return direct
    for record in posted.values():
        if isinstance(record, dict) and _matches_identity(record, identity):
            return record
    return None


def _is_published_on_instagram(identity: str) -> bool:
    """Evidencia real de publicación (nunca se infiere ni se fabrica)."""
    if _social_queue_instagram_state(identity) == "completed":
        return True
    return _find_posted_record(identity) is not None


def _prune_entries(entries: list[dict], now_ts: int) -> list[dict]:
    cutoff = now_ts - TOPIC_WINDOW_SECONDS
    return [entry for entry in entries if int(entry.get("ts") or 0) >= cutoff]


def _entry_from_decision(noticia: dict, decision: RoutingDecision) -> dict:
    return {
        "ts": decision.routed_at_ts,
        "identity": _identity(noticia),
        "titulo": noticia.get("titulo_original") or noticia.get("titulo"),
        "canonical_url": noticia.get("canonical_url"),
        "url": noticia.get("url"),
        "route": decision.route_by_channel.get("instagram"),
        "breaking": decision.breaking,
        "material_update": decision.material_update,
    }


def _find_candidate_by_identity(identity: str, *, channel: str) -> dict | None:
    if not identity:
        return None
    candidates = load_json(_candidates_path(), [], expected_type=list)
    for item in candidates:
        if isinstance(item, dict) and item.get("identity") == identity and item.get("channel") == channel:
            return item
    return None


def _upsert_candidate_for_identity(
    identity: str,
    *,
    channel: str,
    origin: str,
    noticia: dict,
    topic_key: str = "",
    route_reason: str = "",
    now_ts: int | None = None,
) -> dict:
    """Crea la candidata si no existe una para esta identidad+canal
    (idempotente); si ya existe, la devuelve sin duplicar."""
    now_ts = int(now_ts if now_ts is not None else time.time())
    outcome: dict[str, dict] = {}

    def mutate(existing):
        if not isinstance(existing, list):
            raise ValueError("editorial_candidates.json debe contener una lista")
        if identity:
            for item in existing:
                if isinstance(item, dict) and item.get("identity") == identity and item.get("channel") == channel:
                    outcome["item"] = item
                    return existing
        candidate = {
            "candidate_id": uuid.uuid4().hex,
            "channel": channel,
            "status": "candidate",
            "origin": origin,
            "topic_key": topic_key or noticia.get("topic_key"),
            "titulo": noticia.get("titulo_original") or noticia.get("titulo"),
            "seccion": noticia.get("seccion"),
            "source": noticia.get("source"),
            "canonical_url": noticia.get("canonical_url") or noticia.get("url"),
            "identity": identity,
            "route_reason": route_reason,
            "created_at_ts": now_ts,
            "updated_at_ts": now_ts,
            "manual_override_history": [],
            "noticia": copy.deepcopy(noticia),
        }
        existing.append(candidate)
        outcome["item"] = candidate
        return existing

    update_json(_candidates_path(), mutate, [], expected_type=list)
    return outcome["item"]


def _record_candidate(noticia: dict, decision: RoutingDecision, *, channel: str) -> dict:
    return _upsert_candidate_for_identity(
        _identity(noticia),
        channel=channel,
        origin="routed",
        noticia=noticia,
        topic_key=decision.topic_key,
        route_reason=decision.route_reason,
        now_ts=decision.routed_at_ts,
    )


def apply_routing(noticia: dict, *, now_ts: int | None = None) -> RoutingDecision:
    """Calcula y persiste la decisión de ruteo (topic state, evento, candidata).

    Aditivo: nunca modifica colas productivas (noticias_meta.json,
    noticias_sociales_pendientes.json, etc). Sólo la aplicación en
    ``meta/run_ig.py`` (detrás de ``EDITORIAL_ROUTER_ENABLED``) consume
    ``route_by_channel.instagram`` para filtrar la selección automática.
    """
    now_ts = int(now_ts if now_ts is not None else time.time())
    topic_key = compute_topic_key(noticia)

    result: dict[str, RoutingDecision] = {}

    def mutate(state):
        if not isinstance(state, dict):
            raise ValueError("topic_publication_state.json debe contener un objeto")
        topic_state = state.get(topic_key) or {}
        channel_entries = _prune_entries(topic_state.get("instagram") or [], now_ts)

        decision = evaluate_routing(noticia, recent_topic_entries=channel_entries, now_ts=now_ts)
        result["decision"] = decision

        if decision.editorial_route != "suppressed":
            channel_entries.append(_entry_from_decision(noticia, decision))
        topic_state["instagram"] = channel_entries
        state[topic_key] = topic_state
        return state

    update_json(_routing_state_path(), mutate, {}, expected_type=dict)
    decision = result["decision"]

    _record_routing_event(
        status=decision.editorial_route,
        reason=decision.route_reason,
        item={"titulo": noticia.get("titulo_original") or noticia.get("titulo"), "identity": _identity(noticia)},
        metadata=decision.to_dict(),
    )

    if decision.route_by_channel.get("instagram") == "candidate":
        _record_candidate(noticia, decision, channel="instagram")

    logger.info(
        "route=%s instagram=%s topic=%s reason=%s titulo=%s",
        decision.editorial_route,
        decision.route_by_channel.get("instagram"),
        decision.topic_key,
        decision.route_reason,
        str(noticia.get("titulo") or "")[:70],
    )
    return decision


def report_routing(noticias: list[dict], *, limit: int | None = None, now_ts: int | None = None) -> list[dict]:
    """Modo report-only: lee el estado actual pero nunca lo modifica.

    Simula, en memoria, el mismo efecto secuencial que tendría
    ``apply_routing`` sobre el lote dado (para que ítems del mismo
    ``topic_key`` dentro del propio lote se cuenten entre sí), sin guardar
    nada en disco.
    """
    now_ts = int(now_ts if now_ts is not None else time.time())
    persisted_state = load_json(_routing_state_path(), {}, expected_type=dict)
    local_state = copy.deepcopy(persisted_state)

    items = noticias[:limit] if limit else noticias
    rows: list[dict] = []
    for noticia in items:
        topic_key = compute_topic_key(noticia)
        topic_state = local_state.get(topic_key) or {}
        channel_entries = _prune_entries(topic_state.get("instagram") or [], now_ts)

        decision = evaluate_routing(noticia, recent_topic_entries=channel_entries, now_ts=now_ts)

        if decision.editorial_route != "suppressed":
            channel_entries.append(_entry_from_decision(noticia, decision))
        topic_state["instagram"] = channel_entries
        local_state[topic_key] = topic_state

        riojan_link, locality_reason = detect_riojan_link(noticia)
        rows.append(
            {
                "titulo": noticia.get("titulo_original") or noticia.get("titulo"),
                "topic_key": decision.topic_key,
                "localidad": locality_reason,
                "seccion": noticia.get("seccion"),
                "route_by_channel": decision.route_by_channel,
                "editorial_route": decision.editorial_route,
                "route_reason": decision.route_reason,
                "topic_post_number": decision.topic_post_number,
                "breaking": decision.breaking,
                "material_update": decision.material_update,
            }
        )
    return rows


# ── Transiciones manuales de candidatas (rule 16) ────────────────────────

def list_candidates(*, channel: str | None = None, status: str | None = None) -> list[dict]:
    candidates = load_json(_candidates_path(), [], expected_type=list)
    rows = [item for item in candidates if isinstance(item, dict)]
    if channel:
        rows = [item for item in rows if item.get("channel") == channel]
    if status:
        rows = [item for item in rows if item.get("status") == status]
    return rows


def _sync_noticia_route(identity: str, target_route: str) -> bool:
    """Refleja candidate<->automatic en la noticia real de
    noticias_meta.json, si todavía existe y no fue publicada. Nunca
    reescribe el historial de una publicación real confirmada. Devuelve
    True si efectivamente actualizó un registro."""
    if not identity or _is_published_on_instagram(identity):
        return False

    updated = {"ok": False}

    def mutate(items):
        if not isinstance(items, list):
            raise ValueError("noticias_meta.json debe contener una lista")
        for item in items:
            if isinstance(item, dict) and _matches_identity(item, identity):
                route_by_channel = dict(item.get("route_by_channel") or {})
                route_by_channel["instagram"] = target_route
                item["route_by_channel"] = route_by_channel
                item["editorial_route"] = "candidate" if target_route == "candidate" else item.get(
                    "editorial_route", "automatic"
                )
                updated["ok"] = True
                break
        return items

    update_json(_meta_queue_path(), mutate, [], expected_type=list)
    return updated["ok"]


def update_candidate_status(
    candidate_id: str,
    new_status: str,
    *,
    operator: str | None = None,
    note: str | None = None,
) -> dict:
    """Transiciones: candidate<->automatic, candidate<->discarded.

    candidate→automatic y automatic→candidate también reflejan el cambio en
    la noticia real de ``noticias_meta.json`` (si todavía existe y no fue
    publicada), para que ``meta/run_ig.py`` vea el nuevo estado en el
    próximo ciclo. Idempotente: pedir el mismo status actual no falla ni
    duplica evento/historial.
    """
    if new_status not in CANDIDATE_STATUSES:
        raise ValueError(f"status inválido: {new_status}")

    now_ts = int(time.time())
    outcome: dict[str, Any] = {}

    def mutate(existing):
        if not isinstance(existing, list):
            raise ValueError("editorial_candidates.json debe contener una lista")
        for item in existing:
            if not isinstance(item, dict) or item.get("candidate_id") != candidate_id:
                continue
            current = item.get("status")
            outcome["previous_status"] = current
            if current == new_status:
                outcome["item"] = copy.deepcopy(item)
                outcome["changed"] = False
                return existing
            if (current, new_status) not in _ALLOWED_CANDIDATE_TRANSITIONS:
                raise ValueError(f"transición no permitida: {current} -> {new_status}")
            item["status"] = new_status
            item["updated_at_ts"] = now_ts
            history = item.setdefault("manual_override_history", [])
            history.append(
                {
                    "from": current,
                    "to": new_status,
                    "operator": operator,
                    "note": note,
                    "ts": now_ts,
                }
            )
            outcome["item"] = copy.deepcopy(item)
            outcome["changed"] = True
            break
        else:
            raise KeyError(f"candidate_id no encontrado: {candidate_id}")
        return existing

    update_json(_candidates_path(), mutate, [], expected_type=list)
    if "item" not in outcome:
        raise KeyError(f"candidate_id no encontrado: {candidate_id}")

    item = outcome["item"]
    if not outcome["changed"]:
        return item

    route_synced = False
    if item.get("channel") == "instagram" and new_status in {"automatic", "candidate"}:
        route_synced = _sync_noticia_route(item.get("identity", ""), new_status)

    _record_routing_event(
        status="manual_override",
        reason=note or f"status_changed_to_{new_status}",
        item={"candidate_id": candidate_id, "identity": item.get("identity")},
        metadata={
            "previous_route": outcome["previous_status"],
            "new_route": new_status,
            "changed_at_ts": now_ts,
            "changed_by": operator or "operator",
            "reason": note or f"status_changed_to_{new_status}",
            "noticia_route_synced": route_synced,
        },
    )
    return item


def demote_automatic_to_candidate(
    identity: str,
    *,
    reason: str,
    operator: str = "operator",
) -> dict:
    """Caso A: retira una noticia todavía NO publicada de la selección
    automática de Instagram, antes del claim/publicación, y la conserva en
    la bandeja de candidatas.

    Se niega si la noticia ya fue publicada (usar
    ``add_published_to_candidates``) o si hay un claim en curso
    (``instagram_state == "processing"``). Idempotente: una segunda llamada
    no duplica candidata ni evento.
    """
    if _is_published_on_instagram(identity):
        raise ValueError(
            "la noticia ya tiene evidencia de publicación en Instagram; "
            "usá add_published_to_candidates en su lugar"
        )
    social_state = _social_queue_instagram_state(identity)
    if social_state == "processing":
        raise ValueError(
            "hay un claim en curso para esta noticia (instagram_state=processing); reintentá luego"
        )

    meta_item = _find_meta_item(identity)
    if meta_item is None:
        raise KeyError(f"noticia no encontrada en noticias_meta.json: {identity}")

    current_route = (meta_item.get("route_by_channel") or {}).get("instagram") or "automatic"
    now_ts = int(time.time())

    if current_route == "candidate":
        existing = _find_candidate_by_identity(identity, channel="instagram")
        return {
            "changed": False,
            "identity": identity,
            "previous_route": "candidate",
            "new_route": "candidate",
            "candidate_id": existing.get("candidate_id") if existing else None,
        }

    def mutate(files):
        meta_items = files[_meta_queue_path()]
        for item in meta_items:
            if isinstance(item, dict) and _matches_identity(item, identity):
                route_by_channel = dict(item.get("route_by_channel") or {})
                route_by_channel["instagram"] = "candidate"
                item["route_by_channel"] = route_by_channel
                item["editorial_route"] = "candidate"
                item["route_reason"] = ";".join(
                    part
                    for part in (item.get("route_reason"), f"manual_override:demoted_by_operator:{reason}")
                    if part
                )
                break
        social_items = files[_social_queue_path()]
        for item in social_items:
            if isinstance(item, dict) and _matches_identity(item, identity):
                item["instagram_state"] = "excluded"
                item["instagram_updated_at"] = now_ts
                item["instagram_reason"] = f"editorial_override_to_candidate:{reason}"
                item["instagram_done"] = False
                break
        return files

    update_json_files(
        {
            _meta_queue_path(): ([], list),
            _social_queue_path(): ([], list),
        },
        mutate,
        save_order=[_meta_queue_path(), _social_queue_path()],
    )

    candidate = _upsert_candidate_for_identity(
        identity,
        channel="instagram",
        origin="operator_demotion",
        noticia=meta_item,
        route_reason=reason,
        now_ts=now_ts,
    )

    _record_routing_event(
        status="manual_override",
        reason=reason,
        item={"identity": identity, "titulo": meta_item.get("titulo_original") or meta_item.get("titulo")},
        metadata={
            "previous_route": current_route,
            "new_route": "candidate",
            "changed_at_ts": now_ts,
            "changed_by": operator,
            "reason": reason,
        },
    )

    logger.info("Demovida a candidata (operador): identity=%s reason=%s", identity, reason)
    return {
        "changed": True,
        "identity": identity,
        "previous_route": current_route,
        "new_route": "candidate",
        "candidate_id": candidate.get("candidate_id"),
    }


def add_published_to_candidates(
    identity: str,
    *,
    reason: str,
    operator: str = "operator",
) -> dict:
    """Caso B: agrega una noticia YA publicada automáticamente a la bandeja
    de candidatas para reutilizarla en un carrusel premium. Nunca modifica
    ni borra la evidencia histórica de publicación — el estado publicado se
    conserva intacto.
    """
    if not _is_published_on_instagram(identity):
        raise ValueError("la noticia no tiene evidencia de publicación en Instagram")

    now_ts = int(time.time())
    existing = _find_candidate_by_identity(identity, channel="instagram")
    if existing and existing.get("origin") == "published_reuse":
        return {"changed": False, "identity": identity, "candidate_id": existing.get("candidate_id")}

    meta_item = _find_meta_item(identity) or _find_posted_record(identity) or {"titulo": identity}

    candidate = _upsert_candidate_for_identity(
        identity,
        channel="instagram",
        origin="published_reuse",
        noticia=meta_item,
        route_reason=reason,
        now_ts=now_ts,
    )

    _record_routing_event(
        status="added_to_candidates_from_published",
        reason=reason,
        item={"identity": identity, "titulo": meta_item.get("titulo_original") or meta_item.get("titulo")},
        metadata={
            "previous_route": "automatic",
            "new_route": "automatic",  # el histórico de publicación NO cambia
            "changed_at_ts": now_ts,
            "changed_by": operator,
            "reason": reason,
            "note": "agregada a candidatas para reutilización premium; publicación histórica intacta",
        },
    )

    logger.info("Publicación existente agregada a candidatas premium: identity=%s", identity)
    return {"changed": True, "identity": identity, "candidate_id": candidate.get("candidate_id")}
