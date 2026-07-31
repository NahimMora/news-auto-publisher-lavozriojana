"""
Genera el paquete estructurado del Estudio Premium a partir de un texto de
noticia ya escrito por el operador (pegado a mano en la UI).

Distinción importante: esto NO investiga ni busca información nueva — sólo
estructura y redacta el texto que el operador ya pegó, con el mismo
criterio de "no inventar datos" que el resto del pipeline
(openIA/rewrite_news.py, openIA/caption_generator.py). No es la excepción
prohibida por docs/DECISIONS.md ("no agregar llamadas de IA para
investigar noticias") porque no hay investigación: el texto de entrada ya
lo trae el operador.

La salida es el mismo contrato de "paquete de ChatGPT" que
utils/premium_importer.py ya sabe validar e importar — este módulo sólo
genera ese JSON, nunca construye el draft directamente.
"""
from __future__ import annotations

import json
import os
import time

from utils.logging_setup import setup_logger

logger = setup_logger("premium_package_generator", "premium_package_generator.log")

CATEGORIES = (
    "policiales", "interior", "sociedad", "economia", "salud",
    "educacion", "deportes", "cultura", "espectaculos", "politica",
)
TEMPLATES = ("lvr_cronica", "lvr_datos", "lvr_visual")
SLIDE_TYPES = ("cover", "image_text", "full_image", "key_points", "quote", "number", "closing")

_JSON_SCHEMA = """
{
  "title": "...",
  "caption": "...",
  "section": "una de: policiales, interior, sociedad, economia, salud, educacion, deportes, cultura, espectaculos, politica",
  "suggested_template": "lvr_cronica | lvr_datos | lvr_visual",
  "slides": [
    {
      "type": "cover | image_text | full_image | key_points | quote | number | closing",
      "text": "...",
      "title": "...",
      "items": ["..."],
      "highlights": ["..."],
      "asset_hint": "2 a 4 palabras para buscar una imagen relacionada",
      "source_ids": []
    }
  ],
  "sources": [],
  "unknowns": []
}
""".strip()

_SYSTEM_PROMPT = f"""
Sos el editor del Estudio Premium de "La Voz Riojana", medio digital de La Rioja,
Argentina. Tu trabajo es transformar el texto de una noticia que el operador ya
escribió en un paquete estructurado para un carrusel de Instagram/Facebook.

REGLAS CRÍTICAS (no negociables):
- NO inventes datos, armas, personas, cifras, nombres, citas ni hechos que no estén
  explícitamente en el texto que te pasan. Si un dato no está, no lo pongas.
- NO investigues ni completes información faltante — usá solamente el texto dado.
- Si hay algo ambiguo o que no podés determinar con confianza (por ejemplo la
  sección editorial exacta), listalo en "unknowns" en vez de adivinar.
- "section" tiene que ser exactamente una de: {", ".join(CATEGORIES)}.
- "suggested_template": elegí "lvr_cronica" para policiales/última hora/hechos
  fuertes con imagen dominante; "lvr_datos" para economía/servicios/explicadores
  con cifras o bloques de información; "lvr_visual" para deportes/cultura/hechos
  visuales con poco texto.
- Generá entre 3 y 5 slides (nunca menos de 2 ni más de 10). El primer slide debe
  ser type="cover" con el título principal. Cerrá siempre con type="closing".
- Cada "highlights" debe tener 0 a 3 palabras o frases cortas que aparezcan
  literalmente en el "text" o "title" de ese mismo slide.
- "asset_hint" es una pista corta (2-4 palabras) para buscar una imagen
  relacionada en una biblioteca local — no una URL ni una descripción larga.
- Español rioplatense, directo, sin inventar emociones que el texto no exprese.
- "caption" es el texto para el pie de la publicación en redes: breve, sin
  hashtags, sin @menciones, sin URLs.

Salida obligatoria: JSON válido con exactamente esta forma:
{_JSON_SCHEMA}
""".strip()


class PremiumGenerationError(RuntimeError):
    pass


def generate_premium_package_json(raw_text: str) -> str:
    """Devuelve el texto JSON del paquete generado (mismo contrato que un
    paquete pegado manualmente desde ChatGPT). Lanza PremiumGenerationError
    si OpenAI no está configurado o falla tras los reintentos — a
    diferencia del pipeline automático, acá no hay fallback silencioso:
    es una acción manual del operador, que debe ver el error y decidir.
    """
    text = str(raw_text or "").strip()
    if not text:
        raise PremiumGenerationError("el texto de la noticia está vacío")

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        raise PremiumGenerationError("OPENAI_API_KEY no está configurada")

    retry_count = int(os.getenv("OPENAI_RETRY_COUNT", "3"))
    retry_sleep = float(os.getenv("OPENAI_RETRY_SLEEP", "2"))
    timeout = float(os.getenv("OPENAI_TIMEOUT", "60"))
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=timeout)

    last_error: Exception | None = None
    for attempt in range(1, retry_count + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"Texto de la noticia:\n\n{text[:6000]}"},
                ],
                temperature=0.4,
                max_tokens=1800,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content.strip()
            # Validar que es JSON parseable antes de devolverlo — el llamador
            # (import_chatgpt_package) hace la validación de contrato completa.
            json.loads(content)
            logger.info("Paquete premium generado OK (%d chars de entrada)", len(text))
            return content
        except Exception as exc:  # noqa: BLE001 - reintenta cualquier falla de red/parseo
            last_error = exc
            logger.warning("Generación premium intento %d/%d: %s", attempt, retry_count, exc)
            if attempt < retry_count:
                time.sleep(retry_sleep)

    raise PremiumGenerationError(f"no se pudo generar el paquete tras {retry_count} intentos: {last_error}")
