"""Respuestas concretas a preguntas en publicaciones informativas.

Sólo se responde cuando la respuesta está escrita en la nota. Filtro previo
sin IA (preguntas reales, sin chistes ni insultos, nunca en policiales,
política ni espectáculos) y después una llamada corta a Gemini con el texto
de la nota. Toda cifra de la respuesta tiene que estar en la nota.

Modos (``COMMENT_REPLIES_MODE``): ``off`` (default), ``suggest`` (guarda la
respuesta propuesta para revisar con ``cli.py comment-replies``) y ``auto``
(publica, con tope diario). Estado en ``data/comment_replies.json``.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata

from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_time import today_ar

logger = setup_logger("comment_replies", "comment_replies.log")

STATE_PATH = str(data_dir() / "comment_replies.json")
EXCLUDED_SECTIONS = {"policiales", "politica", "espectaculos"}
# Sin "?" sólo cuentan arranques que casi siempre preguntan algo concreto
# ("qué"/"cómo" sueltos suelen ser exclamaciones: "Qué tristeza").
_QUESTION_START = ("cuando", "cuándo", "donde", "dónde", "cuanto", "cuánto", "a que hora", "a qué hora", "desde cuando", "hasta cuando", "se puede", "hay que")
_NOISE = ("jaja", "jeje", "jsjs", "xd", "lol")
_INSULTS = ("pelotud", "boludo", "idiota", "imbecil", "mierda", "carajo", "forro", "hdp", "puta", "chorro", "kuka", "kirchnerista de", "zurdo", "gorila")


def mode() -> str:
    value = str(os.getenv("COMMENT_REPLIES_MODE", "off")).strip().lower()
    return value if value in {"off", "suggest", "auto"} else "off"


def max_per_day() -> int:
    try:
        return int(os.getenv("COMMENT_REPLIES_MAX_PER_DAY", "15"))
    except ValueError:
        return 15


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def is_candidate(text: str) -> bool:
    """Pregunta real y concreta: con signo de pregunta o arranque
    interrogativo, al menos 4 palabras, sin risas ni insultos."""
    clean = re.sub(r"[^\w\s¿?áéíóúñü]", " ", text or "", flags=re.UNICODE).strip()
    folded = _fold(clean)
    words = folded.split()
    if len(words) < 4 or len(text) > 400:
        return False
    if any(n in folded for n in _NOISE) or any(i in folded for i in _INSULTS):
        return False
    if "@" in text:  # charla entre usuarios
        return False
    asks = "?" in text or folded.lstrip("¿ ").startswith(tuple(_fold(q) for q in _QUESTION_START))
    return asks


# ── Estado ───────────────────────────────────────────────────────────────
def load_state() -> dict:
    return load_json(STATE_PATH, {"comments": {}}, expected_type=dict)


def _save(comment_key: str, **fields) -> None:
    def mutate(state):
        entry = state.setdefault("comments", {}).setdefault(comment_key, {})
        entry.update(fields)
        entry["updated_at"] = int(time.time())
        cutoff = time.time() - 30 * 86400
        state["comments"] = {k: v for k, v in state["comments"].items() if int(v.get("updated_at") or 0) >= cutoff}
        return state

    update_json(STATE_PATH, mutate, {"comments": {}}, expected_type=dict)


def replies_today(state: dict) -> int:
    today = today_ar().isoformat()
    return sum(1 for v in (state.get("comments") or {}).values() if v.get("status") == "replied" and v.get("day") == today)


# ── Respuesta ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "Sos el community manager de La Voz Riojana, un medio de comunicación local de La Rioja (Argentina). "
    "Respondés preguntas de lectores en Instagram y Facebook usando EXCLUSIVAMENTE el texto de la nota que se te da.\n"
    "Reglas:\n"
    "- Respondé sólo si la respuesta está escrita de forma explícita en la nota. Si la nota no lo dice, no respondas.\n"
    "- No inventes datos, cifras, horarios, lugares, armas, personas ni hechos ajenos a la nota. No completes con conocimiento propio.\n"
    "- No respondas preguntas retóricas, chistes, opiniones, reclamos políticos, ni preguntas sobre víctimas, menores o causas judiciales.\n"
    "- Tono: cordial, claro y neutral, como un medio local que conoce a su comunidad. Español rioplatense. Sin emojis salvo uno al final como máximo.\n"
    "- Máximo 2 oraciones y 280 caracteres. No incluyas links.\n"
    'Devolvé SOLO un JSON: {"responder": true|false, "respuesta": "texto", "motivo": "breve"}.'
)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text or ""))


def validate_reply(reply: str, source: str) -> str | None:
    """Motivo de rechazo, o ``None`` si la respuesta pasa los controles."""
    if not reply or len(reply) > 300:
        return "length"
    if re.search(r"https?://|www\.", reply):
        return "link"
    invented = _numbers(reply) - _numbers(source)
    if invented:
        return "number_not_in_source"
    return None


def propose_reply(question: str, source_text: str, *, completion=None) -> dict:
    """``{"responder": bool, "respuesta": str, "motivo": str}`` validado."""
    if completion is None:
        from utils.ai_client import chat_completion as completion
    try:
        raw = completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"NOTA:\n{source_text[:5000]}\n\nPREGUNTA DEL LECTOR:\n{question}"},
            ],
            temperature=0.2,
            max_tokens=300,
            json_mode=True,
            stage="comment_reply",
        )
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 — sin respuesta válida no se responde
        logger.warning("Respuesta a comentario no generada: %s", type(exc).__name__)
        return {"responder": False, "respuesta": "", "motivo": "ai_error"}
    if not isinstance(data, dict) or not data.get("responder"):
        return {"responder": False, "respuesta": "", "motivo": str((data or {}).get("motivo") or "no_en_la_nota")[:120]}
    reply = re.sub(r"\s+", " ", str(data.get("respuesta") or "")).strip()
    problem = validate_reply(reply, source_text)
    if problem:
        return {"responder": False, "respuesta": reply, "motivo": f"rechazada:{problem}"}
    return {"responder": True, "respuesta": reply, "motivo": str(data.get("motivo") or "")[:120]}


def article_text(web_url: str) -> str:
    """Texto de la nota publicada (párrafos del artículo)."""
    if not web_url:
        return ""
    from bs4 import BeautifulSoup

    from utils.safe_http import safe_get

    try:
        response = safe_get(web_url, headers={"User-Agent": "LaVozRiojanaBot/1.0"}, timeout=30)
    except Exception:  # noqa: BLE001
        return ""
    if response.status_code != 200:
        return ""
    soup = BeautifulSoup(response.text, "html.parser")
    root = soup.find("article") or soup
    paragraphs = [p.get_text(" ", strip=True) for p in root.find_all("p")]
    return "\n".join(p for p in paragraphs if len(p) > 40)[:6000]


# ── Recorrido ────────────────────────────────────────────────────────────
def _web_url_for(record: dict) -> str:
    try:
        web = load_json(str(data_dir() / "noticias_web_publicadas.json"), [], expected_type=list)
    except JsonStateError:
        return ""
    for r in web:
        if isinstance(r, dict) and r.get("canonical_url") and r.get("canonical_url") == record.get("canonical_url"):
            return str(r.get("web_url") or "")
    return ""


def collect(*, lookback_hours: float = 72, now: float | None = None) -> list[dict]:
    """Comentarios candidatos de publicaciones informativas recientes de
    Instagram y Facebook que todavía no se evaluaron."""
    from meta import fb_client, ig_client

    now = now or time.time()
    state = load_state()
    seen = state.get("comments") or {}
    out: list[dict] = []
    try:
        ig_posted = load_json(str(data_dir() / "ig_posted.json"), {"posted": {}}, expected_type=dict).get("posted") or {}
        fb_posted = load_json(str(data_dir() / "fb_posted.json"), {"posted": {}}, expected_type=dict).get("posted") or {}
    except JsonStateError as exc:
        logger.warning("Estado ilegible para comentarios: %s", exc)
        return []
    username = ig_client.account_username()
    for platform, posted in (("instagram", ig_posted), ("facebook", fb_posted)):
        for record in posted.values():
            if not isinstance(record, dict) or not record.get("external_id"):
                continue
            if now - float(record.get("posted_at") or 0) > lookback_hours * 3600:
                continue
            section = _fold(str(record.get("seccion") or ""))
            if section in EXCLUDED_SECTIONS or str(record.get("source") or "").startswith("paparazzi"):
                continue
            post_id = str(record["external_id"])
            if platform == "instagram":
                comments = ig_client.media_comments(post_id)
                items = [
                    (c["id"], str(c.get("text") or ""), any(r.get("username") == username for r in ((c.get("replies") or {}).get("data") or [])), c.get("username") == username)
                    for c in comments
                ]
            else:
                comments = fb_client.post_comments(post_id)
                page_id = fb_client.PAGE_ID
                items = [
                    (c["id"], str(c.get("message") or ""), any(((r.get("from") or {}).get("id") == page_id) for r in ((c.get("comments") or {}).get("data") or [])), (c.get("from") or {}).get("id") == page_id)
                    for c in comments
                ]
            for comment_id, text, answered, own in items:
                key = f"{platform}:{comment_id}"
                if key in seen or answered or own:
                    continue
                if not is_candidate(text):
                    _save(key, status="skipped", reason="not_a_question", day=today_ar().isoformat())
                    continue
                out.append({"key": key, "platform": platform, "comment_id": comment_id, "text": text, "post_id": post_id, "record": record})
    return out


def process(candidates: list[dict], *, publish: bool, completion=None) -> dict:
    """Propone (y en modo ``auto`` publica) respuestas. Devuelve contadores."""
    from meta import fb_client, ig_client

    counts = {"evaluated": 0, "proposed": 0, "replied": 0, "declined": 0, "failed": 0}
    state = load_state()
    budget = max(0, max_per_day() - replies_today(state))
    per_post: dict[str, int] = {}
    for c in candidates:
        if publish and budget <= 0:
            break
        if per_post.get(c["post_id"], 0) >= 3:
            continue
        record = c["record"]
        source = "\n".join(filter(None, [str(record.get("titulo") or ""), str(record.get("texto_instagram") or ""), article_text(_web_url_for(record))]))
        counts["evaluated"] += 1
        result = propose_reply(c["text"], source, completion=completion)
        day = today_ar().isoformat()
        if not result["responder"]:
            counts["declined"] += 1
            _save(c["key"], status="declined", reason=result["motivo"], question=c["text"][:300], day=day)
            continue
        if not publish:
            counts["proposed"] += 1
            _save(c["key"], status="suggested", question=c["text"][:300], reply=result["respuesta"], post_id=c["post_id"], platform=c["platform"], comment_id=c["comment_id"], day=day)
            continue
        client = ig_client if c["platform"] == "instagram" else fb_client
        sent = client.reply_to_comment(c["comment_id"], result["respuesta"])
        if sent.ok:
            counts["replied"] += 1
            budget -= 1
            per_post[c["post_id"]] = per_post.get(c["post_id"], 0) + 1
            _save(c["key"], status="replied", question=c["text"][:300], reply=result["respuesta"], reply_id=sent.external_id, day=day)
        else:
            counts["failed"] += 1
            ambiguous = (sent.details or {}).get("publication_outcome") == "unknown"
            _save(c["key"], status="ambiguous" if ambiguous else "failed", reason=sent.error_type, question=c["text"][:300], reply=result["respuesta"], day=day)
    return counts


def approve(comment_key: str) -> str:
    """Publica una respuesta sugerida (``cli.py comment-replies approve``)."""
    from meta import fb_client, ig_client

    entry = (load_state().get("comments") or {}).get(comment_key)
    if not entry or entry.get("status") != "suggested":
        return "not_found"
    client = ig_client if entry.get("platform") == "instagram" else fb_client
    sent = client.reply_to_comment(str(entry.get("comment_id")), str(entry.get("reply")))
    if sent.ok:
        _save(comment_key, status="replied", reply_id=sent.external_id, day=today_ar().isoformat())
        return "replied"
    _save(comment_key, status="failed", reason=sent.error_type)
    return sent.error_type or "failed"


def reject(comment_key: str) -> str:
    entry = (load_state().get("comments") or {}).get(comment_key)
    if not entry or entry.get("status") != "suggested":
        return "not_found"
    _save(comment_key, status="rejected")
    return "rejected"
