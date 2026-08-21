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
import re
import time

from utils.logging_setup import setup_logger

logger = setup_logger("premium_package_generator", "premium_package_generator.log")

CATEGORIES = (
    "policiales", "interior", "sociedad", "economia", "salud",
    "educacion", "deportes", "cultura", "espectaculos", "politica",
)
TEMPLATES = ("lvr_cronica", "lvr_datos", "lvr_visual")
SLIDE_TYPES = (
    "cover", "image_text", "full_image", "key_points", "quote", "number",
    "closing", "context", "impact",
)
TITLE_MIN_CHARS = 60
TITLE_MAX_CHARS = 80
GENERATED_MIN_SLIDES = 3
GENERATED_MAX_SLIDES = 4

_JSON_SCHEMA = """
{
  "title": "título informativo de 60 a 80 caracteres",
  "caption": "caption periodístico local con emojis, fuente si consta y hashtags relevantes al final",
  "section": "una de: policiales, interior, sociedad, economia, salud, educacion, deportes, cultura, espectaculos, politica",
  "suggested_template": "lvr_cronica | lvr_datos | lvr_visual",
  "slides": [
    {
      "type": "cover | image_text | full_image | key_points | quote | number | closing | context | impact",
      "text": "...",
      "title": "...",
      "items": ["..."],
      "highlights": ["..."],
      "locality": "nombre de lugar (p.ej. Chilecito) sólo si el texto lo nombra; nunca inventar",
      "asset_hint": "2 a 4 palabras para buscar una imagen relacionada, o vacío en slides sin imagen",
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

OBJETIVO EDITORIAL
El carrusel debe permitir comprender la noticia completa sin abrir el caption.
Al terminar de leerlo, el lector tiene que poder responder: qué pasó, qué
cambia, por qué importa en La Rioja y qué sigue. No reserves información
esencial para el caption — el caption sólo resume, nunca contiene hechos
exclusivos.

TÍTULO PRINCIPAL (campo "title" y "title" del primer cover)
- Debe tener entre {TITLE_MIN_CHARS} y {TITLE_MAX_CHARS} caracteres, contando
  espacios y signos. El título del cover debe ser exactamente el mismo.
- Escribilo en minúsculas editoriales. Conservá mayúsculas sólo cuando sean
  necesarias en nombres propios, siglas o denominaciones oficiales; nunca uses
  TODO EN MAYÚSCULAS ni mayúscula inicial en cada palabra.
- Debe sonar natural, periodístico y humano, no como una plantilla de IA.
- Informá antes que impactar: orden preferido lugar + hecho principal +
  consecuencia o dato decisivo. Ejemplo de tono: "incendio en Guanchín: el fuego
  ya afectó más de 900 hectáreas" (sólo si esos datos aparecen en la entrada).
- Evitá fórmulas vacías o exageradas como "impactante hecho conmociona",
  "tremendo suceso", "dramático episodio" o "noticia que sorprende".
- En policiales, causas judiciales o hechos todavía no probados, atribuí y
  preservá la incertidumbre: "investigan", "habría", "presunto", "señalan" o
  "según informó". No condenes ni afirmes autoría antes de tiempo.
- Hacé visible la localidad o el vínculo riojano cuando el texto lo confirme
  (Capital, Chilecito, Aimogasta, Guanchín u otra). Si la noticia ocurre fuera de
  La Rioja, explicá el vínculo riojano sólo si está explícito; nunca lo inventes.

CANTIDAD Y SECUENCIA DE SLIDES
- Generá exactamente 3 o 4 slides. Usá 4 por defecto
  cuando el texto de entrada supere las 180 palabras o contenga contexto
  local, consecuencias y próximos pasos; usá 3 si el hecho es simple y no
  hay tanto para desarrollar.
- Cada type puede aparecer una sola vez en el carrusel. No generes dos
  context, dos impact, dos key_points ni ninguna otra repetición de tipo.
- Secuencia preferida (adaptar el tipo real al contenido disponible, no
  forzar los cuatro si el texto no da para tanto):
  1. type="cover": qué ocurrió y por qué importa.
  2. type="key_points" o type="number": qué cambia o cuáles son los datos
     centrales.
  3. type="context" o type="image_text": antecedentes y explicación.
  4. type="impact" si existe material para desarrollar el impacto concreto
     en La Rioja, qué sucede ahora, quién decide o qué debe seguirse. Impact
     es textual y no requiere imagen; no repitas context para esta función.
- No uses type="closing" en la generación automática: con sólo 3 o 4 lugares,
  cada slide debe contar una parte sustantiva de la noticia. El operador puede
  agregar un cierre manual después si lo necesita.
- NO generes type="quote" salvo que exista en el texto una declaración
  textual realmente indispensable para entender el conflicto, la decisión o
  la posición de una de las partes. Nunca inventes una cita.
- type="context" es el slide por defecto para ampliar información (no
  requiere imagen): antecedentes, impacto local, explicación o próximos
  pasos. Usa "title" (subtítulo/concepto corto) + "text" (desarrollo). No
  debe sonar a párrafo de caption pegado — tiene que tener una idea
  organizadora clara en "title".
- type="impact" es un segundo slide textual, distinto de context, reservado
  para consecuencias locales, aplicación práctica o próximos pasos. Usá
  "title" + "text", no requiere imagen y sólo debe aparecer una vez.

REGLAS DE TEXTO DE LOS SLIDES
- Portada (cover): repetí exactamente el "title" principal de 60 a 80
  caracteres; la bajada "text" debe tener 20 a 35 palabras y sumar qué pasó,
  dónde ocurrió o por qué importa, sin repetir el título.
- Slides interiores (context/impact/image_text/key_points/number/full_image):
  desarrollá 40 a 80 palabras por slide, sin superar 500 caracteres. No uses
  frases de relleno para alcanzar la extensión.
- key_points: entre 3 y 4 "items", cada uno una idea COMPLETA de 10 a 25
  palabras (no una palabra suelta ni un fragmento); la suma del slide debe
  quedar entre 40 y 80 palabras.
- Cada slide debe aportar información nueva — no repitas el mismo dato en
  título, bajada y cuerpo de distintas slides.
- No uses frases genéricas ("una medida importante", "un tema que genera
  debate"): nombrá sujetos, medidas y consecuencias concretas.
- Diferenciá explícitamente en el texto: efecto directo, consecuencia
  posible, interpretación política, y dato atribuido a una fuente concreta
  (Gobierno u otra). Conservá matices y atribuciones que ya estén en el
  texto original ("podría", "según el Gobierno", "no apunta directamente a
  ...") — no los borres ni los conviertas en afirmaciones categóricas. No
  exageres el impacto local ni presentes una consecuencia indirecta como si
  fuera automática.
- "highlights": el énfasis es de FRASE, no de palabra suelta. 1 o 2 frases
  por slide como máximo, cada una de 2 a 5 palabras, y deben aparecer
  literalmente (contiguas, en ese orden) en el "title" o "text" de esa
  misma slide — nunca palabras sueltas sin relación entre sí. En conjunto,
  las frases destacadas de una slide no deben superar ~30% de las palabras
  de su texto principal. Ejemplos de frases válidas: "un comercio en pleno
  centro", "segundo incendio comercial", "presupuesto 2026", "obra
  pública", "seis departamentos del interior". Ejemplos inválidos: "un",
  "comercio" (palabra suelta), o una frase de una sola palabra salvo que
  sea un término compuesto corto ya usado como tal (p.ej. "presupuesto
  2026").
- "locality": completalo sólo si el texto nombra un lugar concreto de La
  Rioja con relación directa a la noticia (p.ej. "Chilecito", "Aimogasta");
  dejalo vacío si no aplica. Nunca lo repitas dentro de "highlights" — la
  localidad se muestra aparte, como chip, no como frase destacada del
  título.
- "asset_hint" debe quedar vacío en slides sin imagen (context, impact,
  key_points, number, quote, closing). Sólo cover, image_text y full_image pueden pedir
  o recibir una imagen.
- Español rioplatense, directo, sin inventar emociones que el texto no
  exprese.

CAPTION PARA REDES (campo "caption")
- Abrí con un primer párrafo fuerte e informativo: qué pasó, dónde y por qué
  importa. Tono periodístico local, claro y profesional.
- Reordená y limpiá la entrada; no copies literalmente párrafos ni oraciones
  largas. Podés sintetizar, pero no agregues hechos nuevos.
- Usá de 2 a 5 emojis como separadores visuales pertinentes, sin convertir el
  texto en algo gracioso salvo temas de color, fútbol o festejos. Ejemplos:
  🔥 incendio, ⚖️ justicia, 🚨 urgente, 📍 ubicación, 📌 o 📊 dato clave.
- En muertes, violencia, accidentes y causas judiciales evitá morbo,
  adjetivos condenatorios, mayúsculas alarmistas y descripciones innecesarias.
- Agregá contexto sólo cuando figure en la entrada: ubicación, organismo o
  fuente, datos oficiales, estado de la investigación, recomendaciones e
  impacto local. Nunca completes esos datos desde conocimiento externo.
- Si la entrada identifica una fuente, cerrá antes de los hashtags con una
  línea "Fuente: Nombre". No inventes ni deduzcas una fuente ausente.
- La última línea debe contener de 3 a 6 hashtags relevantes. Incluí siempre
  #LaRioja; agregá localidad y tema sólo si corresponden, por ejemplo
  #Chilecito, #Policiales, #Justicia, #IncendioForestal o #Turismo. No uses
  hashtags irrelevantes y no incluyas @menciones ni URLs.
- El caption resume: ningún dato factual puede aparecer sólo acá. Todo hecho,
  cifra, atribución o recomendación importante debe estar también en los
  slides.

ANTES DE DEVOLVER EL JSON, VERIFICÁ INTERNAMENTE
- ¿Se entiende la noticia completa sin necesidad de leer el caption?
- ¿Aparece La Rioja/la localidad cuando el texto realmente aporta una
  relación local (y nunca inventada)?
- ¿Cada slide agrega información que no está en las demás?
- ¿El título tiene 60 a 80 caracteres, evita clickbait y mantiene prudencia
  judicial?
- ¿El caption termina con hashtags pertinentes, incluye #LaRioja y usa emojis
  sin morbo?
- ¿Hay alguna cita o cierre que podría eliminarse sin perder información? Si
  la hay, no la incluyas.
- ¿Se conservaron todos los matices y atribuciones relevantes del texto
  original?

Salida obligatoria: JSON válido con exactamente esta forma:
{_JSON_SCHEMA}
""".strip()


class PremiumGenerationError(RuntimeError):
    pass


_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_HASHTAG_RE = re.compile(r"(?<!\w)#[\wÁÉÍÓÚÜÑáéíóúüñ]+", re.UNICODE)
_CLICKBAIT_PHRASES = (
    "impactante hecho",
    "conmociona",
    "tremendo suceso",
    "dramático episodio",
    "dramatico episodio",
    "noticia que sorprende",
)


def _word_count(value: object) -> int:
    return len(re.findall(r"\b[\wÁÉÍÓÚÜÑáéíóúüñ]+\b", str(value or ""), re.UNICODE))


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def normalize_generated_duplicate_context(payload: object) -> list[str]:
    """Convierte un segundo ``context`` en ``impact`` sin tocar su contenido.

    Es una reparación estructural acotada para la salida automática: ambos tipos
    son textuales y no usan imagen, pero cumplen funciones narrativas distintas.
    No intenta corregir otras repeticiones porque podría cambiar su semántica.
    """
    if not isinstance(payload, dict):
        return []
    slides = payload.get("slides")
    if not isinstance(slides, list):
        return []

    declared_types = {
        str(slide.get("type") or "")
        for slide in slides
        if isinstance(slide, dict)
    }
    if "impact" in declared_types:
        return []

    context_seen = False
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict) or slide.get("type") != "context":
            continue
        if not context_seen:
            context_seen = True
            continue
        slide["type"] = "impact"
        slide["asset_hint"] = ""
        return [f"slide_{index}_tipo_normalizado:context->impact"]
    return []


def validate_generated_payload(payload: object, source_text: str) -> list[str]:
    """Valida la calidad editorial específica de la generación automática.

    No reemplaza ``premium_contract.validate_package``: este gate es más
    estricto y sólo aplica al JSON que produce OpenAI. Los borradores manuales
    existentes mantienen compatibilidad.
    """
    if not isinstance(payload, dict):
        return ["json_debe_ser_objeto"]

    errors: list[str] = []
    title = str(payload.get("title") or "").strip()
    if not (TITLE_MIN_CHARS <= len(title) <= TITLE_MAX_CHARS):
        errors.append(f"title_longitud:{len(title)} (requerido {TITLE_MIN_CHARS}-{TITLE_MAX_CHARS})")
    if "\n" in title or "\r" in title:
        errors.append("title_debe_ser_una_linea")
    title_lower = title.casefold()
    if any(phrase in title_lower for phrase in _CLICKBAIT_PHRASES):
        errors.append("title_clickbait")
    alpha_chars = [char for char in title if char.isalpha()]
    if alpha_chars and title.upper() == title:
        errors.append("title_todo_mayusculas")

    slides = payload.get("slides")
    if not isinstance(slides, list):
        errors.append("slides_debe_ser_lista")
        slides = []
    if not (GENERATED_MIN_SLIDES <= len(slides) <= GENERATED_MAX_SLIDES):
        errors.append(
            f"slides_cantidad:{len(slides)} (requerido {GENERATED_MIN_SLIDES}-{GENERATED_MAX_SLIDES})"
        )
    if slides and isinstance(slides[0], dict):
        if slides[0].get("type") != "cover":
            errors.append("slide_0_debe_ser_cover")
        if str(slides[0].get("title") or "").strip() != title:
            errors.append("cover_title_debe_coincidir_con_title")

    seen_slide_types: set[str] = set()
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            errors.append(f"slide_{index}_debe_ser_objeto")
            continue
        slide_type = str(slide.get("type") or "")
        if slide_type not in SLIDE_TYPES:
            errors.append(f"slide_{index}_tipo_invalido:{slide_type}")
            continue
        if slide_type in seen_slide_types:
            errors.append(f"slide_{index}_tipo_duplicado:{slide_type}")
        else:
            seen_slide_types.add(slide_type)
        if slide_type == "closing":
            errors.append(f"slide_{index}_closing_no_permitido_en_generacion")

        text_words = _word_count(slide.get("text"))
        if slide_type == "cover" and not (20 <= text_words <= 35):
            errors.append(f"slide_{index}_cover_text_palabras:{text_words} (requerido 20-35)")
        elif slide_type in {"context", "impact", "image_text", "full_image"} and not (40 <= text_words <= 80):
            errors.append(f"slide_{index}_text_palabras:{text_words} (requerido 40-80)")
        elif slide_type == "number" and not (25 <= text_words <= 80):
            errors.append(f"slide_{index}_number_text_palabras:{text_words} (requerido 25-80)")
        elif slide_type == "quote" and not (8 <= text_words <= 50):
            errors.append(f"slide_{index}_quote_palabras:{text_words} (requerido 8-50)")

        if slide_type == "key_points":
            items = slide.get("items")
            if not isinstance(items, list) or not (3 <= len(items) <= 4):
                errors.append(f"slide_{index}_key_points_items:{len(items) if isinstance(items, list) else 0} (requerido 3-4)")
            else:
                total_item_words = 0
                for item_index, item in enumerate(items):
                    item_words = _word_count(item)
                    total_item_words += item_words
                    if not (10 <= item_words <= 25):
                        errors.append(
                            f"slide_{index}_item_{item_index}_palabras:{item_words} (requerido 10-25)"
                        )
                if not (40 <= total_item_words <= 80):
                    errors.append(
                        f"slide_{index}_key_points_palabras:{total_item_words} (requerido 40-80)"
                    )

    caption = str(payload.get("caption") or "").strip()
    emoji_count = len(_EMOJI_RE.findall(caption))
    if not caption:
        errors.append("caption_vacio")
    elif not (2 <= emoji_count <= 5):
        errors.append(f"caption_emojis:{emoji_count} (requerido 2-5)")

    hashtags = list(dict.fromkeys(tag.casefold() for tag in _HASHTAG_RE.findall(caption)))
    if not (3 <= len(hashtags) <= 6):
        errors.append(f"caption_hashtags:{len(hashtags)} (requerido 3-6)")
    if "#larioja" not in hashtags:
        errors.append("caption_sin_hashtag_larioja")
    nonempty_lines = [line.strip() for line in caption.splitlines() if line.strip()]
    if nonempty_lines and not all(token.startswith("#") for token in nonempty_lines[-1].split()):
        errors.append("caption_hashtags_deben_ir_en_ultima_linea")

    first_paragraph = re.split(r"\n\s*\n", caption, maxsplit=1)[0]
    normalized_first = _normalized_text(first_paragraph)
    normalized_source = _normalized_text(source_text)
    if len(normalized_first) >= 80 and normalized_first in normalized_source:
        errors.append("caption_primer_parrafo_copiado_literal")

    source_match = re.search(r"(?im)^Fuente:\s*(.+?)\s*$", caption)
    if source_match:
        source_label = _normalized_text(source_match.group(1))
        if source_label and source_label not in normalized_source:
            errors.append("caption_fuente_no_presente_en_texto_original")

    return errors


def generate_premium_package_json(raw_text: str) -> str:
    """Devuelve el texto JSON del paquete generado (mismo contrato que un
    paquete pegado manualmente desde ChatGPT). Lanza PremiumGenerationError
    si Gemini no está configurado o falla tras los reintentos — a
    diferencia del pipeline automático, acá no hay fallback silencioso:
    es una acción manual del operador, que debe ver el error y decidir.
    """
    text = str(raw_text or "").strip()
    if not text:
        raise PremiumGenerationError("el texto de la noticia está vacío")

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key == "PENDIENTE":
        raise PremiumGenerationError("GEMINI_API_KEY no está configurada")

    retry_count = int(os.getenv("GEMINI_RETRY_COUNT", "3"))
    retry_sleep = float(os.getenv("GEMINI_RETRY_SLEEP", "2"))
    timeout = float(os.getenv("GEMINI_TIMEOUT", "60"))
    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    from utils.ai_client import chat_completion

    last_error: Exception | None = None
    previous_content = ""
    last_parseable_content = ""
    validation_errors: list[str] = []
    for attempt in range(1, retry_count + 1):
        try:
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Texto de la noticia:\n\n{text[:6000]}"},
            ]
            if validation_errors:
                messages.extend(
                    [
                        {"role": "assistant", "content": previous_content},
                        {
                            "role": "user",
                            "content": (
                                "Tu JSON anterior no cumplió estas reglas editoriales:\n- "
                                + "\n- ".join(validation_errors)
                                + "\nCorregí exactamente esos puntos usando únicamente el texto "
                                "original. No agregues datos ni relleno para alcanzar las "
                                "extensiones. Devolvé el JSON completo corregido."
                            ),
                        },
                    ]
                )
            content = chat_completion(
                messages=messages,
                model=model,
                api_key=api_key,
                temperature=0.4,
                max_tokens=2600,
                timeout=timeout,
                json_mode=True,
            ).strip()
            payload = json.loads(content)
            structural_repairs = normalize_generated_duplicate_context(payload)
            if structural_repairs:
                content = json.dumps(payload, ensure_ascii=False)
                logger.warning(
                    "Salida premium normalizada sin alterar texto: %s",
                    "; ".join(structural_repairs),
                )
            validation_errors = validate_generated_payload(payload, text)
            if validation_errors:
                previous_content = content
                last_parseable_content = content
                raise ValueError("json editorial inválido: " + "; ".join(validation_errors))
            logger.info("Paquete premium generado OK (%d chars de entrada)", len(text))
            return content
        except Exception as exc:  # noqa: BLE001 - reintenta cualquier falla de red/parseo
            last_error = exc
            logger.warning("Generación premium intento %d/%d: %s", attempt, retry_count, exc)
            if attempt < retry_count:
                time.sleep(retry_sleep)

    if last_parseable_content:
        logger.warning(
            "No se alcanzó el contrato editorial tras %d intentos; se devuelve el "
            "último JSON parseable para revisión manual: %s",
            retry_count,
            "; ".join(validation_errors),
        )
        return last_parseable_content

    raise PremiumGenerationError(f"no se pudo generar el paquete tras {retry_count} intentos: {last_error}")
