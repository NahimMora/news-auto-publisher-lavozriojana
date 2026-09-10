# Editorial Context Engine

Motor determinístico (sin llamadas de IA adicionales) que enriquece la
redacción existente (`pipeline/node_webapp/editorial.py`) con antecedentes
del archivo propio de La Voz Riojana y de fuentes oficiales, cuando
realmente ayudan a entender el hecho actual. Principio rector: **la noticia
actual es el centro**; el contexto es opcional y nunca reemplaza el hecho.

Código: `editorial_context/`. Todo lo que sigue es determinístico —
retrieval, scoring, decisión de profundidad, slots de enriquecimiento — para
no agregar llamadas nuevas a Gemini (ver "Costo" abajo y `docs/COST_MODEL.md`).

## Índice derivado (Archive Context Engine)

`editorial_context/db.py` administra
`data/derived/editorial_context.sqlite3`: **derivado, reconstruible, NO
autoritativo**. Las colas JSON (`utils/file_manager.py`) siguen siendo el
estado autoritativo del pipeline; este índice puede borrarse y reconstruirse
sin pérdida de información productiva (`cli.py archive-index rebuild`).

FTS5 se prueba en runtime (`fts5_supported()`, nunca se asume por versión de
Python) con fallback a una tabla plana + `LIKE` si el build de `sqlite3` no
lo soporta. Confirmado disponible en Python 3.10.0 (mismo build que
producción), pero el fallback existe igual.

Tablas principales: `archive_articles`, `stories`, `story_relations`,
`context_facts` (Context Store), `official_content_cache`,
`source_metrics`, `ai_call_metrics`, `bundle_events`, `source_fetch_state`.

### Cómo se llena el archivo

`noticias_web_publicadas.json` es sólo una **ventana rodante de 7 días**
(`WEB_DEDUP_HISTORY_DAYS`, podada en cada lectura por
`publisher.py::_load_published_history`) — no es un histórico completo. El
archivo real se llena de dos formas:

1. **Tiempo real**: cada publicación exitosa se indexa inmediatamente
   (`publisher.py::_record_archive_article`, best-effort, nunca rompe la
   publicación si falla).
2. **Backfill**: `editorial_context/archive_backfill.py::backfill_from_cms_api`
   pagina el endpoint público ya existente del CMS (`GET /api/public/posts`,
   es nuestro propio sitio) e ingesta cada post. Se detiene en la primera
   página vacía o corta — no hace requests repetidos inútiles. Se invoca con
   `cli.py archive-index backfill-cms [--max-pages N]`.

   Nota abierta: los nombres de campo del endpoint se tomaron de la
   auditoría del repo `LaVozRiojana` con fallbacks razonables; confirmar
   contra una respuesta real antes de depender de esto en producción.

## Extracción de entidades y localidades (sin IA)

`editorial_context/entities.py`: heurística determinística sobre el título y
excerpt — corridas de palabras capitalizadas con conectores intermedios
permitidos ("Ministerio de Salud", "Juan Pérez de la Torre") más siglas de
2+ letras. Duplica intencionalmente el concepto de localidades riojanas de
`utils/editorial_router.py` (no lo importa) para no acoplar el archivo de
largo plazo al routing/dedup de corto plazo.

Limitación conocida y aceptada (mismo tipo de limitación que ya documenta
`editorial_router.compute_topic_key`): una sola palabra capitalizada al
comienzo de una oración se descarta salvo que sea sigla, para evitar falsos
positivos de "inicio de frase" como entidad.

## Retrieval en dos pasos (Parte 7)

**Paso A — candidate retrieval** (`archive_index.candidate_retrieval`):
FTS/BM25 (o `LIKE` en el fallback) sobre título + entidades + localidades +
categoría + tags. Nunca busca por una palabra suelta genérica sola. Devuelve
~20 candidatos baratos.

**Paso B — relation scoring** (`retrieval.score_candidate`): fórmula
explicable, no una caja negra:

| Señal | Peso |
|---|---:|
| `same_entity` (hasta 2 entidades compartidas) | +0.35 c/u |
| `same_locality` específica (hasta 2) | +0.15 c/u |
| `same_locality` sólo provincia ("la rioja") | +0.05 |
| `same_category` | +0.10 |
| `shared_significant_terms` (hasta 3) | +0.05 c/u |
| `date_distance` (bonus de recencia, decae a 0 en 60 días) | hasta +0.15 |

Umbral por categoría (`retrieval.STRICT_RELATION_CATEGORIES`): policiales,
espectáculos y deportes exigen **entidad Y término compartido** (umbral
0.55); el resto acepta entidad O localidad específica (umbral 0.45). Esto
evita agrupar por sola coincidencia de nombre/categoría/localidad — ver
`docs/STORY_ENGINE.md` para los casos concretos.

`confidence`: `high` (≥0.6), `medium` (≥0.35), `low` (resto).

## ContextDepth (Parte 13)

`editorial_context/context_depth.py`. Default **LIGHT**. Nunca arranca en
STORY sin un Story Engine que ya confirmó una historia con timeline real.

| Depth | Cuándo | Presupuesto |
|---|---|---|
| `NONE` | sin archivo ni fuente oficial relevante | 0 palabras |
| `LIGHT` | evidencia débil-media, o sólo fuente oficial | ~120 palabras, 1 nota previa |
| `STANDARD` | score fuerte (≥0.6) o ≥2 candidatos con score ≥0.45 | ~220 palabras, hasta 3 notas previas |
| `STORY` | Story Engine confirmó timeline (≥2 previas, confianza alta) | igual que STANDARD; el timeline vive aparte en la UI |

## EnrichmentSlot (Parte 14)

`editorial_context/enrichment_slots.py`: CONTEXTO, CAMBIO, IMPACTO, DATOS,
PRÓXIMO_PASO. Ninguno es obligatorio; ninguno lleva subtítulo técnico
visible. `available=False` cuando no hay evidencia — Gemini nunca completa
un slot sin evidencia con provenance.

- **CONTEXTO**: disponible si hay un antecedente propio.
- **DATOS**: disponible si un fragmento oficial contiene un patrón
  numérico/monetario (`$`, `%`, miles, "millones", etc.).
- **PRÓXIMO_PASO**: disponible si un fragmento contiene una frase de
  próximo paso ("a partir del", "entrará en vigencia", "se espera", etc.).
- **CAMBIO**: disponible sólo si hay un antecedente con un valor numérico
  distinto al de la nota actual (comparación determinística, no inferida).
- **IMPACTO**: **siempre `available=False`** en esta etapa — no hay señal
  determinística confiable; queda como punto de extensión futuro, no se
  fuerza (Part 14: "NO obligar a completar los cinco").

## Context Store (Partes 15/16)

`editorial_context/context_store.py`: hechos con provenance
(`ContextFact`: entity_key, fact, source_kind, source_url, event_date,
expires_at, confidence, hash). Sólo guarda hechos con fuente real
(`OWN_ARCHIVE` / `OFFICIAL_SOURCE`), nunca "conocimiento general del
modelo". `get_facts()` filtra por defecto cualquier hecho vencido — ante
duda, no se reutiliza un dato vencido.

TTL por `fact_type`:

| Tipo | TTL |
|---|---|
| `hecho_historico` | sin vencimiento |
| `precio_monto` | 3 días |
| `cronograma` | hasta `event_date` (no TTL fijo) |
| `funcionario_cargo` | 90 días |
| `alerta_meteorologica` | 6 horas |
| `resultado_deportivo` | sin vencimiento (estable tras finalizar) |
| `default` | 30 días |

## EditorialContextBundle (Partes 34-37)

`editorial_context/bundle.py::build_context_bundle` es el único punto de
entrada. Orquesta: extracción de entidades/localidades → candidate
retrieval → relation scoring → Story Engine → timeline →
`_gather_official_snippets` (SourceSelector + caché local, **nunca hace red
acá**: sólo lee lo que `refresh_context.py` ya sincronizó una vez por ciclo)
→ ContextDepth → EnrichmentSlots → registro de métricas
(`editorial_context/metrics.py::record_bundle_event`).

**Nunca lanza**: cualquier excepción interna degrada a un bundle vacío
(`ContextDepth.NONE`) y se loguea — una nota nunca deja de publicarse por un
fallo del motor de contexto (Parte 60).

Límites de tamaño (Parte 35, configurables por env, valores por defecto):

```
ARCHIVE_CONTEXT_MAX_ITEMS=3        RELATED_ARTICLES_MAX_ITEMS=5
TIMELINE_MAX_ITEMS=5               ARCHIVE_CONTEXT_MAX_CHARS=3500
OFFICIAL_CONTEXT_MAX_CHARS=4500    OFFICIAL_SNIPPET_MAX_ITEMS=3
```

`to_prompt_fragment()` es **lo único que ve Gemini** además de la noticia:
`archive_context`, `official_context`, `enrichment_hints`, `context_depth` —
nunca el archivo completo. `factual_basis_text` (concatenación de los
mismos fragmentos, con su propia provenance) se agrega a
`_original_text()` en `editorial.py` para que el validador factual
(`invented_number`/`invented_date`/`invented_proper_noun`) no rechace un
hecho legítimo del archivo/fuente oficial sólo por no estar en el scrapeo
original.

`archive_context_entries()` alimenta `metadata.archiveContext` del CMS
("En contexto") — sólo cuando NO hay `story_key` (mutuamente excluyente con
el timeline, Parte 38). `official_sources_used()` alimenta `sources[]` del
CMS (Parte 62) — sólo fuentes que realmente aportaron un fragmento usado,
nunca las meramente consultadas.

## Integración con `editorial.py`/`publisher.py`

`publisher.py::_build_editorial_context_bundle(noticia)` arma el bundle
**antes** de `prepare_editorial`, usando una copia (`noticia_for_editorial`)
para no filtrar `_editorial_context_bundle` a `queue_events.json` ni a
ninguna cola JSON. `_call_ai_enricher` agrega campos opcionales al
`user_payload` de Gemini sólo si el bundle los trae; `_SYSTEM_PROMPT` tiene
un párrafo aditivo explicando el uso opcional y atribuido del contexto (sin
subtítulos técnicos, la noticia actual siempre al frente).

Instrumentación (Parte 47): `utils/ai_client.py::chat_completion` acepta
`stage`/`article_id` opcionales (ningún call site existente los pasaba
antes de esta etapa) y registra latencia/tokens (reales si el SDK los
informa, estimados a ~4 caracteres/token si no) en `ai_call_metrics`.

## Observabilidad (Parte 54)

`cli.py archive-index stats [--since-hours N] [--since-days N]` reporta
`editorial_metrics_summary()` (archive_lookup_count, archive_match_rate,
story_assigned_count, story_timeline_count, context_depth_*,
official_source_lookup/hit_count, context_store_hit/miss_count,
average_context_chars, average_related_articles) y
`source_metrics_summary()` (por fuente, ver `docs/OFFICIAL_SOURCES.md`).

## Fallbacks (Parte 60)

- Falla el archivo → la nota continúa sin contexto (`ContextDepth.NONE`).
- Falla una fuente oficial → la nota continúa; si no dependía de ese dato,
  no se escribe nada sobre él ("si no se pudo recuperar evidencia, no se
  escribe").
- Falla el Story Engine → no rompe la publicación, sólo no hay timeline.
- Todo fallo se loguea (`logger.exception`), nunca se propaga hacia la
  publicación.

## Costo (Parte 44/45)

Cero llamadas de IA nuevas: retrieval, scoring, story assignment, context
depth y enrichment slots son 100% determinísticos. La única llamada de IA
sigue siendo la editorial existente (`_call_ai_enricher`), ahora con más
contexto en el mismo prompt (más tokens de entrada, no más llamadas). Ver
`docs/COST_MODEL.md` para la estimación completa.
