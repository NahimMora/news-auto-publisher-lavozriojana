"""Puntaje editorial con IA para decidir qué videos se publican como Reel.

Aplica a los flujos automáticos de reels (videos de X y notas de paparazzi con
video): no todo video que entra merece un Reel. Con
``REEL_EDITORIAL_SCORE_ENABLED`` apagado (default) todo video queda aprobado,
igual que antes. Encendido, una llamada a IA puntúa el interés del video para
La Voz Riojana y sólo se publica lo que alcanza ``REEL_EDITORIAL_MIN_SCORE``.

Si la IA no responde, el video NO se aprueba (``status="unavailable"``): el
llamador decide si reintenta (X) o publica la nota sin reel (paparazzi).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from utils.logging_setup import setup_logger

logger = setup_logger("reel_editorial_score", "reel_editorial_score.log")

_TRUE = {"1", "true", "yes", "on", "si", "sí"}

_SCORE_PROMPT = """
Sos editor de video de "La Voz Riojana", medio digital de La Rioja, Argentina.
Decidís si un video merece publicarse como Reel en Instagram y Facebook.

Salida obligatoria: JSON válido con exactamente estas claves:
{"score": 0, "motivo": "..."}

- "score": entero de 0 a 100 según el interés editorial del video para la
  audiencia de La Voz Riojana.
  Suman: hecho noticioso y actual, impacto o interés público, relevancia para
  La Rioja o para la Argentina, figuras o hechos que la audiencia sigue,
  momento visual o testimonio que se entiende sin contexto extra.
  Restan: publicidad o autopromoción, contenido trivial o sin información,
  saludos, anuncios genéricos, rumores sin fuente, sensacionalismo, violencia
  explícita, contenido sexual, menores expuestos en situaciones sensibles,
  texto que no permite saber de qué trata el video.
  En espectáculos y deportes de alcance nacional, valorá la popularidad de las
  figuras y el interés del público argentino: no restes por falta de relación
  con La Rioja.
  Referencia: 80-100 imperdible; 60-79 publicable; 40-59 flojo; 0-39 no publicar.
- "motivo": una frase corta (máximo 140 caracteres) que justifique el puntaje.
- Evaluá sólo con el texto provisto. No inventes datos, cifras, armas, personas
  ni hechos ajenos al original; si el texto no alcanza para entender el video,
  puntuá bajo.
""".strip()


@dataclass(frozen=True)
class ReelScoreDecision:
    allowed: bool
    status: str  # "disabled" | "approved" | "rejected" | "unavailable"
    score: int | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "score": self.score,
            "reason": self.reason,
        }


def reel_score_enabled() -> bool:
    return str(os.getenv("REEL_EDITORIAL_SCORE_ENABLED", "false")).strip().lower() in _TRUE


def min_score() -> int:
    try:
        return max(0, min(100, int(os.getenv("REEL_EDITORIAL_MIN_SCORE", "60"))))
    except ValueError:
        return 60


def _parse_score(content: str) -> tuple[int, str]:
    data = json.loads(content.strip())
    raw = data.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"score inválido: {raw!r}")
    score = int(raw)
    if not 0 <= score <= 100:
        raise ValueError(f"score fuera de rango: {score}")
    return score, str(data.get("motivo") or "").strip()[:200]


def score_reel_candidate(noticia: dict, *, origin: str) -> ReelScoreDecision:
    """Decide si ``noticia`` (con video) se publica como Reel. Nunca lanza."""
    titulo = str(noticia.get("titulo") or "")[:60]
    if not reel_score_enabled():
        return ReelScoreDecision(True, "disabled")

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        logger.error("Puntaje de reel no disponible (%s): falta credencial de IA", origin)
        return ReelScoreDecision(False, "unavailable", reason="credential_missing")

    retry_count = int(os.getenv("GEMINI_RETRY_COUNT", "3"))
    retry_sleep = float(os.getenv("GEMINI_RETRY_SLEEP", "2"))
    timeout = float(os.getenv("GEMINI_TIMEOUT", "60"))
    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    from utils.ai_client import chat_completion

    texto = " ".join(str(p) for p in (noticia.get("parrafos") or [])[:4])[:2000]
    user_content = (
        f"Origen: {origin}\n"
        f"Sección: {noticia.get('seccion', '')}\n"
        f"Título: {noticia.get('titulo', '')}\n"
        f"Texto:\n{texto or str(noticia.get('texto_instagram') or '')[:2000]}"
    )

    for attempt in range(1, retry_count + 1):
        try:
            content = chat_completion(
                messages=[
                    {"role": "system", "content": _SCORE_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                model=model,
                api_key=api_key,
                temperature=0.2,
                max_tokens=200,
                timeout=timeout,
                json_mode=True,
            )
            score, motivo = _parse_score(content)
        except Exception as exc:
            logger.warning("Puntaje de reel intento %s/%s (%s): %s", attempt, retry_count, origin, exc)
            if attempt < retry_count:
                time.sleep(retry_sleep)
            continue
        threshold = min_score()
        allowed = score >= threshold
        logger.info(
            "Reel %s (%s) score=%s umbral=%s: %s | %s",
            "aprobado" if allowed else "descartado",
            origin,
            score,
            threshold,
            titulo,
            motivo,
        )
        return ReelScoreDecision(allowed, "approved" if allowed else "rejected", score, motivo)

    logger.error("Puntaje de reel no disponible (%s) para: %s", origin, titulo)
    return ReelScoreDecision(False, "unavailable", reason="ai_failed")
