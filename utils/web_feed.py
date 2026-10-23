"""Datos para la web: JSON públicos en R2 que el sitio arma como quiera.

En vez de widgets cerrados, cada ciclo se publican en ``feed/v1/`` del bucket
público (``R2_PUBLIC_URL``) cinco documentos con datos que el pipeline ya
tiene (contrato en ``docs/WEB_FEED.md``):

* ``mas-visto.json``: notas de la web ordenadas por alcance en Instagram
  (no hay métrica de visitas de la web en el pipeline), con su URL.
* ``servicios.json``: clima, alerta y avisos del SMN, dólar, feriados, pagos a
  estatales, sismos de INPRES y cortes con zona. Si una fuente falla se
  conserva el último dato bueno con su propia hora de actualización.
* ``actualizaciones.json``: notas que actualizan otra (``utils/same_event.py``),
  con la URL de la anterior, para mostrar el aviso en la nota vieja.
* ``videos.json``: Reels publicados en Instagram con su enlace.
* ``historias.json``: cronologías, sólo de cadenas de actualizaciones
  verificadas del mismo hecho (nunca del agrupamiento automático).
* ``ultimo-momento.json``: la nota marcada en el CMS y la alerta del SMN.
* ``index.json``: qué hay y cuándo se actualizó.

Sólo datos ya publicados o de fuentes oficiales: nada se inventa ni se
completa. Las funciones ``build_*`` son puras (reciben el estado) para poder
probarlas sin red.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import date, datetime, timedelta, timezone

from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_time import DIAS, now_ar, today_ar

logger = setup_logger("web_feed", "web_feed.log")

VERSION = 1
PREFIX = "feed/v1"
STATE_PATH = str(data_dir() / "web_feed_state.json")
CACHE_CONTROL = "public, max-age=300"


def _iso(ts: float | int | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(now_ar().tzinfo).isoformat(timespec="seconds")


def _now_iso(now: datetime | None = None) -> str:
    return now_ar(now).isoformat(timespec="seconds")


def _load(name: str, default):
    try:
        return load_json(str(data_dir() / name), default, expected_type=type(default))
    except JsonStateError as exc:
        logger.warning("Estado ilegible para el feed web (%s): %s", name, exc)
        return default


def _web_by_canonical(web: list) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in web:
        if isinstance(r, dict) and r.get("web_url"):
            for key in (r.get("canonical_url"), r.get("url")):
                if key:
                    out[str(key)] = r
    return out


# ── Lo más visto ─────────────────────────────────────────────────────────
def build_most_viewed(insights: dict, ig_posted: dict, web: list, permalinks: dict, *, now: float, limit: int = 10) -> dict:
    """Notas con URL web ordenadas por alcance en Instagram, en dos ventanas."""
    by_media = {str(r.get("external_id")): r for r in ig_posted.values() if isinstance(r, dict) and r.get("external_id")}
    by_url = _web_by_canonical(web)
    rows = []
    for media_id, metrics in (insights or {}).items():
        record = by_media.get(str(media_id))
        if not record or not isinstance(metrics, dict):
            continue
        page = by_url.get(str(record.get("canonical_url") or "")) or by_url.get(str(record.get("url") or ""))
        if not page:
            continue
        posted = float(metrics.get("posted_at") or record.get("posted_at") or 0)
        link = (permalinks.get(str(media_id)) or {}).get("permalink") or ""
        rows.append({
            "titulo": str(record.get("titulo_instagram") or record.get("titulo") or page.get("titulo") or ""),
            "url": page["web_url"],
            "seccion": str(metrics.get("seccion") or record.get("seccion") or ""),
            "publicada": _iso(page.get("published_at_ts") or posted),
            "instagram": {"url": link, "alcance": int(metrics.get("reach") or 0), "interacciones": int(metrics.get("interactions") or 0)},
            "_posted": posted,
        })
    rank = lambda r: (r["instagram"]["alcance"], r["instagram"]["interacciones"])  # noqa: E731

    def window(hours: int) -> list[dict]:
        picked = sorted((r for r in rows if now - r["_posted"] <= hours * 3600), key=rank, reverse=True)[:limit]
        return [{k: v for k, v in r.items() if k != "_posted"} for r in picked]

    week = window(7 * 24)
    by_section: dict[str, list[dict]] = {}
    for r in sorted((r for r in rows if now - r["_posted"] <= 7 * 86400), key=rank, reverse=True):
        bucket = by_section.setdefault(r["seccion"] or "sin_seccion", [])
        if len(bucket) < 5:
            bucket.append({k: v for k, v in r.items() if k != "_posted"})
    return {"metrica": "alcance en Instagram", "ventanas": {"24h": window(24), "7d": week}, "por_seccion_7d": by_section}


def most_viewed_media(insights: dict, *, now: float, limit: int = 10) -> list[str]:
    """Los posts que pueden entrar al ranking (para pedir sólo esos enlaces)."""
    recent = [(m, v) for m, v in (insights or {}).items() if isinstance(v, dict) and now - float(v.get("posted_at") or 0) <= 7 * 86400]
    recent.sort(key=lambda mv: float(mv[1].get("reach") or 0), reverse=True)
    return [m for m, _ in recent[: limit * 8]]


# ── Actualizaciones ──────────────────────────────────────────────────────
def build_updates(web: list, *, now: float, days: int = 7) -> dict:
    by_url = _web_by_canonical(web)
    items = []
    for r in web:
        update = r.get("event_update") if isinstance(r, dict) else None
        if not isinstance(update, dict) or not r.get("web_url"):
            continue
        published = float(r.get("published_at_ts") or 0)
        if now - published > days * 86400:
            continue
        previous = by_url.get(str(update.get("of_canonical_url") or "")) or {}
        previous_url = previous.get("web_url") or update.get("of_web_url") or ""
        if not previous_url:
            continue
        items.append({
            "nota": {"titulo": str(r.get("titulo") or ""), "url": r["web_url"], "publicada": _iso(published)},
            "actualiza": {"titulo": str(previous.get("titulo") or update.get("of_title") or ""), "url": previous_url},
            "novedad": str(update.get("novedad") or ""),
        })
    items.sort(key=lambda i: i["nota"]["publicada"], reverse=True)
    return {"items": items}


# ── Cronologías ──────────────────────────────────────────────────────────
def build_stories(web: list, *, now: float, days: int = 30, story_key_for=None) -> dict:
    """Cadenas de actualizaciones verificadas del mismo hecho (nunca el
    agrupamiento automático, que mezclaba hechos). Cada historia trae sus
    notas en orden y la ``storyKey`` con que el CMS las une, si la hay."""
    by_url = _web_by_canonical(web)
    parent: dict[str, str] = {}
    for r in web:
        update = r.get("event_update") if isinstance(r, dict) else None
        if isinstance(update, dict) and r.get("canonical_url") and update.get("of_canonical_url") in by_url:
            parent[str(r["canonical_url"])] = str(update["of_canonical_url"])

    def root(url: str) -> str:
        seen = set()
        while url in parent and url not in seen:
            seen.add(url)
            url = parent[url]
        return url

    chains: dict[str, list[str]] = {}
    for child in parent:
        top = root(child)
        members = chains.setdefault(top, [top])
        for url in (child, parent[child]):
            if url not in members:
                members.append(url)
    items = []
    for top, members in chains.items():
        notes = sorted((by_url[u] for u in members if u in by_url), key=lambda r: float(r.get("published_at_ts") or 0))
        if len(notes) < 2 or now - float(notes[-1].get("published_at_ts") or 0) > days * 86400:
            continue
        items.append({
            "storyKey": (story_key_for(notes[0]["web_url"]) if story_key_for else "") or "",
            "titulo": str(notes[-1].get("titulo") or ""),
            "actualizado": _iso(notes[-1].get("published_at_ts")),
            "notas": [{
                "titulo": str(n.get("titulo") or ""), "url": n["web_url"], "publicada": _iso(n.get("published_at_ts")),
                "novedad": str((n.get("event_update") or {}).get("novedad") or ""),
            } for n in notes],
        })
    items.sort(key=lambda i: i["actualizado"], reverse=True)
    return {"origen": "actualizaciones verificadas del mismo hecho", "items": items}


def _archive_story_key(url: str) -> str:
    try:
        from editorial_context import archive_index as ai

        article = ai.get_by_canonical_url(url)
    except Exception:
        return ""
    key = article.story_key if article else ""
    return key if key.startswith("event:") else ""


# ── Último momento ───────────────────────────────────────────────────────
def build_breaking(flags: dict, *, alert: dict | None, now: float, lookup=None, max_hours: float = 6) -> dict:
    """La nota marcada "Último momento" en el CMS (con su hora) y la alerta del
    SMN si hay una vigente. La marca no vence sola en el CMS: ``vigente`` dice
    si se activó en las últimas ``max_hours``."""
    note = None
    breaking = (flags or {}).get("breaking") if isinstance(flags, dict) else None
    if isinstance(breaking, dict) and breaking.get("post_id"):
        found = (lookup or _archive_by_post_id)(str(breaking["post_id"]))
        if found:
            try:
                activated = datetime.fromisoformat(str(breaking.get("activated_at") or "").replace("Z", "+00:00")).timestamp()
            except ValueError:
                activated = 0
            note = {**found, "activado": _iso(activated) if activated else "", "vigente": bool(activated) and now - activated <= max_hours * 3600}
    active_alert = alert if isinstance(alert, dict) and alert.get("estado") == "activa" else None
    return {"nota": note, "alerta": active_alert}


def _archive_by_post_id(post_id: str) -> dict | None:
    """La nota del CMS por su id: la cola Meta guarda ``web_post_id`` junto a
    ``web_url`` (el archivo editorial no tiene el post_id de las notas propias)."""
    for item in _load("noticias_meta.json", []):
        if isinstance(item, dict) and str(item.get("web_post_id") or "") == post_id and item.get("web_url"):
            return {"titulo": str(item.get("titulo") or ""), "url": item["web_url"], "seccion": str(item.get("seccion") or "").lower()}
    return None


# ── Videos ───────────────────────────────────────────────────────────────
def reel_records(x_reels: dict, paparazzi_jobs: dict, web: list | None = None) -> list[dict]:
    """Reels publicados en Instagram (videos de X y notas con video). La URL
    de la nota sale de lo publicado en la web: al encolarse todavía no existía."""
    by_url = _web_by_canonical(web or [])
    out = []
    for r in (x_reels or {}).values():
        if isinstance(r, dict) and r.get("status") == "completed" and r.get("instagram_id"):
            out.append({"media_id": str(r["instagram_id"]), "titulo": str(r.get("titulo") or ""), "origen": "x",
                        "fuente_video": str(r.get("url") or ""), "url_nota": "", "at": float(r.get("completed_at") or 0)})
    for job in ((paparazzi_jobs or {}).get("jobs") or {}).values():
        if not isinstance(job, dict) or job.get("status") != "completed" or not job.get("instagram_id"):
            continue
        noticia = job.get("noticia") if isinstance(job.get("noticia"), dict) else {}
        out.append({"media_id": str(job["instagram_id"]), "titulo": str(noticia.get("titulo_instagram") or noticia.get("titulo") or ""),
                    "origen": "nota", "fuente_video": "",
                    "url_nota": str(noticia.get("web_url") or (by_url.get(str(noticia.get("canonical_url") or "")) or {}).get("web_url") or ""),
                    "at": float(job.get("completed_at") or 0)})
    out.sort(key=lambda r: r["at"], reverse=True)
    return out


def build_videos(reels: list[dict], permalinks: dict, *, limit: int = 30) -> dict:
    items = []
    for r in reels:
        meta = permalinks.get(r["media_id"]) or {}
        if not meta.get("permalink"):
            continue  # sin enlace verificado no se ofrece
        items.append({
            "titulo": r["titulo"],
            "publicado": _iso(r["at"]),
            "origen": r["origen"],
            "instagram": {"url": meta["permalink"], "miniatura": meta.get("thumbnail_url", ""), "tipo": meta.get("media_type", "")},
            "url_nota": r["url_nota"],
            "fuente_video": r["fuente_video"],
        })
        if len(items) >= limit:
            break
    return {"items": items}


# ── Servicios ────────────────────────────────────────────────────────────
def weather_block(weather) -> dict:
    return {
        "fuente": "Servicio Meteorológico Nacional",
        "estacion": weather.station,
        "observado": f"{weather.observed_date} {weather.observed_at}".strip(),
        "temperatura": weather.temp,
        "cielo": weather.sky,
        "humedad": weather.humidity,
        "viento": weather.wind,
        "pronostico": [{"fecha": d.get("date"), "dia": d.get("label"), "min": d.get("min"), "max": d.get("max"), "lluvia": d.get("rain")} for d in weather.days],
    }


def alert_block(alerts: dict) -> dict:
    if alerts.get("status") != "active":
        return {"fuente": "Servicio Meteorológico Nacional", "estado": "sin_alerta"}
    return {
        "fuente": "Servicio Meteorológico Nacional",
        "estado": "activa",
        "tipo": "aviso a muy corto plazo" if alerts.get("kind") == "aviso" else "alerta",
        "nivel": alerts.get("level"),
        "fenomeno": alerts.get("phenomenon"),
        "zonas": list(alerts.get("zones") or []),
        "vence": alerts.get("expires"),
        "descripcion": alerts.get("description", ""),
    }


def dollar_block(rows: list[dict]) -> dict:
    by = {r["house"]: r for r in rows}
    gap = None
    if "oficial" in by and "blue" in by and by["oficial"]["sell"]:
        gap = round((by["blue"]["sell"] / by["oficial"]["sell"] - 1) * 100, 1)
    return {
        "fuente": "dolarapi.com",
        "cotizaciones": [{"casa": r["house"], "nombre": r["name"], "compra": r["buy"], "venta": r["sell"], "actualizado": r.get("updated_at", "")} for r in rows],
        "brecha_blue_pct": gap,
    }


def holidays_block(holidays: list[dict]) -> dict:
    return {"fuente": "argentina.gob.ar", "proximos": [{"fecha": h["date"], "nombre": h["name"], "tipo": h.get("kind", "")} for h in holidays]}


def payments_block(schedule: list[dict], today: date) -> dict:
    upcoming = sorted((p for p in schedule if p.get("date", "") >= today.isoformat()), key=lambda p: p["date"])
    rows = [{
        "fecha": p["date"],
        "dia": DIAS[date.fromisoformat(p["date"]).weekday()],
        "concepto": p.get("concept", ""),
        "organismos": [{"banco": g.get("title", ""), "items": list(g.get("items") or [])} for g in p.get("groups") or []],
        "url": p.get("url", ""),
    } for p in upcoming]
    return {"fuente": "Hacienda La Rioja", "hoy": [r for r in rows if r["fecha"] == today.isoformat()], "proximos": rows[:6]}


def quakes_block(quakes: list[dict], details: dict, *, now: datetime, days: int = 7) -> dict:
    cutoff = now - timedelta(days=days)
    rows = []
    for q in quakes:
        if "rioja" not in q.get("province", "").lower():
            continue
        try:
            moment = datetime.fromisoformat(q["at"])
        except (KeyError, ValueError):
            continue
        if moment < cutoff:
            continue
        places = (details.get(q["id"]) or {}).get("places") or []
        rows.append({
            "id": q["id"], "fecha": now_ar(moment).isoformat(timespec="seconds"), "magnitud": q["magnitude"],
            "profundidad_km": q["depth_km"], "lugar": places[0] if places else "",
            "estado": {"automatic": "automático", "revised": "revisado", "felt": "sentido"}.get(q.get("status"), "sin dato"),
        })
    rows.sort(key=lambda r: r["fecha"], reverse=True)
    return {"fuente": "INPRES", "ultimos_7_dias": rows[:15]}


def cuts_block(notices: list[dict]) -> dict:
    from utils.service_data import notice_zone

    return {"fuente": "notas de La Voz Riojana", "avisos": [{
        "servicio": n["service"], "titulo": n["title"], "zona": notice_zone(n["title"], n.get("excerpt", "")),
        "url": n["url"], "publicado": n.get("published_at", ""),
    } for n in notices]}


def build_services(previous: dict, *, now: datetime | None = None, fetchers: dict | None = None) -> tuple[dict, list[str]]:
    """Cada bloque por separado. Si una fuente falla se conserva el bloque
    anterior (con su hora); devuelve (documento, fuentes que fallaron)."""
    from utils import service_data as sd

    moment = now_ar(now)
    today = moment.date()
    f = {
        "clima": lambda: weather_block(sd.fetch_weather()),
        "alerta": lambda: alert_block(_alerts(moment)),
        "dolar": lambda: dollar_block(sd.fetch_dollar()),
        "feriados": lambda: holidays_block(sd.upcoming_holidays(today, limit=5)),
        "pagos": lambda: payments_block(sd.fetch_payment_schedule(), today),
        "sismos": lambda: _quakes(moment),
        "cortes": lambda: cuts_block(sd.recent_notices(hours=48, now=moment)),
        **(fetchers or {}),
    }
    doc: dict = {}
    failed: list[str] = []
    for name, fetch in f.items():
        try:
            block = fetch()
            if block is None:
                raise ValueError("sin_dato")
            doc[name] = {**block, "actualizado": _now_iso(moment)}
        except Exception as exc:  # cada fuente falla sola; nunca tumba el feed
            logger.warning("Feed web: %s no disponible (%s: %s)", name, type(exc).__name__, exc)
            failed.append(name)
            if previous.get(name):
                doc[name] = previous[name]
    return doc, failed


def _alerts(moment: datetime) -> dict:
    from utils.social_formats import fetch_alerts_cached

    return fetch_alerts_cached(moment)


def _quakes(moment: datetime) -> dict:
    from utils import service_data as sd

    quakes = sd.fetch_quakes()
    details = {}
    recent = [q for q in quakes if "rioja" in q.get("province", "").lower()][:3]
    for q in recent:
        try:
            details[q["id"]] = sd.fetch_quake_detail(q["id"])
        except sd.ServiceDataError:
            pass
    return quakes_block(quakes, details, now=moment)


# ── Enlaces de Instagram ─────────────────────────────────────────────────
def fetch_permalinks(media_ids: list[str], known: dict, *, limit: int = 120, getter=None) -> dict:
    """Completa ``known`` con permalink, miniatura y tipo de los que faltan
    (lectura de la Graph API; nunca publica). Devuelve sólo los nuevos."""
    from meta.ig_client import GRAPH_API, IG_ACCESS_TOKEN

    if getter is None:
        import requests

        def getter(media_id: str) -> dict | None:
            response = requests.get(f"{GRAPH_API}/{media_id}", params={
                "fields": "permalink,thumbnail_url,media_type,timestamp", "access_token": IG_ACCESS_TOKEN,
            }, timeout=int(os.getenv("IG_REQUEST_TIMEOUT_SECONDS", "30")))
            return response.json() if response.status_code == 200 else None

    new: dict = {}
    for media_id in [m for m in dict.fromkeys(media_ids) if m and m not in known][:limit]:  # los ya conocidos no se piden
        try:
            data = getter(media_id)
        except Exception as exc:
            logger.info("Permalink de Instagram no disponible para %s: %s", media_id, type(exc).__name__)
            continue
        if isinstance(data, dict) and str(data.get("permalink") or "").startswith("https://www.instagram.com/"):
            new[media_id] = {k: str(data.get(k) or "") for k in ("permalink", "thumbnail_url", "media_type", "timestamp")}
    return new


# ── Publicación ──────────────────────────────────────────────────────────
def collect(*, now: datetime | None = None, fetch_links: bool = True) -> tuple[dict[str, dict], list[str]]:
    """Arma todos los documentos. Devuelve ({nombre: documento}, fuentes fallidas)."""
    moment = now_ar(now)
    ts = moment.timestamp()
    state = _load("web_feed_state.json", {})
    insights = (_load("ig_media_insights.json", {}).get("media") or {})
    ig_posted = (_load("ig_posted.json", {"posted": {}}).get("posted") or {})
    web = _load("noticias_web_publicadas.json", [])
    reels = reel_records(_load("x_video_reels.json", {}), _load("paparazzi_video_jobs.json", {}), web)
    permalinks = dict(state.get("permalinks") or {})
    if fetch_links:
        wanted = [r["media_id"] for r in reels[:30]] + most_viewed_media(insights, now=ts)
        permalinks.update(fetch_permalinks(wanted, permalinks))
    services, failed = build_services(state.get("servicios") or {}, now=moment)
    docs = {
        "mas-visto": build_most_viewed(insights, ig_posted, web, permalinks, now=ts),
        "servicios": services,
        "actualizaciones": build_updates(web, now=ts),
        "videos": build_videos(reels, permalinks),
        "historias": build_stories(web, now=ts, story_key_for=_archive_story_key),
        "ultimo-momento": build_breaking(_load("editorial_flags.json", {}), alert=services.get("alerta"), now=ts),
    }
    stamp = _now_iso(moment)
    docs = {name: {"version": VERSION, "actualizado": stamp, **doc} for name, doc in docs.items()}

    def mutate(st):
        st["permalinks"] = permalinks
        st["servicios"] = services
        st["updated_at"] = int(time.time())
        return st

    update_json(STATE_PATH, mutate, {}, expected_type=dict)
    return docs, failed


def publish(docs: dict[str, dict], *, uploader=None) -> tuple[list[str], list[str]]:
    """Sube cada documento y el índice. Devuelve (subidos, fallidos)."""
    from utils import r2_storage

    upload = uploader or r2_storage.upload_file_detailed
    base = os.getenv("R2_PUBLIC_URL", "").rstrip("/")
    ok: list[str] = []
    bad: list[str] = []
    stamp = next(iter(docs.values()))["actualizado"] if docs else _now_iso()
    index = {"version": VERSION, "actualizado": stamp, "feeds": {name: f"{base}/{PREFIX}/{name}.json" for name in docs}}
    for name, doc in [*docs.items(), ("index", index)]:
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, ensure_ascii=False, separators=(",", ":"))
            result = upload(path, f"{PREFIX}/{name}.json", "application/json; charset=utf-8", cache_control=CACHE_CONTROL)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        (ok if result.ok else bad).append(name)
    return ok, bad
