"""Canal y grupo de WhatsApp: qué se envía, con qué texto y qué ya salió.

* Grupo (``WHATSAPP_GROUP_JID``): todo lo que salió en Facebook — las notas con
  link (``fb_posted.json``) y los Reels de notas con video
  (``paparazzi_reels_posted.json``), que van como link a la nota con la marca
  "VIDEO".
* Canal (``WHATSAPP_CHANNEL_JID``): sólo último momento, apenas sale.

El envío lo hace ``whatsapp/wa.mjs`` (Baileys, sin navegador). Acá no hay red
salvo la miniatura de la vista previa. Sin IA: el texto sale de la nota.

Arranque: sin marca de agua guardada se toma "ahora" (no se envía el historial).
Una nota más vieja que ``WHATSAPP_MAX_AGE_HOURS`` no se envía; en horario
silencioso (``WHATSAPP_QUIET_HOURS``) sólo sale último momento.

Estados por mensaje (``data/whatsapp_state.json``): ``sent`` (con
``message_id``), ``failed`` (reintenta hasta ``WHATSAPP_MAX_ATTEMPTS``),
``dead_letter``, ``unverified`` (pudo haber salido: nunca se reintenta a ciegas)
y ``skipped_stale``.
"""
from __future__ import annotations

import base64
import io
import os
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from utils.editorial_priority import item_is_breaking
from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_time import quiet_hours

logger = setup_logger("whatsapp_feed", "whatsapp.log")

_TRUE = {"1", "true", "yes", "on", "si", "sí"}

SENT = "sent"
FAILED = "failed"
DEAD = "dead_letter"
UNVERIFIED = "unverified"
STALE = "skipped_stale"
QUEUED = "queued"  # esperando turno en el envío espaciado
SENDING = "sending"  # en curso; si el envío se corta, queda unverified
_FINAL = {SENT, DEAD, UNVERIFIED, STALE}
_IN_FLIGHT = {QUEUED, SENDING}


# ── Configuración ────────────────────────────────────────────────────────
def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUE


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return _flag("WHATSAPP_ENABLED")


def dry_run() -> bool:
    return _flag("WHATSAPP_DRY_RUN", "true")


def group_jid() -> str:
    return os.getenv("WHATSAPP_GROUP_JID", "").strip()


def channel_jid() -> str:
    return os.getenv("WHATSAPP_CHANNEL_JID", "").strip()


def max_age_seconds() -> float:
    return _float("WHATSAPP_MAX_AGE_HOURS", 3.0) * 3600


def max_per_cycle() -> int:
    return max(1, int(_float("WHATSAPP_MAX_PER_CYCLE", 15)))


def max_attempts() -> int:
    return max(1, int(_float("WHATSAPP_MAX_ATTEMPTS", 3)))


def state_path() -> str:
    return str(data_dir() / "whatsapp_state.json")


def load_state() -> dict:
    return load_json(state_path(), {}, expected_type=dict)


# ── Origen: lo que salió en Facebook ─────────────────────────────────────
def _load_posted(name: str) -> dict:
    return load_json(str(data_dir() / name), {"posted": {}}, expected_type=dict).get("posted") or {}


def _meta_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for name in ("noticias_meta.json", "noticias_web_publicadas.json"):
        try:
            items = load_json(str(data_dir() / name), [], expected_type=list)
        except JsonStateError:
            logger.warning("%s ilegible: sin datos de nota para WhatsApp", name)
            continue
        for item in items:
            if isinstance(item, dict):
                for key in ("canonical_url", "url"):
                    if item.get(key):
                        index.setdefault(str(item[key]), item)
    return index


def facebook_items(since: float) -> list[dict]:
    """Notas que salieron en Facebook desde ``since``, la más vieja primero."""
    index = _meta_index()
    out: list[dict] = []
    for record in _load_posted("fb_posted.json").values():
        if not isinstance(record, dict) or not record.get("external_id"):
            continue
        posted_at = float(record.get("posted_at") or 0)
        if posted_at <= since:
            continue
        url = str(record.get("canonical_url") or record.get("url") or "")
        out.append({"posted_at": posted_at, "canonical_url": url, "video": False,
                    "item": index.get(url) or {}, "titulo": record.get("titulo")})
    for record in _load_posted("paparazzi_reels_posted.json").values():
        # Reel de nota con video: en Facebook salió el video sin link.
        if not isinstance(record, dict) or not record.get("facebook_id"):
            continue
        posted_at = float(record.get("posted_at") or 0)
        if posted_at <= since:
            continue
        url = str(record.get("canonical_url") or "")
        out.append({"posted_at": posted_at, "canonical_url": url, "video": True,
                    "item": index.get(url) or {}, "titulo": record.get("titulo")})
    out.sort(key=lambda entry: entry["posted_at"])
    return out


# ── Texto ────────────────────────────────────────────────────────────────
def with_utm(url: str, medium: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")]
    query += [("utm_source", "whatsapp"), ("utm_medium", medium)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return f"{cut}…"


def compose(entry: dict, *, medium: str) -> dict | None:
    """Mensaje para una nota, o ``None`` si no tiene nota en la web."""
    item = entry.get("item") or {}
    web_url = str(item.get("web_url") or item.get("noticia_url") or "").strip()
    if not web_url.startswith("https://"):
        return None
    title = _clip(item.get("titulo") or entry.get("titulo") or "", 160)
    if not title:
        return None
    link = with_utm(web_url, medium)
    breaking = item_is_breaking(item) if item else False
    if breaking:
        head = f"🔴 *ÚLTIMO MOMENTO*\n*{title}*"
    elif entry.get("video"):
        head = f"🎥 *VIDEO* | *{title}*"
    else:
        head = f"📰 *{title}*"
    excerpt = _clip(item.get("excerpt") or "", 220)
    body = f"{head}\n\n{excerpt}\n\n👉 {link}" if excerpt and breaking else f"{head}\n\n👉 {link}"
    return {
        "text": body,
        "breaking": breaking,
        "preview": {"url": link, "title": title, "description": excerpt,
                    "image_url": str(item.get("imagen_url") or "")},
    }


def thumbnail_b64(image_url: str) -> str:
    """Miniatura JPEG chica para la vista previa del link ("" si no se pudo)."""
    if not image_url.startswith("https://"):
        return ""
    try:
        from PIL import Image

        from utils.safe_http import safe_get

        response = safe_get(image_url, timeout=15, headers={"User-Agent": "LaVozRiojanaBot/1.0"})
        content = getattr(response, "content", b"") or b""
        if getattr(response, "status_code", 0) != 200 or not content or len(content) > 10 * 1024 * 1024:
            return ""
        with Image.open(io.BytesIO(content)) as image:
            image = image.convert("RGB")
            image.thumbnail((320, 320))
            out = io.BytesIO()
            image.save(out, "JPEG", quality=70)
        return base64.b64encode(out.getvalue()).decode("ascii")
    except Exception as exc:  # noqa: BLE001 — sin miniatura el link sale igual
        logger.info("Sin miniatura para WhatsApp: %s", type(exc).__name__)
        return ""


# ── Selección ────────────────────────────────────────────────────────────
def message_key(target: str, canonical_url: str) -> str:
    return f"{target}:{canonical_url}"


def plan(state: dict, *, now: float | None = None) -> tuple[list[dict], list[str]]:
    """Mensajes a enviar en este ciclo y claves que vencieron sin enviarse."""
    now = now or time.time()
    since = float(state.get("watermark") or now)
    messages = state.get("messages") or {}
    quiet = quiet_hours(window=os.getenv("WHATSAPP_QUIET_HOURS", "0-7"))
    targets = [("grupo", group_jid())]
    if channel_jid():
        targets.append(("canal", channel_jid()))
    out: list[dict] = []
    stale: list[str] = []
    window_start = since - max_age_seconds()
    for entry in facebook_items(window_start):
        for medium, jid in targets:
            if not jid or not entry["canonical_url"]:
                continue
            key = message_key(medium, entry["canonical_url"])
            previous = messages.get(key) or {}
            if previous.get("status") in _FINAL | _IN_FLIGHT:
                continue
            if previous.get("status") == FAILED and int(previous.get("attempts") or 0) >= max_attempts():
                continue
            if not previous and entry["posted_at"] <= since:
                continue  # anterior al arranque
            message = compose(entry, medium=medium)
            if message is None:
                continue
            if medium == "canal" and not message["breaking"]:
                continue
            if now - entry["posted_at"] > max_age_seconds():
                stale.append(key)
                continue
            if quiet and not message["breaking"]:
                continue
            out.append({"key": key, "jid": jid, "medium": medium, "posted_at": entry["posted_at"], **message})
    # Último momento primero; después, en el orden en que salieron.
    out.sort(key=lambda m: not m["breaking"])
    return out[: max_per_cycle()], stale


def gap_seconds() -> tuple[float, float]:
    """``WHATSAPP_GAP_SECONDS`` ("90-240"): pausa al azar entre mensajes."""
    try:
        low, high = (float(x) for x in os.getenv("WHATSAPP_GAP_SECONDS", "90-240").split("-", 1))
        return max(0.0, low), max(low, high)
    except ValueError:
        return 90.0, 240.0


def enqueue(messages: list[dict], *, now: float | None = None) -> int:
    """Deja los mensajes del ciclo en cola para el envío espaciado."""
    now = now or time.time()
    added = 0

    def mutate(state):
        nonlocal added
        box = state.setdefault("messages", {})
        for m in messages:
            if (box.get(m["key"]) or {}).get("status") in _FINAL | _IN_FLIGHT:
                continue
            box[m["key"]] = {**(box.get(m["key"]) or {}), "status": QUEUED, "queued_at": int(now),
                             "title": m["preview"]["title"][:120],
                             "payload": {k: m[k] for k in ("jid", "medium", "text", "preview", "breaking", "posted_at")
                                         if k in m}}
            added += 1
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)
    return added


def next_queued(state: dict, *, now: float | None = None) -> tuple[str, dict] | None:
    """Próximo mensaje de la cola: último momento primero, después el más viejo."""
    rows = [(not (v.get("payload") or {}).get("breaking"), float(v.get("queued_at") or 0), k, v)
            for k, v in (state.get("messages") or {}).items() if v.get("status") == QUEUED and v.get("payload")]
    if not rows:
        return None
    rows.sort()
    return rows[0][2], rows[0][3]


def recover_in_flight() -> int:
    """Un ``sending`` que quedó de un envío cortado no se reenvía a ciegas."""
    count = 0

    def mutate(state):
        nonlocal count
        for v in (state.get("messages") or {}).values():
            if v.get("status") == SENDING:
                v["status"] = UNVERIFIED
                v["error"] = "envio_cortado"
                count += 1
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)
    return count


def mark_status(key: str, status: str) -> None:
    def mutate(state):
        state.setdefault("messages", {}).setdefault(key, {})["status"] = status
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)


def start_watermark(now: float | None = None) -> float:
    """Primer arranque: desde ahora, sin historial."""
    stamp = now or time.time()

    def mutate(state):
        if not state.get("watermark"):
            state["watermark"] = stamp
        return state

    return float(update_json(state_path(), mutate, {}, expected_type=dict)["watermark"])


def record(results: dict[str, dict], titles: dict[str, str], *, now: float | None = None) -> None:
    now = now or time.time()

    def mutate(state):
        messages = state.setdefault("messages", {})
        for key, result in results.items():
            entry = messages.get(key) or {}
            attempts = int(entry.get("attempts") or 0) + (1 if result["status"] in {FAILED, SENT, UNVERIFIED} else 0)
            status = result["status"]
            if status == FAILED and attempts >= max_attempts():
                status = DEAD
            if status == FAILED and entry.get("payload"):
                status = QUEUED  # vuelve a la cola espaciada
            if status not in {FAILED, QUEUED}:
                entry.pop("payload", None)
            messages[key] = {**entry, "status": status,
                             "attempts": attempts, "updated_at": int(now),
                             "title": titles.get(key, entry.get("title", ""))[:120],
                             **({"message_id": result["message_id"], "sent_at": int(now)} if result.get("message_id") else {}),
                             **({"error": result["error"][:200]} if result.get("error") else {})}
        # Lo anterior a la antigüedad máxima ya no se va a enviar: la marca de
        # agua avanza para no volver a recorrerlo.
        state["watermark"] = max(float(state.get("watermark") or 0), now - max_age_seconds())
        # Poda: lo resuelto hace más de 14 días.
        cutoff = now - 14 * 86400
        for key in [k for k, v in messages.items() if v.get("status") in _FINAL and float(v.get("updated_at") or 0) < cutoff]:
            messages.pop(key, None)
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)


def parse_results(lines: list[str], sent_keys: list[str]) -> dict[str, dict]:
    """Resultado por clave a partir del JSONL de ``wa.mjs send``.

    ``sending`` sin respuesta = ``unverified``; una clave que el proceso ni
    llegó a intentar queda pendiente (no se registra).
    """
    import json

    phases: dict[str, dict] = {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("key") in sent_keys:
            phases[row["key"]] = row
    out: dict[str, dict] = {}
    for key, row in phases.items():
        phase = row.get("phase")
        if phase == "sent" and row.get("message_id"):
            out[key] = {"status": SENT, "message_id": str(row["message_id"])}
        elif phase == "failed":
            out[key] = {"status": FAILED, "error": str(row.get("error") or "")}
        else:
            out[key] = {"status": UNVERIFIED, "error": str(row.get("error") or "sin_confirmacion")}
    return out
