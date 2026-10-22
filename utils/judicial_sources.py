"""Fuentes judiciales oficiales (MPF y Función Judicial de La Rioja).

Publican casi todos los días y repiten casos entre sí y con Tiempo Popular y
Nueva Rioja. Antes de pagar la reescritura, ``assess_judicial`` hace una sola
llamada a Gemini que devuelve el puntaje editorial (0-10) y si la nota es el
mismo caso que algo ya encolado en las últimas horas. Sólo pasan las de puntaje
alto (``JUDICIAL_MIN_SCORE``, default 7).

La información es oficial y verificada: la redacción no la suaviza ni agrega
condicionales que la fuente no usa, pero tampoco copia el texto crudo
(``JUDICIAL_RULES`` se suma a los prompts de título, nota Web y caption).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

from utils.logging_setup import setup_logger

logger = setup_logger("judicial_sources", "judicial_sources.log")

JUDICIAL_SOURCE_PREFIX = "judicial_"

JUDICIAL_RULES = (
    "Fuente oficial judicial (Ministerio Público Fiscal o Función Judicial de La Rioja): "
    "la información está verificada. Contá el estado procesal exacto que dice la fuente "
    "(si hay condena, decí que fue condenado; si es un pedido de pena, una imputación o "
    "un alegato, decilo así), sin suavizarlo ni agregar condicionales que la fuente no "
    "usa, y sin morbo. Redactá con tus palabras: no copies el comunicado. No agregues "
    "ningún dato que permita identificar a la víctima (nombre, edad exacta, domicilio, "
    "barrio, escuela) más allá de lo que publica la propia fuente, y no incluyas ningún "
    "dato de víctimas menores de edad. No inventes datos, armas, personas ni hechos que "
    "no estén en el texto original."
)

_PROMPT = """Sos el editor de policiales de "La Voz Riojana", un medio digital de La Rioja, Argentina. \
Recibís un comunicado oficial del Ministerio Público Fiscal o de la Función Judicial de La Rioja.

1) Puntuá del 0 al 10 su valor como noticia para el público riojano:
- 9-10: condena o sentencia en un caso grave (homicidio, femicidio, abuso, narcotráfico), \
caso con repercusión pública previa o con funcionarios involucrados.
- 7-8: juicio, pedido de pena, imputación o detención en un caso grave o de interés local claro.
- 4-6: causa menor (estafa chica, amenazas) o trámite procesal sin novedad para el lector.
- 0-3: institucional: capacitaciones, congresos, designaciones, concursos, visitas, actos.

2) Decidí si es EL MISMO CASO (mismo hecho y mismo acusado o víctima) que alguna de las noticias \
recientes de la lista. Un caso distinto del mismo delito NO es el mismo caso. Si no estás seguro, \
respondé null.

Evaluá sólo con el texto provisto; no inventes datos, armas, personas ni hechos ajenos al original.

Respondé ÚNICAMENTE con JSON: {{"puntaje": <entero 0-10>, "mismo_caso": <número de la lista o null>}}

Noticias recientes:
{recientes}

Comunicado:
Título: {titulo}
Texto: {texto}
"""


@dataclass(frozen=True)
class JudicialAssessment:
    score: int | None
    duplicate_of: str | None = None
    error_type: str | None = None


def is_judicial(item: dict) -> bool:
    return str(item.get("source") or "").strip().lower().startswith(JUDICIAL_SOURCE_PREFIX)


def min_score() -> int:
    try:
        return int(os.getenv("JUDICIAL_MIN_SCORE", "7"))
    except ValueError:
        return 7


def assess_judicial(titulo: str, parrafos: list, recent_titles: list[str]) -> JudicialAssessment:
    """Puntaje y mismo caso en una sola llamada. Sin respuesta válida, ``score`` es None."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        logger.warning("GEMINI_API_KEY no configurada; la nota judicial queda sin puntaje")
        return JudicialAssessment(None, error_type="credential_missing")

    from utils.ai_client import chat_completion

    recientes = "\n".join(f"{i}. {t}" for i, t in enumerate(recent_titles, start=1)) or "(ninguna)"
    prompt = _PROMPT.format(
        recientes=recientes,
        titulo=titulo,
        texto=" ".join(str(p) for p in parrafos[:4])[:1800],
    )
    retry_count = int(os.getenv("GEMINI_RETRY_COUNT", "3"))
    retry_sleep = float(os.getenv("GEMINI_RETRY_SLEEP", "2"))
    for attempt in range(1, retry_count + 1):
        try:
            raw = chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
                api_key=api_key,
                temperature=0,
                max_tokens=60,
                timeout=float(os.getenv("GEMINI_TIMEOUT", "30")),
                json_mode=True,
            )
            return _parse(raw, recent_titles, titulo)
        except Exception as exc:
            logger.warning("Evaluación judicial intento %s/%s: %s", attempt, retry_count, exc)
            if attempt < retry_count:
                time.sleep(retry_sleep)
    logger.error("Evaluación judicial falló para: %s", titulo[:70])
    return JudicialAssessment(None, error_type="gemini_failed")


def _parse(raw: str, recent_titles: list[str], titulo: str) -> JudicialAssessment:
    match = re.search(r"\{.*\}", str(raw or ""), re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    score = data.get("puntaje")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        logger.warning("Evaluación judicial sin puntaje válido: %r", str(raw)[:120])
        return JudicialAssessment(None, error_type="invalid_model_response")
    duplicate_of = None
    index = data.get("mismo_caso")
    if isinstance(index, int) and not isinstance(index, bool) and 1 <= index <= len(recent_titles):
        duplicate_of = recent_titles[index - 1]
    score = max(0, min(10, int(score)))
    logger.info("Judicial %s/10%s: %s", score, " (mismo caso)" if duplicate_of else "", titulo[:70])
    return JudicialAssessment(score, duplicate_of)
