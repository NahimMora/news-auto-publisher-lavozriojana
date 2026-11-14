"""EditorialContextBundle: lo único que ve la redacción existente (Partes 34-37).

``build_context_bundle`` es el único punto de entrada que
``pipeline/node_webapp/publisher.py`` necesita llamar antes de
``prepare_editorial``. Todo lo demás (archive, story, depth, slots) es un
detalle de implementación de este módulo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from editorial_context import archive_index as ai
from editorial_context import context_depth as cd
from editorial_context import entities as ec_entities
from editorial_context import enrichment_slots as es
from editorial_context import metrics as ec_metrics
from editorial_context import retrieval
from editorial_context import story_engine
from editorial_context import timeline as tl
from utils.logging_setup import setup_logger

# Import diferido dentro de _gather_official_snippets para evitar acoplar
# este módulo a sources/ cuando sólo se usa el motor de archivo propio.

logger = setup_logger("editorial_context.bundle", "editorial_context.log")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# Límites de tamaño (Parte 35). No son requisitos matemáticos: ajustables por env.
ARCHIVE_CONTEXT_MAX_ITEMS = _env_int("ARCHIVE_CONTEXT_MAX_ITEMS", 3)
RELATED_ARTICLES_MAX_ITEMS = _env_int("RELATED_ARTICLES_MAX_ITEMS", 5)
TIMELINE_MAX_ITEMS = _env_int("TIMELINE_MAX_ITEMS", 5)
ARCHIVE_CONTEXT_MAX_CHARS = _env_int("ARCHIVE_CONTEXT_MAX_CHARS", 3500)
OFFICIAL_CONTEXT_MAX_CHARS = _env_int("OFFICIAL_CONTEXT_MAX_CHARS", 4500)
ANTECEDENT_SNIPPET_MAX_CHARS = 280
OFFICIAL_SNIPPET_MAX_ITEMS = _env_int("OFFICIAL_SNIPPET_MAX_ITEMS", 3)
OFFICIAL_SNIPPET_TEXT_MAX_CHARS = 400
OFFICIAL_ITEMS_PER_SOURCE_SCANNED = 10


@dataclass
class ContextSnippet:
    """Provenance auditable de cada fragmento usado (Parte 37)."""

    text: str
    source_type: str  # "own_archive" | "official_source"
    source_id: str = ""
    source_url: str = ""
    post_id: str = ""
    published_at: str = ""
    relation_score: float = 0.0
    # Evidencia que justificó usar el fragmento (entidades, localidades y
    # términos en común): queda en el log para auditar cada fuente citada.
    evidence: str = ""


@dataclass
class EditorialContextBundle:
    context_depth: str = "NONE"
    archive_snippets: list[ContextSnippet] = field(default_factory=list)
    official_snippets: list[ContextSnippet] = field(default_factory=list)
    enrichment_slot_dicts: list[dict] = field(default_factory=list)
    related_articles: list[dict] = field(default_factory=list)
    story_key: str = ""
    timeline: list[dict] = field(default_factory=list)
    factual_basis_text: str = ""
    # Nota anterior que hay que pasar a la misma historia verificada en el CMS
    # (el archivo no siempre tiene su post_id: el publicador lo busca por URL).
    link_previous_post_id: str = ""
    link_previous_url: str = ""

    def archive_context_text(self) -> str:
        if self.context_depth == "NONE" or not self.archive_snippets:
            return ""
        text = " ".join(s.text for s in self.archive_snippets[:ARCHIVE_CONTEXT_MAX_ITEMS])
        return text[:ARCHIVE_CONTEXT_MAX_CHARS]

    def official_context_text(self) -> str:
        if self.context_depth == "NONE" or not self.official_snippets:
            return ""
        text = " ".join(s.text for s in self.official_snippets)
        return text[:OFFICIAL_CONTEXT_MAX_CHARS]

    def enrichment_hints(self) -> list[dict]:
        if self.context_depth == "NONE":
            return []
        return [slot for slot in self.enrichment_slot_dicts if slot.get("available")]

    def to_prompt_fragment(self) -> dict:
        """Lo único que Gemini recibe además de la noticia (Parte 34/36):
        fragmentos ya seleccionados y acotados, nunca el archivo completo."""
        fragment: dict = {}
        archive_text = self.archive_context_text()
        official_text = self.official_context_text()
        hints = self.enrichment_hints()
        if archive_text:
            fragment["archive_context"] = archive_text
        if official_text:
            fragment["official_context"] = official_text
        if hints:
            fragment["enrichment_hints"] = [{"type": h["type"], "value": h["value"]} for h in hints]
        if fragment:
            fragment["context_depth"] = self.context_depth
        return fragment

    def archive_context_entries(self) -> list[dict]:
        """Antecedentes propios para el módulo web "En contexto" (Parte 38).

        Sólo tiene sentido cuando NO hay timeline (``story_key`` vacío): si
        hay historia, el timeline la reemplaza (módulos no redundantes).
        ``archive_snippets``/``related_articles`` comparten el mismo prefijo
        de origen (ambos son slices de la misma lista ``relevant``), así que
        alinean por índice.
        """
        if self.story_key:
            return []
        entries = []
        for snippet, related in zip(self.archive_snippets, self.related_articles):
            entries.append(
                {
                    "postId": related.get("article_id", ""),
                    "title": related.get("title", ""),
                    "url": related.get("url", ""),
                    "snippet": snippet.text,
                }
            )
        return entries

    def official_sources_used(self) -> list[dict]:
        """``sources[]`` del CMS (Parte 62): sólo fuentes que realmente
        aportaron un dato (ya pasaron el filtro de relevancia de
        ``_gather_official_snippets``), nunca las que sólo se consultaron."""
        from sources.registry import get_source

        seen: set[str] = set()
        entries: list[dict] = []
        for snippet in self.official_snippets:
            if not snippet.source_id or snippet.source_id in seen:
                continue
            seen.add(snippet.source_id)
            source = get_source(snippet.source_id)
            name = source.name if source else snippet.source_id
            entries.append({"name": name, "url": snippet.source_url or None, "type": "OFICIAL"})
        return entries

    def to_dict(self) -> dict:
        return {
            "context_depth": self.context_depth,
            "story_key": self.story_key,
            "timeline": list(self.timeline),
            "related_articles": list(self.related_articles),
            "enrichment_slots": list(self.enrichment_slot_dicts),
            "archive_snippet_count": len(self.archive_snippets),
            "official_snippet_count": len(self.official_snippets),
        }


def _summarize_antecedent(article: ai.ArchiveArticle) -> str:
    """Extrae el antecedente, no copia el artículo entero (Parte 36)."""
    text = (article.excerpt or article.title or "").strip()
    return text[:ANTECEDENT_SNIPPET_MAX_CHARS]


# Entidades que comparten casi todas las notas riojanas y no prueban que la fuente
# oficial hable del mismo hecho (LVR-BUG-0001).
_GENERIC_OFFICIAL_ENTITIES = {
    "la rioja", "rioja", "gobierno", "gobierno provincial", "gobierno de la rioja",
    "provincia", "provincia de la rioja", "nacion", "gobierno nacional", "argentina",
    "justicia", "la justicia", "poder judicial", "policia", "legislatura", "ministerio",
    "municipio", "municipalidad", "tribunal", "fiscalia", "camara",
}
# Gentilicios y la provincia no prueban que se hable del mismo lugar puntual.
_GENERIC_OFFICIAL_LOCALITIES = {"la rioja", "rioja", "riojano", "riojana", "riojanos", "riojanas"}
# Vocabulario que comparten todas las notas policiales/judiciales o palabras
# vacías largas: coincidir en ellas no indica el mismo hecho.
_GENERIC_OFFICIAL_TERMS = {
    "entre", "contra", "desde", "hasta", "sobre", "durante", "luego", "ademas",
    "acusado", "acusada", "delito", "delitos", "detenido", "detenida", "detuvieron",
    "causa", "imputado", "imputada", "fiscal", "fiscalia", "sexual", "integridad",
    "investigacion", "denuncia", "victima", "juicio", "condena", "condenado",
    "tribunal", "camara", "justicia", "policia", "policial", "provincial", "gobierno",
    "nacional", "registro", "avanza", "avanzan", "mejoras", "trabajo", "conjunto",
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "setiembre", "octubre", "noviembre", "diciembre",
    # Palabras de función o de relato que aparecen en cualquier nota: el caso
    # de Anguinán (13/11/2026) se asoció a un juicio por otro homicidio sólo
    # por compartir "cuando", "primera" y "joven".
    "cuando", "donde", "mientras", "aunque", "porque", "segun", "despues",
    "antes", "ahora", "todavia", "tambien", "primera", "primer", "primero",
    "segunda", "segundo", "ultima", "ultimo", "joven", "jovenes", "hombre",
    "hombres", "mujer", "mujeres", "persona", "personas", "vecino", "vecinos",
    "vecina", "vecinas", "lugar", "hecho", "hechos", "caso", "casos", "parte",
    "manera", "momento", "horas", "jornada", "semana", "tiempo", "situacion",
    "llevo", "adelante", "realizo", "informo", "indico", "confirmo", "senalo",
    # Tipo de hecho: dos choques o dos homicidios distintos comparten estas
    # palabras sin ser el mismo acontecimiento.
    "homicidio", "homicidios", "muerte", "murio", "fallecio", "fallecimiento",
    "victima", "victimas", "herido", "heridos", "herida", "heridas",
    "accidente", "siniestro", "choque", "choco", "colision", "impacto",
    "motociclista", "motocicleta", "vehiculo", "rodado", "conductor",
    "robo", "robos", "hurto", "estafa", "estafas", "agresion", "pelea",
    "disputa", "audiencia", "audiencias", "sentencia", "proceso", "debate",
    "operativo", "procedimiento", "secuestro", "allanamiento", "arresto",
}
OFFICIAL_MIN_SHARED_TERMS = 2
# En policiales una persona, un lugar o el tipo de hecho por sí solos no
# prueban que el comunicado hable del mismo acontecimiento (un fiscal o un
# barrio aparecen en muchos casos): se exigen dos evidencias independientes
# y que el comunicado no sea anterior al hecho.
OFFICIAL_STRICT_CATEGORIES = {"policiales"}
OFFICIAL_STRICT_MAX_AGE_DAYS = _env_int("OFFICIAL_STRICT_MAX_AGE_DAYS", 3)
_AR_TZ = timezone(timedelta(hours=-3))  # Argentina no usa horario de verano.


def _parse_item_time(value: str) -> datetime | None:
    """Fecha de un ítem oficial: ISO 8601 o RFC 822 (feeds RSS). ``None`` si
    no se entiende; nunca se supone una fecha."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _official_label(item_time: datetime | None, reference: datetime) -> str:
    """Rótulo temporal del fragmento oficial para el prompt. Un comunicado
    anterior a ``OFFICIAL_STRICT_MAX_AGE_DAYS`` días es antecedente: puede dar
    contexto, nunca confirmar el hecho actual."""
    if item_time is None:
        return "[Fuente oficial sin fecha: usar sólo como antecedente] "
    day = item_time.astimezone(_AR_TZ).strftime("%d/%m/%Y")
    if reference - item_time > timedelta(days=OFFICIAL_STRICT_MAX_AGE_DAYS):
        return f"[Antecedente oficial del {day}: no confirma el hecho actual] "
    return f"[Comunicado oficial del {day}] "


def _gather_official_snippets(
    *,
    category: str,
    entities: list[str],
    localities: list[str],
    title: str,
    excerpt: str,
    riojan_source: bool = False,
    path: Path | str | None = None,
    reference_time: datetime | None = None,
) -> tuple[list[ContextSnippet], int]:
    """SourceSelector + caché local (Parte 24/57): nunca consulta la red acá
    (eso lo hace ``editorial_context/refresh_context.py`` una vez por ciclo,
    Parte 56); sólo filtra lo ya cacheado por relevancia real al hecho
    puntual (entidad/término/localidad compartidos), no por sola coincidencia
    de fuente/categoría.

    En ``OFFICIAL_STRICT_CATEGORIES`` hacen falta dos evidencias distintas
    (entidad, localidad, términos) y un comunicado contemporáneo: entre un día
    después y ``OFFICIAL_STRICT_MAX_AGE_DAYS`` antes de ``reference_time``. Un
    comunicado sin fecha legible no se usa. Ante la duda, no se atribuye nada
    a una fuente oficial."""
    reference = reference_time or datetime.now(timezone.utc)
    strict = category in OFFICIAL_STRICT_CATEGORIES
    # La fecha no prueba el mismo hecho: sólo rotula el fragmento (comunicado
    # contemporáneo o antecedente) para que la redacción no use un comunicado
    # viejo como confirmación de lo que pasó ahora.
    from sources import cache as source_cache
    from sources import selector as source_selector

    sources = source_selector.select_sources(
        category=category, localities=localities, keywords_text=" ".join([title, excerpt])
    )
    # Una nota nacional o de otra provincia no se enriquece con organismos
    # riojanos: sólo con señal riojana (localidad o sección local de origen).
    if not (localities or riojan_source):
        sources = [source for source in sources if source.scope != "provincial"]
    if not sources:
        return [], 0

    probe_entities_norm = {
        ec_entities.normalize_entity(e) for e in entities
    } - _GENERIC_OFFICIAL_ENTITIES
    probe_terms = (
        retrieval.significant_terms(title, excerpt, exclude=probe_entities_norm)
        - _GENERIC_OFFICIAL_TERMS
    )
    probe_localities = set(localities) - _GENERIC_OFFICIAL_LOCALITIES

    snippets: list[ContextSnippet] = []
    for source in sources:
        for item in source_cache.recent_items_for_source(
            source.source_id, limit=OFFICIAL_ITEMS_PER_SOURCE_SCANNED, path=path
        ):
            item_title = str(item.get("title") or "")
            item_excerpt = str(item.get("excerpt") or "")
            item_entities_norm = {
                ec_entities.normalize_entity(e) for e in ec_entities.extract_entities(item_title, item_excerpt)
            }
            item_terms = retrieval.significant_terms(item_title, item_excerpt, exclude=item_entities_norm)
            item_localities = set(ec_entities.extract_localities(item_title, item_excerpt))

            # Un solo término compartido ("gobierno", "obra") colaba contexto
            # oficial en la mayoría de las notas: se exige entidad específica,
            # localidad específica o al menos dos términos en común.
            shared_entities = probe_entities_norm & item_entities_norm
            shared_localities = probe_localities & item_localities
            shared_terms = probe_terms & item_terms
            kinds = sum(
                (
                    bool(shared_entities),
                    bool(shared_localities),
                    len(shared_terms) >= OFFICIAL_MIN_SHARED_TERMS,
                )
            )
            if kinds < (2 if strict else 1):
                continue
            evidence = (
                f"entidades={sorted(shared_entities)} localidades={sorted(shared_localities)} "
                f"terminos={sorted(shared_terms)}"
            )
            logger.info("Fuente oficial asociada %s (%s)", item.get("url") or item_title[:80], evidence)
            snippets.append(
                ContextSnippet(
                    text=_official_label(_parse_item_time(str(item.get("published_at") or "")), reference)
                    + (item_excerpt or item_title)[:OFFICIAL_SNIPPET_TEXT_MAX_CHARS],
                    source_type="official_source",
                    source_id=source.source_id,
                    source_url=str(item.get("url") or ""),
                    published_at=str(item.get("published_at") or ""),
                    evidence=evidence,
                )
            )
            if len(snippets) >= OFFICIAL_SNIPPET_MAX_ITEMS:
                break
        if len(snippets) >= OFFICIAL_SNIPPET_MAX_ITEMS:
            break

    return snippets, len(sources)


VERIFIED_STORY_PREFIX = "event:"


def story_engine_auto_enabled() -> bool:
    return os.getenv("STORY_ENGINE_AUTO_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _story_for_update(article_id: str, previous_url: str, *, title: str, category: str, path) -> tuple[str, str]:
    """(story_key, post_id de la nota anterior a enlazar en el CMS o "").

    Sólo reutiliza una historia verificada (``event:``): una clave del
    agrupamiento automático no se hereda, porque puede mezclar hechos."""
    previous = ai.get_by_canonical_url(previous_url, path=path)
    if previous is None:
        return "", ""
    verified = previous.story_key if previous.story_key.startswith(VERIFIED_STORY_PREFIX) else ""
    story_key = verified or VERIFIED_STORY_PREFIX + story_engine.story_key_from_seed(previous.article_id).split(":", 1)[1]
    link_post = ""
    if not verified:
        ai.set_story_key(previous.article_id, story_key, path=path)
        link_post = previous.post_id or previous.canonical_url
    ai.upsert_story(story_key, category=category, title_hint=title, path=path)
    for linked in (previous.article_id, article_id):
        ai.add_story_relation(
            linked, story_key, relation_score=1.0, relation_reason="same_event_update",
            matched_entities=[], matched_terms=[], time_distance_days=None, confidence="high", path=path,
        )
    return story_key, link_post


def build_context_bundle(
    *,
    article_id: str,
    title: str,
    excerpt: str = "",
    category: str = "",
    published_at: str = "",
    official_snippets: list[ContextSnippet] | None = None,
    official_source_lookup_count: int = 0,
    riojan_source: bool = False,
    update_of_url: str = "",
    path: Path | str | None = None,
) -> EditorialContextBundle:
    """Punto de entrada único. Nunca lanza: una falla acá degrada a NONE
    (Parte 60, "si falla el archivo, la nota puede continuar sin contexto").

    ``official_snippets=None`` (default) hace que este módulo los reúna solo
    vía ``SourceSelector`` + caché local; pasar una lista explícita (incluso
    vacía) omite ese paso automático (útil para tests o para un caller que ya
    los resolvió por su cuenta)."""
    try:
        return _build_context_bundle(
            article_id=article_id,
            title=title,
            excerpt=excerpt,
            category=category,
            published_at=published_at,
            official_snippets=official_snippets,
            official_source_lookup_count=official_source_lookup_count,
            riojan_source=riojan_source,
            update_of_url=update_of_url,
            path=path,
        )
    except Exception:
        logger.exception("Fallo construyendo EditorialContextBundle para %s; se continua sin contexto", article_id)
        return EditorialContextBundle()


def _build_context_bundle(
    *,
    article_id: str,
    title: str,
    excerpt: str,
    category: str,
    published_at: str,
    official_snippets: list[ContextSnippet] | None,
    official_source_lookup_count: int,
    path: Path | str | None,
    riojan_source: bool = False,
    update_of_url: str = "",
) -> EditorialContextBundle:
    entities_found = ec_entities.extract_entities(title, excerpt)
    localities_found = ec_entities.extract_localities(title, excerpt)

    if official_snippets is None:
        official_snippets, official_source_lookup_count = _gather_official_snippets(
            category=category,
            entities=entities_found,
            localities=localities_found,
            title=title,
            excerpt=excerpt,
            riojan_source=riojan_source,
            path=path,
            reference_time=_parse_item_time(published_at),
        )

    candidates = ai.candidate_retrieval(
        title=title,
        excerpt=excerpt,
        entities=entities_found,
        localities=localities_found,
        category=category,
        exclude_article_id=article_id,
        path=path,
    )

    ranked = (
        retrieval.rank_candidates(
            candidates,
            probe_title=title,
            probe_excerpt=excerpt,
            probe_entities=entities_found,
            probe_localities=localities_found,
            probe_category=category,
            probe_published_at=published_at,
        )
        if candidates
        else []
    )
    relevant = [item for item in ranked if item.meets_category_bar(category)]

    story_assignment = None
    # El agrupamiento automático juntaba hechos distintos que sólo compartían
    # una localidad y una palabra ("Chilecito" + "joven", "Córdoba" +
    # "trasladar") y la web los mostraba como cronología (2026-10-23). Queda
    # apagado: las historias salen sólo de actualizaciones verificadas del
    # mismo hecho (utils/same_event.py, ``update_of_url``).
    if candidates and story_engine_auto_enabled():
        story_assignment = story_engine.assign_story(
            article_id=article_id,
            title=title,
            excerpt=excerpt,
            category=category,
            entities=entities_found,
            localities=localities_found,
            published_at=published_at,
            candidates=candidates,
            path=path,
        )

    story_key = story_assignment.story_key if story_assignment else ""
    link_previous_post_id = ""
    if update_of_url:
        # Actualización del mismo hecho (utils/same_event.py): misma historia
        # que la nota anterior, aunque las palabras no alcancen para agruparlas.
        linked_key, link_previous_post_id = _story_for_update(article_id, update_of_url, title=title, category=category, path=path)
        story_key = linked_key or story_key
    timeline_items = tl.build_timeline(story_key, exclude_article_id=article_id, path=path) if story_key else []
    has_strong_story = bool(timeline_items)

    archive_snippets = [
        ContextSnippet(
            text=_summarize_antecedent(item.candidate),
            source_type="own_archive",
            source_url=item.candidate.canonical_url,
            post_id=item.candidate.post_id,
            published_at=item.candidate.published_at,
            relation_score=item.score,
        )
        for item in relevant[:ARCHIVE_CONTEXT_MAX_ITEMS]
    ]

    best_score = relevant[0].score if relevant else 0.0
    depth = cd.decide_depth(
        best_archive_score=best_score,
        archive_item_count=len(relevant),
        has_official_context=bool(official_snippets),
        has_strong_story=has_strong_story,
    )

    slots = es.build_enrichment_slots(
        current_text=" ".join([title, excerpt]),
        archive_snippets=[
            es.Snippet(text=s.text, source_url=s.source_url, confidence="medium") for s in archive_snippets
        ],
        official_snippets=[
            es.Snippet(text=s.text, source_url=s.source_url, confidence="medium") for s in official_snippets
        ],
    )

    factual_basis_text = " ".join([s.text for s in archive_snippets] + [s.text for s in official_snippets])

    bundle = EditorialContextBundle(
        context_depth=depth.value,
        archive_snippets=archive_snippets,
        official_snippets=official_snippets,
        enrichment_slot_dicts=[slot.to_dict() for slot in slots],
        related_articles=[
            {
                "article_id": item.candidate.article_id,
                "title": item.candidate.title,
                "url": item.candidate.canonical_url,
                "score": item.score,
            }
            for item in relevant[:RELATED_ARTICLES_MAX_ITEMS]
        ],
        story_key=story_key,
        link_previous_post_id="" if link_previous_post_id.startswith("http") else link_previous_post_id,
        link_previous_url=link_previous_post_id if link_previous_post_id.startswith("http") else "",
        timeline=[
            {"article_id": i.article_id, "title": i.title, "published_at": i.published_at, "url": i.url}
            for i in timeline_items[:TIMELINE_MAX_ITEMS]
        ],
        factual_basis_text=factual_basis_text,
    )

    ec_metrics.record_bundle_event(
        article_id=article_id,
        category=category,
        context_depth=bundle.context_depth,
        archive_lookup_count=1,
        archive_match_count=len(relevant),
        story_assigned=bool(story_key),
        timeline_shown=has_strong_story,
        official_source_lookup_count=official_source_lookup_count,
        official_source_hit_count=len(official_snippets),
        context_chars=len(bundle.archive_context_text()) + len(bundle.official_context_text()),
        related_articles_count=len(bundle.related_articles),
        path=path,
    )
    return bundle
