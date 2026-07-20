"""
Reescribe títulos de noticias con OpenAI para adaptarlos al estilo de La Voz Riojana.
Lee desde noticias_norewrite_*.json y escribe en noticias_meta.json (cola unificada para redes sociales).
"""
import copy
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from utils.file_manager import load_json, save_json
from utils.editorial_priority import priority_interleave
from utils.news_filters import is_blocked
from utils.news_dedup import duplicate_reason
from utils.logging_setup import setup_logger
from utils.classifier import clasificar
from utils.url_normalization import url_hash
from openIA.caption_generator import generate_caption

logger = setup_logger("rewrite_news", "rewrite_news.log")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INPUT_FILES = [
    os.path.join(DATA_DIR, "noticias_norewrite_locales.json"),
    os.path.join(DATA_DIR, "noticias_norewrite_policiales.json"),
    os.path.join(DATA_DIR, "noticias_norewrite_interior.json"),
    os.path.join(DATA_DIR, "noticias_norewrite_deportes.json"),
    os.path.join(DATA_DIR, "noticias_norewrite_nuevarioja.json"),
]
META_OUTPUT = os.path.join(DATA_DIR, "noticias_meta.json")
WEB_OUTPUT = os.path.join(DATA_DIR, "noticias_web_pending.json")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_RETRY_COUNT = int(os.getenv("OPENAI_RETRY_COUNT", "4"))
OPENAI_RETRY_SLEEP = float(os.getenv("OPENAI_RETRY_SLEEP", "3"))
OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "60"))

META_FIELDS = (
    "titulo",
    "titulo_original",
    "titulo_instagram",
    "texto_instagram",
    "cta",
    "url",
    "canonical_url",
    "seccion",
    "seccion_scraper",
    "imagen_url",
    "fecha",
    "source",
    "hashtag_localidad",
    "queued_at",
)

WEB_EXCLUDE_FIELDS = {
    "titulo_instagram",
    "texto_instagram",
    "cta",
    "dedup_key",
    "social_queued_at",
    "facebook_done",
    "instagram_done",
}

# ── Hashtags de localidades riojanas ────────────────────────
LOCALITY_HASHTAGS = [
    "#LaRioja", "#Chilecito", "#Famatina", "#Vinchina", "#Arauco",
    "#ChamicalRioja", "#Aimogasta", "#Chepes", "#Patquia", "#GeneralAngel",
    "#Tinogasta", "#AndalgalaRioja", "#CasaBlanca", "#Nonogasta",
    "#AnguinanRioja", "#SerroNegro", "#VillaUnion", "#Guandacol",
    "#SantaFlorentina", "#VillaFamatina", "#AmingoCiudad",
]

PROMPT_TEMPLATE = """Sos el editor de "La Voz Riojana", un medio digital de noticias de La Rioja, Argentina.

Tu tarea es reescribir el TÍTULO de la siguiente noticia para que sea más atractivo, claro e impactante, respetando ESTRICTAMENTE estos criterios:

REGLAS:
- Máximo 100 caracteres en el título
- No inventar datos, armas, personas ni hechos que no estén en el texto original
- No agregar emociones ni adjetivos que no estén implícitos en la noticia
- Respetar los hechos tal cual son
- El título debe ser en español rioplatense (Argentina)
- Si la noticia tiene una localidad claramente identificable de La Rioja, agregar UN solo hashtag de localidad al final del título. Si hay varias localidades o no se menciona ninguna específica, NO agregar hashtag.
- Hashtags disponibles: {hashtags}
- NO agregar hashtags de categoría (Policiales, Locales, etc.)

FORMATO DE RESPUESTA (solo esto, sin explicaciones):
TITULO: <título reescrito>
HASHTAG: <#HashtagLocalidad o NINGUNO>

NOTICIA ORIGINAL:
Título: {titulo}
Texto: {texto}
"""


def _call_openai(titulo: str, parrafos: list[str]) -> tuple[str, str]:
    """Retorna (nuevo_titulo, hashtag). Lanza excepción si falla."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=OPENAI_TIMEOUT)
    texto_resumen = " ".join(parrafos[:3])  # Primeros 3 párrafos como contexto
    prompt = PROMPT_TEMPLATE.format(
        hashtags=", ".join(LOCALITY_HASHTAGS),
        titulo=titulo,
        texto=texto_resumen[:1500],
    )

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=200,
    )
    content = resp.choices[0].message.content.strip()

    nuevo_titulo = titulo
    hashtag = ""
    for line in content.splitlines():
        if line.startswith("TITULO:"):
            nuevo_titulo = line[7:].strip()
        elif line.startswith("HASHTAG:"):
            val = line[8:].strip()
            if val and val.upper() != "NINGUNO":
                hashtag = val
    return nuevo_titulo, hashtag


def rewrite_noticia(noticia: dict) -> dict:
    titulo_original = noticia.get("titulo", "")
    parrafos = noticia.get("parrafos", [])

    for attempt in range(1, OPENAI_RETRY_COUNT + 1):
        try:
            nuevo_titulo, hashtag = _call_openai(titulo_original, parrafos)
            noticia["titulo_original"] = titulo_original
            noticia["titulo"] = nuevo_titulo
            noticia["hashtag_localidad"] = hashtag
            logger.info(f"Reescrito: {nuevo_titulo[:70]}")
            break
        except Exception as e:
            logger.warning(f"Error OpenAI intento {attempt}/{OPENAI_RETRY_COUNT}: {e}")
            if attempt < OPENAI_RETRY_COUNT:
                time.sleep(OPENAI_RETRY_SLEEP)
    else:
        # Si fallan todos los intentos, conservar título original
        logger.error(f"OpenAI falló para: {titulo_original[:60]}, conservando original")
        noticia["titulo_original"] = titulo_original
        noticia["hashtag_localidad"] = ""

    # Clasificar con IA y sobreescribir sección
    noticia["seccion_scraper"] = noticia.get("seccion", "")
    noticia["seccion"] = clasificar(noticia["titulo"], parrafos)

    # Generar caption estructurado (titulo mayusculas + que paso + lo relevante + el detalle + CTA)
    caption_data = generate_caption(noticia)
    noticia.update(caption_data)

    noticia.setdefault("queued_at", int(time.time()))
    return noticia


def _queue_key(noticia: dict) -> str:
    url = noticia.get("canonical_url") or noticia.get("url") or ""
    if url:
        return f"link:{url_hash(url)}"
    basis = "|".join(str(noticia.get(key) or "") for key in ("titulo_original", "titulo", "fecha"))
    return f"item:{url_hash(basis)}"


def _drop_empty(value):
    if isinstance(value, dict):
        return {
            key: _drop_empty(item)
            for key, item in value.items()
            if item is not None and item != "" and item != [] and item != {}
        }
    if isinstance(value, list):
        return [_drop_empty(item) for item in value if item not in (None, "", [], {})]
    return value


def build_meta_item(noticia: dict) -> dict:
    """Construye la cola social/Meta sin arrastrar el cuerpo completo scrapeado."""
    item = {
        key: copy.deepcopy(noticia.get(key))
        for key in META_FIELDS
        if key in noticia
    }
    parrafos = noticia.get("parrafos") or []
    if parrafos:
        item["excerpt"] = str(parrafos[0]).strip()
    item["meta_queue_key"] = _queue_key(noticia)
    item.setdefault("queued_at", int(time.time()))
    return _drop_empty(item)


def build_web_item(noticia: dict, editorial_seed: dict | None = None) -> dict:
    """Construye la cola web con la noticia scrapeada original."""
    item = copy.deepcopy(noticia)
    seed = editorial_seed or {}
    title_for_web = str(seed.get("titulo_instagram") or item.get("titulo_instagram") or "").strip()
    category_for_web = str(seed.get("seccion") or item.get("seccion") or "").strip()
    for key in WEB_EXCLUDE_FIELDS:
        item.pop(key, None)
    if title_for_web:
        original_title = item.get("titulo")
        if original_title and original_title != title_for_web:
            item["titulo_original_scrapeado"] = original_title
        item["titulo"] = title_for_web
    if category_for_web:
        item["categoria"] = category_for_web
    item["web_queue_key"] = _queue_key(noticia)
    item["web_queued_at"] = int(time.time())
    return _drop_empty(item)


def append_queue_items(
    *,
    original_noticia: dict,
    rewritten_noticia: dict,
    pending_meta: list[dict],
    pending_web: list[dict],
) -> tuple[bool, bool]:
    """Agrega Meta desde la noticia reescrita y Web desde la scrapeada original."""
    meta_added = _append_unique(pending_meta, build_meta_item(rewritten_noticia), "meta_queue_key")
    web_added = _append_unique(
        pending_web,
        build_web_item(original_noticia, editorial_seed=rewritten_noticia),
        "web_queue_key",
    )
    return meta_added, web_added


def _append_unique(queue: list[dict], item: dict, key_field: str) -> bool:
    key = item.get(key_field)
    if key and any(existing.get(key_field) == key for existing in queue):
        logger.info(f"Ya en cola {key_field}: {item.get('titulo', '')[:60]}")
        return False
    reason = duplicate_reason(item, queue, key_fields=(key_field, "canonical_url", "url"))
    if reason:
        logger.info(
            "Descartado duplicado cross-fuente (%s): %s",
            reason,
            item.get("titulo", "")[:60],
        )
        return False
    queue.append(item)
    return True


def _prune_queue(path: str, queue: list[dict], *, ttl_days: int, time_field: str) -> list[dict]:
    cutoff = int(time.time()) - ttl_days * 86400
    before = len(queue)
    queue = [n for n in queue if n.get(time_field, n.get("queued_at", cutoff)) >= cutoff]
    removed = before - len(queue)
    if removed:
        logger.info(f"{os.path.basename(path)}: {removed} entradas expiradas (>{ttl_days}d)")
        save_json(path, queue)
    return queue


def normalize_meta_queue() -> list[dict]:
    """Migra entradas completas viejas hacia la cola web y deja Meta en formato social."""
    pending = load_json(META_OUTPUT, [])
    pending_web = load_json(WEB_OUTPUT, [])
    web_added = 0
    for item in pending:
        if item.get("parrafos") and (
            item.get("imagen")
            or item.get("imagen_optimizada")
            or item.get("imagen_url")
        ):
            if _append_unique(pending_web, build_web_item(item), "web_queue_key"):
                web_added += 1
    if web_added:
        save_json(WEB_OUTPUT, pending_web)
        logger.info("Migradas %s entradas completas de noticias_meta.json a noticias_web_pending.json", web_added)

    normalized = [build_meta_item(item) for item in pending]
    if normalized != pending:
        save_json(META_OUTPUT, normalized)
        logger.info("noticias_meta.json normalizado al formato social/Meta")
    return normalized


ARTICLE_MAX_AGE_DAYS = int(os.getenv("ARTICLE_MAX_AGE_DAYS", "1"))


def _is_too_old(noticia: dict) -> bool:
    """Descarta artículos cuya fecha de publicación supera ARTICLE_MAX_AGE_DAYS."""
    fecha = noticia.get("fecha")
    if not fecha:
        return False
    try:
        article_date = date.fromisoformat(str(fecha)[:10])
        return article_date < date.today() - timedelta(days=ARTICLE_MAX_AGE_DAYS)
    except ValueError:
        return False


def main():
    logger.info("=== Iniciando reescritura de noticias con OpenAI ===")
    os.makedirs(DATA_DIR, exist_ok=True)

    todas = []
    for path in INPUT_FILES:
        batch = load_json(path, [])
        if batch:
            logger.info(f"Cargando {len(batch)} noticias de {os.path.basename(path)}")
            todas.extend(batch)
            # Limpiar el archivo de entrada después de procesar
            save_json(path, [])

    normalize_meta_queue()

    if not todas:
        logger.info("Sin noticias para reescribir")
        return
    todas = priority_interleave(todas)
    logger.info("Orden editorial aplicado antes de reescritura (Deportes queda con menor prioridad)")

    meta_ttl_days = int(os.getenv("META_TTL_DAYS", "7"))
    web_ttl_days = int(os.getenv("WEB_QUEUE_TTL_DAYS", "30"))

    pending_meta = _prune_queue(
        META_OUTPUT,
        load_json(META_OUTPUT, []),
        ttl_days=meta_ttl_days,
        time_field="queued_at",
    )
    pending_web = _prune_queue(
        WEB_OUTPUT,
        load_json(WEB_OUTPUT, []),
        ttl_days=web_ttl_days,
        time_field="web_queued_at",
    )

    # Guardar incrementalmente: cada artículo se persiste al terminar
    # para que un kill inesperado no pierda el trabajo ya completado
    procesadas = 0
    meta_added = 0
    web_added = 0
    for noticia in todas:
        if is_blocked(noticia, stage="rewrite"):
            continue
        if _is_too_old(noticia):
            logger.info(f"Descartada (>{ARTICLE_MAX_AGE_DAYS}d): {noticia.get('titulo', '')[:70]}")
            continue
        original_noticia = copy.deepcopy(noticia)
        reescrita = rewrite_noticia(noticia)
        added_meta, added_web = append_queue_items(
            original_noticia=original_noticia,
            rewritten_noticia=reescrita,
            pending_meta=pending_meta,
            pending_web=pending_web,
        )
        if added_meta:
            meta_added += 1
        if added_web:
            web_added += 1
        save_json(META_OUTPUT, pending_meta)
        save_json(WEB_OUTPUT, pending_web)
        procesadas += 1

    logger.info(
        "Total procesadas: %s | Meta nuevas: %s | Web nuevas: %s",
        procesadas,
        meta_added,
        web_added,
    )


if __name__ == "__main__":
    main()
