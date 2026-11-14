"""Gasto estimado de IA por etapa y modelo (``cli.py ai-usage``).

Lee ``ai_call_metrics`` (``data/derived/editorial_context.sqlite3``), donde
``utils/ai_client.py`` registra cada llamada con los tokens que informa el SDK.
Los precios son de lista en USD por millón de tokens y se pueden pisar con
``AI_PRICE_<MODELO>`` (``in,out``; p. ej. ``AI_PRICE_GEMINI_3_1_FLASH_LITE=0.25,1.5``).
En los modelos de voz, la salida son tokens de audio (25 por segundo).

Es una estimación: la factura real está en AI Studio (facturación del proyecto).
"""
from __future__ import annotations

import os
import re
import time

# USD por millón de tokens (entrada, salida). Fuente: listas públicas, nov-2026.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro-preview-tts": (1.00, 20.00),
    "gemini-2.5-flash-preview-tts": (0.50, 10.00),
    "gemini-3.8-flash-tts": (0.50, 9.00),
    "gemini-3.8-flash-lite-tts": (0.50, 9.00),
}


def price(model: str) -> tuple[float, float] | None:
    env = os.getenv("AI_PRICE_" + re.sub(r"[^A-Z0-9]", "_", model.upper()), "")
    if env:
        try:
            a, b = (float(x) for x in env.split(","))
            return a, b
        except ValueError:
            pass
    return DEFAULT_PRICES.get(model)


def summary(*, days: float = 7, path=None, now: float | None = None) -> dict:
    """Totales por etapa/modelo y por día, con costo estimado en USD."""
    from editorial_context import db as ec_db

    now = now or time.time()
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - days * 86400))
    with ec_db.connection(path) as conn:
        rows = conn.execute(
            "SELECT stage, model, substr(created_at, 1, 10) AS day, COUNT(*) AS calls, SUM(COALESCE(tokens_in, 0)) AS tin, "
            "SUM(COALESCE(tokens_out, 0)) AS tout, SUM(CASE WHEN success THEN 0 ELSE 1 END) AS failed "
            "FROM ai_call_metrics WHERE created_at >= ? GROUP BY stage, model, day",
            (cutoff,),
        ).fetchall()
    stages: dict[tuple[str, str], dict] = {}
    per_day: dict[str, float] = {}
    unpriced: set[str] = set()
    for row in rows:
        key = (row["stage"] or "?", row["model"] or "?")
        entry = stages.setdefault(key, {"stage": key[0], "model": key[1], "calls": 0, "failed": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0})
        entry["calls"] += row["calls"]
        entry["failed"] += row["failed"]
        entry["tokens_in"] += row["tin"]
        entry["tokens_out"] += row["tout"]
        p = price(key[1])
        if p is None:
            unpriced.add(key[1])
            continue
        usd = row["tin"] / 1e6 * p[0] + row["tout"] / 1e6 * p[1]
        entry["usd"] += usd
        per_day[row["day"]] = per_day.get(row["day"], 0.0) + usd
    total = sum(e["usd"] for e in stages.values())
    ordered = sorted(stages.values(), key=lambda e: -e["usd"])
    for e in ordered:
        e["usd"] = round(e["usd"], 4)
    return {
        "days": days,
        "total_usd": round(total, 4),
        "usd_per_day": round(total / days, 4) if days else 0.0,
        "usd_per_month_estimate": round(total / days * 30, 2) if days else 0.0,
        "by_stage": ordered,
        "by_day": {d: round(v, 4) for d, v in sorted(per_day.items())},
        "unpriced_models": sorted(unpriced),
    }


def render_text(report: dict) -> str:
    lines = [f"Gasto estimado de IA (últimos {report['days']:g} días): USD {report['total_usd']:.2f} "
             f"-> USD {report['usd_per_day']:.2f}/día, ~USD {report['usd_per_month_estimate']:.2f}/mes", ""]
    lines.append(f"{'Etapa':32} {'Modelo':28} {'Llamadas':>8} {'Tok. entrada':>12} {'Tok. salida':>11} {'USD':>8}")
    for e in report["by_stage"]:
        lines.append(f"{e['stage'][:32]:32} {e['model'][:28]:28} {e['calls']:8d} {e['tokens_in']:12d} {e['tokens_out']:11d} {e['usd']:8.3f}")
    if report["by_day"]:
        lines += ["", "Por día: " + ", ".join(f"{d[5:]} USD {v:.2f}" for d, v in report["by_day"].items())]
    if report["unpriced_models"]:
        lines += ["", "Sin precio cargado (no suman): " + ", ".join(report["unpriced_models"])]
    lines += ["", "Estimación con precios de lista; la factura real está en AI Studio."]
    return "\n".join(lines)
