"""Datos de servicio para La Rioja: clima y alertas del SMN, dólar, feriados
y avisos de cortes/rutas.

Cada función devuelve datos tal como los publica la fuente (o ``None``/vacío
si no hay datos verificables): nunca completa ni estima. Los avisos de cortes
y rutas salen de notas ya publicadas por La Voz Riojana (EDELaR y Aguas
Riojanas no tienen un listado de cortes en sus sitios).
"""
from __future__ import annotations

import io
import json
import re
import sqlite3
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import requests

from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.safe_http import UnsafeURLError, safe_get
from utils.social_time import DIAS, DIAS_CORTOS, MESES_CORTOS, now_ar

logger = setup_logger("service_data", "service_data.log")

USER_AGENT = "LaVozRiojanaBot/1.0 (+https://lavozriojana.com; servicios)"
SMN_OPEN_DATA = "https://ssl.smn.gob.ar/dpd/zipopendata.php?dato={dato}"
DOLLAR_URL = "https://dolarapi.com/v1/dolares"
HOLIDAYS_URL = "https://www.argentina.gob.ar/sites/default/files/holidays-{year}-es.json"
TIMEOUT = 30


class ServiceDataError(RuntimeError):
    """La fuente no respondió o devolvió algo que no se puede leer."""


def _get(url: str, fetcher=None) -> bytes:
    fetch = fetcher or (lambda u: safe_get(u, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT))
    try:
        response = fetch(url)
    except (UnsafeURLError, requests.RequestException) as exc:
        raise ServiceDataError(f"{type(exc).__name__}: {exc}") from exc
    if int(getattr(response, "status_code", 0) or 0) != 200:
        raise ServiceDataError(f"http_status:{getattr(response, 'status_code', None)}")
    return response.content


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def _zip_text(raw: bytes) -> str:
    """Primer archivo de texto del zip de datos abiertos del SMN (ISO-8859-1)."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".txt")]
            if not names:
                return ""
            data = archive.read(names[0])
    except zipfile.BadZipFile as exc:
        raise ServiceDataError("zip_invalido") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


# ── SMN: tiempo presente + pronóstico ────────────────────────────────────
@dataclass
class Weather:
    station: str
    observed_at: str  # "12:00"
    observed_date: str  # "18-octubre-2026"
    temp: float
    sky: str
    humidity: int | None
    wind: str
    days: list[dict] = field(default_factory=list)  # {date, label, min, max, rain}

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def parse_present_weather(text: str, station: str = "La Rioja") -> dict | None:
    """Línea de ``estado_tiempo*.txt``: estación;fecha;hora;cielo;visib.;temp;ST;humedad;viento;presión."""
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 9 or _fold(parts[0]) != _fold(station):
            continue
        try:
            temp = float(parts[5].replace(",", "."))
        except ValueError:
            return None
        try:
            humidity = int(float(parts[7]))
        except ValueError:
            humidity = None
        wind = re.sub(r"\s+", " ", parts[8]).strip()
        return {"observed_date": parts[1], "observed_at": parts[2], "sky": parts[3], "temp": temp, "humidity": humidity, "wind": wind}
    return None


_FORECAST_ROW = re.compile(r"^\s*(\d{2})/([A-Z]{3})/(\d{4})\s+(\d{2})Hs\.\s+(-?\d+(?:\.\d+)?)\s+\d+\s*\|\s*\d+\s+(\d+(?:\.\d+)?)")
_MONTHS_EN = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}
_MONTHS_ES = {m: i + 1 for i, m in enumerate(("ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"))}


def parse_forecast(text: str, station: str = "LA_RIOJA_AERO") -> list[dict]:
    """Bloque de ``pronostico_5dias*.txt`` de la estación: temperatura y
    lluvia cada 3 horas, agregadas por día (mín./máx. de los valores del
    pronóstico, lluvia sumada)."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == station)
    except StopIteration:
        return []
    by_day: dict[date, dict] = {}
    for line in lines[start + 1 :]:
        if line.strip() and not line.strip().startswith("=") and line.strip().isupper() and "/" not in line and "FECHA" not in line:
            break  # empieza la estación siguiente
        match = _FORECAST_ROW.match(line)
        if not match:
            continue
        day_s, mon_s, year_s, _hour, temp_s, rain_s = match.groups()
        month = _MONTHS_ES.get(mon_s) or _MONTHS_EN.get(mon_s)
        if not month:
            continue
        day = date(int(year_s), month, int(day_s))
        temp = float(temp_s)
        bucket = by_day.setdefault(day, {"min": temp, "max": temp, "rain": 0.0})
        bucket["min"] = min(bucket["min"], temp)
        bucket["max"] = max(bucket["max"], temp)
        bucket["rain"] = round(bucket["rain"] + float(rain_s), 1)
    return [
        {"date": d.isoformat(), "label": DIAS_CORTOS[d.weekday()], "min": v["min"], "max": v["max"], "rain": v["rain"]}
        for d, v in sorted(by_day.items())
    ]


def fetch_weather(*, station: str = "La Rioja", forecast_station: str = "LA_RIOJA_AERO", fetcher=None) -> Weather | None:
    present = parse_present_weather(_zip_text(_get(SMN_OPEN_DATA.format(dato="tiepre"), fetcher)), station)
    if present is None:
        logger.warning("SMN: sin dato de tiempo presente para %s", station)
        return None
    days = parse_forecast(_zip_text(_get(SMN_OPEN_DATA.format(dato="pron5d"), fetcher)), forecast_station)
    return Weather(station=station, days=days, **present)


# ── SMN: alertas ─────────────────────────────────────────────────────────
_LEVELS = ("roja", "naranja", "amarilla")
_PHENOMENA = (
    "viento zonda", "tormentas fuertes", "tormentas", "lluvias", "nevadas", "viento",
    "calor extremo", "temperaturas extremas", "frío extremo", "niebla", "polvo en suspensión",
)


def parse_alerts(text: str, province: str = "La Rioja") -> dict:
    """``status``: ``none`` (archivo sin alertas o sin la provincia),
    ``active`` (nivel y fenómeno reconocidos) o ``unparsed`` (menciona la
    provincia pero no se reconoce el formato: no se publica, queda en el
    reporte)."""
    lines = [line for line in text.splitlines() if _fold(province) in _fold(line)]
    if not lines:
        return {"status": "none"}
    joined = _fold(" ".join(lines))
    level = next((lv for lv in _LEVELS if lv in joined), "")
    phenomenon = next((ph for ph in _PHENOMENA if _fold(ph) in joined), "")
    if not level or not phenomenon:
        return {"status": "unparsed", "raw": " | ".join(lines)[:400]}
    return {"status": "active", "level": level, "phenomenon": phenomenon, "raw": " | ".join(lines)[:400]}


def fetch_alerts(*, province: str = "La Rioja", fetcher=None) -> dict:
    return parse_alerts(_zip_text(_get(SMN_OPEN_DATA.format(dato="alertas"), fetcher)), province)


# ── Dólar ────────────────────────────────────────────────────────────────
_DOLLAR_NAMES = {"oficial": "Oficial", "blue": "Blue", "bolsa": "MEP", "contadoconliqui": "CCL"}


def parse_dollar(payload: list) -> list[dict]:
    rows = []
    by_house = {str(item.get("casa")): item for item in payload if isinstance(item, dict)}
    for house, name in _DOLLAR_NAMES.items():
        item = by_house.get(house)
        if not item or item.get("venta") in (None, ""):
            continue
        rows.append({
            "house": house,
            "name": name,
            "buy": float(item["compra"]) if item.get("compra") not in (None, "") else None,
            "sell": float(item["venta"]),
            "updated_at": str(item.get("fechaActualizacion") or ""),
        })
    return rows


def fetch_dollar(*, fetcher=None) -> list[dict]:
    try:
        payload = json.loads(_get(DOLLAR_URL, fetcher).decode("utf-8"))
    except ValueError as exc:
        raise ServiceDataError("json_invalido") from exc
    return parse_dollar(payload if isinstance(payload, list) else [])


def money(value: float) -> str:
    """1534.3 → "1.534,30"; 1535 → "1.535"."""
    whole = abs(value - round(value)) < 0.005
    text = f"{value:,.0f}" if whole else f"{value:,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


# ── Feriados (calendario oficial) ────────────────────────────────────────
def parse_holidays(payload: dict) -> list[dict]:
    """Feriados nacionales del JSON oficial de argentina.gob.ar. Se excluyen
    los "especiales" (feriados de otras provincias o ciudades)."""
    items = (((payload or {}).get("mainEntity") or {}).get("itemListElement")) or []
    out = []
    for element in items:
        item = (element or {}).get("item") or {}
        kind = str(((item.get("additionalProperty") or {}).get("value")) or "")
        if kind == "especial":
            continue
        try:
            day = date.fromisoformat(str(item.get("startDate") or ""))
        except ValueError:
            continue
        name = re.sub(r"<[^>]+>", "", str(item.get("name") or ""))
        name = re.sub(r"\s*\((\d{1,2}/\d{1,2})\)\s*$", "", re.sub(r"\s+", " ", name)).strip()
        out.append({"date": day.isoformat(), "name": name, "kind": kind, "description": str(item.get("description") or "")})
    return sorted(out, key=lambda h: h["date"])


def fetch_holidays(year: int, *, fetcher=None) -> list[dict]:
    try:
        payload = json.loads(_get(HOLIDAYS_URL.format(year=year), fetcher).decode("utf-8"))
    except ValueError as exc:
        raise ServiceDataError("json_invalido") from exc
    return parse_holidays(payload)


def upcoming_holidays(today: date, *, fetcher=None, limit: int = 4) -> list[dict]:
    items = []
    for year in (today.year, today.year + 1):
        try:
            items.extend(fetch_holidays(year, fetcher=fetcher))
        except ServiceDataError:
            if year == today.year:
                raise
    return [h for h in items if h["date"] >= today.isoformat()][:limit]


def holiday_story_rows(holidays: list[dict]) -> list[dict]:
    rows = []
    for h in holidays:
        day = date.fromisoformat(h["date"])
        kind = {"inamovible": "Feriado inamovible", "trasladable": "Feriado trasladable", "turistico": "Día no laborable con fines turísticos", "puente": "Feriado puente"}.get(h["kind"], h.get("description") or "")
        rows.append({"day": str(day.day), "month": MESES_CORTOS[day.month - 1], "weekday": DIAS[day.weekday()].capitalize(), "name": h["name"], "kind": kind})
    return rows


# ── Avisos de cortes y rutas (desde notas publicadas) ────────────────────
_LUZ = ("corte de luz", "cortes de luz", "corte de energia", "cortes de energia", "sin luz")
_AGUA = ("corte de agua", "cortes de agua", "sin agua", "baja presion")
# "suministro"/"servicio" sólo cuentan con un verbo de interrupción: "obras
# para mejorar el suministro de agua" no es un aviso de corte.
_CUT = ("corte", "interrup", "suspend", "sin servicio")
_RUTA_HINTS = ("ruta", "paso pircas negras", "paso de jaguel", "camino")
_RUTA_STATE = ("cortad", "corte", "intransitable", "habilit", "despej", "desvio", "transitab", "cerrad", "reabr", "precaucion")
_ROUTE_EXCLUDE = ("siniestro", "choque", "accidente", "murio", "fallec", "detuv", "contrabando", "herido", "vuelco")


def classify_notice(title: str, excerpt: str = "") -> str:
    """``luz``, ``agua``, ``rutas`` o "" (no es un aviso de servicio)."""
    text = _fold(f"{title} {excerpt}")
    head = _fold(title)
    cut = any(k in head for k in _CUT)
    if any(k in head for k in _LUZ) or (cut and ("edelar" in head or "electric" in head or "energia" in head)):
        return "luz"
    if any(k in head for k in _AGUA) or (cut and ("aguas riojanas" in head or " agua" in f" {head}")):
        return "agua"
    if any(k in head for k in _RUTA_HINTS) and any(k in head for k in _RUTA_STATE) and not any(k in text for k in _ROUTE_EXCLUDE):
        return "rutas"
    return ""


def _archive_path() -> str:
    return str(data_dir() / "derived" / "editorial_context.sqlite3")


def recent_notices(*, hours: int = 36, now: datetime | None = None, db_path: str | None = None) -> list[dict]:
    """Notas propias de las últimas ``hours`` horas que son avisos de servicio."""
    path = db_path or _archive_path()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:
        logger.warning("Archivo editorial no disponible: %s", exc)
        return []
    try:
        rows = conn.execute(
            "select title, excerpt, canonical_url, published_at from archive_articles "
            "where published_at >= ? order by published_at desc limit 300",
            (_utc_iso(now_ar(now) - timedelta(hours=hours)),),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("No se pudo leer el archivo editorial: %s", exc)
        return []
    finally:
        conn.close()
    out = []
    for title, excerpt, url, published_at in rows:
        service = classify_notice(str(title or ""), str(excerpt or ""))
        if service:
            out.append({"service": service, "title": str(title or ""), "excerpt": str(excerpt or ""), "url": str(url or ""), "published_at": str(published_at or "")})
    return out


def _utc_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ── Hacienda: cronograma de pagos a estatales ────────────────────────────
HACIENDA_POSTS_URL = "https://hacienda.larioja.gob.ar/wp-json/wp/v2/posts?per_page=15&_fields=date,link,title,content"
# "QUINCENA OCTUBRE – LUNES 19/10", "HABERES SEPTIEMBRE – MIÉRCOLES 7/10".
_PAYMENT_TITLE = re.compile(
    r"^\s*(?P<concept>[A-ZÁÉÍÓÚÑ ]+?)\s+(?P<month>[A-ZÁÉÍÓÚÑ]+)\s*[–—-]\s*(?P<weekday>[A-ZÁÉÍÓÚÑ]+)\s+(?P<day>\d{1,2})/(?P<mon>\d{1,2})\s*$"
)
_PAYMENT_CONCEPTS = ("quincena", "haberes", "aguinaldo", "sac", "bono", "medio aguinaldo")
_MONTH_NAMES = {_fold(name): i + 1 for i, name in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"))}


def _clean_payment_item(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(,\s*y|,|\.|\s+y)$", "", text).strip()
    return text


def parse_payment_post(title: str, content_html: str, published: str, link: str) -> dict | None:
    """Un post del cronograma de pagos de Hacienda, o ``None`` si no lo es.

    Agrupa los organismos por banco cuando el post los separa ("Banco Rioja",
    "Banco Hipotecario"). La fecha de pago sale del título; el año, de la
    fecha de publicación (un pago de enero publicado en diciembre es del año
    siguiente).
    """
    from bs4 import BeautifulSoup

    match = _PAYMENT_TITLE.match(re.sub(r"\s+", " ", title.replace("&#8211;", "–")).upper())
    if not match or not any(_fold(match.group("concept")).startswith(c) for c in _PAYMENT_CONCEPTS):
        return None
    try:
        posted = datetime.fromisoformat(published[:19])
        pay_day = date(posted.year, int(match.group("mon")), int(match.group("day")))
        if pay_day < posted.date() - timedelta(days=180):
            pay_day = pay_day.replace(year=posted.year + 1)
    except ValueError:
        return None
    groups: list[dict] = []
    for raw in BeautifulSoup(content_html or "", "html.parser").get_text("\n", strip=True).split("\n"):
        line = _clean_payment_item(raw)
        if not line:
            continue
        if _fold(line).startswith("banco ") and not raw.strip().endswith(","):
            groups.append({"title": line, "items": []})
            continue
        if not groups:
            groups.append({"title": "", "items": []})
        groups[-1]["items"].append(line)
    groups = [g for g in groups if g["items"]]
    if not groups:
        return None
    concept = match.group("concept").strip().capitalize()
    month = match.group("month").strip().lower()
    return {
        "concept": f"{concept} de {month}" if _fold(month) in _MONTH_NAMES else concept,
        "date": pay_day.isoformat(),
        "groups": groups,
        "url": link,
        "published": published[:19],
    }


def fetch_payment_schedule(*, fetcher=None) -> list[dict]:
    """Posts del cronograma de pagos publicados por Hacienda (más nuevos primero)."""
    try:
        payload = json.loads(_get(HACIENDA_POSTS_URL, fetcher).decode("utf-8"))
    except ValueError as exc:
        raise ServiceDataError("json_invalido") from exc
    out = []
    for post in payload if isinstance(payload, list) else []:
        title = re.sub(r"<[^>]+>", "", str(((post or {}).get("title") or {}).get("rendered") or ""))
        import html as _html

        parsed = parse_payment_post(
            _html.unescape(title),
            str(((post or {}).get("content") or {}).get("rendered") or ""),
            str((post or {}).get("date") or ""),
            str((post or {}).get("link") or ""),
        )
        if parsed:
            out.append(parsed)
    return out


# ── INPRES: sismos sentidos ──────────────────────────────────────────────
# Sólo HTTP: el HTTPS de contenidos.inpres.gob.ar no responde.
INPRES_FELT_URL = "http://contenidos.inpres.gob.ar/mapa/sentidos.xml"
_INTENSITY_ENTRY = re.compile(r"^\s*(?P<intensity>[IVX]+(?:\s*a\s*[IVX]+)?)\s*-\s*(?P<place>.+?)\s*$")


def _decode_feed(raw: bytes) -> str:
    """El XML dice ISO-8859-1 pero a veces trae UTF-8: se prueba UTF-8 primero."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return re.sub(r"^<\?xml[^>]*\?>", "", text.lstrip("\ufeff").lstrip())


def parse_felt_quakes(raw: bytes, province: str = "La Rioja") -> list[dict]:
    """Sismos del feed de INPRES sentidos en ``province`` (por localidad o epicentro)."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(_decode_feed(raw))
    except ET.ParseError as exc:
        raise ServiceDataError("xml_invalido") from exc
    target = _fold(province)
    out = []
    for item in root.iter("item"):
        quake_id = str(item.findtext("idSismo") or "").strip()
        try:
            moment = datetime.strptime(quake_id, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            magnitude = float(str(item.findtext("magnitude") or "").replace(",", "."))
        except ValueError:
            continue
        felt = []
        for entry in str(item.findtext("intensity") or "").split(";"):
            match = _INTENSITY_ENTRY.match(entry)
            if match:
                felt.append({"place": re.sub(r"\s+", " ", match.group("place")), "intensity": re.sub(r"\s+", " ", match.group("intensity"))})
        felt_here = [f for f in felt if _fold(f["place"]).endswith(target) or _fold(f["place"]) == f"ciudad de {target}"]
        epicenter_here = _fold(str(item.findtext("province") or "")) == target
        if not felt_here and not epicenter_here:
            continue
        out.append({
            "id": quake_id,
            "at": moment.isoformat(),
            "magnitude": magnitude,
            "depth": re.sub(r"\s*\.\s*$", "", str(item.findtext("depth") or "").strip()),
            "epicenter": str(item.findtext("epiczone") or "").strip().rstrip("."),
            "province": str(item.findtext("province") or "").strip(),
            "felt": felt_here + [f for f in felt if f not in felt_here],
        })
    return out


def fetch_felt_quakes(*, province: str = "La Rioja", fetcher=None) -> list[dict]:
    return parse_felt_quakes(_get(INPRES_FELT_URL, fetcher), province)


# ── INPRES: listado inmediato + detalle (placas v2) ──────────────────────
INPRES_LIST_URL = "http://contenidos.inpres.gob.ar/mapa/sismos.xml"
INPRES_DETAIL_URL = "http://contenidos.inpres.gob.ar/epicentro3.php?s={id}"
# Leyenda de la página de INPRES: azul = automático, negro = revisado, rojo = sentido.
_QUAKE_STATUS = {"00f": "automatic", "000": "revised", "f00": "felt"}


def parse_quake_list(raw: bytes) -> list[dict]:
    """Últimos sismos de INPRES (``sismos.xml``) con su estado de revisión."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(_decode_feed(raw))
    except ET.ParseError as exc:
        raise ServiceDataError("xml_invalido") from exc
    out = []
    for item in root.iter("item"):
        quake_id = str(item.findtext("idSismo") or "").strip()
        try:
            moment = datetime.strptime(quake_id, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            magnitude = float(str(item.findtext("mg") or "").replace(",", "."))
            depth = int(float(str(item.findtext("prof") or "")))
        except ValueError:
            continue
        out.append({
            "id": quake_id,
            "at": moment.isoformat(),
            "magnitude": magnitude,
            "depth_km": depth,
            "province": str(item.findtext("prov") or "").strip(),
            "status": _QUAKE_STATUS.get(str(item.findtext("color_link") or "").strip().lower(), "unknown"),
        })
    return out


def parse_quake_detail(html_text: str) -> dict:
    """Distancias a localidades tal como las informa INPRES (la más cercana primero)."""
    import html as _html

    text = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", html_text or "")))
    places = [m.group(0).strip() for m in re.finditer(r"\d+ km al [NSEO]{1,2} de [^;&\d]+?(?=;|\s-?\d+\.\d+ \(lat\)|$)", text)]
    return {"places": places, "automatic": "automaticamente" in _fold(text)}


def fetch_quakes(*, fetcher=None) -> list[dict]:
    return parse_quake_list(_get(INPRES_LIST_URL, fetcher))


def fetch_quake_detail(quake_id: str, *, fetcher=None) -> dict:
    return parse_quake_detail(_get(INPRES_DETAIL_URL.format(id=quake_id), fetcher).decode("utf-8", "replace"))
