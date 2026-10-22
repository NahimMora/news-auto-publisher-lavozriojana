"""Placas de servicio: cronograma de pagos de Hacienda y sismos sentidos (INPRES).

Cada placa sale como post (Instagram + Facebook, 1080×1350, ``ServiceCardV2``)
y como historia de servicio (``StoryV2``) con el mismo contenido. Formato fijo,
sin IA: todo el texto es el que publica la fuente oficial. La historia
automática del post ("Nueva publicación") se marca como cubierta para no
duplicarla. Estado en ``data/social_formats_state.json`` (``service_posts``).

- Pagos: el día anterior al pago (Hacienda lo publica a la tarde) o la mañana
  del pago, de 7 a 22.
- Sismos: sentidos en La Rioja, magnitud >= ``QUAKE_MIN_MAGNITUDE`` (3,0) y de
  las últimas ``QUAKE_MAX_AGE_HOURS`` (12).
"""
from __future__ import annotations

import io
import os
import tempfile
import time
from datetime import date, datetime, timedelta

from PIL import Image

from utils import service_data as sd
from utils.logging_setup import setup_logger
from utils.social_time import DIAS, now_ar
from utils.url_normalization import url_hash

logger = setup_logger("service_posts", "social_formats.log")

_TRUE = {"1", "true", "yes", "on", "si", "sí"}
HACIENDA_SOURCE = "Fuente: Ministerio de Hacienda de La Rioja"
INPRES_SOURCE = "Fuente: INPRES"


def _flag(name: str) -> bool:
    return str(os.getenv(name, "false")).strip().lower() in _TRUE


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _short_place(place: str) -> str:
    return place.removesuffix(", La Rioja").strip()


# ── Pagos ────────────────────────────────────────────────────────────────
def _pay_headline(pay_day: date, today: date) -> str:
    when = f"{DIAS[pay_day.weekday()]} {pay_day.day}/{pay_day.month}"
    if pay_day == today:
        return f"Hoy {when} cobran"
    if pay_day == today + timedelta(days=1):
        return f"Mañana {when} cobran"
    return f"El {when} cobran"


def payment_props(payment: dict, today: date) -> dict:
    pay_day = date.fromisoformat(payment["date"])
    return {
        "kind": "payments",
        "headline": _pay_headline(pay_day, today),
        "subhead": payment["concept"],
        "groups": payment["groups"],
        "sourceLabel": HACIENDA_SOURCE,
    }


def payment_caption(payment: dict, today: date) -> str:
    pay_day = date.fromisoformat(payment["date"])
    lines = [f"💰 CRONOGRAMA DE PAGOS · {payment['concept'].upper()} 👇", "", f"📅 {_pay_headline(pay_day, today)}:"]
    for group in payment["groups"]:
        lines.append("")
        if group["title"]:
            lines.append(f"🏦 {group['title']}")
        lines.extend(f"▪️ {item}" for item in group["items"])
    lines += ["", f"{HACIENDA_SOURCE}.", "", "#LaRioja #EstatalesRiojanos #LaVozRiojana"]
    return "\n".join(lines)


def due_payments(now: datetime | None = None, *, fetch=sd.fetch_payment_schedule) -> list[dict]:
    moment = now_ar(now)
    today = moment.date()
    if not 7 <= moment.hour < 22:
        return []
    out = []
    for payment in fetch():
        pay_day = date.fromisoformat(payment["date"])
        if pay_day == today + timedelta(days=1) or (pay_day == today and moment.hour < 12):
            out.append({
                "key": f"svcpost:pagos:{payment['date']}:{url_hash(payment['url'])[:12]}",
                "kind": "payments",
                "props": payment_props(payment, today),
                "caption": payment_caption(payment, today),
                "fb_link": payment["url"],
                "label": f"{payment['concept']} · {payment['date']}",
            })
    return out


# ── Sismos ───────────────────────────────────────────────────────────────
def quake_props(quake: dict) -> dict:
    moment = now_ar(datetime.fromisoformat(quake["at"]))
    riojan = [f for f in quake["felt"] if f["place"].endswith("La Rioja")]
    return {
        "kind": "quake",
        "headline": "Sismo sentido en La Rioja",
        "magnitude": _decimal(quake["magnitude"]),
        "timeLabel": f"{DIAS[moment.weekday()].capitalize()} {moment.day}/{moment.month} · {moment:%H:%M} h",
        "epicenter": quake["epicenter"],
        "depth": f"Profundidad: {quake['depth']}" if quake["depth"] else "",
        "felt": [{"place": _short_place(f["place"]), "intensity": f["intensity"]} for f in (riojan or quake["felt"])[:6]],
        "sourceLabel": INPRES_SOURCE,
    }


def quake_caption(quake: dict) -> str:
    props = quake_props(quake)
    lines = [
        "🌎 SISMO SENTIDO EN LA RIOJA 👇",
        "",
        f"📌 Magnitud {props['magnitude']} · {props['timeLabel']}",
        f"📍 Epicentro: {quake['epicenter']}",
    ]
    if quake["depth"]:
        lines.append(f"🔎 Profundidad: {quake['depth']}")
    lines += ["", "📳 Se sintió en:"]
    lines.extend(f"▪️ {_short_place(f['place'])} (intensidad {f['intensity']})" for f in quake["felt"][:8])
    lines += ["", "¿Lo sentiste? Contanos desde dónde 👇", "", f"{INPRES_SOURCE}.", "", "#LaRioja #Sismo #LaVozRiojana"]
    return "\n".join(lines)


def due_quakes(now: datetime | None = None, *, fetch=sd.fetch_felt_quakes) -> list[dict]:
    moment = now_ar(now)
    if not 7 <= moment.hour < 23:
        return []
    min_magnitude = _float("QUAKE_MIN_MAGNITUDE", 3.0)
    max_age = _float("QUAKE_MAX_AGE_HOURS", 12) * 3600
    out = []
    for quake in fetch():
        age = moment.timestamp() - datetime.fromisoformat(quake["at"]).timestamp()
        if quake["magnitude"] < min_magnitude or not 0 <= age <= max_age:
            continue
        out.append({
            "key": f"svcpost:sismo:{quake['id']}",
            "kind": "quake",
            "props": quake_props(quake),
            "caption": quake_caption(quake),
            "fb_link": "",
            "label": f"Sismo {quake['magnitude']} · {quake['id']}",
        })
    return out


def due_service_posts(now: datetime | None = None, *, done=lambda key: False) -> list[dict]:
    """Placas que corresponden ahora. Cada fuente falla por separado."""
    jobs: list[dict] = []
    for enabled, builder, label in (
        (_flag("PAYMENT_POSTS_ENABLED"), due_payments, "Cronograma de Hacienda"),
        (_flag("QUAKE_POSTS_ENABLED"), due_quakes, "Sismos de INPRES"),
    ):
        if not enabled:
            continue
        try:
            jobs.extend(job for job in builder(now) if not done(job["key"]))
        except (sd.ServiceDataError, ValueError, KeyError) as exc:
            logger.warning("%s no disponible: %s", label, exc)
    return jobs


# ── Render y publicación ─────────────────────────────────────────────────
def render_card(props: dict) -> bytes:
    """JPEG 1080×1350 de ``ServiceCardV2``. Lanza ``RemotionRenderError`` si falla."""
    from utils.remotion_renderer import render_still
    from utils.story_publisher import story_props

    png, _meta = render_still("ServiceCardV2", story_props(**props), timeout=240)
    with Image.open(io.BytesIO(png)) as image:
        out = io.BytesIO()
        image.convert("RGB").save(out, "JPEG", quality=92, optimize=True, subsampling=0)
        return out.getvalue()


def _record(key: str, **fields) -> None:
    from utils.social_formats import update_state

    def mutate(state):
        entry = state.setdefault("service_posts", {}).setdefault(key, {})
        entry.update({k: v for k, v in fields.items() if v is not None})
        entry["updated_at"] = int(time.time())
        cutoff = time.time() - 30 * 86400
        state["service_posts"] = {k: v for k, v in state["service_posts"].items() if int(v.get("updated_at") or 0) >= cutoff}
        return state

    update_state(mutate)


def already_done(key: str, state: dict | None = None) -> bool:
    from utils.social_formats import load_state

    state = state if state is not None else load_state()
    entry = (state.get("service_posts") or {}).get(key) or {}
    return bool(entry.get("ig_id") or entry.get("fb_id") or entry.get("ambiguous"))


def _classify(result) -> str:
    if result is None:
        return "failed"
    if result.ok:
        return "success"
    if result.error_type == "rate_limit":
        return "rate_limit"
    if (result.details or {}).get("publication_outcome") == "unknown":
        return "ambiguous"
    return result.error_type or "failed"


def publish_post(job: dict, card: bytes, *, instagram: bool, facebook: bool) -> dict:
    """Post de la placa en Instagram y/o Facebook, con evidencia por canal."""
    from meta import fb_client, ig_client
    from utils import r2_storage
    from utils.social_formats import load_state

    key = job["key"]
    entry = (load_state().get("service_posts") or {}).get(key) or {}
    outcome = {"ig": "skipped", "fb": "skipped", "ig_id": entry.get("ig_id", "")}
    if instagram and not entry.get("ig_id"):
        result = None
        if r2_storage.is_configured():
            handle, tmp = tempfile.mkstemp(suffix=".jpg", prefix="lvr_placa_")
            os.close(handle)
            r2_key = ""
            try:
                with open(tmp, "wb") as fh:
                    fh.write(card)
                public_url, r2_key = r2_storage.upload_temp(tmp, ttl_hint="placa")
                result = ig_client.post_single_image(public_url, job["caption"])
            except RuntimeError as exc:
                logger.warning("No se pudo subir la placa a R2: %s", exc)
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            status = _classify(result)
            if r2_key and status != "ambiguous":
                try:
                    r2_storage.delete(r2_key)
                except Exception:  # noqa: BLE001 — el temporal expira solo
                    logger.warning("No se pudo borrar la placa temporal de R2")
        outcome["ig"] = _classify(result)
        if outcome["ig"] == "success":
            outcome["ig_id"] = result.external_id
            _record(key, ig_id=result.external_id, ig_at=int(time.time()), kind=job["kind"], label=job["label"])
        elif outcome["ig"] == "ambiguous":
            _record(key, ambiguous="instagram", kind=job["kind"], label=job["label"])
    if facebook and not entry.get("fb_id") and outcome["ig"] != "ambiguous":
        message = job["caption"] + (f"\n\n{job['fb_link']}" if job.get("fb_link") else "")
        result = fb_client.post_photo(card, message)
        outcome["fb"] = _classify(result)
        if outcome["fb"] == "success":
            _record(key, fb_id=result.external_id, fb_at=int(time.time()), kind=job["kind"], label=job["label"])
        elif outcome["fb"] == "ambiguous":
            _record(key, ambiguous="facebook", kind=job["kind"], label=job["label"])
    logger.info("Placa %s → instagram=%s facebook=%s", key, outcome["ig"], outcome["fb"])
    return outcome


def publish_story(job: dict, post_ig_id: str, *, instagram: bool, facebook: bool) -> dict:
    """Historia de servicio de la placa. Cubre la historia automática del post."""
    from utils import story_publisher as sp

    if sp.already_done(f"svc:{job['key']}"):
        return {"ig": "skipped", "fb": "skipped"}
    jpeg = sp.render_story(job["props"])
    outcome = sp.publish_story(f"svc:{job['key']}", jpeg, instagram=instagram, facebook=facebook, meta={"kind": job["kind"], "label": job["label"]})
    if post_ig_id and "success" in outcome.values():
        story = (sp.load_state().get("posted") or {}).get(f"svc:{job['key']}") or {}
        # Sin "day": no suma al cupo diario de historias.
        sp._record(f"post:{post_ig_id}", ig_id=story.get("ig_id"), fb_id=story.get("fb_id"), covered_by=f"svc:{job['key']}")
    return outcome
