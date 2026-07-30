"""
Clasificador de noticias con IA.
Determina la categoría editorial a partir del título + cuerpo de la noticia.
"""
import os
import time
from dataclasses import dataclass
from utils.logging_setup import setup_logger

logger = setup_logger("classifier", "classifier.log")

CATEGORIAS = [
    "Politica",
    "Policiales",
    "Interior",
    "Sociedad",
    "Economia",
    "Salud",
    "Educacion",
    "Deportes",
    "Cultura",
    "Espectaculos",
]

_PROMPT = """\
Sos un clasificador de noticias del diario "La Voz Riojana" (La Rioja, Argentina).

Clasificá la siguiente noticia en UNA SOLA de estas categorías:
{categorias}

CRITERIOS:
- Interior      → noticias de localidades del interior de La Rioja (fuera de la capital)
- Policiales    → crímenes, accidentes, detenciones, violencia, robos
- Politica      → gobierno, funcionarios, elecciones, legislatura, gestión pública
- Sociedad      → comunidad, vecinos, servicios, clima, medio ambiente, género
- Economia      → finanzas, precios, trabajo, empresas, industria, minería, agro
- Salud         → medicina, hospitales, epidemias, salud pública
- Educacion     → escuelas, universidades, docentes, becas
- Deportes      → fútbol, deporte, competencias, resultados
- Cultura       → arte, patrimonio, tradiciones, eventos culturales, turismo
- Espectaculos  → artistas, shows, televisión, cine, música, farándula

Respondé ÚNICAMENTE con el nombre exacto de la categoría, sin explicaciones ni puntos.

Noticia:
Título: {titulo}
Texto: {texto}

Categoría:"""


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    fallback_used: bool = False
    error_type: str | None = None


def clasificar_con_resultado(titulo: str, parrafos: list) -> ClassificationResult:
    """
    Clasifica una noticia y retorna una categoría de CATEGORIAS.
    Usa temperature=0 y pocos tokens (barato y rápido).
    Fallback: 'Sociedad' si OpenAI no está disponible o falla.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        logger.warning("OPENAI_API_KEY no configurada, usando categoria por defecto")
        return ClassificationResult("Sociedad", True, "credential_missing")

    retry_count = int(os.getenv("OPENAI_RETRY_COUNT", "3"))
    retry_sleep = float(os.getenv("OPENAI_RETRY_SLEEP", "2"))
    timeout     = float(os.getenv("OPENAI_TIMEOUT", "30"))
    model       = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=timeout)

    texto  = " ".join(parrafos[:3])[:1200]
    prompt = _PROMPT.format(
        categorias="\n".join(f"- {c}" for c in CATEGORIAS),
        titulo=titulo,
        texto=texto,
    )

    for attempt in range(1, retry_count + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=15,
            )
            raw = resp.choices[0].message.content.strip()
            for cat in CATEGORIAS:
                if cat.lower() in raw.lower():
                    logger.info(f"Clasificado como '{cat}': {titulo[:60]}")
                    return ClassificationResult(cat)
            logger.warning(f"Respuesta no reconocida '{raw}', usando Sociedad")
            return ClassificationResult("Sociedad", True, "invalid_model_response")
        except Exception as e:
            logger.warning(f"Clasificador intento {attempt}/{retry_count}: {e}")
            if attempt < retry_count:
                time.sleep(retry_sleep)

    logger.error(f"Clasificador falló para: {titulo[:60]}, usando Sociedad")
    return ClassificationResult("Sociedad", True, "openai_failed")


def clasificar(titulo: str, parrafos: list) -> str:
    """Compatibilidad: retorna sólo la categoría."""
    return clasificar_con_resultado(titulo, parrafos).category
