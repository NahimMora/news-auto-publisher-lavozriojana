"""
Filtro de relevancia editorial para la fuente paparazzi.com.ar.
A diferencia de las demás fuentes (con vínculo riojano confirmado por diseño
editorial), paparazzi es farándula nacional sin curación local — este score
es lo único que separa una nota de alto impacto de un relleno menor antes de
competir por el cupo reservado de Instagram (ver docs/DECISIONS.md, cupo 8+2).
"""
import os
import time
from dataclasses import dataclass
from utils.logging_setup import setup_logger

logger = setup_logger("paparazzi_relevance", "paparazzi_relevance.log")

_PROMPT = """\
Sos el editor de espectáculos de "La Voz Riojana", un medio digital de noticias \
de La Rioja, Argentina. Recibís notas de farándula nacional (fuente: \
paparazzi.com.ar) que compiten por un cupo limitado en Instagram.

Puntuá del 0 al 10 la RELEVANCIA/IMPACTO NACIONAL de la siguiente noticia para \
una audiencia general argentina:

- 9-10: hecho mayor con figuras de primer nivel (escándalo grave, muerte, \
  separación/romance de figuras masivas, femicidio o delito con figura pública \
  involucrada, declaración de fuerte repercusión pública)
- 6-8: noticia de farándula relevante con figuras conocidas (pelea, romance, \
  declaración polémica, entrevista con revelación real)
- 3-5: contenido de relleno sobre figuras conocidas (detalle menor, aniversario, \
  publicidad encubierta, opinión sin novedad real)
- 0-2: contenido trivial o sin figura pública relevante (recomendación de \
  series/TV, horóscopo, participante menor de reality, rumor sin sustento)

Respondé ÚNICAMENTE con el número entero (0 a 10), sin texto adicional.

Noticia:
Título: {titulo}
Texto: {texto}

Puntaje:"""

# Score aplicado cuando el modelo falla o no responde un número válido: la
# meta es filtrar relleno, no perder notas por un problema de infraestructura,
# así que una falla nunca debe bloquear la nota (fail-open).
_FALLBACK_SCORE = 10


@dataclass(frozen=True)
class RelevanceResult:
    score: int
    fallback_used: bool = False
    error_type: str | None = None


def score_relevance(titulo: str, parrafos: list) -> RelevanceResult:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        logger.warning("GEMINI_API_KEY no configurada, usando score por defecto (fail-open)")
        return RelevanceResult(_FALLBACK_SCORE, True, "credential_missing")

    retry_count = int(os.getenv("GEMINI_RETRY_COUNT", "3"))
    retry_sleep = float(os.getenv("GEMINI_RETRY_SLEEP", "2"))
    timeout = float(os.getenv("GEMINI_TIMEOUT", "30"))
    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    from utils.ai_client import chat_completion

    texto = " ".join(parrafos[:3])[:1200]
    prompt = _PROMPT.format(titulo=titulo, texto=texto)

    for attempt in range(1, retry_count + 1):
        try:
            raw = chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                api_key=api_key,
                temperature=0,
                max_tokens=10,
                timeout=timeout,
            ).strip()
            digits = "".join(ch for ch in raw if ch.isdigit())
            if digits:
                score = max(0, min(10, int(digits[:2])))
                logger.info(f"Relevancia {score}/10: {titulo[:70]}")
                return RelevanceResult(score)
            logger.warning(f"Respuesta no numérica '{raw}', usando score por defecto")
            return RelevanceResult(_FALLBACK_SCORE, True, "invalid_model_response")
        except Exception as e:
            logger.warning(f"Score de relevancia intento {attempt}/{retry_count}: {e}")
            if attempt < retry_count:
                time.sleep(retry_sleep)

    logger.error(f"Score de relevancia falló para: {titulo[:60]}, usando default (fail-open)")
    return RelevanceResult(_FALLBACK_SCORE, True, "gemini_failed")
