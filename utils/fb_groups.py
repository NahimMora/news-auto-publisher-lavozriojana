"""Grupos de Facebook por localidad: qué nota va a qué grupo y qué ya salió.

Cada nota con vínculo riojano que salió en Facebook se comparte en los grupos
de la localidad que nombra su título o copete (``config/fb_groups.json``); sin
localidad del interior, en los de Capital. Sin IA: la localidad se reconoce
por palabras completas y el texto sale de la nota.

Estado (``data/fb_groups_state.json``): ``posts`` por clave
``<grupo>:<url de la nota>`` con ``pending`` → ``posted`` |
``pending_approval`` | ``failed`` (reintenta 1 vez) | ``unverified`` (nunca se
reintenta a ciegas) | ``expired``; ``blocked_until`` frena todo ante un aviso
de Facebook. Lo publica ``meta/fb_groups_worker.py``, de a una, con pausas.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import unicodedata
from datetime import datetime
from functools import lru_cache

from utils.editorial_router import detect_riojan_link
from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_time import now_ar
from utils.whatsapp_feed import facebook_items

logger = setup_logger("fb_groups", "fb_groups.log")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "fb_groups.json")
_TRUE = {"1", "true", "yes", "on", "si", "sí"}

PENDING, POSTED, APPROVAL, FAILED, UNVERIFIED, EXPIRED = (
    "pending", "posted", "pending_approval", "failed", "unverified", "expired")
_DONE = {POSTED, APPROVAL, UNVERIFIED, EXPIRED}


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return os.getenv("FB_GROUPS_ENABLED", "false").strip().lower() in _TRUE


def dry_run() -> bool:
    return os.getenv("FB_GROUPS_DRY_RUN", "true").strip().lower() in _TRUE


def state_path() -> str:
    return str(data_dir() / "fb_groups_state.json")


def load_state() -> dict:
    return load_json(state_path(), {}, expected_type=dict)


def active_hours() -> tuple[int, int]:
    raw = os.getenv("FB_GROUPS_HOURS", "9-21")
    try:
        start, end = (int(p) for p in raw.split("-", 1))
        return start, end
    except ValueError:
        return 9, 21


def in_active_hours(now: datetime | None = None) -> bool:
    start, end = active_hours()
    return start <= now_ar(now).hour < end


# ── Localidad ────────────────────────────────────────────────────────────
def _fold(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFD", str(text or "")) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", plain.lower())


@lru_cache(maxsize=1)
def config(path: str = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("localities") or {}


def localities_for(item: dict) -> list[str]:
    """Localidades que nombra la nota (las del interior primero; Capital si no
    hay otra). Lista vacía si la nota no tiene vínculo riojano."""
    text = _fold(" ".join(str(item.get(k) or "") for k in ("titulo", "titulo_original", "excerpt")))
    found: list[tuple[int, str]] = []
    for name, entry in config().items():
        positions = [m.start() for kw in entry.get("keywords") or [] for m in re.finditer(rf"\b{re.escape(_fold(kw))}\b", text)]
        if positions:
            found.append((min(positions), name))
    interior = [name for _, name in sorted(found) if name != "Capital"]
    if interior:
        return interior[:2]
    if found or detect_riojan_link(item)[0]:
        return ["Capital"] if "Capital" in config() else []
    return []


# ── Texto ────────────────────────────────────────────────────────────────
def compose(item: dict, locality: str) -> str:
    title = " ".join(str(item.get("titulo") or "").split())
    excerpt = " ".join(str(item.get("excerpt") or "").split())
    if len(excerpt) > 240:
        excerpt = excerpt[:240].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    # Link limpio: Facebook ya leyó su og:image al publicar la nota en la página
    # (con UTM sería otra URL y la tarjeta sale sin imagen).
    link = str(item["web_url"]).split("?", 1)[0]
    opener = random.choice([f"📍 {locality} | {title}", f"📰 {title}", f"🗞️ {title}"]) if locality != "Capital" else \
        random.choice([f"📰 {title}", f"🗞️ {title}", title])
    closer = random.choice(["Leé la nota completa 👉", "Más información 👉", "Toda la info 👉"])
    parts = [opener]
    if excerpt:
        parts.append(excerpt)
    parts.append(f"{closer} {link}")
    return "\n\n".join(parts)


# ── Planificación ────────────────────────────────────────────────────────
def _post_key(group_id: str, url: str) -> str:
    return f"{group_id}:{url}"


def plan(*, now: float | None = None) -> int:
    """Agrega a la cola las notas nuevas de Facebook con su grupo. Devuelve
    cuántas publicaciones se agregaron."""
    now = now or time.time()
    max_age = _num("FB_GROUPS_MAX_AGE_HOURS", 8) * 3600
    added = 0
    state = load_state()
    since = float(state.get("watermark") or now)
    entries = facebook_items(min(since, now - max_age))
    additions: dict[str, dict] = {}
    for entry in entries:
        item = entry.get("item") or {}
        url = str(item.get("web_url") or "")
        if not url.startswith("https://") or entry["posted_at"] <= since or now - entry["posted_at"] > max_age:
            continue
        for locality in localities_for(item):
            for group in config()[locality].get("groups") or []:
                key = _post_key(group["id"], entry["canonical_url"])
                if key in (state.get("posts") or {}) or key in additions:
                    continue
                additions[key] = {
                    "status": PENDING, "group_id": group["id"], "group_name": group["name"], "locality": locality,
                    "title": str(item.get("titulo") or "")[:160], "web_url": url, "note_posted_at": entry["posted_at"],
                    "text": compose(item, locality), "queued_at": int(now), "attempts": 0,
                }

    def mutate(current):
        current.setdefault("watermark", since)
        posts = current.setdefault("posts", {})
        for key, value in additions.items():
            posts.setdefault(key, value)
        current["watermark"] = max(float(current["watermark"]), now - max_age)
        return current

    update_json(state_path(), mutate, {}, expected_type=dict)
    added = len(additions)
    return added


def start_watermark(now: float | None = None) -> None:
    stamp = now or time.time()

    def mutate(state):
        if not state.get("watermark"):
            state["watermark"] = stamp
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)


def posted_today(state: dict, group_id: str, now: float | None = None) -> int:
    day = now_ar(datetime.fromtimestamp(now or time.time())).date()
    return sum(
        1 for p in (state.get("posts") or {}).values()
        if p.get("group_id") == group_id and p.get("status") in {POSTED, APPROVAL, UNVERIFIED}
        and p.get("posted_at") and now_ar(datetime.fromtimestamp(p["posted_at"])).date() == day
    )


def last_post_at(state: dict, group_id: str) -> float:
    return max((float(p.get("posted_at") or 0) for p in (state.get("posts") or {}).values()
                if p.get("group_id") == group_id and p.get("status") in {POSTED, APPROVAL, UNVERIFIED}), default=0.0)


def next_post(state: dict, *, now: float | None = None) -> tuple[str, dict] | None:
    """La próxima publicación a hacer: la nota más reciente primero (lo viejo
    pierde interés). Por grupo, una por ciclo: entre dos publicaciones en el
    mismo grupo pasan al menos ``FB_GROUPS_GROUP_GAP_MINUTES`` (50, lo que dura
    un ciclo). ``FB_GROUPS_MAX_PER_GROUP_DAY`` es sólo un techo de seguridad
    (12; 0 = sin techo)."""
    now = now or time.time()
    max_age = _num("FB_GROUPS_MAX_AGE_HOURS", 8) * 3600
    group_gap = _num("FB_GROUPS_GROUP_GAP_MINUTES", 50) * 60
    per_day = int(_num("FB_GROUPS_MAX_PER_GROUP_DAY", 12))
    candidates = []
    for key, post in (state.get("posts") or {}).items():
        if post.get("status") not in {PENDING, FAILED}:
            continue
        if post.get("status") == FAILED and int(post.get("attempts") or 0) >= 2:
            continue
        if now - float(post.get("note_posted_at") or 0) > max_age:
            continue
        if now - last_post_at(state, post["group_id"]) < group_gap:
            continue
        if per_day and posted_today(state, post["group_id"], now) >= per_day:
            continue
        candidates.append((float(post.get("note_posted_at") or 0), key, post))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1], candidates[0][2]


def expire_old(*, now: float | None = None) -> int:
    now = now or time.time()
    max_age = _num("FB_GROUPS_MAX_AGE_HOURS", 8) * 3600
    count = 0

    def mutate(state):
        nonlocal count
        for post in (state.get("posts") or {}).values():
            if post.get("status") in {PENDING, FAILED} and now - float(post.get("note_posted_at") or 0) > max_age:
                post["status"] = EXPIRED
                count += 1
        # Poda: lo resuelto hace más de 14 días.
        posts = state.get("posts") or {}
        for key in [k for k, p in posts.items() if p.get("status") in _DONE | {FAILED}
                    and now - float(p.get("queued_at") or 0) > 14 * 86400]:
            posts.pop(key, None)
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)
    return count


def mark(key: str, **fields) -> None:
    def mutate(state):
        post = (state.setdefault("posts", {})).setdefault(key, {})
        post.update(fields)
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)


def set_blocked(reason: str, hours: float | None = None) -> float:
    until = time.time() + (hours if hours is not None else _num("FB_GROUPS_BLOCK_HOURS", 48)) * 3600

    def mutate(state):
        state["blocked_until"] = until
        state["block_reason"] = reason[:200]
        return state

    update_json(state_path(), mutate, {}, expected_type=dict)
    logger.error("Grupos de Facebook frenados hasta %s: %s", time.strftime("%d/%m %H:%M", time.localtime(until)), reason)
    return until


def blocked(state: dict) -> bool:
    return float(state.get("blocked_until") or 0) > time.time()


def summary(state: dict) -> dict:
    counts: dict[str, int] = {}
    for post in (state.get("posts") or {}).values():
        counts[post.get("status", "?")] = counts.get(post.get("status", "?"), 0) + 1
    return counts


__all__ = ["JsonStateError"]
