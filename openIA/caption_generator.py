"""
Genera captions estructurados para Instagram/Facebook.
Formato visual: 2 emojis + TITULO + 👇, cuerpo con emojis consistentes, sin etiquetas de texto.
"""
import json
import os
import re
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
    Genera titulo_instagram, texto_instagram y cta con Gemini.
    Retorna fallback si Gemini no está disponible o falla.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        return _fallback(noticia, "credential_missing")

    retry_count = int(os.getenv("GEMINI_RETRY_COUNT", "3"))
    retry_sleep  = float(os.getenv("GEMINI_RETRY_SLEEP", "2"))
    timeout      = float(os.getenv("GEMINI_TIMEOUT", "60"))
    model        = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    from utils.ai_client import chat_completion

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
            content = chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ],
                model=model,
                api_key=api_key,
                temperature=0.6,
                max_tokens=700,
                timeout=timeout,
                json_mode=True,
            )
            data = json.loads(content.strip())
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
    return _fallback(noticia, "gemini_failed")


# ── Localidad + bajada para piezas de una sola imagen ──────────
# Completa el chip de lugar y la bajada (texto corto ANTES del título) de
# AutomaticInstagramCard.tsx (ver docs/DECISIONS.md). Función separada de
# generate_caption: pauta y esquema propios, y así un cambio acá nunca
# arriesga el contrato/prompt ya validado de los captions.

_LOCALITY_DECK_SCHEMA = """
{
  "locality": "...",
  "deck": "..."
}
""".strip()

_LOCALITY_DECK_HIGHLIGHT_SCHEMA = """
{
  "locality": "...",
  "deck": "...",
  "highlight_phrase": "..."
}
""".strip()

_LOCALITY_DECK_PROMPT = f"""
Sos editor de "La Voz Riojana", medio digital de La Rioja, Argentina.

Salida obligatoria: JSON válido con exactamente estas claves:
{_LOCALITY_DECK_SCHEMA}

- "locality": una localidad, departamento o ciudad de La Rioja (p.ej. "Chilecito", "Capital", "Famatina") SOLO si el texto la nombra explícitamente. Si no hay ninguna localidad riojana concreta y verificable en el texto, dejalo vacío ("").
- "deck": una frase corta (máximo 90 caracteres) que funciona como bajada ANTES del título — agrega contexto o un dato (cuándo, quién, por qué importa), nunca repite ni parafrasea el título. Español rioplatense, sin emojis, sin comillas, sin punto final.
- No inventes lugares, datos, cifras, armas, personas ni hechos que no estén en el texto.
""".strip()

_LOCALITY_DECK_HIGHLIGHT_PROMPT = _LOCALITY_DECK_PROMPT.replace(
    _LOCALITY_DECK_SCHEMA,
    _LOCALITY_DECK_HIGHLIGHT_SCHEMA,
).replace(
    '- No inventes lugares, datos, cifras, armas, personas ni hechos que no estén en el texto.',
    '- "highlight_phrase": elegí UNA frase de 2 a 4 palabras CONTIGUAS copiadas literalmente del título. Aplicá estas reglas en orden:\n'
    '  1. Debe expresar el núcleo de la noticia: acción + objeto, sujeto + decisión o resultado principal.\n'
    '  2. Priorizá la cláusula principal y la primera mitad del título.\n'
    '  3. No elijas sólo lugar, fecha, horario ni cierres genéricos como "en la ciudad", "durante la jornada" o "en distintos puntos".\n'
    '  4. No elijas las últimas palabras por el solo hecho de estar al final; usalas únicamente si allí está la acción o el resultado principal.\n'
    '  5. No empieces ni termines la frase con artículos, preposiciones o conjunciones. No reescribas ni agregues palabras.\n'
    'Se usará en azul o rojo dentro de la card.\n'
    '- No inventes lugares, datos, cifras, armas, personas ni hechos que no estén en el texto.',
)


_HIGHLIGHT_STOPWORDS = {
    "a", "al", "ante", "bajo", "con", "contra", "de", "del", "desde",
    "durante", "e", "el", "en", "entre", "hacia", "hasta", "la", "las",
    "lo", "los", "o", "para", "por", "que", "se", "sin", "sobre", "su",
    "sus", "tras", "un", "una", "y",
}

_HIGHLIGHT_GENERIC_WORDS = {
    "actualidad", "administración", "ahora", "área", "áreas", "autoridad",
    "autoridades", "ciudad", "comunidad", "departamento", "diferentes",
    "distinto", "distintos", "diversas", "diversos", "gobierno", "hoy",
    "institución", "jornada", "local", "localidad", "lugar", "mañana", "mes",
    "meses", "momento", "municipalidad", "municipio", "organismo", "parte",
    "policía", "policia", "provincia", "punto", "puntos", "región", "rioja",
    "riojana", "riojano", "sector", "sectores", "semana", "toda", "todas",
    "todo", "todos", "varias", "varios", "zona", "zonas",
}

# Raíces de acciones/resultados frecuentes en títulos. Sólo se usan para
# permitir una frase ubicada al final cuando allí está realmente el hecho
# principal; no agregan ni reescriben texto.
_HIGHLIGHT_EVENT_PREFIXES = (
    "acord", "anunci", "aprob", "aument", "comenz", "confirm", "declar",
    "denunci", "despleg", "detuv", "disp", "fallec", "gan", "habilit",
    "inaugur", "investig", "lanz", "muri", "orden", "perdi", "present",
    "rechaz", "recuper", "reduj", "reforz", "realiz", "resolv", "secuestr",
    "suspend",
)

_HIGHLIGHT_EVENT_NOUNS = {
    "acuerdo", "aumento", "choque", "condena", "detención", "incendio",
    "medida", "obras", "operativo", "plan", "reforma", "rescate",
}


def _normalized_title_word(value: str) -> str:
    """Normaliza sólo puntuación de borde, igual que FittedTitle.tsx."""
    return re.sub(r"^\W+|\W+$", "", str(value or "").casefold(), flags=re.UNICODE)


def _is_highlight_event_word(word: str) -> bool:
    return word in _HIGHLIGHT_EVENT_NOUNS or any(
        word.startswith(prefix) for prefix in _HIGHLIGHT_EVENT_PREFIXES
    )


def _highlight_candidate_score(normalized_title: list[str], start: int, length: int) -> float | None:
    """Aplica reglas estructurales y puntúa una ventana exacta del título."""
    window = normalized_title[start : start + length]
    if not 2 <= length <= 4 or len(window) != length or not all(window):
        return None
    if window[0] in _HIGHLIGHT_STOPWORDS or window[-1] in _HIGHLIGHT_STOPWORDS:
        return None

    content = [word for word in window if word not in _HIGHLIGHT_STOPWORDS]
    informative = [word for word in content if word not in _HIGHLIGHT_GENERIC_WORDS]
    event_count = sum(_is_highlight_event_word(word) for word in informative)
    if len(content) < 2 or len(informative) < 2:
        return None

    # Un cierre tardío sólo pasa si contiene una acción o resultado concreto.
    # Evita destacar por defecto frases como "distintos puntos de la ciudad".
    if len(normalized_title) >= 7 and start * 100 >= len(normalized_title) * 65 and event_count == 0:
        return None

    stopword_count = length - len(content)
    generic_count = len(content) - len(informative)
    return (
        sum(min(len(word), 10) for word in informative)
        + len(informative) * 6
        + event_count * 10
        - stopword_count * 4
        - generic_count * 7
        - abs(length - 3.5) * 2
        - start * 1.35
    )


def _validated_highlight_phrase(title: str, phrase: str) -> str:
    """Acepta sólo una frase exacta que cumpla las reglas editoriales."""
    title_words = str(title or "").split()
    phrase_words = str(phrase or "").split()
    if not 2 <= len(phrase_words) <= 4:
        return ""
    normalized_phrase = [_normalized_title_word(word) for word in phrase_words]
    if not all(normalized_phrase):
        return ""
    normalized_title = [_normalized_title_word(word) for word in title_words]
    for start in range(0, len(title_words) - len(phrase_words) + 1):
        if normalized_title[start : start + len(phrase_words)] != normalized_phrase:
            continue
        if _highlight_candidate_score(normalized_title, start, len(phrase_words)) is None:
            return ""
        return " ".join(title_words[start : start + len(phrase_words)])
    return ""


def _select_highlight_phrase(title: str) -> str:
    """Fallback local: aplica las mismas reglas sin inventar texto."""
    words = str(title or "").split()
    normalized = [_normalized_title_word(word) for word in words]
    if len(words) < 2:
        return ""

    best: tuple[float, int, int] | None = None
    for length in range(2, min(4, len(words)) + 1):
        for start in range(0, len(words) - length + 1):
            score = _highlight_candidate_score(normalized, start, length)
            if score is None:
                continue
            candidate = (score, -start, length)
            if best is None or candidate > best:
                best = candidate

    if best is None:
        # Títulos demasiado cortos o genéricos: no se colorea nada antes que
        # forzar una frase sin sentido.
        return ""
    _score, neg_start, length = best
    start = -neg_start
    return " ".join(words[start : start + length])


def select_highlight_phrase(title: str) -> str:
    """API pública del selector local verificable para renders sin metadata previa."""
    return _select_highlight_phrase(title)


def _locality_deck_fallback(reason: str, noticia: dict, *, include_highlight: bool = False) -> dict:
    result = {
        "locality": "",
        "deck": "",
        "locality_deck_fallback_used": True,
        "locality_deck_fallback_reason": reason,
    }
    if include_highlight:
        result["highlight_phrase"] = _select_highlight_phrase(noticia.get("titulo", ""))
    return result


def generate_locality_and_deck(noticia: dict, *, include_highlight: bool = False) -> dict:
    """Completa localidad y bajada; opcionalmente, la frase destacada.

    ``include_highlight`` se activa desde Publicaciones manuales y, detrás
    de su flag propio, desde el lote automático. La frase siempre se toma
    de palabras contiguas del título; si Gemini no está disponible o propone
    texto ajeno, se usa un selector local que no inventa contenido.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        return _locality_deck_fallback("credential_missing", noticia, include_highlight=include_highlight)

    retry_count = int(os.getenv("GEMINI_RETRY_COUNT", "3"))
    retry_sleep  = float(os.getenv("GEMINI_RETRY_SLEEP", "2"))
    timeout      = float(os.getenv("GEMINI_TIMEOUT", "60"))
    model        = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    from utils.ai_client import chat_completion

    texto_body   = " ".join(noticia.get("parrafos", [])[:4])[:2000]
    user_content = f"Titulo: {noticia.get('titulo', '')}\nNoticia:\n{texto_body}"
    system_prompt = _LOCALITY_DECK_HIGHLIGHT_PROMPT if include_highlight else _LOCALITY_DECK_PROMPT

    for attempt in range(1, retry_count + 1):
        try:
            content = chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ],
                model=model,
                api_key=api_key,
                temperature=0.4,
                max_tokens=240 if include_highlight else 200,
                timeout=timeout,
                json_mode=True,
            )
            data = json.loads(content.strip())
            result = {
                "locality": str(data.get("locality") or "").strip()[:40],
                "deck":     str(data.get("deck") or "").strip()[:90],
                "locality_deck_fallback_used": False,
            }
            if include_highlight:
                title = str(noticia.get("titulo") or "")
                highlight_phrase = _validated_highlight_phrase(title, data.get("highlight_phrase") or "")
                if not highlight_phrase:
                    highlight_phrase = _select_highlight_phrase(title)
                result["highlight_phrase"] = highlight_phrase
            logger.info(f"Locality/deck OK: locality={result['locality']!r}")
            return result
        except Exception as e:
            logger.warning(f"Locality/deck intento {attempt}/{retry_count}: {e}")
            if attempt < retry_count:
                time.sleep(retry_sleep)

    logger.error(f"Locality/deck falló para: {noticia.get('titulo', '')[:60]}, usando vacío")
    return _locality_deck_fallback("gemini_failed", noticia, include_highlight=include_highlight)
