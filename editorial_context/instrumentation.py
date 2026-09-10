"""Instrumentación central de llamadas de IA (Parte 47).

Se engancha desde ``utils/ai_client.py`` sin cambiar la interfaz pública que
ya usan los 8 call sites existentes (parámetros nuevos opcionales). Nunca
loguea prompts completos ni secretos: sólo tamaños, latencias y conteos.
"""
from __future__ import annotations

import time

from editorial_context import db as ec_db
from utils.logging_setup import setup_logger

logger = setup_logger("editorial_context.instrumentation", "editorial_context.log")


def record_ai_call(
    *,
    stage: str,
    model: str = "",
    attempt: int = 1,
    latency_ms: float | None = None,
    input_chars: int | None = None,
    output_chars: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    tokens_estimated: bool = False,
    success: bool = True,
    article_id: str = "",
    path=None,
) -> None:
    """Nunca lanza: una falla al registrar métricas no puede tumbar una
    llamada de IA real (Parte 60, "todo fallo debe registrarse" sin romper
    el pipeline)."""
    try:
        with ec_db.connection(path) as conn:
            conn.execute(
                """
                INSERT INTO ai_call_metrics (
                    stage, model, attempt, latency_ms, input_chars, output_chars,
                    tokens_in, tokens_out, tokens_estimated, success, article_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stage,
                    model,
                    attempt,
                    latency_ms,
                    input_chars,
                    output_chars,
                    tokens_in,
                    tokens_out,
                    int(tokens_estimated),
                    int(success),
                    article_id,
                    ec_db.now_iso(),
                ),
            )
    except Exception:
        logger.exception("No se pudo registrar métrica de IA (stage=%s)", stage)


def estimate_tokens(text: str) -> int:
    """Estimación barata (~4 caracteres/token) cuando el SDK no informa uso real."""
    return max(0, round(len(text or "") / 4))


def summary(*, since_hours: int = 24, path=None) -> dict:
    """Métricas acumulables pedidas por la Parte 47."""
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - since_hours * 3600))
    with ec_db.connection(path) as conn:
        rows = conn.execute("SELECT * FROM ai_call_metrics WHERE created_at >= ?", (cutoff,)).fetchall()

    per_stage: dict[str, int] = {}
    per_article: dict[str, int] = {}
    tokens_in_total = 0
    tokens_out_total = 0
    failures = 0
    for row in rows:
        per_stage[row["stage"]] = per_stage.get(row["stage"], 0) + 1
        if row["article_id"]:
            per_article[row["article_id"]] = per_article.get(row["article_id"], 0) + 1
        tokens_in_total += row["tokens_in"] or 0
        tokens_out_total += row["tokens_out"] or 0
        if not row["success"]:
            failures += 1

    calls_per_article = sum(per_article.values()) / len(per_article) if per_article else 0.0
    return {
        "since_hours": since_hours,
        "total_calls": len(rows),
        "failures": failures,
        "ai_calls_per_stage": per_stage,
        "ai_calls_per_article_avg": round(calls_per_article, 2),
        "estimated_tokens_in": tokens_in_total,
        "estimated_tokens_out": tokens_out_total,
    }
