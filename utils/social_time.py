"""Hora argentina y rótulos de fecha para los formatos sociales.

La Rioja usa UTC−3 todo el año (sin horario de verano): offset fijo, igual
que ``utils/visual_v2_props.date_label``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

AR_TZ = timezone(timedelta(hours=-3))
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
DIAS_CORTOS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
MESES_CORTOS = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")


def now_ar(now: datetime | None = None) -> datetime:
    return (now or datetime.now(AR_TZ)).astimezone(AR_TZ)


def today_ar(now: datetime | None = None) -> date:
    return now_ar(now).date()


def day_label(day: date, *, year: bool = False, capital: bool = True) -> str:
    """"Domingo 18 de octubre" (con año opcional)."""
    text = f"{DIAS[day.weekday()]} {day.day} de {MESES[day.month - 1]}"
    if year:
        text += f" de {day.year}"
    return text[:1].upper() + text[1:] if capital else text


def range_label(start: date, end: date) -> str:
    """"12 al 18 de octubre" / "28 de septiembre al 4 de octubre"."""
    if start.month == end.month:
        return f"{start.day} al {end.day} de {MESES[end.month - 1]}"
    return f"{start.day} de {MESES[start.month - 1]} al {end.day} de {MESES[end.month - 1]}"


def hhmm(moment: datetime) -> str:
    return now_ar(moment).strftime("%H:%M")


def in_window(start_hour: int, end_hour: int, now: datetime | None = None) -> bool:
    """True si la hora argentina está en [start_hour, end_hour)."""
    hour = now_ar(now).hour
    return start_hour <= hour < end_hour


def quiet_hours(now: datetime | None = None, window: str = "0-7") -> bool:
    """Horario sin publicaciones ("0-7" = desde las 0 hasta antes de las 7)."""
    try:
        start, end = (int(part) for part in window.split("-", 1))
    except ValueError:
        return False
    hour = now_ar(now).hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end
