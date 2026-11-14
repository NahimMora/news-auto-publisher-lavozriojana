"""Placas de servicio: cronograma de pagos de Hacienda y sismos de INPRES.

Formato fijo, sin IA (``ServicePieces.tsx``): etiqueta de estado (HOY,
MAÑANA, ACTUALIZADO, CANCELADO), un dato protagonista, pie "Fuente ·
actualizado HH:MM" y como máximo ``MAX_WORDS`` palabras. Todo el texto es el
que publica la fuente oficial. Cada placa sale como post (``ServiceCardV2``,
1080×1350) y/o historia (``StoryV2``); la historia automática del post
("Nueva publicación") queda cubierta por la de servicio. Estado en
``data/social_formats_state.json`` (``service_posts``).

- Pagos: historia desde las 7 de cada día de pago; post en Instagram sólo el
  primer día del cronograma (mismo concepto) y en Facebook todos los días de
  pago. La lista de organismos va en el texto del post.
- Sismos: epicentro en La Rioja y magnitud >= ``QUAKE_MIN_MAGNITUDE`` (4,0),
  a cualquier hora, de las últimas ``QUAKE_MAX_AGE_HOURS`` (12): post en
  Instagram y Facebook más historia. Si era automático y INPRES lo revisa
  con otro valor, sale una historia ACTUALIZADO.
"""
from __future__ import annotations

import io
import os
import tempfile
import time
from datetime import date, datetime

from PIL import Image

from utils import service_data as sd
from utils.logging_setup import setup_logger
from utils.social_time import DIAS, now_ar
from utils.url_normalization import url_hash

logger = setup_logger("service_posts", "social_formats.log")

_TRUE = {"1", "true", "yes", "on", "si", "sí"}
HACIENDA_SOURCE = "Fuente: Ministerio de Hacienda de La Rioja"
INPRES_SOURCE = "Fuente: INPRES"
MAX_WORDS = 25
MAX_LINES = 3  # renglones de apoyo que dibuja la placa
# Mismas etiquetas que dibuja la placa (cuentan para el máximo de palabras).
STATUS_LABELS = {"hoy": "Hoy", "manana": "Mañana", "actualizado": "Actualizado", "cancelado": "Cancelado"}
# Una revisión de INPRES puede mover unos segundos el id del sismo.
QUAKE_MATCH_SECONDS = 180


def _flag(name: str) -> bool:
    return str(os.getenv(name, "false")).strip().lower() in _TRUE


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _day(day: date) -> str:
    return f"{DIAS[day.weekday()]} {day.day}/{day.month}"


def _words(text: str) -> int:
    return sum(1 for token in str(text or "").split() if any(c.isalnum() for c in token))


def plate_words(props: dict) -> int:
    """Palabras visibles de la placa, sin contar la marca ni el pie."""
    parts = [STATUS_LABELS.get(props.get("status", ""), ""), props.get("kicker", ""), props.get("hero", ""), props.get("heroLabel", "")]
    return sum(_words(p) for p in parts + list(props.get("lines") or []))


def plate_props(*, kind: str, status: str, kicker: str, hero: str, hero_label: str, lines: list[tuple[str, bool]], source: str, now: datetime) -> dict:
    """Props de la placa. ``lines`` va en orden de importancia como (texto,
    obligatorio): si sobran palabras se quitan desde el final las opcionales;
    si aun así no entra, ``ValueError`` (la placa no sale)."""
    rows = [(text, required) for text, required in lines if text]
    props = {
        "kind": kind,
        "status": status,
        "kicker": kicker,
        "hero": hero,
        "heroLabel": hero_label,
        "lines": [text for text, _ in rows],
        "footer": f"{source} · actualizado {now_ar(now):%H:%M}",
    }
    while plate_words(props) > MAX_WORDS or len(rows) > MAX_LINES:
        optional = [i for i, (_, required) in enumerate(rows) if not required]
        if not optional:
            raise ValueError(f"placa_demasiado_larga:{plate_words(props)}:{len(rows)}")
        rows.pop(optional[-1])
        props["lines"] = [text for text, _ in rows]
    return props


# ── Pagos ────────────────────────────────────────────────────────────────
def _next_payment(payment: dict, schedule: list[dict]) -> date | None:
    pay_day = date.fromisoformat(payment["date"])
    later = sorted({date.fromisoformat(p["date"]) for p in schedule if date.fromisoformat(p["date"]) > pay_day})
    return later[0] if later else None


def payment_props(payment: dict, schedule: list[dict], now: datetime) -> dict:
    pay_day = date.fromisoformat(payment["date"])
    nxt = _next_payment(payment, schedule)
    return plate_props(
        kind="payments",
        status="hoy" if pay_day == now_ar(now).date() else "manana",
        kicker="Pagos",
        hero="Cobran estatales",
        hero_label=_day(pay_day).capitalize(),
        lines=[(payment["concept"], True), (f"Próximo pago: {_day(nxt)}" if nxt else "", False)],
        source="Fuente: Hacienda La Rioja",
        now=now,
    )


def payment_caption(payment: dict, schedule: list[dict], today: date) -> str:
    pay_day = date.fromisoformat(payment["date"])
    when = "Hoy" if pay_day == today else "El"
    lines = [f"💰 COBRAN ESTATALES · {payment['concept'].upper()} 👇", "", f"📅 {when} {_day(pay_day)} cobran:"]
    for group in payment["groups"]:
        lines.append("")
        if group["title"]:
            lines.append(f"🏦 {group['title']}")
        lines.extend(f"▪️ {item}" for item in group["items"])
    nxt = _next_payment(payment, schedule)
    if nxt:
        lines += ["", f"⏭️ Próximo pago anunciado: {_day(nxt)}."]
    lines += ["", f"{HACIENDA_SOURCE}.", "", "#LaRioja #EstatalesRiojanos #LaVozRiojana"]
    return "\n".join(lines)


def due_payments(now: datetime | None = None, *, fetch=sd.fetch_payment_schedule, state: dict | None = None) -> list[dict]:
    """Placas del día de pago, desde las 7. El post de Instagram sale sólo el
    primer día del cronograma (el pago más temprano del mismo concepto)."""
    moment = now_ar(now)
    today = moment.date()
    if not 7 <= moment.hour < 22:
        return []
    schedule = fetch()
    out = []
    for payment in schedule:
        if date.fromisoformat(payment["date"]) != today:
            continue
        first_day = min(p["date"] for p in schedule if p["concept"] == payment["concept"]) == payment["date"]
        out.append({
            "key": f"svcpost:pagos:{payment['date']}:{url_hash(payment['url'])[:12]}",
            "kind": "payments",
            "props": payment_props(payment, schedule, moment),
            "caption": payment_caption(payment, schedule, today),
            "fb_link": payment["url"],
            "label": f"{payment['concept']} · {payment['date']}",
            "post_ig": first_day,
            "post_fb": True,
            "story": True,
        })
    return out


# ── Sismos ───────────────────────────────────────────────────────────────
def _quake_time(quake: dict, now: datetime) -> str:
    moment = now_ar(datetime.fromisoformat(quake["at"]))
    prefix = "" if moment.date() == now_ar(now).date() else f"{_day(moment.date()).capitalize()} · "
    return f"{prefix}{moment:%H:%M} h"


def _is_automatic(quake: dict, detail: dict) -> bool:
    # El color del listado manda: revisado (negro) o sentido (rojo) ya no es
    # automático aunque el detalle conserve el texto viejo.
    if quake["status"] in ("revised", "felt"):
        return False
    return quake["status"] == "automatic" or bool(detail.get("automatic"))


def quake_props(quake: dict, detail: dict, now: datetime, *, previous: dict | None = None) -> dict:
    """Placa del sismo. Con ``previous`` (lo publicado), es la ACTUALIZADO."""
    place = (detail.get("places") or [""])[0]
    if not place:
        raise ValueError("sismo_sin_localidad")
    lines: list[tuple[str, bool]] = [(place, True)]
    if previous:
        changed_magnitude = previous.get("magnitude") != _decimal(quake["magnitude"])
        before = f"magnitud {previous.get('magnitude')}" if changed_magnitude else previous.get("place", "")
        lines.append((f"Antes informado: {before}", True))
    if _is_automatic(quake, detail):
        lines.append(("Dato automático", True))
    lines.append((f"{_quake_time(quake, now)} · {quake['depth_km']} km de profundidad", False))
    return plate_props(
        kind="quake",
        status="actualizado" if previous else "hoy",
        kicker="Sismo en La Rioja",
        hero=_decimal(quake["magnitude"]),
        hero_label="Magnitud",
        lines=lines,
        source=INPRES_SOURCE,
        now=now,
    )


def quake_caption(quake: dict, detail: dict) -> str:
    moment = now_ar(datetime.fromisoformat(quake["at"]))
    places = detail.get("places") or []
    lines = [
        f"🌎 SISMO EN LA RIOJA · MAGNITUD {_decimal(quake['magnitude'])} 👇",
        "",
        f"📍 Epicentro: {places[0]}",
        f"🕐 {_day(moment.date()).capitalize()} · {moment:%H:%M} h",
        f"🔎 Profundidad: {quake['depth_km']} km",
    ]
    if len(places) > 1:
        lines.append(f"🧭 También: {'; '.join(places[1:3])}")
    if _is_automatic(quake, detail):
        lines += ["", "⚠️ Dato automático de INPRES, sujeto a revisión."]
    lines += ["", "¿Lo sentiste? ¿Desde dónde? 👇", "", f"{INPRES_SOURCE}.", "", "#LaRioja #Sismo #LaVozRiojana"]
    return "\n".join(lines)


def _snapshot(quake: dict, detail: dict) -> dict:
    return {
        "id": quake["id"],
        "at": quake["at"],
        "magnitude": _decimal(quake["magnitude"]),
        "place": (detail.get("places") or [""])[0],
        "status": "automatic" if _is_automatic(quake, detail) else quake["status"],
    }


def _published_quake(quake: dict, entries: dict) -> tuple[str, dict] | None:
    """Placa ya publicada (o intentada) del mismo sismo: mismo id o, tras una
    revisión que lo movió, la misma hora con ``QUAKE_MATCH_SECONDS`` de margen."""
    at = datetime.fromisoformat(quake["at"]).timestamp()
    for key, entry in entries.items():
        snap = entry.get("snapshot") or {}
        if entry.get("kind") != "quake" or not snap.get("at"):
            continue
        if snap.get("id") == quake["id"] or abs(datetime.fromisoformat(snap["at"]).timestamp() - at) <= QUAKE_MATCH_SECONDS:
            return key, snap
    return None


def due_quakes(now: datetime | None = None, *, fetch=sd.fetch_quakes, detail=sd.fetch_quake_detail, state: dict | None = None) -> list[dict]:
    moment = now_ar(now)
    min_magnitude = _float("QUAKE_MIN_MAGNITUDE", 4.0)
    max_age = _float("QUAKE_MAX_AGE_HOURS", 12) * 3600
    entries = (state or {}).get("service_posts") or {}
    out = []
    for quake in fetch():
        if sd._fold(quake["province"]) != "la rioja":
            continue
        age = moment.timestamp() - datetime.fromisoformat(quake["at"]).timestamp()
        if not 0 <= age <= max_age:
            continue
        try:
            job = _quake_job(quake, _published_quake(quake, entries), moment, min_magnitude, detail)
        except (sd.ServiceDataError, ValueError, KeyError) as exc:
            # Un sismo sin detalle legible no frena a los demás.
            logger.warning("Sismo %s sin placa: %s", quake.get("id"), exc)
            continue
        if job:
            out.append(job)
    return out


def _quake_job(quake: dict, published: tuple[str, dict] | None, moment: datetime, min_magnitude: float, detail) -> dict | None:
    if published is None:
        if quake["magnitude"] < min_magnitude:
            return None
        info = detail(quake["id"])
        return {
            "key": f"svcpost:sismo:{quake['id']}",
            "kind": "quake",
            "props": quake_props(quake, info, moment),
            "caption": quake_caption(quake, info),
            "fb_link": "",
            "label": f"Sismo {quake['magnitude']} · {quake['id']}",
            "snapshot": _snapshot(quake, info),
            "post_ig": True,
            "post_fb": True,
            "story": True,
        }
    key, snap = published
    # "felt" (rojo) también es un dato revisado por INPRES.
    if snap.get("status") != "automatic" or quake["status"] not in ("revised", "felt"):
        return None
    info = detail(quake["id"])
    current = _snapshot(quake, info)
    if (current["magnitude"], current["place"]) == (snap.get("magnitude"), snap.get("place")):
        return None
    return {
        "key": f"{key}:actualizado",
        "kind": "quake",
        "props": quake_props(quake, info, moment, previous=snap),
        "caption": "",
        "fb_link": "",
        "label": f"Sismo actualizado {quake['magnitude']} · {quake['id']}",
        "post_ig": False,
        "post_fb": False,
        "story": True,
    }


def due_service_posts(now: datetime | None = None, *, state: dict | None = None, wanted=lambda job: True) -> list[dict]:
    """Placas que corresponden ahora y tienen algo pendiente (``wanted``).
    Cada fuente falla por separado."""
    jobs: list[dict] = []
    for enabled, builder, label in (
        (_flag("PAYMENT_POSTS_ENABLED"), due_payments, "Cronograma de Hacienda"),
        (_flag("QUAKE_POSTS_ENABLED"), due_quakes, "Sismos de INPRES"),
    ):
        if not enabled:
            continue
        try:
            jobs.extend(job for job in builder(now, state=state) if wanted(job))
        except (sd.ServiceDataError, ValueError, KeyError) as exc:
            logger.warning("%s no disponible: %s", label, exc)
    return jobs


def pending_parts(job: dict, state: dict, story_state: dict, *, instagram: bool, facebook: bool, stories: bool) -> dict:
    """Qué falta publicar de la placa: post en cada red e historia."""
    from utils import story_publisher as sp

    entry = (state.get("service_posts") or {}).get(job["key"]) or {}
    blocked = bool(entry.get("ambiguous"))
    return {
        "ig": bool(instagram and job.get("post_ig") and not entry.get("ig_id") and not blocked),
        "fb": bool(facebook and job.get("post_fb") and not entry.get("fb_id") and not blocked),
        "story": bool(stories and job.get("story") and not sp.already_done(f"svc:{job['key']}", story_state)),
    }


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
    meta = {"kind": job["kind"], "label": job["label"], "snapshot": job.get("snapshot")}
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
            _record(key, ig_id=result.external_id, ig_at=int(time.time()), **meta)
        elif outcome["ig"] == "ambiguous":
            _record(key, ambiguous="instagram", **meta)
    if facebook and not entry.get("fb_id") and outcome["ig"] != "ambiguous":
        message = job["caption"] + (f"\n\n{job['fb_link']}" if job.get("fb_link") else "")
        result = fb_client.post_photo(card, message)
        outcome["fb"] = _classify(result)
        if outcome["fb"] == "success":
            _record(key, fb_id=result.external_id, fb_at=int(time.time()), **meta)
        elif outcome["fb"] == "ambiguous":
            _record(key, ambiguous="facebook", **meta)
    logger.info("Placa %s → instagram=%s facebook=%s", key, outcome["ig"], outcome["fb"])
    return outcome


def publish_story(job: dict, post_ig_id: str, *, instagram: bool, facebook: bool) -> dict:
    """Historia de servicio de la placa. Si ya salió, sólo registra que cubre
    la historia automática del post (``post_ig_id``), por si el post llegó
    después."""
    from utils import story_publisher as sp

    key = f"svc:{job['key']}"
    outcome = {"ig": "skipped", "fb": "skipped"}
    if not sp.already_done(key):
        jpeg = sp.render_story(job["props"])
        outcome = sp.publish_story(key, jpeg, instagram=instagram, facebook=facebook, meta={"kind": job["kind"], "label": job["label"]})
    if post_ig_id:
        posted = sp.load_state().get("posted") or {}
        story = posted.get(key) or {}
        if (story.get("ig_id") or story.get("fb_id")) and not posted.get(f"post:{post_ig_id}"):
            # Sin "day": no suma al cupo diario de historias.
            sp._record(f"post:{post_ig_id}", ig_id=story.get("ig_id"), fb_id=story.get("fb_id"), covered_by=key)
    return outcome
