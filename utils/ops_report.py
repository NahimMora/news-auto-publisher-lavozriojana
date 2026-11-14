"""Reporte operativo cada 3 días (correo) y vigilante del supervisor.

El reporte junta lo que hoy está repartido en logs y archivos de estado:
salud del supervisor y de cada etapa, errores, publicaciones por canal,
crecimiento de seguidores, alcance, fuentes caídas, uso de Gemini, vencimiento
de tokens y espacio en disco. Gemini redacta un resumen corto a partir de esos
datos (una llamada); si falla, el correo sale igual con los números.

Sólo lectura: nunca modifica ``data/`` salvo su propio estado
(``data/ops_report_state.json``).
"""
from __future__ import annotations

import glob
import html
import json
import os
import re
import shutil
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta

from utils.file_manager import JsonStateError, load_json, update_json
from utils.heartbeat import heartbeat_snapshot
from utils.logging_setup import redact_secrets, setup_logger
from utils.paths import data_dir, logs_dir
from utils.social_time import AR_TZ, MESES, now_ar

logger = setup_logger("ops_report", "reports.log")

STATE_PATH = str(data_dir() / "ops_report_state.json")
_LOG_LINE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (\w+) \[([^\]]+)\] (.*)$")


def _safe(fn, default):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — una sección rota no tumba el reporte
        logger.warning("Sección del reporte no disponible (%s): %s", getattr(fn, "__name__", "?"), type(exc).__name__)
        return default


def _load(name: str, default, kind):
    try:
        return load_json(str(data_dir() / name), default, expected_type=kind)
    except JsonStateError:
        return default


# ── Logs ─────────────────────────────────────────────────────────────────
def scan_logs(since: datetime) -> dict:
    """Errores y avisos por archivo de log desde ``since`` (hora local)."""
    cutoff = since.strftime("%Y-%m-%d %H:%M:%S")
    errors: Counter = Counter()
    warnings: Counter = Counter()
    samples: dict[str, Counter] = {}
    cycles: Counter = Counter()
    stage_status: dict[str, Counter] = {}
    fallbacks = 0
    for path in glob.glob(os.path.join(str(logs_dir()), "*.log")):
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    match = _LOG_LINE.match(line)
                    if not match or match.group(1) < cutoff:
                        continue
                    level, message = match.group(2), match.group(4)
                    if level in {"ERROR", "CRITICAL"}:
                        errors[name] += 1
                        key = re.sub(r"\d+", "#", redact_secrets(message))[:140]
                        samples.setdefault(name, Counter())[key] += 1
                    elif level == "WARNING":
                        warnings[name] += 1
                    if name == "run_24x7.log":
                        cyc = re.match(r"Ciclo #\d+ status=(\w+)", message)
                        if cyc:
                            cycles[cyc.group(1)] += 1
                        st = re.match(r"Etapa (\S+) status=(\w+)", message)
                        if st:
                            stage_status.setdefault(st.group(1), Counter())[st.group(2)] += 1
                    if name == "remotion_renderer.log" and "fallback_reason=" in message and "fallback_reason=None" not in message:
                        fallbacks += 1
        except OSError:
            continue
    top = []
    for name, counter in samples.items():
        for text, count in counter.most_common(2):
            top.append({"log": name, "count": count, "message": text})
    top.sort(key=lambda t: -t["count"])
    return {
        "errors_by_log": dict(errors.most_common()),
        "warnings_total": sum(warnings.values()),
        "top_errors": top[:8],
        "cycles": dict(cycles),
        "stages": {k: dict(v) for k, v in stage_status.items()},
        "render_fallbacks": fallbacks,
    }


# ── Publicaciones, crecimiento y alcance ─────────────────────────────────
def publications(since_ts: float) -> dict:
    web = _load("noticias_web_publicadas.json", [], list)
    ig = (_load("ig_posted.json", {"posted": {}}, dict).get("posted") or {}).values()
    fb = (_load("fb_posted.json", {"posted": {}}, dict).get("posted") or {}).values()
    stories = (_load("stories_state.json", {"posted": {}}, dict).get("posted") or {}).values()
    formats = _load("social_formats_state.json", {}, dict)
    comments = (_load("comment_replies.json", {"comments": {}}, dict).get("comments") or {}).values()

    def count(items, field="posted_at"):
        return sum(1 for r in items if isinstance(r, dict) and float(r.get(field) or 0) >= since_ts)

    since_day = datetime.fromtimestamp(since_ts, AR_TZ).date().isoformat()
    updates = sum(1 for e in (formats.get("updates") or {}).values() for log in (e.get("log") or []) if float(log.get("at") or 0) >= since_ts)
    return {
        "web": sum(1 for r in web if isinstance(r, dict) and float(r.get("published_at_ts") or 0) >= since_ts),
        "instagram": count(ig),
        "facebook": count(fb),
        "stories_instagram": sum(1 for r in stories if float(r.get("ig_at") or 0) >= since_ts),
        "stories_facebook": sum(1 for r in stories if float(r.get("fb_at") or 0) >= since_ts),
        "stories_ambiguous": sum(1 for r in stories if r.get("ambiguous") and float(r.get("updated_at") or 0) >= since_ts),
        "morning_briefs": sum(1 for d, r in (formats.get("brief") or {}).items() if d >= since_day and r.get("ig_id")),
        "morning_briefs_failed": sum(1 for d, r in (formats.get("brief") or {}).items() if d >= since_day and not r.get("ig_id") and r.get("attempts")),
        "weekly_recaps": sum(1 for d, r in (formats.get("weekly") or {}).items() if d >= since_day and r.get("ig_id")),
        "updates": updates,
        "comment_replies": sum(1 for r in comments if r.get("status") == "replied" and float(r.get("updated_at") or 0) >= since_ts),
        "comment_suggestions_pending": [
            {"pregunta": r.get("question", "")[:160], "respuesta": r.get("reply", "")[:280]}
            for r in comments if r.get("status") == "suggested"
        ][:10],
    }


def growth(days: int) -> dict:
    kpi = (_load("kpi_daily.json", {"days": {}}, dict).get("days") or {})
    ordered = sorted(kpi.items())
    if not ordered:
        return {}
    today = now_ar().date()

    def at(day_offset: int) -> dict:
        target = (today - timedelta(days=day_offset)).isoformat()
        candidates = [v for d, v in ordered if d <= target]
        return (candidates[-1] if candidates else ordered[0][1]).get("followers") or {}

    now_f, prev_f, prev2_f = at(0), at(days), at(days * 2)
    out = {}
    for platform in ("instagram", "facebook"):
        if platform in now_f:
            out[platform] = {
                "followers": now_f[platform],
                "delta": now_f[platform] - prev_f.get(platform, now_f[platform]),
                "previous_delta": prev_f.get(platform, 0) - prev2_f.get(platform, prev_f.get(platform, 0)),
            }
    return out


def reach(since_ts: float) -> dict:
    media = (_load("ig_media_insights.json", {"media": {}}, dict).get("media") or {})
    posted = {str(r.get("external_id")): r for r in (_load("ig_posted.json", {"posted": {}}, dict).get("posted") or {}).values() if isinstance(r, dict)}
    period = [(mid, v) for mid, v in media.items() if float(v.get("posted_at") or 0) >= since_ts]
    by_section: Counter = Counter()
    for _mid, v in period:
        by_section[v.get("seccion") or "otras"] += float(v.get("reach") or 0)
    top = sorted(period, key=lambda kv: -float(kv[1].get("reach") or 0))[:3]
    return {
        "posts": len(period),
        "reach": int(sum(float(v.get("reach") or 0) for _, v in period)),
        "interactions": int(sum(float(v.get("interactions") or 0) for _, v in period)),
        "reach_by_section": {k: int(v) for k, v in by_section.most_common(6)},
        "top": [{"titulo": str((posted.get(mid) or {}).get("titulo") or "(sin título)")[:110], "seccion": v.get("seccion"), "alcance": int(v.get("reach") or 0)} for mid, v in top],
    }


# ── Fuentes, IA, tokens y disco ──────────────────────────────────────────
def sources(since: datetime) -> dict:
    path = str(data_dir() / "derived" / "editorial_context.sqlite3")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        rows = conn.execute(
            "select source_id, sum(requests), sum(items_new), sum(parse_failures), sum(timeouts), max(last_success) from source_metrics where date >= ? group by source_id",
            (since.date().isoformat(),),
        ).fetchall()
        ai = conn.execute(
            "select count(*), sum(success), sum(coalesce(tokens_in,0)), sum(coalesce(tokens_out,0)) from ai_call_metrics where created_at >= ?",
            (since.astimezone(AR_TZ).isoformat(),),
        ).fetchone()
    finally:
        conn.close()
    failing = [r[0] for r in rows if (r[1] or 0) > 0 and (not r[5] or (r[3] or 0) >= (r[1] or 0) * 0.8)]
    return {
        "official_total": len(rows),
        "official_failing": failing,
        "ai_calls": int(ai[0] or 0) if ai else 0,
        "ai_failed": int((ai[0] or 0) - (ai[1] or 0)) if ai else 0,
        "ai_tokens": int((ai[2] or 0) + (ai[3] or 0)) if ai else 0,
    }


def service_sources() -> dict:
    from utils import service_data as sd

    status = {}
    for name, fn in (("SMN clima", sd.fetch_weather), ("SMN alertas", sd.fetch_alerts), ("Dólar", sd.fetch_dollar)):
        try:
            value = fn()
            status[name] = "ok" if value else "sin datos"
        except sd.ServiceDataError as exc:
            status[name] = f"falla ({exc})"[:80]
    try:
        status["Feriados"] = "ok" if sd.upcoming_holidays(now_ar().date()) else "sin datos"
    except sd.ServiceDataError as exc:
        status["Feriados"] = f"falla ({exc})"[:80]
    return status


def token_expiry() -> dict:
    """Días hasta que vencen los tokens de Meta (``debug_token``, sólo lectura)."""
    import requests

    graph = os.getenv("META_GRAPH_API", "https://graph.facebook.com/v19.0").rstrip("/")
    out = {}
    for label, env in (("Instagram", "IG_ACCESS_TOKEN"), ("Facebook", "FB_PAGE_ACCESS_TOKEN")):
        token = os.getenv(env, "")
        if not token or token == "PENDIENTE":
            out[label] = "sin configurar"
            continue
        try:
            data = requests.get(f"{graph}/debug_token", params={"input_token": token, "access_token": token}, timeout=20).json().get("data") or {}
        except Exception:  # noqa: BLE001
            out[label] = "no se pudo consultar"
            continue
        if not data.get("is_valid"):
            out[label] = "INVÁLIDO"
        elif data.get("expires_at"):
            out[label] = f"{int((float(data['expires_at']) - time.time()) // 86400)} días"
        else:
            out[label] = "no vence"
    return out


def disk() -> dict:
    usage = shutil.disk_usage(str(data_dir()))
    return {"free_gb": round(usage.free / 1e9, 1), "used_pct": round(usage.used / usage.total * 100)}


def supervisor() -> dict:
    snap = heartbeat_snapshot()
    data = snap.get("data") or {}
    stages = data.get("stages") or []
    return {
        "status": data.get("supervisor_status") or snap.get("status"),
        "stale": bool(snap.get("stale")),
        "age_minutes": round((snap.get("age_seconds") or 0) / 60),
        "cycle": data.get("cycle_number"),
        "last_cycle": {s.get("stage"): s.get("status") for s in stages},
    }


def collect(days: int = 3) -> dict:
    moment = now_ar()
    since = moment - timedelta(days=days)
    since_local = since.astimezone().replace(tzinfo=None)
    since_ts = since.timestamp()
    return {
        "period": {"from": since.strftime("%Y-%m-%d %H:%M"), "to": moment.strftime("%Y-%m-%d %H:%M"), "days": days},
        "supervisor": _safe(supervisor, {}),
        "logs": _safe(lambda: scan_logs(since_local), {}),
        "publications": _safe(lambda: publications(since_ts), {}),
        "growth": _safe(lambda: growth(days), {}),
        "reach": _safe(lambda: reach(since_ts), {}),
        "sources": _safe(lambda: sources(since), {}),
        "service_sources": _safe(service_sources, {}),
        "tokens": _safe(token_expiry, {}),
        "disk": _safe(disk, {}),
    }


# ── Diagnóstico y redacción ──────────────────────────────────────────────
def assess(facts: dict) -> tuple[str, list[str]]:
    """(``ok``/``atención``/``crítico``, avisos concretos) sin IA."""
    notes: list[str] = []
    level = "ok"
    sup = facts.get("supervisor") or {}
    if sup.get("stale") or sup.get("status") in {"stopped", "missing", "corrupt"}:
        notes.append(f"El supervisor no da señales hace {sup.get('age_minutes')} minutos (estado: {sup.get('status')}).")
        level = "crítico"
    for label, value in (facts.get("tokens") or {}).items():
        if value == "INVÁLIDO":
            notes.append(f"El token de {label} es inválido: no se puede publicar.")
            level = "crítico"
        elif value.endswith("días") and int(value.split()[0]) < 15:
            notes.append(f"El token de {label} vence en {value}.")
            level = "atención" if level == "ok" else level
    pubs = facts.get("publications") or {}
    if pubs.get("instagram", 1) == 0 or pubs.get("web", 1) == 0:
        notes.append("Hubo 0 publicaciones en Instagram o en la web en el período.")
        level = "crítico"
    cycles = (facts.get("logs") or {}).get("cycles") or {}
    total = sum(cycles.values())
    if total and cycles.get("failed", 0) / total > 0.2:
        notes.append(f"{cycles['failed']} de {total} ciclos terminaron con falla.")
        level = "atención" if level == "ok" else level
    failing = (facts.get("sources") or {}).get("official_failing") or []
    if failing:
        notes.append("Fuentes oficiales sin respuesta útil: " + ", ".join(failing) + ".")
        level = "atención" if level == "ok" else level
    for name, value in (facts.get("service_sources") or {}).items():
        if value != "ok":
            notes.append(f"Fuente de servicio {name}: {value}.")
            level = "atención" if level == "ok" else level
    if (facts.get("disk") or {}).get("free_gb", 99) < 10:
        notes.append(f"Queda poco espacio en disco ({facts['disk']['free_gb']} GB).")
        level = "atención" if level == "ok" else level
    if (facts.get("logs") or {}).get("render_fallbacks", 0) > 5:
        notes.append(f"{facts['logs']['render_fallbacks']} imágenes usaron el diseño de respaldo (Remotion no respondió).")
        level = "atención" if level == "ok" else level
    if pubs.get("stories_ambiguous"):
        notes.append(f"{pubs['stories_ambiguous']} historias quedaron con resultado dudoso (revisar en las redes).")
    return level, notes


SUMMARY_PROMPT = (
    "Sos el asistente técnico de La Voz Riojana. Escribí para el dueño del medio (no técnico) un resumen ejecutivo del "
    "funcionamiento del sistema de publicación automática en los últimos días, en español rioplatense, usando SÓLO los datos "
    "JSON que se te dan. No inventes cifras ni causas. Estructura: 1) una oración con el estado general; 2) qué falló o "
    "necesita atención y qué conviene hacer (si no hay nada, decilo); 3) crecimiento y qué contenido funcionó mejor. "
    "Máximo 170 palabras, sin títulos ni viñetas, en 2 o 3 párrafos cortos."
)


def ai_summary(facts: dict, level: str, notes: list[str], *, completion=None) -> str:
    if completion is None:
        from utils.ai_client import chat_completion as completion
    payload = {**facts, "estado_calculado": level, "avisos": notes}
    payload.get("publications", {}).pop("comment_suggestions_pending", None)
    try:
        text = completion(
            messages=[{"role": "system", "content": SUMMARY_PROMPT}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)[:12000]}],
            temperature=0.3,
            max_tokens=600,
            stage="ops_report",
        )
        return text.strip()
    except Exception as exc:  # noqa: BLE001 — el reporte sale igual sin resumen de IA
        logger.warning("Resumen de IA no disponible: %s", type(exc).__name__)
        return ""


def _fmt(n) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)


def _signed(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"+{_fmt(n)}" if n > 0 else _fmt(n)


def subject(facts: dict, level: str) -> str:
    end = now_ar()
    start = end - timedelta(days=facts["period"]["days"])
    rng = f"{start.day}–{end.day} {MESES[end.month - 1][:3]}" if start.month == end.month else f"{start.day} {MESES[start.month - 1][:3]}–{end.day} {MESES[end.month - 1][:3]}"
    ig = (facts.get("growth") or {}).get("instagram") or {}
    mark = {"ok": "✅ Todo bien", "atención": "⚠ Atención", "crítico": "🔴 Crítico"}[level]
    tail = f" · Instagram {_signed(ig.get('delta'))} seguidores" if ig else ""
    return f"LVR · Reporte {rng} · {mark}{tail}"


def render(facts: dict, level: str, notes: list[str], summary: str) -> tuple[str, str]:
    """(html, texto) del correo."""
    pubs = facts.get("publications") or {}
    grow = facts.get("growth") or {}
    rch = facts.get("reach") or {}
    logs = facts.get("logs") or {}
    src = facts.get("sources") or {}
    color = {"ok": "#1d7a46", "atención": "#a86207", "crítico": "#b3261e"}[level]
    e = html.escape

    def row(label, value):
        return f'<tr><td style="padding:6px 10px;border-bottom:1px solid #e5e5e5;color:#555">{e(str(label))}</td><td style="padding:6px 10px;border-bottom:1px solid #e5e5e5;text-align:right;font-weight:600">{e(str(value))}</td></tr>'

    def table(rows):
        return '<table style="border-collapse:collapse;width:100%;font-size:14px">' + "".join(row(a, b) for a, b in rows) + "</table>"

    def h(text):
        return f'<h3 style="font:700 15px Arial,sans-serif;margin:22px 0 8px;color:#111">{e(text)}</h3>'

    growth_rows = [(f"Seguidores {p.capitalize()}", f"{_fmt(v['followers'])} ({_signed(v['delta'])}; período anterior {_signed(v['previous_delta'])})") for p, v in grow.items()]
    pub_rows = [
        ("Notas en la web", pubs.get("web")), ("Posts en Instagram", pubs.get("instagram")), ("Posts en Facebook", pubs.get("facebook")),
        ("Historias Instagram / Facebook", f"{pubs.get('stories_instagram', 0)} / {pubs.get('stories_facebook', 0)}"),
        ("Carruseles de la mañana", pubs.get("morning_briefs")), ("Resúmenes semanales", pubs.get("weekly_recaps")),
        ("Actualizaciones de noticias", pubs.get("updates")), ("Respuestas a comentarios", pubs.get("comment_replies")),
    ]
    reach_rows = [("Alcance total en Instagram", _fmt(rch.get("reach"))), ("Interacciones", _fmt(rch.get("interactions")))]
    reach_rows += [(f"Alcance · {k}", _fmt(v)) for k, v in (rch.get("reach_by_section") or {}).items()]
    cycles = logs.get("cycles") or {}
    health_rows = [
        ("Supervisor", f"{(facts.get('supervisor') or {}).get('status')} · ciclo {(facts.get('supervisor') or {}).get('cycle')}"),
        ("Ciclos (ok / degradados / fallidos)", f"{cycles.get('success', 0)} / {cycles.get('degraded', 0)} / {cycles.get('failed', 0)}"),
        ("Errores registrados", sum((logs.get("errors_by_log") or {}).values())),
        ("Imágenes con diseño de respaldo", logs.get("render_fallbacks", 0)),
        ("Llamadas a Gemini (fallidas)", f"{src.get('ai_calls', 0)} ({src.get('ai_failed', 0)})"),
        ("Disco libre", f"{(facts.get('disk') or {}).get('free_gb')} GB"),
    ]
    health_rows += [(f"Token {k}", v) for k, v in (facts.get("tokens") or {}).items()]
    health_rows += [(f"Fuente {k}", v) for k, v in (facts.get("service_sources") or {}).items()]

    notes_html = "".join(f'<li style="margin:4px 0">{e(n)}</li>' for n in notes) or "<li>Sin avisos.</li>"
    top_html = "".join(f'<li style="margin:4px 0">{e(t["titulo"])} · <b>{_fmt(t["alcance"])}</b></li>' for t in rch.get("top") or [])
    err_html = "".join(f'<li style="margin:4px 0"><code>{e(t["log"])}</code> ×{t["count"]}: {e(t["message"])}</li>' for t in logs.get("top_errors") or []) or "<li>Sin errores.</li>"
    sugg = pubs.get("comment_suggestions_pending") or []
    sugg_html = "".join(f'<li style="margin:6px 0">«{e(s["pregunta"])}»<br><span style="color:#555">→ {e(s["respuesta"])}</span></li>' for s in sugg)
    body = f"""<div style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;color:#111">
<div style="border-left:6px solid {color};padding:10px 16px;background:#fafafa"><div style="font:700 13px Arial;color:{color};text-transform:uppercase;letter-spacing:.06em">Estado: {e(level)}</div>
<div style="font-size:13px;color:#555">{e(facts['period']['from'])} → {e(facts['period']['to'])} (hora argentina)</div></div>
{('<div style="font-size:15px;line-height:1.55;margin:16px 0;white-space:pre-line">' + e(summary) + '</div>') if summary else ''}
{h('Avisos')}<ul style="font-size:14px;padding-left:20px">{notes_html}</ul>
{h('Crecimiento')}{table(growth_rows)}
{h('Publicaciones')}{table(pub_rows)}
{h('Alcance')}{table(reach_rows)}
{('<p style="font-size:14px;margin:10px 0 4px">Lo más visto:</p><ul style="font-size:14px;padding-left:20px">' + top_html + '</ul>') if top_html else ''}
{h('Salud del sistema')}{table(health_rows)}
{h('Errores más repetidos')}<ul style="font-size:13px;padding-left:20px">{err_html}</ul>
{(h('Respuestas a comentarios para revisar') + '<ul style="font-size:14px;padding-left:20px">' + sugg_html + '</ul><p style="font-size:13px;color:#555">Se aprueban con <code>python cli.py comment-replies approve</code>.</p>') if sugg_html else ''}
<p style="font-size:12px;color:#888;margin-top:26px">Reporte automático de La Voz Riojana. Próximo envío en 3 días.</p></div>"""
    lines = [f"Estado: {level}", f"{facts['period']['from']} → {facts['period']['to']}", ""]
    if summary:
        lines += [summary, ""]
    lines += ["Avisos:"] + [f"- {n}" for n in notes or ["Sin avisos."]] + [""]
    lines += [f"{a}: {b}" for a, b in growth_rows + pub_rows + reach_rows + health_rows]
    return body, "\n".join(lines)


def build(days: int = 3, *, use_ai: bool = True) -> dict:
    facts = collect(days)
    level, notes = assess(facts)
    summary = ai_summary(facts, level, notes) if use_ai else ""
    html_body, text_body = render(facts, level, notes, summary)
    return {"subject": subject(facts, level), "html": html_body, "text": text_body, "level": level, "facts": facts}


def mark_sent(kind: str) -> None:
    def mutate(state):
        state[kind] = int(time.time())
        return state

    update_json(STATE_PATH, mutate, {}, expected_type=dict)


def last_sent(kind: str) -> float:
    try:
        return float(load_json(STATE_PATH, {}, expected_type=dict).get(kind) or 0)
    except JsonStateError:
        return 0.0


# ── Vigilante ────────────────────────────────────────────────────────────
def watchdog_check(stale_minutes: int = 120) -> tuple[str, str] | None:
    """Correo a mandar (asunto, texto) si el supervisor dejó de funcionar o
    volvió; ``None`` si no hay novedad. Un aviso por incidente."""
    snap = heartbeat_snapshot()
    data = snap.get("data") or {}
    age = float(snap.get("age_seconds") or 0)
    down = snap.get("status") in {"missing", "corrupt"} or data.get("supervisor_status") == "stopped" or age > stale_minutes * 60
    try:
        state = load_json(STATE_PATH, {}, expected_type=dict)
    except JsonStateError:
        state = {}
    incident = state.get("watchdog_incident")
    if down and not incident:
        update_json(STATE_PATH, lambda s: {**s, "watchdog_incident": int(time.time())}, {}, expected_type=dict)
        minutes = round(age / 60) if age else None
        return (
            "🔴 LVR · El sistema dejó de publicar",
            f"El supervisor 24/7 no da señales desde hace {minutes} minutos (estado: {data.get('supervisor_status') or snap.get('status')}).\n"
            "Revisá que la PC esté encendida y con internet. La tarea programada LaVozRiojana-24x7 lo vuelve a levantar sola cada 5 minutos; "
            "si en 15 minutos no vuelve, reiniciá la PC.",
        )
    if not down and incident:
        update_json(STATE_PATH, lambda s: {k: v for k, v in s.items() if k != "watchdog_incident"}, {}, expected_type=dict)
        lost = round((time.time() - float(incident)) / 60)
        return ("✅ LVR · El sistema volvió a funcionar", f"El supervisor volvió a publicar (ciclo {data.get('cycle_number')}). Estuvo sin señales unos {lost} minutos o más.")
    return None
