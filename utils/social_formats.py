"""Formatos sociales programados: historias de servicio, carrusel "Lo que
tenés que saber hoy" (8 h) y Reel "La semana en cinco" (domingos 20 h).

Todo el texto sale de fuentes verificables (SMN, dolarapi, calendario
oficial, notas ya publicadas y métricas reales de Instagram): no hay llamadas
a IA. Estado propio en ``data/social_formats_state.json``.
"""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
import unicodedata
from datetime import date, datetime, timedelta

from PIL import Image

from utils import service_data as sd
from utils.article_media import fetch_article
from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_time import DIAS, MESES, day_label, hhmm, now_ar, range_label, today_ar
from utils.story_publisher import download_image, story_props
from utils.url_normalization import url_hash

logger = setup_logger("social_formats", "social_formats.log")

STATE_PATH = str(data_dir() / "social_formats_state.json")
_TRUE = {"1", "true", "yes", "on", "si", "sí"}


def flag(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def load_state() -> dict:
    return load_json(STATE_PATH, {}, expected_type=dict)


def update_state(mutator) -> dict:
    return update_json(STATE_PATH, mutator, {}, expected_type=dict)


def _note(state_key: str, value) -> None:
    def mutate(state):
        state[state_key] = value
        return state

    update_state(mutate)


# ── Historias de servicio ────────────────────────────────────────────────
def _alert_line(alerts: dict) -> str:
    if alerts.get("status") == "active":
        return f"Alerta {alerts['level']} por {alerts['phenomenon']} para La Rioja"
    return "Sin alertas del SMN para La Rioja"


def weather_story(weather: sd.Weather, alerts: dict, now: datetime | None = None) -> dict:
    moment = now_ar(now)
    detail = []
    if weather.humidity is not None:
        detail.append(f"Humedad {weather.humidity} %")
    if weather.wind:
        detail.append(f"viento {weather.wind.lower()} km/h" if re.search(r"\d", weather.wind) else f"viento {weather.wind.lower()}")
    days = [d for d in weather.days if d["date"] >= moment.date().isoformat()][:5]
    return story_props(
        kind="weather",
        place="La Rioja · Capital",
        dateLabel=day_label(moment.date()),
        temp=weather.temp,
        sky=weather.sky,
        detail=" · ".join(detail),
        days=[{"label": d["label"], "min": d["min"], "max": d["max"], "rain": d["rain"]} for d in days],
        alertSummary=_alert_line(alerts),
        sourceLabel=f"Fuente: SMN · medición de las {weather.observed_at}",
    )


def alert_story(alerts: dict) -> dict:
    return story_props(
        kind="alert",
        level=alerts["level"],
        titulo=f"Alerta {alerts['level']} por {alerts['phenomenon']}",
        body="El Servicio Meteorológico Nacional emitió una alerta que alcanza a La Rioja.",
        sourceLabel="Fuente: Servicio Meteorológico Nacional",
    )


def dollar_story(rows: list[dict], previous: dict, now: datetime | None = None) -> dict:
    out = []
    for row in rows:
        prev = previous.get(row["house"])
        delta = round(row["sell"] - float(prev), 2) if prev not in (None, "") else 0
        out.append({"name": row["name"], "buy": sd.money(row["buy"]) if row["buy"] is not None else "", "sell": sd.money(row["sell"]), "delta": delta})
    by = {r["house"]: r for r in rows}
    body = "Precios de venta en pesos."
    if "oficial" in by and "blue" in by and by["oficial"]["sell"]:
        gap = (by["blue"]["sell"] / by["oficial"]["sell"] - 1) * 100
        body += f" Brecha entre el blue y el oficial: {str(round(gap, 1)).replace('.', ',')} %."
    return story_props(kind="dollar", dateLabel=day_label(today_ar(now)), rows=out, body=body, timeLabel=hhmm(now_ar(now)), sourceLabel="Fuente: dolarapi.com")


def holidays_story(holidays: list[dict], today: date) -> dict:
    nxt = date.fromisoformat(holidays[0]["date"])
    days = (nxt - today).days
    countdown = "Mañana es feriado" if days == 1 else "Hoy es feriado" if days == 0 else f"Faltan {days} días para el próximo"
    return story_props(kind="holidays", holidays=sd.holiday_story_rows(holidays), countdown=countdown, sourceLabel="Fuente: calendario oficial (argentina.gob.ar)")


def notice_story(notice: dict) -> dict:
    published = notice.get("published_at") or ""
    label = ""
    try:
        moment = datetime.fromisoformat(published.replace("Z", "+00:00"))
        label = f"Aviso publicado el {day_label(now_ar(moment).date(), capital=False)}"
    except ValueError:
        pass
    source = {"luz": "Fuente: EDELaR", "agua": "Fuente: Aguas Riojanas", "rutas": "Fuente: Vialidad"}.get(notice["service"], "Información de servicio")
    title = notice["title"]
    if title.isupper():
        title = title[:1] + title[1:].lower()
    return story_props(kind="notice", service=notice["service"], titulo=title, body=notice.get("excerpt", ""), dateLabel=label, sourceLabel=source)


def due_service_stories(now: datetime | None = None, *, done=lambda key: False) -> list[tuple[str, dict, str | None]]:
    """Historias de servicio que corresponden ahora. Cada fuente falla por
    separado: si el SMN no responde, el dólar sigue."""
    moment = now_ar(now)
    today = moment.date()
    hour = moment.hour
    out: list[tuple[str, dict, str | None]] = []
    state = load_state()

    alerts: dict = {"status": "none"}
    try:
        alerts = sd.fetch_alerts()
    except sd.ServiceDataError as exc:
        logger.warning("Alertas SMN no disponibles: %s", exc)
        alerts = {"status": "error"}
    _note("last_alerts", {**alerts, "checked_at": int(time.time())})
    if alerts.get("status") == "active":
        key = f"svc:alert:{today.isoformat()}:{alerts['level']}:{alerts['phenomenon']}"
        if not done(key):
            out.append((key, alert_story(alerts), None))
    elif alerts.get("status") == "unparsed":
        logger.warning("Alerta SMN para La Rioja con formato no reconocido: no se publica (%s)", alerts.get("raw", "")[:200])

    if 7 <= hour < 11:
        key = f"svc:weather:{today.isoformat()}"
        if not done(key):
            try:
                weather = sd.fetch_weather()
                if weather:
                    out.append((key, weather_story(weather, alerts, now), None))
            except sd.ServiceDataError as exc:
                logger.warning("Clima SMN no disponible: %s", exc)

    if today.weekday() < 5 and (11 <= hour < 13 or 16 <= hour < 18):
        slot = "am" if hour < 13 else "pm"
        key = f"svc:dollar:{today.isoformat()}:{slot}"
        if not done(key):
            try:
                rows = sd.fetch_dollar()
                previous = state.get("last_dollar") or {}
                changed = any(abs(r["sell"] - float(previous.get(r["house"], -1))) >= 0.01 for r in rows)
                if rows and changed:
                    out.append((key, dollar_story(rows, previous, now), None))
                    out[-1][1]["_dollar_values"] = {r["house"]: r["sell"] for r in rows}
            except sd.ServiceDataError as exc:
                logger.warning("Dólar no disponible: %s", exc)

    if 9 <= hour < 21:
        try:
            holidays = sd.upcoming_holidays(today)
        except sd.ServiceDataError as exc:
            logger.warning("Calendario de feriados no disponible: %s", exc)
            holidays = []
        if holidays:
            days_left = (date.fromisoformat(holidays[0]["date"]) - today).days
            if days_left in (7, 1):
                key = f"svc:holidays:{holidays[0]['date']}:{days_left}d"
                if not done(key):
                    out.append((key, holidays_story(holidays, today), None))

    for notice in sd.recent_notices(hours=int(os.getenv("SERVICE_NOTICE_LOOKBACK_HOURS", "18")), now=now):
        key = f"svc:notice:{url_hash(notice['url'])}"
        if not done(key):
            out.append((key, notice_story(notice), None))
    return out


def remember_dollar(values: dict) -> None:
    _note("last_dollar", values)


# ── Selección de notas (carrusel y resumen) ──────────────────────────────
_LOCAL_SOURCES = ("nuevarioja", "tiempopopular", "fenix", "judicial_")
_WEATHER = ("pronostico", "temperatura", "el tiempo en", "clima en", "frente frio")
_SENSITIVE = ("abuso", "violacion", "femicidio", "suicid", "menor de edad", "intimo", "pornograf", "grooming")
_CATEGORY_WEIGHT = {
    "politica": 1.0, "sociedad": 1.0, "economia": 1.0, "salud": 0.9, "educacion": 0.9, "interior": 0.9,
    "locales": 1.0, "policiales": 0.8, "deportes": 0.6, "cultura": 0.6, "espectaculos": 0.3,
}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def _archive_rows(urls: list[str]) -> dict[str, dict]:
    path = str(data_dir() / "derived" / "editorial_context.sqlite3")
    if not urls:
        return {}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return {}
    try:
        marks = ",".join("?" for _ in urls)
        rows = conn.execute(f"select canonical_url, category, story_key, topic_key from archive_articles where canonical_url in ({marks})", urls).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return {r[0]: {"category": r[1] or "", "story_key": r[2] or "", "topic_key": r[3] or ""} for r in rows}


_STOP = {"La", "El", "Los", "Las", "Un", "Una", "En", "De", "Del", "Por", "Con", "Tras", "Para", "Rioja", "Riojana", "Argentina", "Capital"}


def _proper_names(title: str) -> set[str]:
    words = re.findall(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñü]{3,}", title)
    return {w for i, w in enumerate(words) if w not in _STOP and not title.startswith(w)}


def same_topic(a: dict, b: dict) -> bool:
    if a.get("story_key") and a.get("story_key") == b.get("story_key"):
        return True
    if a.get("topic_key") and a.get("topic_key") == b.get("topic_key"):
        return True
    return len(_proper_names(a.get("title", "")) & _proper_names(b.get("title", ""))) >= 1


def _published_web(hours: float, now: float) -> list[dict]:
    try:
        records = load_json(str(data_dir() / "noticias_web_publicadas.json"), [], expected_type=list)
    except JsonStateError:
        return []
    return [r for r in records if isinstance(r, dict) and now - float(r.get("published_at_ts") or 0) <= hours * 3600 and r.get("web_url")]


def select_brief_items(*, now: float | None = None, count: int = 5, fetch=fetch_article) -> list[dict]:
    """Las 5 notas para la mañana: últimas 24 h, locales primero, sin temas
    repetidos ni notas sensibles, cada una con su foto original."""
    now = now or time.time()
    records = _published_web(24, now)
    meta = _archive_rows([r["web_url"] for r in records])
    scored = []
    for r in records:
        title_fold = _fold(r.get("titulo", ""))
        if any(word in title_fold for word in _SENSITIVE):
            continue
        if any(word in title_fold for word in _WEATHER):
            continue  # el clima ya va en la tapa y en la lámina de servicios
        info = meta.get(r["web_url"], {})
        category = info.get("category", "")
        local = str(r.get("source") or "").startswith(_LOCAL_SOURCES) and category != "espectaculos"
        score = (2.0 if local else 0.0) + _CATEGORY_WEIGHT.get(category, 0.5) + float(r.get("published_at_ts") or 0) / now * 0.01
        scored.append((score, r, info))
    scored.sort(key=lambda x: -x[0])
    chosen: list[dict] = []
    for _score, r, info in scored:
        if len(chosen) >= count:
            break
        article = fetch(r["web_url"])
        if not article or not article.get("title") or not article.get("photo_url"):
            continue
        item = {
            "title": article["title"], "section": (info.get("category") or article.get("section") or "").lower(),
            "deck": article.get("description") or r.get("excerpt") or "", "photo_url": article["photo_url"],
            "web_url": r["web_url"], "story_key": info.get("story_key", ""), "topic_key": info.get("topic_key", ""),
        }
        if any(same_topic(item, c) for c in chosen):
            continue
        chosen.append(item)
    return chosen


# ── Carrusel "Lo que tenés que saber hoy" ────────────────────────────────
BRIEF_DEFAULTS = {"slide": "cover", "dateLabel": "", "weatherLine": "", "index": [], "number": 1, "total": 5, "page": "", "seccion": "", "titulo": "", "deck": "", "assetFile": "", "services": []}


def _render_brief_slide(props: dict, asset: str | None = None) -> bytes:
    from utils.remotion_renderer import render_still

    full = {**BRIEF_DEFAULTS, **props}
    png, _ = render_still("MorningBriefV2", full, asset_paths={"assetFile": asset} if asset else {}, timeout=240, scale=2)
    with Image.open(io.BytesIO(png)) as image:
        out = io.BytesIO()
        image.convert("RGB").save(out, "JPEG", quality=90, optimize=True, subsampling=0)
        return out.getvalue()


def brief_services(weather: sd.Weather | None, alerts: dict, dollar: list[dict], holidays: list[dict], notices: list[dict], today: date) -> list[dict]:
    rows = []
    if weather and weather.days:
        d0 = next((d for d in weather.days if d["date"] == today.isoformat()), weather.days[0])
        rows.append({"label": "Clima", "value": f"{round(d0['min'])}° / {round(d0['max'])}° · {weather.sky}", "note": _alert_line(alerts)})
    by = {r["house"]: r for r in dollar}
    if "oficial" in by:
        rows.append({"label": "Dólar oficial", "value": f"${sd.money(by['oficial']['sell'])}", "note": "Venta"})
    if "blue" in by:
        rows.append({"label": "Dólar blue", "value": f"${sd.money(by['blue']['sell'])}", "note": "Venta"})
    if holidays:
        h = date.fromisoformat(holidays[0]["date"])
        left = (h - today).days
        rows.append({"label": "Próximo feriado", "value": f"{DIAS[h.weekday()].capitalize()} {h.day} de {MESES[h.month - 1]}", "note": "Hoy" if left == 0 else "Mañana" if left == 1 else f"Faltan {left} días"})
    cuts = [n for n in notices if n["service"] in ("luz", "agua")]
    rows.append({"label": "Cortes anunciados", "value": f"{len(cuts)} aviso{'s' if len(cuts) != 1 else ''}" if cuts else "Ninguno para hoy", "note": "EDELaR y Aguas Riojanas"})
    return rows[:6]


def brief_caption(items: list[dict], today: date, weather: sd.Weather | None, dollar: list[dict]) -> str:
    lines = [f"☀️ Lo que tenés que saber hoy, {day_label(today, capital=False)}", ""]
    numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    for i, item in enumerate(items):
        lines.append(f"{numbers[i]} {item['title']}")
    lines.append("")
    if weather and weather.days:
        d0 = next((d for d in weather.days if d["date"] == today.isoformat()), weather.days[0])
        lines.append(f"🌡️ La Rioja: mínima de {round(d0['min'])}° y máxima de {round(d0['max'])}°, {weather.sky.lower()} (SMN)")
    by = {r["house"]: r for r in dollar}
    if "oficial" in by and "blue" in by:
        lines.append(f"💵 Dólar oficial ${sd.money(by['oficial']['sell'])} · blue ${sd.money(by['blue']['sell'])}")
    lines += ["", "Deslizá para leer cada noticia. Todas las notas completas en lavozriojana.com", "", "#LaVozRiojana #LaRioja #Noticias"]
    return "\n".join(lines)[:2200]


def build_morning_brief(now: datetime | None = None) -> dict | None:
    """Arma las láminas (JPEG) y el texto. ``None`` si no hay 3 notas con foto."""
    today = today_ar(now)
    items = select_brief_items(now=time.time() if now is None else now.timestamp())
    if len(items) < 3:
        logger.warning("Carrusel de la mañana: sólo %s notas con foto; no se publica", len(items))
        return None
    weather = None
    alerts: dict = {"status": "none"}
    dollar: list[dict] = []
    holidays: list[dict] = []
    try:
        weather = sd.fetch_weather()
        alerts = sd.fetch_alerts()
    except sd.ServiceDataError as exc:
        logger.warning("SMN no disponible para el carrusel: %s", exc)
    try:
        dollar = sd.fetch_dollar()
    except sd.ServiceDataError as exc:
        logger.warning("Dólar no disponible para el carrusel: %s", exc)
    try:
        holidays = sd.upcoming_holidays(today)
    except sd.ServiceDataError as exc:
        logger.warning("Feriados no disponibles para el carrusel: %s", exc)
    notices = sd.recent_notices(hours=24, now=now)

    total = len(items) + 2
    weather_line = ""
    if weather and weather.days:
        d0 = next((d for d in weather.days if d["date"] == today.isoformat()), weather.days[0])
        weather_line = f"La Rioja · {round(d0['min'])}° / {round(d0['max'])}° · {weather.sky}"
    slides = [_render_brief_slide({
        "slide": "cover", "dateLabel": day_label(today, year=True), "weatherLine": weather_line,
        "index": [{"seccion": i["section"], "titulo": i["title"]} for i in items], "page": f"1/{total}",
    })]
    paths: list[str] = []
    try:
        for n, item in enumerate(items, 1):
            photo = download_image(item["photo_url"])
            if photo:
                paths.append(photo)
            slides.append(_render_brief_slide({
                "slide": "news", "number": n, "total": len(items), "seccion": item["section"], "titulo": item["title"],
                "deck": item["deck"], "page": f"{n + 1}/{total}",
            }, photo))
        slides.append(_render_brief_slide({
            "slide": "services", "dateLabel": day_label(today), "page": f"{total}/{total}",
            "services": brief_services(weather, alerts, dollar, holidays, notices, today),
        }))
    finally:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass
    return {"date": today.isoformat(), "slides": slides, "caption": brief_caption(items, today, weather, dollar), "items": items}


def _upload_all(slides: list[bytes], hint: str) -> tuple[list[str], list[str]]:
    from utils import r2_storage

    urls, keys = [], []
    for data in slides:
        handle, tmp = tempfile.mkstemp(suffix=".jpg", prefix=f"lvr_{hint}_")
        os.close(handle)
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            url, key = r2_storage.upload_temp(tmp, ttl_hint=hint)
            urls.append(url)
            keys.append(key)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return urls, keys


def publish_morning_brief(brief: dict, *, instagram: bool, facebook: bool) -> dict:
    from meta import fb_client, ig_client
    from utils import r2_storage

    day = brief["date"]
    record = (load_state().get("brief") or {}).get(day) or {}
    outcome = {"ig": "skipped", "fb": "skipped"}
    if instagram and not record.get("ig_id") and not record.get("ambiguous"):
        keys: list[str] = []
        try:
            urls, keys = _upload_all(brief["slides"], "brief")
            result = ig_client.post_image_carousel(urls, brief["caption"])
        except RuntimeError as exc:
            logger.warning("No se pudieron subir las láminas a R2: %s", exc)
            result = None
        finally:
            for key in keys:
                try:
                    r2_storage.delete(key)
                except Exception:  # noqa: BLE001 — los temporales expiran solos
                    pass
        if result is not None and result.ok:
            outcome["ig"] = "success"
            _mark_day("brief", day, ig_id=result.external_id)
        elif result is not None and (result.details or {}).get("publication_outcome") == "unknown":
            outcome["ig"] = "ambiguous"
            _mark_day("brief", day, ambiguous="instagram")
        else:
            outcome["ig"] = result.error_type if result is not None else "r2_error"
    if facebook and not record.get("fb_id") and outcome["ig"] != "ambiguous":
        message = brief["caption"].replace("Todas las notas completas en lavozriojana.com", "Todas las notas completas en https://lavozriojana.com")
        result = fb_client.post_photo_album(brief["slides"], message)
        if result.ok:
            outcome["fb"] = "success"
            _mark_day("brief", day, fb_id=result.external_id)
        else:
            outcome["fb"] = "ambiguous" if (result.details or {}).get("publication_outcome") == "unknown" else result.error_type or "failed"
            if outcome["fb"] == "ambiguous":
                _mark_day("brief", day, ambiguous="facebook")
    logger.info("Carrusel de la mañana %s → instagram=%s facebook=%s", day, outcome["ig"], outcome["fb"])
    return outcome


def _mark_day(section: str, day: str, **fields) -> None:
    def mutate(state):
        bucket = state.setdefault(section, {})
        bucket.setdefault(day, {}).update(fields)
        bucket[day]["updated_at"] = int(time.time())
        for old in sorted(bucket)[:-60]:
            bucket.pop(old, None)
        return state

    update_state(mutate)


def brief_due(now: datetime | None = None) -> bool:
    moment = now_ar(now)
    start = int(os.getenv("MORNING_BRIEF_HOUR", "8"))
    if not start <= moment.hour < start + 3:
        return False
    record = (load_state().get("brief") or {}).get(moment.date().isoformat()) or {}
    return not (record.get("ig_id") or record.get("ambiguous") or record.get("attempts", 0) >= 3)


def note_brief_attempt(day: str) -> None:
    def mutate(state):
        entry = state.setdefault("brief", {}).setdefault(day, {})
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        return state

    update_state(mutate)


# ── Reel "La semana en cinco" ────────────────────────────────────────────
def _reach_label(reach: float) -> str:
    if reach >= 1_000_000:
        return f"{str(round(reach / 1_000_000, 1)).replace('.', ',')} millones de cuentas alcanzadas"
    if reach >= 1000:
        return f"{round(reach / 1000)} mil cuentas alcanzadas"
    return f"{int(reach)} cuentas alcanzadas"


def select_week_top(*, now: float | None = None, count: int = 5, fetch=fetch_article) -> list[dict]:
    """Las publicaciones de Instagram con más alcance de los últimos 7 días,
    una por tema, con su nota web y foto original."""
    now = now or time.time()
    try:
        insights = (load_json(str(data_dir() / "ig_media_insights.json"), {"media": {}}, expected_type=dict).get("media") or {})
        posted = load_json(str(data_dir() / "ig_posted.json"), {"posted": {}}, expected_type=dict).get("posted") or {}
        web = load_json(str(data_dir() / "noticias_web_publicadas.json"), [], expected_type=list)
    except JsonStateError as exc:
        logger.warning("Estado ilegible para el resumen semanal: %s", exc)
        return []
    by_media = {str(r.get("external_id")): r for r in posted.values() if isinstance(r, dict) and r.get("external_id")}
    by_source = {}
    for r in web:
        if isinstance(r, dict) and r.get("web_url"):
            for k in (r.get("canonical_url"), r.get("url"), r.get("web_queue_key")):
                if k:
                    by_source[k] = r
    week = sorted(((mid, v) for mid, v in insights.items() if now - float(v.get("posted_at") or 0) <= 7 * 86400), key=lambda kv: -float(kv[1].get("reach") or 0))
    chosen: list[dict] = []
    seen_urls: set[str] = set()
    for media_id, metrics in week:
        if len(chosen) >= count:
            break
        record = by_media.get(media_id) or {}
        web_record = None
        for k in (record.get("canonical_url"), record.get("url"), record.get("web_queue_key"), record.get("meta_queue_key")):
            if k and k in by_source:
                web_record = by_source[k]
                break
        if not web_record or web_record["web_url"] in seen_urls:
            continue
        article = fetch(web_record["web_url"])
        if not article or not article.get("photo_url") or not article.get("title"):
            continue
        info = _archive_rows([web_record["web_url"]]).get(web_record["web_url"], {})
        item = {
            "title": article["title"], "section": (metrics.get("seccion") or article.get("section") or "").lower(),
            "photo_url": article["photo_url"], "reach": float(metrics.get("reach") or 0), "metric": _reach_label(float(metrics.get("reach") or 0)),
            "web_url": web_record["web_url"], "story_key": info.get("story_key", ""), "topic_key": info.get("topic_key", ""),
        }
        if any(same_topic(item, c) for c in chosen):
            continue
        seen_urls.add(web_record["web_url"])
        chosen.append(item)
    return chosen


def weekly_due(now: datetime | None = None) -> bool:
    moment = now_ar(now)
    if moment.weekday() != 6 or not int(os.getenv("WEEKLY_RECAP_HOUR", "20")) <= moment.hour < 23:
        return False
    week = moment.date().isoformat()
    record = (load_state().get("weekly") or {}).get(week) or {}
    return not (record.get("ig_id") or record.get("ambiguous") or record.get("attempts", 0) >= 2)


def render_weekly_recap(items: list[dict], end: date) -> str | None:
    """MP4 de ``WeeklyRecapV2`` (puesto 5 → 1). Devuelve la ruta o ``None``."""
    from utils.remotion_renderer import REMOTION_DIR
    from utils.video_renderer import _npx_args

    work = os.path.join(REMOTION_DIR, "public", "tmp", f"recap_{int(time.time())}")
    os.makedirs(work, exist_ok=True)
    entries = []
    downloaded: list[str] = []
    try:
        for i, item in enumerate(reversed(items)):
            photo = download_image(item["photo_url"])
            if not photo:
                return None
            downloaded.append(photo)
            name = f"{i}.jpg"
            dest = os.path.join(work, name)
            with Image.open(photo) as image:
                w, h = image.size
                image.save(dest, "JPEG", quality=92)
            entries.append({"titulo": item["title"], "seccion": item["section"], "assetFile": f"tmp/{os.path.basename(work)}/{name}", "assetWidth": w, "assetHeight": h, "metric": item["metric"]})
        props = {"rangeLabel": range_label(end - timedelta(days=6), end), "entries": entries}
        props_path = os.path.join(work, "props.json")
        with open(props_path, "w", encoding="utf-8") as fh:
            json.dump(props, fh, ensure_ascii=False)
        output = os.path.join(tempfile.gettempdir(), f"lvr_weekly_{end.isoformat()}.mp4")
        result = subprocess.run(
            _npx_args(["remotion", "render", "WeeklyRecapV2", output, "--codec=h264", "--crf=19", f"--props={props_path}"]),
            cwd=REMOTION_DIR, capture_output=True, text=True, timeout=900,
        )
        if result.returncode != 0 or not os.path.isfile(output):
            logger.warning("No se pudo renderizar el resumen semanal: %s", result.stderr[-400:])
            return None
        return output
    finally:
        for p in downloaded:
            try:
                os.unlink(p)
            except OSError:
                pass
        for name in os.listdir(work):
            try:
                os.unlink(os.path.join(work, name))
            except OSError:
                pass
        try:
            os.rmdir(work)
        except OSError:
            pass


def weekly_caption(items: list[dict], end: date) -> str:
    lines = [f"📊 La semana en cinco: lo más visto del {range_label(end - timedelta(days=6), end)}", ""]
    for rank, item in zip(range(len(items), 0, -1), reversed(items)):
        lines.append(f"{rank}. {item['title']}")
    lines += ["", "Todas las notas en lavozriojana.com. Cada domingo, el resumen de la semana."]
    return "\n".join(lines)


def publish_weekly_recap(video_path: str, items: list[dict], end: date, *, instagram: bool, facebook: bool) -> dict:
    from meta import fb_client, ig_client
    from utils import r2_storage

    week = end.isoformat()
    outcome = {"ig": "skipped", "fb": "skipped"}
    try:
        url, _key = r2_storage.upload_temp(video_path, ttl_hint="reel")
    except RuntimeError as exc:
        logger.warning("No se pudo subir el resumen semanal: %s", exc)
        return {"ig": "r2_error", "fb": "skipped"}
    # El temporal expira solo: Facebook descarga file_url de forma asíncrona.
    item = {"video_url": url, "texto_instagram": weekly_caption(items, end), "titulo": "La semana en cinco", "seccion": "", "share_to_feed": True, "thumb_offset_ms": 3000}
    record = (load_state().get("weekly") or {}).get(week) or {}
    if instagram and not record.get("ig_id"):
        result = ig_client.post_reel_video_to_instagram(item)
        if result.ok:
            outcome["ig"] = "success"
            _mark_day("weekly", week, ig_id=result.external_id)
        else:
            outcome["ig"] = "ambiguous" if (result.details or {}).get("publication_outcome") == "unknown" else result.error_type or "failed"
            if outcome["ig"] == "ambiguous":
                _mark_day("weekly", week, ambiguous="instagram")
    if facebook and not record.get("fb_id") and outcome["ig"] != "ambiguous":
        result = fb_client.post_reel_video_to_facebook(item)
        if result.ok:
            outcome["fb"] = "success"
            _mark_day("weekly", week, fb_id=result.external_id)
        else:
            outcome["fb"] = result.error_type or "failed"
    logger.info("Resumen semanal %s → instagram=%s facebook=%s", week, outcome["ig"], outcome["fb"])
    return outcome


def note_weekly_attempt(week: str) -> None:
    def mutate(state):
        entry = state.setdefault("weekly", {}).setdefault(week, {})
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        return state

    update_state(mutate)
