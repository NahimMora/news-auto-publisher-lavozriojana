"""
Genera captions estructurados para Instagram/Facebook.
Formato visual: 2 emojis + TITULO + 👇, cuerpo con emojis consistentes, sin etiquetas de texto.
"""
import json
import os
import time
from utils.logging_setup import setup_logger

logger = setup_logger("caption_generator", "caption_generator.log")

_JSON_SCHEMA = """
{
  "titulo_instagram": "...",
  "texto_instagram": "...",
  "cta": "..."
}
""".strip()

# ── Estructura visual unificada ───────────────────────────────
#
# [EMOJI_A][EMOJI_B] TITULO EN MAYUSCULAS 👇
#
# 📌 Párrafo 1 — qué pasó
#
# 🔑 Párrafo 2 — lo relevante / impacto
#
# 💬 Párrafo 3 — cifra, cita o detalle sorpresivo
#
# ❓ Pregunta CTA
#
# Los emojis de cuerpo (📌 🔑 💬 ❓) son SIEMPRE los mismos en todas las secciones.
# Solo cambia el emoji de apertura según la sección.

_REGLAS_COMUNES = """
REGLAS CRÍTICAS:
- NUNCA escribas etiquetas como "TITULO:", "Lo relevante:", "El detalle:", "CTA:", "📌 ¿Qué pasó?" — los emojis ya actúan como indicadores visuales.
- titulo_instagram: el título limpio, SIN emojis, máximo 80 caracteres. Es solo para la imagen.
- texto_instagram: el caption completo con la estructura de arriba, incluyendo emojis y título con emojis.
- cta: solo la pregunta final (sin emoji, sin "CTA:", sin el ❓ — eso va dentro de texto_instagram).
- Español rioplatense. Sin URLs, sin @menciones, sin hashtags dentro del texto.
- No inventes datos, cifras ni nombres que no estén en la noticia.
- Máximo 2000 caracteres en texto_instagram.
""".strip()

# ── Prompts por sección ───────────────────────────────────────

_NEWS_PROMPT = f"""
Sos redactor de "La Voz Riojana", medio digital de La Rioja, Argentina. Tono directo, informativo, vecinal.

Salida obligatoria: JSON válido con exactamente estas claves:
{_JSON_SCHEMA}

ESTRUCTURA EXACTA del campo texto_instagram:

📢🗞️ TITULO EN MAYUSCULAS 👇

📌 [Quién, qué, dónde, cuándo. 2-3 oraciones concretas.]

🔑 [Impacto para los riojanos, contexto, dato clave. 2-3 oraciones.]

💬 [Cifra, declaración textual o hecho sorpresivo. 1-2 oraciones.]

❓ [Pregunta directa y corta para que comenten.]

{_REGLAS_COMUNES}
""".strip()

_POLICIAL_PROMPT = f"""
Sos redactor policial/judicial de "La Voz Riojana", La Rioja, Argentina. Tono sobrio, informativo, sin morbo.

Salida obligatoria: JSON válido con exactamente estas claves:
{_JSON_SCHEMA}

ESTRUCTURA EXACTA del campo texto_instagram:

🚨🔴 TITULO EN MAYUSCULAS 👇

📌 [Descripción objetiva del hecho: qué ocurrió, dónde, cuándo. 2-3 oraciones.]

🔑 [Estado judicial: carátula, medidas tomadas, estado del caso. 2 oraciones.]

💬 [Dato relevante o declaración de fuente oficial. 1-2 oraciones.]

❓ [Pregunta al lector.]

{_REGLAS_COMUNES}
REGLA EXTRA: NUNCA afirmar culpabilidad sin sentencia. Usar "se lo imputa", "según la fiscalía", "habría".
No publicar datos privados de víctimas menores.
""".strip()

_DEPORTES_PROMPT = f"""
Sos redactor deportivo de "La Voz Riojana", La Rioja, Argentina. Tono dinámico, apasionado.

Salida obligatoria: JSON válido con exactamente estas claves:
{_JSON_SCHEMA}

ESTRUCTURA EXACTA del campo texto_instagram:

⚽🏆 TITULO EN MAYUSCULAS 👇

📌 [Resultado, equipo/deportista, competencia. 2-3 oraciones.]

🔑 [Lo más destacado: goleadores, estadísticas, récord. 2 oraciones.]

💬 [Declaración del protagonista o dato curioso. 1-2 oraciones.]

❓ [Pregunta al hincha o seguidor.]

{_REGLAS_COMUNES}
""".strip()

_ESPECTACULOS_PROMPT = f"""
Sos redactor de espectáculos/cultura de "La Voz Riojana", La Rioja, Argentina. Tono amigable y curioso.

Salida obligatoria: JSON válido con exactamente estas claves:
{_JSON_SCHEMA}

ESTRUCTURA EXACTA del campo texto_instagram:

🎭⭐ TITULO EN MAYUSCULAS 👇

📌 [Quién, qué ocurrió, contexto breve. 2-3 oraciones.]

🔑 [Lo más llamativo, giro interesante o impacto. 2 oraciones.]

💬 [Declaración, cita o detalle que sorprende. 1-2 oraciones.]

❓ [Pregunta al lector.]

{_REGLAS_COMUNES}
No inventes conflictos, romances ni separaciones sin fuente.
""".strip()

_PROMPT_BY_SECTION = {
    "policiales":   _POLICIAL_PROMPT,
    "deportes":     _DEPORTES_PROMPT,
    "cultura":      _ESPECTACULOS_PROMPT,
    "espectaculos": _ESPECTACULOS_PROMPT,
}


def _get_prompt(seccion: str) -> str:
    return _PROMPT_BY_SECTION.get(seccion.lower().strip(), _NEWS_PROMPT)


def _fallback(noticia: dict, reason: str = "fallback") -> dict:
    titulo = noticia.get("titulo", "")
    parrafos = noticia.get("parrafos", [])
    primer_parrafo = parrafos[0] if parrafos else ""
    texto = f"📢🗞️ {titulo.upper()} 👇\n\n📌 {primer_parrafo}" if primer_parrafo else f"📢🗞️ {titulo.upper()} 👇"
    return {
        "titulo_instagram": titulo[:80],
        "texto_instagram":  texto[:2200],
        "cta":              "¿Qué opinás?",
        "caption_fallback_used": True,
        "caption_fallback_reason": reason,
    }


def generate_caption(noticia: dict) -> dict:
    """
    Genera titulo_instagram, texto_instagram y cta con OpenAI.
    Retorna fallback si OpenAI no está disponible o falla.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        return _fallback(noticia, "credential_missing")

    retry_count = int(os.getenv("OPENAI_RETRY_COUNT", "3"))
    retry_sleep  = float(os.getenv("OPENAI_RETRY_SLEEP", "2"))
    timeout      = float(os.getenv("OPENAI_TIMEOUT", "60"))
    model        = os.getenv("OPENAI_MODEL", "gpt-4o")

    from openai import OpenAI
    client = OpenAI(api_key=api_key, timeout=timeout)

    seccion       = noticia.get("seccion", "")
    system_prompt = _get_prompt(seccion)
    texto_body    = " ".join(noticia.get("parrafos", [])[:4])[:2000]
    user_content  = (
        f"Titulo: {noticia.get('titulo', '')}\n"
        f"Seccion: {seccion}\n"
        f"Noticia:\n{texto_body}"
    )

    for attempt in range(1, retry_count + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ],
                temperature=0.6,
                max_tokens=700,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content.strip())
            result = {
                "titulo_instagram": (data.get("titulo_instagram") or noticia.get("titulo", ""))[:80],
                "texto_instagram":  (data.get("texto_instagram") or "")[:2200],
                "cta":              data.get("cta") or "¿Qué opinás?",
                "caption_fallback_used": False,
            }
            logger.info(f"Caption OK: {result['titulo_instagram'][:60]}")
            return result
        except Exception as e:
            logger.warning(f"Caption intento {attempt}/{retry_count}: {e}")
            if attempt < retry_count:
                time.sleep(retry_sleep)

    logger.error(f"Caption falló para: {noticia.get('titulo', '')[:60]}, usando fallback")
    return _fallback(noticia, "openai_failed")
