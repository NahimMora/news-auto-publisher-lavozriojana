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
