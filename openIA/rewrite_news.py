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
from utils.file_manager import (
    JsonStateError,
    load_json,
    update_json,
    update_json_files,
)
from utils.durable_queue import DurableQueue
from utils.editorial_policy import evaluate_fallback_policy
from utils.editorial_priority import priority_interleave
from utils.editorial_router import apply_routing
from utils.news_filters import is_blocked
from utils.news_dedup import duplicate_reason
from utils.logging_setup import setup_logger
from utils.classifier import clasificar_con_resultado
from utils.paths import data_dir
from utils.queue_events import record_queue_event
from utils.stage_result import StageResult, StageStatus, emit_stage_result, result_from_counts
from utils.url_normalization import url_hash
from openIA.caption_generator import generate_caption

logger = setup_logger("rewrite_news", "rewrite_news.log")

DATA_DIR = str(data_dir())
INPUT_FILES = [
    os.path.join(DATA_DIR, "noticias_norewrite_locales.json"),
    os.path.join(DATA_DIR, "noticias_norewrite_policiales.json"),
    os.path.join(DATA_DIR, "noticias_norewrite_interior.json"),
    os.path.join(DATA_DIR, "noticias_norewrite_deportes.json"),
    os.path.join(DATA_DIR, "noticias_norewrite_nuevarioja.json"),
]
META_OUTPUT = os.path.join(DATA_DIR, "noticias_meta.json")
WEB_OUTPUT = os.path.join(DATA_DIR, "noticias_web_pending.json")
REWRITE_STATE = os.path.join(DATA_DIR, "rewrite_queue_state.json")

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
    "fallbacks_used",
    "fallback_policy",
    "editorial_route",
    "route_by_channel",
    "route_reason",
    "topic_key",
    "topic_post_number",
    "material_update",
    "breaking",
    "routed_at_ts",
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

    fallbacks_used: dict[str, bool] = {}
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
        noticia["rewrite_fallback_used"] = True
        fallbacks_used["original_title"] = True
    if "rewrite_fallback_used" not in noticia:
        noticia["rewrite_fallback_used"] = False

    # Clasificar con IA y sobreescribir sección
    noticia["seccion_scraper"] = noticia.get("seccion", "")
    classification = clasificar_con_resultado(noticia["titulo"], parrafos)
    noticia["seccion"] = classification.category
    noticia["classification_fallback_used"] = classification.fallback_used
    if classification.fallback_used:
        fallbacks_used["category"] = True

    # Generar caption estructurado (titulo mayusculas + que paso + lo relevante + el detalle + CTA)
    caption_data = generate_caption(noticia)
    noticia.update(caption_data)
    if caption_data.get("caption_fallback_used"):
        fallbacks_used["caption"] = True

    noticia.setdefault("queued_at", int(time.time()))
    noticia["fallbacks_used"] = fallbacks_used
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
    if seed.get("fallbacks_used"):
        item["rewrite_fallbacks_used"] = copy.deepcopy(seed["fallbacks_used"])
    if seed.get("fallback_policy"):
        item["rewrite_fallback_policy"] = copy.deepcopy(seed["fallback_policy"])
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


def _prune_queue(path: str, *, ttl_days: int, time_field: str) -> int:
    cutoff = int(time.time()) - ttl_days * 86400
    expired: list[dict] = []

    def prune(queue):
        for item in queue:
            try:
                timestamp = int(item.get(time_field, item.get("queued_at", cutoff)) or cutoff)
            except (TypeError, ValueError):
                timestamp = cutoff
            if timestamp < cutoff:
                expired.append(copy.deepcopy(item))
        return [item for item in queue if item not in expired]

    update_json(path, prune, [], expected_type=list)
    if expired:
        for item in expired:
            record_queue_event(
                stage="rewrite_output_ttl",
                status="expired",
                reason=f"ttl_exceeded:{ttl_days}d",
                item=item,
                metadata={"queue": os.path.basename(path)},
            )
        logger.info("%s: %s entradas expiradas (>%sd)", os.path.basename(path), len(expired), ttl_days)
    return len(expired)


def normalize_meta_queue() -> list[dict]:
    """Migra entradas completas viejas hacia la cola web y deja Meta en formato social."""
    stats = {"web_added": 0, "normalized": False}

    def migrate(files):
        pending = files[META_OUTPUT]
        pending_web = files[WEB_OUTPUT]
        for item in pending:
            if item.get("parrafos") and (
                item.get("imagen")
                or item.get("imagen_optimizada")
                or item.get("imagen_url")
            ):
                if _append_unique(pending_web, build_web_item(item), "web_queue_key"):
                    stats["web_added"] += 1
        normalized = [build_meta_item(item) for item in pending]
        stats["normalized"] = normalized != pending
        files[WEB_OUTPUT] = pending_web
        files[META_OUTPUT] = normalized
        return files

    values = update_json_files(
        {
            META_OUTPUT: ([], list),
            WEB_OUTPUT: ([], list),
        },
        migrate,
        save_order=[WEB_OUTPUT, META_OUTPUT],
    )
    if stats["web_added"]:
        logger.info(
            "Migradas %s entradas completas a noticias_web_pending.json",
            stats["web_added"],
        )
    if stats["normalized"]:
        logger.info("noticias_meta.json normalizado al formato social/Meta")
    return values[META_OUTPUT]


ARTICLE_MAX_AGE_DAYS = int(os.getenv("ARTICLE_MAX_AGE_DAYS", "1"))
_ARTICLE_NOT_BEFORE_RAW = str(os.getenv("ARTICLE_NOT_BEFORE_DATE") or "").strip()
ARTICLE_NOT_BEFORE_DATE = (
    date.fromisoformat(_ARTICLE_NOT_BEFORE_RAW)
    if _ARTICLE_NOT_BEFORE_RAW
    else None
)


def _is_too_old(noticia: dict) -> bool:
    """Descarta artículos anteriores al corte operativo o demasiado antiguos."""
    fecha = noticia.get("fecha")
    if not fecha:
        return ARTICLE_NOT_BEFORE_DATE is not None
    try:
        article_date = date.fromisoformat(str(fecha)[:10])
        if ARTICLE_NOT_BEFORE_DATE and article_date < ARTICLE_NOT_BEFORE_DATE:
            return True
        return article_date < date.today() - timedelta(days=ARTICLE_MAX_AGE_DAYS)
    except ValueError:
        return ARTICLE_NOT_BEFORE_DATE is not None


def _expiry_reason(noticia: dict) -> str:
    fecha = str(noticia.get("fecha") or "")
    try:
        article_date = date.fromisoformat(fecha[:10])
    except ValueError:
        article_date = None
    if ARTICLE_NOT_BEFORE_DATE and article_date is None:
        return (
            "article_date_unverifiable_for_cutoff:"
            f"{ARTICLE_NOT_BEFORE_DATE.isoformat()}"
        )
    if (
        ARTICLE_NOT_BEFORE_DATE
        and article_date
        and article_date < ARTICLE_NOT_BEFORE_DATE
    ):
        return f"article_before_cutoff:{ARTICLE_NOT_BEFORE_DATE.isoformat()}"
    return f"article_age_exceeded:{ARTICLE_MAX_AGE_DAYS}d"


def _append_output(path: str, item: dict, key_field: str) -> bool:
    added = False

    def append(queue):
        nonlocal added
        if not isinstance(queue, list):
            raise ValueError(f"{path} debe contener una lista")
        added = _append_unique(queue, item, key_field)
        return queue

    update_json(path, append, [], expected_type=list)
    return added


def run_rewrite_pipeline(*, processor=None) -> StageResult:
    """Transfiere staging a Processing durable y procesa con recuperación idempotente."""
    started = time.monotonic()
    processor = processor or rewrite_noticia
    os.makedirs(DATA_DIR, exist_ok=True)
    queue = DurableQueue(
        REWRITE_STATE,
        "rewrite",
        max_attempts=int(os.getenv("REWRITE_MAX_ATTEMPTS", "3")),
    )

    try:
        recovered = queue.recover_processing()
        ingested = sum(queue.transfer_from_legacy(path) for path in INPUT_FILES)
        normalize_meta_queue()
        output_expired = _prune_queue(
            META_OUTPUT,
            ttl_days=int(os.getenv("SOCIAL_QUEUE_TTL_DAYS", "30")),
            time_field="queued_at",
        ) + _prune_queue(
            WEB_OUTPUT,
            ttl_days=int(os.getenv("WEB_QUEUE_TTL_DAYS", "30")),
            time_field="web_queued_at",
        )
        snapshot = queue.snapshot()
    except (JsonStateError, ValueError) as exc:
        logger.error("No se pudo preparar la cola durable de reescritura: %s", exc)
        return StageResult(
            "rewrite",
            StageStatus.FAILED,
            failed=1,
            duration_seconds=time.monotonic() - started,
            error_type="state_error",
            details={"message": str(exc)},
        )

    pending_count = len(snapshot["pending"])
    if pending_count == 0:
        return StageResult(
            "rewrite",
            StageStatus.NO_WORK,
            expired=output_expired,
            duration_seconds=time.monotonic() - started,
            details={"ingested": ingested, "recovered": recovered},
        )

    processed = 0
    succeeded = 0
    failed = 0
    expired = output_expired
    deferred = 0
    meta_added = 0
    web_added = 0
    fallback_count = 0

    while True:
        job = queue.claim_one()
        if not job:
            break
        item_id = job["id"]
        noticia = copy.deepcopy(job["payload"])
        processed += 1

        if is_blocked(noticia, stage="rewrite"):
            queue.dead_letter(item_id, "blocked_by_editorial_keyword")
            record_queue_event(
                stage="rewrite",
                status="dead_letter",
                reason="blocked_by_editorial_keyword",
                item=noticia,
            )
            succeeded += 1
            continue

        if _is_too_old(noticia):
            expiry_reason = _expiry_reason(noticia)
            queue.expire(item_id, expiry_reason)
            record_queue_event(
                stage="rewrite",
                status="expired",
                reason=expiry_reason,
                item=noticia,
            )
            expired += 1
            succeeded += 1
            continue

        original = copy.deepcopy(noticia)
        try:
            rewritten = processor(noticia)
        except Exception as exc:
            destination = queue.fail(
                item_id,
                f"{type(exc).__name__}:{exc}",
                retryable=True,
            )
            record_queue_event(
                stage="rewrite",
                status="failed" if destination == "pending" else "dead_letter",
                reason="rewrite_exception",
                item=original,
                metadata={"error_type": type(exc).__name__, "message": str(exc)},
            )
            failed += 1
            if destination == "pending":
                deferred += 1
            continue

        decision = evaluate_fallback_policy(
            original,
            rewritten.get("fallbacks_used") or {},
        )
        rewritten["fallback_policy"] = decision.to_dict()
        if not decision.allowed:
            queue.dead_letter(item_id, decision.reason or "fallback_blocked")
            record_queue_event(
                stage="rewrite",
                status="dead_letter",
                reason=decision.reason or "fallback_blocked",
                item=rewritten,
                metadata={"fallbacks": list(decision.fallbacks)},
            )
            failed += 1
            continue

        # Router editorial: sólo para noticias que efectivamente van a cola
        # (no para las bloqueadas por política de fallback arriba). Aditivo
        # y resiliente: un fallo acá nunca reintenta la reescritura ni la
        # llamada a OpenAI; se conserva "automatic" por omisión.
        try:
            routing_decision = apply_routing(rewritten)
            rewritten.update(routing_decision.to_dict())
        except (JsonStateError, ValueError) as exc:
            logger.warning("Router editorial falló, se conserva comportamiento actual: %s", exc)

        try:
            meta_item = build_meta_item(rewritten)
            web_item = build_web_item(original, editorial_seed=rewritten)
            if _append_output(META_OUTPUT, meta_item, "meta_queue_key"):
                meta_added += 1
            if _append_output(WEB_OUTPUT, web_item, "web_queue_key"):
                web_added += 1
            queue.complete(
                item_id,
                {
                    "meta_queue_key": meta_item.get("meta_queue_key"),
                    "web_queue_key": web_item.get("web_queue_key"),
                    "fallback_policy": decision.to_dict(),
                },
            )
            if decision.degraded:
                fallback_count += 1
                record_queue_event(
                    stage="rewrite",
                    status="degraded",
                    reason="fallback_published_to_queue",
                    item=rewritten,
                    metadata={"fallbacks": list(decision.fallbacks)},
                )
            succeeded += 1
        except (JsonStateError, ValueError) as exc:
            destination = queue.fail(item_id, f"state_write_error:{exc}", retryable=True)
            failed += 1
            if destination == "pending":
                deferred += 1
            record_queue_event(
                stage="rewrite",
                status="failed",
                reason="state_write_error",
                item=rewritten,
                metadata={"message": str(exc)},
            )

    result = result_from_counts(
        "rewrite",
        received=pending_count,
        selected=pending_count,
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        deferred=deferred,
        expired=expired,
        duration_seconds=time.monotonic() - started,
        details={
            "ingested": ingested,
            "recovered": recovered,
            "meta_added": meta_added,
            "web_added": web_added,
            "fallback_count": fallback_count,
            "state_path": REWRITE_STATE,
        },
    )
    if fallback_count and result.status == StageStatus.SUCCESS:
        result.status = StageStatus.DEGRADED
        result.error_type = "fallback_used"
    logger.info(
        "Reescritura status=%s procesadas=%s exitosas=%s fallidas=%s expiradas=%s",
        result.status.value,
        result.processed,
        result.succeeded,
        result.failed,
        result.expired,
    )
    return result


def main() -> StageResult:
    return run_rewrite_pipeline()


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
