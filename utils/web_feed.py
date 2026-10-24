"""Datos para la web: JSON públicos en R2 que el sitio arma como quiera.

En vez de widgets cerrados, cada ciclo se publican en ``feed/v1/`` del bucket
público (``R2_PUBLIC_URL``) documentos con datos que el pipeline ya tiene
(contrato en ``docs/WEB_FEED.md``, validador de la web en
``lib/feed-types.ts`` del repo del sitio):

* ``mas-visto.json``: notas de la web ordenadas por alcance en Instagram
  (no hay métrica de visitas de la web en el pipeline), con su URL.
* ``servicios.json``: clima, alerta y avisos del SMN, dólar, feriados, pagos a
  estatales, sismos de INPRES y cortes con zona. Si una fuente falla se
  conserva el último dato bueno con su propia hora de actualización.
* ``actualizaciones.json``: pares nota original → nota que la actualiza
  (``utils/same_event.py``), para mostrar el aviso en la nota vieja.
* ``videos.json``: Reels publicados en Instagram con su enlace.
* ``historias.json``: cronologías, sólo de cadenas de actualizaciones
  verificadas del mismo hecho (nunca del agrupamiento automático).
* ``ultimo-momento.json``: la nota marcada en el CMS y la alerta del SMN.
* ``index.json``: qué hay y cuándo se actualizó.

Sólo datos ya publicados o de fuentes oficiales: nada se inventa ni se
completa; un dato desconocido va como ``null``. Los títulos van en texto plano
y en formato oración. Las funciones ``build_*`` son puras (reciben el estado)
para poder probarlas sin red. Antes de subir, ``validate`` revisa cada
documento con las reglas de la web: uno que no pasa no se sube y queda el
anterior.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone

from utils.file_manager import JsonStateError, load_json, update_json
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.social_time import DIAS, now_ar

logger = setup_logger("web_feed", "web_feed.log")

VERSION = 1
PREFIX = "feed/v1"
STATE_PATH = str(data_dir() / "web_feed_state.json")
CACHE_CONTROL = "public, max-age=300"
SITE_PREFIX = "https://lavozriojana.com/noticias/"
# Slugs de sección del CMS (claves de ``por_seccion_7d``).
SECTIONS = ("politica", "policiales", "interior", "sociedad", "economia", "salud", "educacion", "deportes",
            "cultura", "espectaculos", "ultimo-momento")


def _iso(ts: float | int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(now_ar().tzinfo).isoformat(timespec="seconds")


def _iso_text(value) -> str | None:
    """ISO de la fuente (con ``Z``, offset o UTC sin zona) → ISO con ``-03:00``."""
    text = str(value or "").strip()
    if not text:
        return None
    # Python 3.10 sólo lee fracciones de 3 o 6 dígitos: se normalizan a 6.
    text = re.sub(r"\.(\d{1,9})", lambda m: "." + m.group(1)[:6].ljust(6, "0"), text, count=1)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return now_ar(moment).isoformat(timespec="seconds")


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


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def section_slug(value) -> str | None:
    """"Policiales" → "policiales"; una sección que el CMS no tiene → ``None``."""
    slug = _fold(str(value or "")).strip().replace(" ", "-")
    return slug if slug in SECTIONS else None


# ── Títulos en texto plano y formato oración ─────────────────────────────
_EMOJI_CATEGORIES = {"So", "Sk", "Cs", "Co", "Cn"}
_INVISIBLE = {"‍", "️", "︎", "⃣"}
# Palabras chicas que nunca toman mayúscula por sí solas ("la" de "La Rioja"
# se resuelve con los nombres compuestos de abajo).
_LOWER_WORDS = {"a", "al", "ante", "con", "de", "del", "el", "en", "la", "las", "lo", "los", "o", "para", "por",
                "que", "se", "sin", "su", "sus", "tras", "u", "un", "una", "y", "e", "es", "le", "les"}
# Nombres propios que la nota puede no traer escritos con mayúscula:
# departamentos y localidades riojanas, provincias y algunos compuestos.
# Quedan afuera los que también son palabras comunes ("Capital",
# "Independencia", "Salta", "Misiones", "Milagro").
_PLACES = ("Aimogasta", "Chepes", "Patquía", "Nonogasta", "Anguinán", "Villa Unión", "Guandacol", "Santa Florentina",
           "Villa Castelli", "Chañarmuyo", "Ulapes", "Aminga", "Anillaco", "Malanzán", "Catuna", "Villa Mazán",
           "Sañogasta", "Vichigasta", "Pituil", "Los Sarmientos", "Talampaya", "Alpasinche", "Pagancillo",
           "Talamuyuna", "Chuquis", "Olta", "Tinogasta", "Andalgalá", "Los Llanos",
           "Buenos Aires", "Catamarca", "Chaco", "Chubut", "Córdoba", "Corrientes", "Entre Ríos", "Formosa", "Jujuy",
           "La Pampa", "La Rioja", "Mendoza", "Neuquén", "Río Negro", "San Juan", "San Luis", "Santa Cruz", "Santa Fe",
           "Santiago del Estero", "Tierra del Fuego", "Tucumán", "Argentina",
           "La Plata", "La Matanza", "Las Heras", "Mar del Plata", "Casa Rosada", "Corte Suprema", "El Chacho")
_NOT_PLACES = {"Capital", "Independencia"}


def _proper_places() -> list[str]:
    from utils.service_data import RIOJA_DEPARTMENT_POINTS

    names = {*_PLACES, *(d for d in RIOJA_DEPARTMENT_POINTS if d not in _NOT_PLACES)}
    return sorted(names, key=len, reverse=True)


def _fold_chars(text: str) -> str:
    """Como ``_fold`` pero carácter por carácter: conserva las posiciones."""
    return "".join(_fold(c)[:1] or c for c in text)
_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+(?:['’][A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)?")


def plain_text(value) -> str:
    """Sin HTML, markdown ni emojis; espacios colapsados."""
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"[*_`#]+", "", text)
    text = "".join(" " if unicodedata.category(c) in _EMOJI_CATEGORIES else c for c in text if c not in _INVISIBLE)
    text = re.sub(r"[\u0000-\u001f\u007f]+", " ", text)
    return re.sub(r"\s+", " ", text).strip(" -–—|·")


def _mostly_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.7


def _casing_map(references: tuple[str, ...]) -> dict[str, str]:
    """Cómo se escribe cada palabra en textos con mayúsculas normales (el
    título original de la fuente, la bajada): mayúscula si casi siempre la
    lleva fuera del comienzo de oración, sigla si va toda en mayúsculas."""
    votes: dict[str, dict[str, int]] = {}
    for ref in references:
        ref = plain_text(ref)
        if not ref or _mostly_upper(ref):
            continue
        for sentence in re.split(r"(?<=[.!?:])\s+|\n", ref):
            for i, match in enumerate(_WORD_RE.finditer(sentence)):
                word = match.group(0)
                if i == 0 or word.isdigit():
                    continue
                form = word if (word.isupper() and len(word) >= 2) or word[:1].isupper() else word.lower()
                bucket = votes.setdefault(word.lower(), {})
                bucket[form] = bucket.get(form, 0) + 1
    out = {}
    for key, forms in votes.items():
        best, count = max(forms.items(), key=lambda kv: kv[1])
        if best != key and count > forms.get(key, 0):
            out[key] = best
    return out


def clean_title(title, *references: str) -> str:
    """Título en texto plano y formato oración. Si viene en MAYÚSCULAS, las
    mayúsculas de nombres propios y siglas salen de ``references`` (textos de
    la misma nota): nada se adivina fuera de eso y de los nombres compuestos."""
    text = plain_text(title)
    if not _mostly_upper(text):
        return text[:1].upper() + text[1:]
    casing = _casing_map(references)

    def word(match: re.Match) -> str:
        lower = match.group(0).lower()
        if lower in _LOWER_WORDS:
            return lower
        return casing.get(lower, lower)

    text = unicodedata.normalize("NFC", _WORD_RE.sub(word, text.lower()))
    for name in _proper_places():
        folded = _fold_chars(text)
        for match in reversed(list(re.finditer(rf"(?<![\w]){re.escape(_fold(name))}(?![\w])", folded))):
            text = text[: match.start()] + name + text[match.end():]
    return text[:1].upper() + text[1:]


def _refs(*records: dict) -> tuple[str, ...]:
    keys = ("titulo_original_scrapeado", "titulo_instagram", "excerpt", "texto_instagram", "caption", "copete")
    return tuple(str(r.get(k) or "") for r in records if isinstance(r, dict) for k in keys)


# ── Lo más visto ─────────────────────────────────────────────────────────
def _number(value) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if float(value).is_integer() else value


def build_most_viewed(insights: dict, ig_posted: dict, web: list, permalinks: dict, *, now: float,
                      limit: int = 50, per_section: int = 30) -> dict:
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
        link = (permalinks.get(str(media_id)) or {}).get("permalink") or None
        rows.append({
            "titulo": clean_title(page.get("titulo") or record.get("titulo"), *_refs(page, record)),
            "url": page["web_url"],
            "seccion": section_slug(metrics.get("seccion") or record.get("seccion")),
            "publicada": _iso(page.get("published_at_ts") or posted),
            "instagram": {"url": link, "alcance": _number(metrics.get("reach")), "interacciones": _number(metrics.get("interactions"))},
            "_posted": posted,
        })
    rank = lambda r: (r["instagram"]["alcance"] or 0, r["instagram"]["interacciones"] or 0)  # noqa: E731
    rows = [r for r in rows if r["titulo"] and r["instagram"]["alcance"] is not None]

    def public(r: dict) -> dict:
        return {k: v for k, v in r.items() if k != "_posted"}

    def window(hours: int) -> list[dict]:
        return [public(r) for r in sorted((r for r in rows if now - r["_posted"] <= hours * 3600), key=rank, reverse=True)[:limit]]

    by_section: dict[str, list[dict]] = {}
    for r in sorted((r for r in rows if now - r["_posted"] <= 7 * 86400), key=rank, reverse=True):
        if not r["seccion"]:
            continue
        bucket = by_section.setdefault(r["seccion"], [])
        if len(bucket) < per_section:
            bucket.append(public(r))
    return {"metrica": "alcance en Instagram", "ventanas": {"24h": window(24), "7d": window(7 * 24)}, "por_seccion_7d": by_section}


def most_viewed_media(insights: dict, *, now: float, limit: int = 50) -> list[str]:
    """Los posts que pueden entrar al ranking (para pedir sólo esos enlaces)."""
    recent = [(m, v) for m, v in (insights or {}).items() if isinstance(v, dict) and now - float(v.get("posted_at") or 0) <= 7 * 86400]
    recent.sort(key=lambda mv: float(mv[1].get("reach") or 0), reverse=True)
    return [m for m, _ in recent[: limit * 3]]


# ── Actualizaciones ──────────────────────────────────────────────────────
def build_updates(web: list, *, now: float, days: int = 7) -> dict:
    """Un par por actualización: ``nota`` es la ORIGINAL (más vieja) y
    ``actualiza`` la nueva que trae la novedad. Una cadena A→B→C sale como
    A→B y B→C; la web la sigue."""
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
        if not previous_url or previous_url == r["web_url"]:
            continue
        items.append({
            "nota": {"titulo": clean_title(previous.get("titulo") or update.get("of_title"), *_refs(previous)),
                     "url": previous_url, "publicada": _iso(previous.get("published_at_ts"))},
            "actualiza": {"titulo": clean_title(r.get("titulo"), *_refs(r)), "url": r["web_url"]},
            "novedad": plain_text(update.get("novedad"))[:400] or None,
            "_at": published,
        })
    items.sort(key=lambda i: i["_at"], reverse=True)
    return {"items": [{k: v for k, v in i.items() if k != "_at"} for i in items]}


# ── Cronologías ──────────────────────────────────────────────────────────
def build_stories(web: list, *, now: float, days: int = 30, story_key_for=None) -> dict:
    """Cadenas de actualizaciones verificadas del mismo hecho (nunca el
    agrupamiento automático, que mezclaba hechos). Cada historia trae todas
    sus notas en orden y la ``storyKey`` ``event:`` con que el CMS las une;
    una cadena sin esa clave (anterior al 2026-10-23) no sale."""
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
        notes = sorted((by_url[u] for u in members if u in by_url and by_url[u].get("published_at_ts")),
                       key=lambda r: float(r.get("published_at_ts") or 0))
        if len(notes) < 2 or now - float(notes[-1].get("published_at_ts") or 0) > days * 86400:
            continue
        key = ""
        for note in notes:
            key = (story_key_for(note["web_url"]) if story_key_for else "") or ""
            if key:
                break
        if not key.startswith("event:"):
            continue
        items.append({
            "storyKey": key,
            "titulo": clean_title(notes[-1].get("titulo"), *_refs(notes[-1])),
            "actualizado": _iso(notes[-1].get("published_at_ts")),
            "notas": [{
                "titulo": clean_title(n.get("titulo"), *_refs(n)), "url": n["web_url"], "publicada": _iso(n.get("published_at_ts")),
                "novedad": plain_text((n.get("event_update") or {}).get("novedad"))[:400],
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
    si se activó en las últimas ``max_hours`` (la web igual la oculta a las 12 h)."""
    note = None
    breaking = (flags or {}).get("breaking") if isinstance(flags, dict) else None
    if isinstance(breaking, dict) and breaking.get("post_id"):
        found = (lookup or _archive_by_post_id)(str(breaking["post_id"]))
        activated = _iso_text(breaking.get("activated_at"))
        if found and activated:
            elapsed = now - datetime.fromisoformat(activated).timestamp()
            note = {**found, "activado": activated, "vigente": 0 <= elapsed <= max_hours * 3600}
    return {"nota": note, "alerta": active_alert(alert, now=now)}


def active_alert(alert: dict | None, *, now: float) -> dict | None:
    """La alerta sólo si está activa y no venció; si no, ``None``."""
    if not isinstance(alert, dict) or alert.get("estado") != "activa":
        return None
    try:
        if datetime.fromisoformat(str(alert.get("vence"))).timestamp() <= now:
            return None
    except ValueError:
        return None
    return alert


def _archive_by_post_id(post_id: str) -> dict | None:
    """La nota del CMS por su id: la cola Meta guarda ``web_post_id`` junto a
    ``web_url`` (el archivo editorial no tiene el post_id de las notas propias)."""
    for item in _load("noticias_meta.json", []):
        if isinstance(item, dict) and str(item.get("web_post_id") or "") == post_id and item.get("web_url"):
            return {"titulo": clean_title(item.get("titulo"), *_refs(item)), "url": item["web_url"],
                    "seccion": section_slug(item.get("seccion"))}
    return None


# ── Videos ───────────────────────────────────────────────────────────────
def reel_records(x_reels: dict, paparazzi_jobs: dict, web: list | None = None) -> list[dict]:
    """Reels publicados en Instagram (videos de X y notas con video). La URL
    de la nota sale de lo publicado en la web: al encolarse todavía no existía."""
    by_url = _web_by_canonical(web or [])
    out = []
    for r in (x_reels or {}).values():
        if isinstance(r, dict) and r.get("status") == "completed" and r.get("instagram_id"):
            out.append({"media_id": str(r["instagram_id"]), "titulo": clean_title(r.get("titulo"), *_refs(r)), "origen": "x",
                        "fuente_video": str(r.get("url") or "") or None, "url_nota": None, "at": float(r.get("completed_at") or 0)})
    for job in ((paparazzi_jobs or {}).get("jobs") or {}).values():
        if not isinstance(job, dict) or job.get("status") != "completed" or not job.get("instagram_id"):
            continue
        noticia = job.get("noticia") if isinstance(job.get("noticia"), dict) else {}
        page = by_url.get(str(noticia.get("canonical_url") or "")) or {}
        out.append({"media_id": str(job["instagram_id"]),
                    "titulo": clean_title(noticia.get("titulo_instagram") or noticia.get("titulo"), *_refs(noticia, page)),
                    "origen": "nota", "fuente_video": None,
                    "url_nota": str(noticia.get("web_url") or page.get("web_url") or "") or None,
                    "at": float(job.get("completed_at") or 0)})
    out.sort(key=lambda r: r["at"], reverse=True)
    return out


def build_videos(reels: list[dict], permalinks: dict, *, now: float, limit: int = 25) -> dict:
    items = []
    for r in reels:
        meta = permalinks.get(r["media_id"]) or {}
        if not meta.get("permalink") or not r["titulo"] or not r["at"] or r["at"] > now:
            continue  # sin enlace verificado no se ofrece; nada programado a futuro
        items.append({
            "titulo": r["titulo"],
            "publicado": _iso(r["at"]),
            "origen": r["origen"],
            "instagram": {"url": meta["permalink"], "miniatura": meta.get("thumbnail_url") or None, "tipo": meta.get("media_type") or None},
            "url_nota": r["url_nota"],
            "fuente_video": r["fuente_video"],
        })
        if len(items) >= limit:
            break
    return {"items": items}


# ── Servicios ────────────────────────────────────────────────────────────
_MONTHS = {m: i + 1 for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                           "septiembre", "octubre", "noviembre", "diciembre"))}


def observed_iso(observed_date: str, observed_at: str) -> str | None:
    """"23-octubre-2026", "12:00" (hora de la observación del SMN) → ISO."""
    try:
        day, month, year = str(observed_date).strip().split("-")
        hour, minute = str(observed_at).strip().split(":")[:2]
        moment = datetime(int(year), _MONTHS[_fold(month)], int(day), int(hour), int(minute))
    except (KeyError, ValueError):
        return None
    return moment.replace(tzinfo=now_ar().tzinfo).isoformat(timespec="seconds")


def _mm(value) -> str | None:
    """Lluvia del pronóstico del SMN: milímetros acumulados del día, como texto
    ("2,5 mm"): un número la web lo leería como probabilidad."""
    if not isinstance(value, (int, float)):
        return None
    return f"{value:g} mm".replace(".", ",")


def _wind(value) -> str | None:
    """"Norte  13" (el SMN informa km/h sin unidad) → "Norte 13 km/h"; "Calma" igual."""
    text = plain_text(value)
    return (f"{text} km/h" if re.search(r"\d$", text) else text) or None


def weather_block(weather, *, today: date) -> dict:
    return {
        "fuente": "Servicio Meteorológico Nacional",
        "estacion": weather.station,
        "observado": observed_iso(weather.observed_date, weather.observed_at),
        "temperatura": weather.temp,
        "cielo": plain_text(weather.sky).lower() or None,
        "humedad": weather.humidity,
        "viento": _wind(weather.wind),
        "pronostico": [{"fecha": d.get("date"), "dia": DIAS[date.fromisoformat(d["date"]).weekday()],
                        "min": d.get("min"), "max": d.get("max"), "lluvia": _mm(d.get("rain"))}
                       for d in weather.days if d.get("date") and d["date"] >= today.isoformat()],
    }


def alert_block(alerts: dict) -> dict:
    """Alerta activa del SMN (``actualizado`` = emisión del SMN) o
    ``{"estado": "sin_alerta"}``, que en los documentos sale como ``null``."""
    if alerts.get("status") != "active":
        return {"fuente": "Servicio Meteorológico Nacional", "estado": "sin_alerta"}
    block = {
        "fuente": "Servicio Meteorológico Nacional",
        "estado": "activa",
        "tipo": "aviso a muy corto plazo" if alerts.get("kind") == "aviso" else "alerta",
        "nivel": alerts.get("level"),
        "fenomeno": plain_text(alerts.get("phenomenon")),
        "zonas": list(alerts.get("zones") or []),
        "vence": _iso_text(alerts.get("expires")),
        "descripcion": plain_text(alerts.get("description"))[:4000] or None,
    }
    sent = _iso_text(alerts.get("sent"))
    if sent:
        block["actualizado"] = sent
    return block


def dollar_block(rows: list[dict]) -> dict:
    by = {r["house"]: r for r in rows}
    gap = None
    if "oficial" in by and "blue" in by and by["oficial"]["sell"]:
        gap = round((by["blue"]["sell"] / by["oficial"]["sell"] - 1) * 100, 2)
    quotes = []
    for r in rows:
        updated = _iso_text(r.get("updated_at"))
        if updated:  # sin hora de la fuente la web la descarta
            quotes.append({"casa": r["house"], "nombre": r["name"], "compra": r["buy"], "venta": r["sell"], "actualizado": updated})
    return {"fuente": "DolarApi.com", "cotizaciones": quotes, "brecha_blue_pct": gap}


def holidays_block(holidays: list[dict]) -> dict:
    return {"fuente": "argentina.gob.ar", "proximos": [{"fecha": h["date"], "nombre": h["name"], "tipo": h.get("kind") or None} for h in holidays]}


def payments_block(schedule: list[dict], today: date) -> dict:
    upcoming = sorted((p for p in schedule if p.get("date", "") >= today.isoformat()), key=lambda p: p["date"])
    rows = [{
        "fecha": p["date"],
        "dia": DIAS[date.fromisoformat(p["date"]).weekday()],
        "concepto": plain_text(p.get("concept")),
        "organismos": [{"banco": plain_text(g.get("title")) or "Sin banco indicado", "items": [plain_text(i) for i in g.get("items") or []]}
                       for g in p.get("groups") or []],
        "url": p.get("url") or None,
    } for p in upcoming]
    return {"fuente": "Hacienda La Rioja", "hoy": [r for r in rows if r["fecha"] == today.isoformat()], "proximos": rows[:6]}


_QUAKE_STATES = {"automatic": "automático", "revised": "revisado", "felt": "sentido"}


def quakes_block(quakes: list[dict], details: dict, *, now: datetime, days: int = 7) -> dict:
    """Sismos de La Rioja de los últimos ``days`` días. ``lugar`` es la
    localidad más cercana según INPRES; sin detalle, la provincia del listado."""
    cutoff = now - timedelta(days=days)
    rows = []
    for q in quakes:
        if "rioja" not in q.get("province", "").lower() or q.get("status") not in _QUAKE_STATES:
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
            "profundidad_km": q["depth_km"], "lugar": (places[0] if places else q["province"].title())[:240],
            "estado": _QUAKE_STATES[q["status"]],
        })
    rows.sort(key=lambda r: r["fecha"], reverse=True)
    return {"fuente": "INPRES", "ultimos_7_dias": rows[:50]}


def cuts_block(notices: list[dict]) -> dict:
    from utils.service_data import notice_zone

    avisos = []
    for n in notices:
        published = _iso_text(n.get("published_at"))
        if not published or not str(n.get("url") or "").startswith("https://"):
            continue
        avisos.append({
            "servicio": n["service"], "titulo": clean_title(n["title"], n.get("excerpt", "")),
            "zona": notice_zone(n["title"], n.get("excerpt", ""))[:200] or None,
            "url": n["url"], "publicado": published,
        })
    return {"fuente": "Notas de La Voz Riojana", "avisos": avisos}


def build_services(previous: dict, *, now: datetime | None = None, fetchers: dict | None = None) -> tuple[dict, list[str]]:
    """Cada bloque por separado. Si una fuente falla se conserva el bloque
    anterior (con su hora); devuelve (documento, fuentes que fallaron)."""
    from utils import service_data as sd

    moment = now_ar(now)
    today = moment.date()
    f = {
        "clima": lambda: weather_block(sd.fetch_weather(), today=today),
        "alerta": lambda: alert_block(_alerts(moment)),
        "dolar": lambda: dollar_block(sd.fetch_dollar()),
        "feriados": lambda: holidays_block(sd.upcoming_holidays(today, limit=5)),
        "pagos": lambda: payments_block(sd.fetch_payment_schedule(), today),
        "sismos": lambda: _quakes(moment),
        "cortes": lambda: cuts_block(sd.recent_notices(hours=72, now=moment)),
        **(fetchers or {}),
    }
    doc: dict = {}
    failed: list[str] = []
    for name, fetch in f.items():
        try:
            block = fetch()
            if block is None:
                raise ValueError("sin_dato")
            # La hora de la fuente (la emisión de una alerta) manda sobre la de la consulta.
            doc[name] = {"actualizado": _now_iso(moment), **block}
        except Exception as exc:  # cada fuente falla sola; nunca tumba el feed
            logger.warning("Feed web: %s no disponible (%s: %s)", name, type(exc).__name__, exc)
            failed.append(name)
            if previous.get(name):
                doc[name] = previous[name]
    return doc, failed


def public_services(services: dict, *, now: float) -> dict:
    """``servicios.json``: la alerta sólo si está activa y vigente."""
    return {**services, "alerta": active_alert(services.get("alerta"), now=now)}


def _alerts(moment: datetime) -> dict:
    from utils.social_formats import fetch_alerts_cached

    return fetch_alerts_cached(moment)


_QUAKE_DETAILS: dict = {}


def _quakes(moment: datetime) -> dict:
    """Detalle (localidad más cercana) de cada sismo riojano de la semana; los
    ya leídos se toman de ``_QUAKE_DETAILS``, que ``collect`` guarda en el estado."""
    from utils import service_data as sd

    quakes = sd.fetch_quakes()
    for q in [q for q in quakes if "rioja" in q.get("province", "").lower()][:50]:
        if q["id"] in _QUAKE_DETAILS:
            continue
        try:
            detail = sd.fetch_quake_detail(q["id"])
        except sd.ServiceDataError:
            continue
        if detail.get("places"):
            _QUAKE_DETAILS[q["id"]] = {"places": detail["places"][:1]}
    return quakes_block(quakes, _QUAKE_DETAILS, now=moment)


# ── Enlaces de Instagram ─────────────────────────────────────────────────
def fetch_permalinks(media_ids: list[str], known: dict, *, refresh: list[str] | None = None, limit: int = 120, getter=None) -> dict:
    """Permalink, miniatura y tipo de los posts que faltan en ``known`` y de los
    de ``refresh`` (la miniatura es una URL firmada que vence: los videos se
    piden en cada corrida). Lectura de la Graph API; nunca publica. Devuelve
    sólo lo leído ahora."""
    from meta.ig_client import GRAPH_API, IG_ACCESS_TOKEN

    if getter is None:
        import requests

        def getter(media_id: str) -> dict | None:
            response = requests.get(f"{GRAPH_API}/{media_id}", params={
                "fields": "permalink,thumbnail_url,media_type,timestamp", "access_token": IG_ACCESS_TOKEN,
            }, timeout=int(os.getenv("IG_REQUEST_TIMEOUT_SECONDS", "30")))
            return response.json() if response.status_code == 200 else None

    again = set(refresh or [])
    wanted = [m for m in dict.fromkeys([*(refresh or []), *media_ids]) if m and (m in again or m not in known)]
    new: dict = {}
    for media_id in wanted[:limit]:
        try:
            data = getter(media_id)
        except Exception as exc:
            logger.info("Permalink de Instagram no disponible para %s: %s", media_id, type(exc).__name__)
            continue
        if isinstance(data, dict) and str(data.get("permalink") or "").startswith("https://www.instagram.com/"):
            new[media_id] = {k: str(data.get(k) or "") for k in ("permalink", "thumbnail_url", "media_type", "timestamp")}
    return new


# ── Validación (reglas de lib/feed-types.ts de la web) ───────────────────
_ISO_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_IG_PATH = re.compile(r"^https://(www\.)?instagram\.com/(?:[A-Za-z0-9._]{1,30}/)?(p|reel|reels|tv)/[A-Za-z0-9_-]{5,40}/?(\?.*)?$")


def _is_dt(value) -> bool:
    if not isinstance(value, str) or not _ISO_DT.match(value.strip()):
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _is_date(value) -> bool:
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _is_text(value, limit: int) -> bool:
    return isinstance(value, str) and 0 < len(plain_text(value)) <= limit and value == value.strip()


def _is_news_url(value) -> bool:
    if not isinstance(value, str) or not value.startswith(SITE_PREFIX):
        return False
    slug = value[len(SITE_PREFIX):].rstrip("/")
    return bool(_SLUG.match(slug)) and len(slug) <= 200


def _is_title(value, limit: int = 300) -> bool:
    return _is_text(value, limit) and value == plain_text(value) and not _mostly_upper(value)


def _check_item(name: str, item) -> str:
    """Motivo por el que la web descartaría la entrada, o "" si pasa."""
    if not isinstance(item, dict):
        return "no es un objeto"
    if name == "mas-visto":
        if not _is_title(item.get("titulo")) or not _is_news_url(item.get("url")):
            return "titulo/url"
        if item.get("seccion") is not None and not _is_text(item["seccion"], 80):
            return "seccion"
        ig = item.get("instagram") or {}
        if ig.get("url") is not None and not _IG_PATH.match(str(ig["url"])):
            return "instagram.url"
        if ig.get("alcance") is not None and _number(ig["alcance"]) is None:
            return "alcance"
    elif name == "actualizaciones":
        nota, nueva = item.get("nota") or {}, item.get("actualiza") or {}
        if not (_is_title(nota.get("titulo")) and _is_news_url(nota.get("url")) and _is_title(nueva.get("titulo")) and _is_news_url(nueva.get("url"))):
            return "nota/actualiza"
        if nota["url"] == nueva["url"]:
            return "se actualiza a sí misma"
        if item.get("novedad") is not None and not _is_text(item["novedad"], 400):
            return "novedad"
    elif name == "historias":
        if not re.match(r"^event:[A-Za-z0-9_:-]{1,150}$", str(item.get("storyKey") or "")):
            return "storyKey"
        if not _is_title(item.get("titulo")) or not _is_dt(item.get("actualizado")):
            return "titulo/actualizado"
        if any(not (_is_title(n.get("titulo")) and _is_news_url(n.get("url")) and _is_dt(n.get("publicada"))) for n in item.get("notas") or []):
            return "notas"
    elif name == "videos":
        ig = item.get("instagram") or {}
        if not _is_title(item.get("titulo")) or not _is_dt(item.get("publicado")) or item.get("origen") not in ("nota", "x"):
            return "titulo/publicado/origen"
        if not _IG_PATH.match(str(ig.get("url") or "")):
            return "instagram.url"
        if item.get("url_nota") is not None and not _is_news_url(item["url_nota"]):
            return "url_nota"
    elif name == "cortes":
        if item.get("servicio") not in ("luz", "agua", "rutas") or not _is_title(item.get("titulo")) or not _is_dt(item.get("publicado")):
            return "servicio/titulo/publicado"
        if not str(item.get("url") or "").startswith(("https://", "http://")):
            return "url"
    elif name == "sismos":
        if not _is_dt(item.get("fecha")) or not _is_text(item.get("lugar"), 240) or item.get("estado") not in ("automático", "revisado", "sentido"):
            return "fecha/lugar/estado"
        if _number(item.get("magnitud")) is None or not 0 <= item["magnitud"] <= 10:
            return "magnitud"
    elif name == "cotizaciones":
        if not _is_text(item.get("casa"), 40) or not _is_text(item.get("nombre"), 80) or not _is_dt(item.get("actualizado")):
            return "casa/nombre/actualizado"
    elif name in ("pagos", "pronostico", "feriados"):
        if not _is_date(item.get("fecha")):
            return "fecha"
    return ""


def _check_alert(alert: dict) -> str:
    if not _is_text(alert.get("fuente"), 160) or alert.get("estado") != "activa":
        return "fuente/estado"
    if alert.get("tipo") not in ("alerta", "aviso a muy corto plazo") or alert.get("nivel") not in ("amarilla", "naranja", "roja"):
        return "tipo/nivel"
    if not _is_text(alert.get("fenomeno"), 80) or not _is_dt(alert.get("vence")) or not _is_dt(alert.get("actualizado")):
        return "fenomeno/vence/actualizado"
    return ""


def validate(name: str, doc: dict, *, now: datetime | None = None) -> tuple[list[str], list[str]]:
    """Revisa un documento con las reglas de la web. Devuelve (errores que
    harían descartar el archivo entero, entradas o bloques que se descartarían)."""
    errors: list[str] = []
    dropped: list[str] = []
    moment = now_ar(now)
    if doc.get("version") != VERSION:
        errors.append("version")
    if not _is_dt(doc.get("actualizado")):
        errors.append("actualizado sin zona")
    elif datetime.fromisoformat(doc["actualizado"].replace("Z", "+00:00")) > moment + timedelta(minutes=10):
        errors.append("actualizado en el futuro")
    if len(json.dumps(doc, ensure_ascii=False).encode("utf-8")) >= 2 * 1024 * 1024:
        errors.append("pesa 2 MB o más")

    def items(kind: str, values, label: str) -> None:
        for i, item in enumerate(values or []):
            reason = _check_item(kind, item)
            if reason:
                dropped.append(f"{label}[{i}]: {reason}")

    if name == "mas-visto":
        if "instagram" not in str(doc.get("metrica") or "").lower():
            dropped.append("metrica sin Instagram")
        for window in ("24h", "7d"):
            items("mas-visto", (doc.get("ventanas") or {}).get(window), f"ventanas.{window}")
        for key, values in (doc.get("por_seccion_7d") or {}).items():
            if not _SLUG.match(key):
                dropped.append(f"por_seccion_7d.{key}: clave")
            items("mas-visto", values, f"por_seccion_7d.{key}")
    elif name in ("actualizaciones", "historias", "videos"):
        items(name, doc.get("items"), "items")
    elif name == "ultimo-momento":
        nota = doc.get("nota")
        if nota is not None and not (_is_title(nota.get("titulo")) and _is_news_url(nota.get("url")) and _is_dt(nota.get("activado")) and isinstance(nota.get("vigente"), bool)):
            dropped.append("nota")
        if doc.get("alerta") is not None and _check_alert(doc["alerta"]):
            dropped.append(f"alerta: {_check_alert(doc['alerta'])}")
    elif name == "servicios":
        for block_name in ("clima", "alerta", "dolar", "feriados", "pagos", "sismos", "cortes"):
            block = doc.get(block_name)
            if block is None:
                continue
            if not _is_text(block.get("fuente"), 160) or not _is_dt(block.get("actualizado")):
                dropped.append(f"{block_name}: fuente/actualizado")
                continue
            if block_name == "alerta" and _check_alert(block):
                dropped.append(f"alerta: {_check_alert(block)}")
            if block_name == "clima":
                if block.get("observado") is not None and not _is_dt(block["observado"]):
                    dropped.append("clima.observado")
                items("pronostico", block.get("pronostico"), "clima.pronostico")
            items("cotizaciones", block.get("cotizaciones") if block_name == "dolar" else None, "dolar.cotizaciones")
            items("feriados", block.get("proximos") if block_name == "feriados" else None, "feriados.proximos")
            if block_name == "pagos":
                items("pagos", [*(block.get("hoy") or []), *(block.get("proximos") or [])], "pagos")
            items("sismos", block.get("ultimos_7_dias") if block_name == "sismos" else None, "sismos")
            items("cortes", block.get("avisos") if block_name == "cortes" else None, "cortes")
    return errors, dropped


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
        videos = [r["media_id"] for r in reels[:25]]
        permalinks.update(fetch_permalinks(most_viewed_media(insights, now=ts), permalinks, refresh=videos))
    _QUAKE_DETAILS.clear()
    _QUAKE_DETAILS.update(state.get("quake_details") or {})
    services, failed = build_services(state.get("servicios") or {}, now=moment)
    docs = {
        "mas-visto": build_most_viewed(insights, ig_posted, web, permalinks, now=ts),
        "servicios": public_services(services, now=ts),
        "actualizaciones": build_updates(web, now=ts),
        "videos": build_videos(reels, permalinks, now=ts),
        "historias": build_stories(web, now=ts, story_key_for=_archive_story_key),
        "ultimo-momento": build_breaking(_load("editorial_flags.json", {}), alert=services.get("alerta"), now=ts),
    }
    stamp = _now_iso(moment)
    docs = {name: {"version": VERSION, "actualizado": stamp, **doc} for name, doc in docs.items()}
    week_ago = (moment - timedelta(days=8)).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")

    def mutate(st):
        st["permalinks"] = permalinks
        st["servicios"] = services
        st["quake_details"] = {k: v for k, v in _QUAKE_DETAILS.items() if k >= week_ago}
        st["updated_at"] = int(time.time())
        return st

    update_json(STATE_PATH, mutate, {}, expected_type=dict)
    return docs, failed


def publish(docs: dict[str, dict], *, uploader=None, now: datetime | None = None) -> tuple[list[str], list[str]]:
    """Valida y sube cada documento, y después el índice. Uno que no valida no
    se sube (queda el anterior en R2). Devuelve (subidos, fallidos)."""
    from utils import r2_storage

    upload = uploader or r2_storage.upload_file_detailed
    base = os.getenv("R2_PUBLIC_URL", "").rstrip("/")
    ok: list[str] = []
    bad: list[str] = []
    for name, doc in docs.items():
        errors, dropped = validate(name, doc, now=now)
        if dropped:
            logger.warning("Feed web %s: la web descartaría %d entradas: %s", name, len(dropped), "; ".join(dropped[:5]))
        if errors:
            logger.error("Feed web %s no se sube (%s); queda el anterior", name, ", ".join(errors))
            bad.append(name)
            continue
        (ok if _upload(upload, name, doc) else bad).append(name)
    if ok:
        stamp = docs[ok[0]]["actualizado"]
        index = {"version": VERSION, "actualizado": stamp, "feeds": {name: f"{base}/{PREFIX}/{name}.json" for name in docs}}
        if not _upload(upload, "index", index):
            bad.append("index")
    return ok, bad


def _upload(upload, name: str, doc: dict) -> bool:
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
    return bool(result.ok)
