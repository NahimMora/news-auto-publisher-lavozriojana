# Progreso — Editorial Context & Story Engine

> Documento de trabajo vivo. Si esta sesión se corta o se pide "resumir", leer este
> archivo primero para saber exactamente dónde se quedó. Se actualiza después de
> cada fase completada, no al final.

Plan origen: `C:\Users\pc10\Desktop\AutoPublicadores\PLAN-LVR-AUTOPUBLICADOR.txt`
(76 partes). Rama: `feature/editorial-context-story-engine` (creada desde
`feature/editorial-cinematica-riojana`, que a su vez está 8 commits adelante de
`main` sin mergear — PR pendiente ya existente para ese trabajo, no tocar).

## Restricción detectada — acceso a producción

No hay acceso remoto (SSH/RDP) a la PC servidor donde corre
`LaVozRiojana-24x7` en Task Scheduler. Todo el trabajo de esta sesión es sobre
el checkout local únicamente. Los pasos del plan que requieren tocar la PC
servidor (pausar servicio, backup, restart) se van a documentar como
instrucciones manuales exactas para que el usuario las ejecute allá — no se
ejecutan desde acá. No se hace push a `main` ni se activa nada en producción
sin autorización explícita.

## Estado por fase

- [x] Fase 0a — Leer plan completo.
- [x] Fase 0b — Crear rama `feature/editorial-context-story-engine`.
- [x] Fase 0c — Auditoría repo autopublicador (fork completo, hallazgos abajo).
- [x] Fase 0d — Auditoría repo CMS/web (fork completo, hallazgos abajo).
- [x] Fase 0e — Auditoría técnica de ~25 fuentes oficiales (fork completo, hallazgos abajo).
- [x] Fase 1 — Plan técnico corto (sección "Diseño técnico" abajo).
- [x] Fase 2 — Archive Context Engine + índice SQLite FTS (derived, gitignored).
  Archivos: `editorial_context/db.py`, `editorial_context/entities.py`,
  `editorial_context/archive_index.py`. Tests:
  `tests/test_editorial_context_db.py`,
  `tests/test_editorial_context_entities.py`,
  `tests/test_editorial_context_archive_index.py`. Todos verdes.
- [x] Fase 3 — Retrieval en 2 pasos (candidate + relation scoring) + story_key.
  Archivo: `editorial_context/retrieval.py`
  (`candidate_retrieval` en archive_index.py = paso A,
  `score_candidate`/`rank_candidates` = paso B). Test:
  `tests/test_editorial_context_retrieval.py`. Verde.
- [x] Fase 4 — Story Engine + timeline.
  Archivos: `editorial_context/story_engine.py` (`assign_story`, muy
  conservador: policiales/espectáculos/deportes exigen entidad+término
  compartido), `editorial_context/timeline.py` (máx 5, exige ≥2 previas y
  al menos una relación `confidence=high`). Tests:
  `tests/test_editorial_context_story_engine.py`,
  `tests/test_editorial_context_timeline.py`. Verdes.
- [x] Fase 5 — Context Depth / Context Budget / EnrichmentSlot.
  Archivos: `editorial_context/context_depth.py` (default LIGHT, reglas
  determinísticas), `editorial_context/enrichment_slots.py` (los 5 slots;
  IMPACTO queda siempre `available=False` por falta de señal determinística
  confiable — documentado explícitamente, no se fuerza). Test:
  `tests/test_editorial_context_depth_and_slots.py`. Verde.
- [x] Fase 6 — Context Store (ContextFact, TTL por tipo).
  Archivo: `editorial_context/context_store.py` (TTL por `fact_type`:
  hecho_historico=sin vencimiento, precio_monto=3 días,
  cronograma=vence en `event_date`, funcionario_cargo=90 días,
  alerta_meteorologica=6h, resultado_deportivo=sin vencimiento,
  default=30 días). Test: `tests/test_editorial_context_store.py`. Verde.
- [x] Fase 6b — Instrumentación IA (Parte 47).
  Archivo: `editorial_context/instrumentation.py` + hook aditivo en
  `utils/ai_client.py::chat_completion` (nuevos kwargs opcionales
  `stage`/`article_id`, sin romper los 8 call sites existentes que no los
  pasan). Test: `tests/test_ai_client_instrumentation.py`. Verde.
  **Suite completa verificada sin regresiones: 592/592 tests OK después de
  este cambio** (`python -m unittest discover tests`).
- [x] Fase 6c — `editorial_context/metrics.py` (Partes 54/55): tabla nueva
  `bundle_events` en `db.py`, `record_bundle_event`/`editorial_metrics_summary`/
  `source_metrics_summary`.
- [x] Fase 6d — `editorial_context/bundle.py` (EditorialContextBundle,
  Partes 34-37): orquesta archive+story+depth+slots, aplica límites de la
  Parte 35 (`ARCHIVE_CONTEXT_MAX_ITEMS/CHARS`, `RELATED_ARTICLES_MAX_ITEMS`,
  `TIMELINE_MAX_ITEMS`, `OFFICIAL_CONTEXT_MAX_CHARS`, todos configurables por
  env), `to_prompt_fragment()` sólo expone lo seleccionado, nunca lanza
  (degrada a bundle vacío + logea). Test:
  `tests/test_editorial_context_bundle.py`. Verde.
- [x] **Fase 10 (adelantada) — Integración real en editorial.py/publisher.py.**
  - `pipeline/node_webapp/editorial.py`: `_original_text` ahora incluye
    `factual_basis_text` del bundle (para que el validador de
    invented_number/date/proper_noun no rechace hechos legítimos del
    archivo/fuente oficial); `_call_ai_enricher` agrega
    `archive_context`/`official_context`/`enrichment_hints`/`context_depth`
    opcionales al `user_payload` y pasa `stage="editorial_enricher"` +
    `article_id` a `chat_completion` (instrumentación real activada);
    `_SYSTEM_PROMPT` ganó un párrafo aditivo explicando el uso opcional y
    atribuido del contexto, sin subtítulos técnicos.
  - `pipeline/node_webapp/publisher.py`: **corregido el bug de la Parte 61**
    (`_CATEGORY_AUTHORS` eliminado por completo, ya no se manda `authorName`
    fijo por categoría — el CMS resuelve Fernando Nahim Mora solo); nueva
    `_build_editorial_context_bundle(noticia)` arma el bundle ANTES de
    `prepare_editorial` sin mutar el `noticia` original (usa una copia
    `noticia_for_editorial` sólo para la llamada editorial, así
    `_editorial_context_bundle` nunca se filtra a `queue_events.json` ni a
    ninguna cola JSON); `build_post_payload` acepta `story_key` opcional →
    `payload["storyKey"]`; nueva `_record_archive_article(...)` ingesta el
    artículo en el índice derivado en tiempo real tras una publicación
    exitosa (best-effort, nunca rompe la publicación si falla).
  - Test nuevo end-to-end: `tests/test_publisher_context_bundle_integration.py`
    (publish_one_detailed real con HTTP/editorial/media mockeados, confirma
    que no se manda `authorName` y que el artículo queda indexado en el
    archivo tras publicar).
  - Corregido test viejo que afirmaba el comportamiento incorrecto:
    `tests/test_node_webapp_publisher.py::test_build_post_payload_uses_private_api_contract_fields`.
  - **Suite completa: 599/599 tests OK, `python -m compileall -q .` limpio.**
- [x] Fase 7 — Source Registry + fuentes provinciales/nacionales sembradas.
  `config/official_sources.json` (27 fuentes, datos reales del probe técnico:
  4 RSS confirmados, ~17 HTML_INDEX confirmados, 6 deshabilitadas con
  `notes` explicando por qué — Facebook sin alternativa, sitio caído,
  fetch estático vacío en anses/indec, etc). `sources/registry.py`
  (`SourceDefinition`, `load_registry`, `enabled_sources`). Test:
  `tests/test_sources_registry.py`. Verde.
- [x] Fase 8 — Estrategia de scraping por fuente + source-probe CLI.
  `sources/http_client.py` (sesión reutilizable + allowlist de host sobre
  `utils/safe_http.py` + ETag/If-Modified-Since), `sources/contract.py`
  (`OfficialSourceItem`), `sources/strategies/rss.py` (RSS2+Atom, stdlib),
  `sources/strategies/html_index.py` (heurística genérica, no un script por
  sitio), `sources/fetch_state.py` (condicional + `poll_ttl` por fuente),
  `sources/sync.py` (orquesta fetch→parse→caché→métricas,
  `force=True` para diagnosticar fuentes deshabilitadas),
  `sources/probe.py` (read-only, nunca escribe). Tests:
  `test_sources_http_client.py`, `test_sources_strategies.py` (fixtures en
  `tests/fixtures/official_sources/`), `test_sources_fetch_state.py`,
  `test_sources_sync.py`, `test_sources_probe.py`. Todos verdes.
- [x] Fase 9 — SourceSelector + métricas por fuente + caché/dedup.
  `sources/selector.py` (categoría+keyword→fuentes, exige localidad riojana
  para Gendarmería/PFA/Prefectura/Seguridad Nación — Parte 19),
  `sources/cache.py` (`official_content_cache`, dedup cross-fuente
  reusando `utils/news_dedup.duplicate_reason`, marca
  `republished_official_content`), `sources/metrics.py` (escritura de
  `source_metrics`, acumulado diario). Tests: `test_sources_selector.py`,
  `test_sources_cache.py`, `test_sources_metrics.py`. Verdes.
- [x] Fase 9b — `editorial_context/refresh_context.py` (Parte 56): nueva
  etapa de ciclo, agregada a `run_24x7.py::CYCLE_STEPS` entre `run_all.py` y
  `pipeline/publish_web.py`, sin canal (no sujeta a kill switches de
  web/fb/ig). Sólo sincroniza fuentes cuyo `poll_ttl` venció
  (`sources/fetch_state.py::is_due`). Un fallo en una fuente no rompe el
  ciclo. Test: `test_editorial_context_refresh_context.py`. Actualizado
  `tests/test_deployment_modes.py::test_supervisor_observe_skips_every_external_stage`
  (ahora 2 pasos sin canal en vez de 1).
- [x] Fase 9c — `editorial_context/archive_backfill.py` (Parte 6): backfill
  real desde `GET /api/public/posts` del CMS propio (paginado, se detiene en
  página corta/vacía). **Nota abierta**: nombres de campo del endpoint
  tomados de la auditoría con fallbacks razonables, no confirmados contra
  una respuesta real — documentar como riesgo pendiente. Test:
  `test_editorial_context_archive_backfill.py`. Verde.
  **Suite completa: 664/664 tests OK, compileall limpio.**
- [x] Fase 10 — Integración en `editorial.py`/`publisher.py`: hecha antes de
  tiempo (ver más abajo, sección "Fase 10 (adelantada)"). Pendiente todavía:
  conectar `sources/selector.py` + `sources/cache.py` como
  `official_snippets` reales dentro de `editorial_context/bundle.py` — HECHO
  (ver abajo).

## Fase 9d — SourceSelector + caché conectados al bundle (cierre del loop)

- `editorial_context/bundle.py::_gather_official_snippets`: cuando el
  caller no pasa `official_snippets` explícitos (`None`, el caso real de
  `publisher.py`), se auto-completan vía `sources.selector.select_sources` +
  `sources.cache.recent_items_for_source`. **Nunca hace red acá**: sólo lee
  lo que `editorial_context/refresh_context.py` ya cacheó una vez por ciclo
  (Parte 56). Filtra por relevancia real (entidad/término/localidad
  compartidos con la noticia), no por sola coincidencia de fuente/categoría.
- Tests nuevos en `test_editorial_context_bundle.py`: confirma que un item
  cacheado relevante aparece en `official_snippets` y uno irrelevante se
  descarta, ambos vía la ruta automática (sin pasar `official_snippets`
  manualmente).
- `cli.py`: nuevos subcomandos `source-probe --source <id> [--json]` (Parte
  22, nunca escribe caché/métricas, `force=True` interno para poder
  diagnosticar una fuente aún deshabilitada) y `archive-index
  {rebuild,backfill-cms,stats}`. Test: `tests/test_cli_source_context.py`.
- **Bug propio detectado y corregido en el mismo paso**: el primer test de
  `source-probe` parcheaba `sources.sync.sync_source` en vez de
  `sources.probe.sync_source` (el `from ... import` de `probe.py` crea un
  binding local independiente) — la suite terminó haciendo un GET real a
  `mpf_larioja.gob.ar` durante los tests. Corregido antes de commitear;
  ninguna corrida de tests debe volver a pegarle a una fuente real.
  **Suite completa: 671/671 tests OK, sin tocar red.**
- [ ] Fase 11 — Instrumentación IA (ai_client.py).
- [ ] Fase 12 — CMS/web: schema Prisma story_key + endpoint + `<StoryTimeline />`.
- [ ] Fase 13 — Backfill script (--report-only).
- [ ] Fase 14 — Tests unitarios + fixtures + E2E.
- [ ] Fase 15 — Validaciones (unittest, compileall, doctor, dry-run, lint/typecheck/build web).
- [ ] Fase 16 — Documentación (ARCHITECTURE, CURRENT_STATE, DECISIONS, RUNBOOK, OFFICIAL_SOURCES, EDITORIAL_CONTEXT, STORY_ENGINE, COST_MODEL).
- [ ] Fase 17 — Commits por etapa + dejar PR lista.
- [ ] Fase 18 — Informe final (Parte 76) para pegar en ChatGPT.

## Hallazgos clave de la auditoría (no re-investigar esto)

- **`topic_key`** vive en `utils/editorial_router.py:216` (`compute_topic_key`,
  prefijo `"topic:"`, hash de entity_tokens+localidad+categoría+día). Sólo lo
  usa `editorial_router.py` (cap de 12h por tema en Instagram). `news_dedup.py`
  NO lo usa (usa similitud Jaccard sobre título/URL). Agregar `story_key` en
  paralelo es seguro; usar prefijo `"story:"` para no colisionar en logs.
- **`noticias_web_publicadas.json` es una ventana rodante de 7 días**
  (`WEB_DEDUP_HISTORY_DAYS`, podado en cada lectura por
  `_load_published_history` en `publisher.py:470`) — **NO es un archivo
  histórico completo**. Confirma que el plan tiene razón: hace falta backfill
  desde el sitio propio. Como el CMS ya expone `GET /api/public/posts`
  (paginado, con category/slug/excerpt/publishedAt/tags), ese endpoint propio
  de lectura es la fuente de backfill preferida en la práctica (más barata y
  estructurada que sitemap+JSON-LD por artículo) — se documenta como decisión
  explícita en DECISIONS.md, aunque la Parte 6 del plan pone sitemap primero
  en la lista genérica de preferencias.
- **Bug real encontrado, corrección pedida explícitamente por la Parte 61**:
  `pipeline/node_webapp/publisher.py:44-55` (`_CATEGORY_AUTHORS`) publica hoy
  con `authorName="Redacción Política"`, `"Redacción Deportes"`, etc. según
  categoría. El plan pide explícitamente mantener `Fernando Nahim Mora` (que
  ya es el autor real en el CMS, `lib/post-mutations.ts::resolveAuthor`) y NO
  reintroducir "Redacción X". Se va a eliminar `_CATEGORY_AUTHORS` y dejar de
  mandar `authorName` fijo por categoría (o mandar directamente
  `"Fernando Nahim Mora"`), documentado como corrección explícita en
  DECISIONS.md — no es scope creep, es la Parte 61 aplicada.
- **Validador factual de `editorial.py` (`validate_editorial_result` +
  `_original_text`, líneas 346-675)**: cualquier número/fecha/nombre propio en
  la salida de Gemini que no esté en `_original_text(noticia)` se marca
  `invented_*` y fuerza reintento/fallback. Para que el contexto agregado
  (archivo propio/fuente oficial) no dispare falsos "inventado", hay que
  **extender `_original_text` para incluir también el texto de las fuentes
  legítimas del `EditorialContextBundle`** (con su propia provenance), no
  relajar la validación en general.
- **Punto de inyección limpio, sin tocar firmas públicas**: `publish_one_detailed`
  (`publisher.py:656`) llama `prepare_editorial(noticia)` en la línea 683. El
  bundle se arma ahí mismo y se cuelga de una clave nueva del dict
  (`noticia["_editorial_context_bundle"]`) ANTES de esa llamada.
  `_call_ai_enricher` (línea 1042) sólo necesita leer esa clave si existe y
  agregar 2-3 campos opcionales a `user_payload` (`archive_context`,
  `official_context`, `enrichment_hints`) — cero cambios de firma.
- **CMS (`Post` en `prisma/schema.prisma`)**: ya tiene `metadata Json?` y
  `sources: PostSource[]` (con `SourceType.OFICIAL`/`ORGANISMO_PUBLICO`, etc).
  Decisión (Parte 41, "preferir la solución más simple"):
  - Agregar sólo **una columna nueva real**: `storyKey String? @db.VarChar(160)`
    + índice `[storyKey, publishedAt]` en `Post` (migración aditiva, nullable,
    sigue el patrón de `add_post_video`/`eeat_sources_contact`). Sirve para la
    query de timeline (`findMany({where:{storyKey}, orderBy:{publishedAt}})`).
  - El antecedente "En contexto" (cuando NO hay timeline) se guarda dentro del
    `metadata` JSON ya existente (`metadata.archiveContext: [{postId, slug,
    title, url, snippet}]`) — cero migración adicional, ya es compatible.
  - `sources[]` (Parte 62) usa el modelo `PostSource` que YA EXISTE; el
    autopublicador sólo tiene que empezar a poblarlo cuando una fuente oficial
    aportó un dato real. No requiere cambios de schema.
  - `postCreateSchema`/`postUpdateSchema` (zod, `lib/schemas.ts`) necesitan un
    campo opcional `storyKey` nuevo; el resto ya soporta `sources[]`/`metadata`.
  - Página de nota (`app/noticias/[slug]/page.tsx`): insertar
    `<StoryTimeline />` (si hay ≥2 publicados con mismo storyKey) o el bloque
    "En contexto" (si hay `metadata.archiveContext` y no hay timeline),
    mutuamente excluyentes, entre `Sources`/`AuthorBox` y "También puede
    interesarte" (que sigue igual).
- **Ciclo del supervisor** (`run_24x7.py:34`, `CYCLE_STEPS`): orden real es
  `run_all.py` (scraping+rewrite+select_publish_batch) → `pipeline/publish_web.py`
  (publica, acá vive `publish_one_detailed`) → `meta/run_fb.py` → `meta/run_ig.py`
  → `meta/ig_insights.py`. El refresh de fuentes oficiales (Parte 56, "una vez
  por ciclo") se agrega como paso nuevo `editorial_context/refresh_context.py`
  entre `run_all.py` y `pipeline/publish_web.py`, respetando `poll_ttl` por
  fuente para no pegarle a fuentes que no vencieron su caché. El intervalo real
  de ciclo es `PIPELINE_24X7_INTERVAL_SECONDS` (default 3600s = 1h), no los 5
  minutos de Task Scheduler (que sólo relanzan el proceso si murió).
- **FTS5 confirmado disponible** en Python 3.10.0 (mismo build que producción
  según `docs/CURRENT_STATE.md`) — probado localmente con
  `CREATE VIRTUAL TABLE ... USING fts5(...)`. Igual se implementa el probe en
  runtime + fallback `LIKE` por si producción difiere.
- `docs/DECISIONS.md` ya había rechazado migrar a SQLite como reemplazo de
  JSON por falta de evidencia de volumen. El índice nuevo se documenta
  explícitamente como **derivado/reconstruible/no autoritativo**, complemento
  y no contradicción de esa decisión.
- **Auditoría de fuentes oficiales completa** (evidencia real, no inventada):
  - RSS confirmado: `mpf_larioja` (`/feed/`), `justicia_larioja` (Joomla,
    `?format=feed&type=rss` en la categoría noticias, NO `/feed/` raíz),
    `turismo_larioja` (**path real es `/novedades/feed/`, no `/noticias/`
    como decía el plan** — corregir en el registry), `crilar`
    (`/categoria/noticias/feed/`).
  - HTML_INDEX confirmado con URLs reales: `gobierno_larioja`
    (`/noticias/`), `legislatura_larioja` (`/noticias.php`, URLs
    `/noticias/2026/Slug.php`, paginación "cargar más" probablemente JS —
    la primera página alcanza), `hacienda_larioja`, `agua_energia_larioja`,
    `estadisticas_larioja` (confirmado `REFERENCE_ONLY`, no es sitio de
    noticias), y **todo el clúster `argentina.gob.ar`**
    (`seguridad_nacion`, `gendarmeria` con paginación `?page=N` confirmada,
    `pfa`, `vialidad_nacional`, `salud_nacion`, `educacion_nacion`, `arca`,
    `senasa`, `energia_nacion`, `prefectura`) — sin RSS/JSON-LD en ninguno;
    el `sitemap.xml` de ese dominio es un índice genérico de todo el
    portal (no filtrable barato por sección), así que **HTML_INDEX por
    sección gana a sitemap acá pese al orden de preferencia genérico del
    plan** (decisión documentada). `bcra` y `smn_news` también HTML_INDEX
    con fechas confirmadas.
  - **Deshabilitadas por evidencia real** (`enabled=false`, con `notes`):
    `policia_larioja` (Facebook sin alternativa estable; el sitio propio
    `policiadelarioja.gob.ar` es de trámites, no tiene prensa —
    `reason=no_stable_supported_access`), `salud_larioja`
    (`reason=site_under_maintenance`, sitio caído ahora mismo),
    `secretaria_justicia_larioja` (home sin listado de noticias real
    navegable, requiere revisión manual), `anses` e `indec` (fetch estático
    no trajo contenido — probable render client-side o bloqueo a fetch
    automatizado; **antes de descartarlas del todo, probar con
    `requests`+headers de navegador real desde Python**, ya que son
    prioridad HIGH del plan), `smn_alerts` (contenido de alertas vía JS,
    sin endpoint público visible — no se inventa uno).
  - **Boletín Oficial (Parte 20)**: dos dominios candidatos sin provenance
    confirmada desde infraestructura oficial (`boletinoflarioja.com.ar` y
    `web.larioja.org/bor-portada`) — se siembra como `candidate source
    disabled` sin activar ninguno, tal como pide el plan. (Ojo:
    `municipiolarioja.gob.ar/boletinOficial` es el boletín MUNICIPAL, no el
    provincial — no confundir.)
  - Ningún JSON-LD `NewsArticle` detectado en la muestra revisada.

## Diseño técnico (Fase 1 — plan corto)

Paquetes nuevos en el autopublicador:

- `editorial_context/` — Archive Context Engine + Story Engine + Context
  Store + Context Budget + EditorialContextBundle + instrumentación IA.
  - `db.py` (conexión sqlite derivada `data/derived/editorial_context.sqlite3`,
    resuelta vía `utils/paths.py` nuevo `derived_dir()`; probe FTS5 + fallback;
    creación de esquema idempotente).
  - `entities.py` (extracción determinística de entidades/localidad — NO
    reutiliza `_entity_tokens` privado de editorial_router, copia acotada
    propia siguiendo el mismo patrón de duplicación intencional que ya usa el
    repo entre `editorial_router` y `rewrite_news`).
  - `archive_index.py` (ingestión/upsert + `ArchiveSearchProvider`:
    `search`, `related`, `story`).
  - `archive_backfill.py` (backfill real desde `GET /api/public/posts` del
    CMS propio, paginado, respetuoso; ingestión también en tiempo real al
    publicar).
  - `retrieval.py` (candidate retrieval FTS + relation scoring explicable).
  - `story_engine.py` (asignación conservadora de `story_key`, reglas por
    categoría: policiales exige misma causa/hecho, no sólo misma persona).
  - `timeline.py` (máx 5 items, sólo con umbral alto, cronológico).
  - `context_depth.py` (NONE/LIGHT/STANDARD/STORY, reglas determinísticas,
    default LIGHT, sin llamadas IA extra).
  - `enrichment_slots.py` (CONTEXTO/CAMBIO/IMPACTO/DATOS/PRÓXIMO_PASO,
    `available=false` si no hay evidencia, nunca inventado por Gemini).
  - `context_store.py` (ContextFact + TTL por tipo de dato/fuente).
  - `bundle.py` (EditorialContextBundle, aplica límites de Parte 35,
    serializa fragmento de prompt + `factual_basis_text` para el validador).
  - `instrumentation.py` (métricas de llamadas IA, tabla `ai_call_metrics`).
  - `refresh_context.py` (script de stage nuevo para `run_24x7.py`).
- `sources/` — Source Registry + adapters.
  - `registry.py` + `config/official_sources.json` (metadata sembrada de
    Partes 18-20, incluyendo fuentes `enabled=false` cuando no hay método
    estable confirmado).
  - `http_client.py` (sesión reutilizable + ETag/If-Modified-Since sobre
    `utils/safe_http.py`).
  - `strategies/` (rss.py, sitemap.py, html_index.py, jsonld.py — genéricas,
    configuración por fuente, no un script por sitio).
  - `selector.py` (SourceSelector determinístico por categoría/entidad).
  - `cache.py` (official_content_cache + dedup `republished_official_content`).
  - `metrics.py` (métricas por fuente).
  - `probe.py` (`cli.py source-probe`).
- Cambios quirúrgicos en código existente:
  - `utils/paths.py`: agregar `derived_dir()`.
  - `utils/ai_client.py`: agregar kwargs opcionales `stage`/`article_id` a
    `chat_completion` + instrumentación interna (no cambia firma para los 8
    call sites existentes).
  - `pipeline/node_webapp/editorial.py`: `_original_text` incluye
    `factual_basis_text` del bundle; `_call_ai_enricher` agrega campos
    opcionales al `user_payload`; `_SYSTEM_PROMPT` gana un párrafo aditivo
    sobre uso opcional/atribuido del contexto.
  - `pipeline/node_webapp/publisher.py`: arma el bundle antes de
    `prepare_editorial`; elimina `_CATEGORY_AUTHORS` (Parte 61); agrega
    `storyKey`/`sources[]` reales al payload cuando corresponda; registra el
    artículo publicado en el archive index en tiempo real.
  - `cli.py`: nuevos subcomandos `archive-index` (rebuild/backfill/stats,
    read-only salvo `--apply` explícito) y `source-probe` (Parte 22).
  - `run_24x7.py`: nuevo `CYCLE_STEPS` entry `editorial_context/refresh_context.py`.
- CMS (`LaVozRiojana`): migración Prisma aditiva (`storyKey`), zod schema,
  `<StoryTimeline />` + bloque "En contexto", `scripts/backfill_story_index.py`
  (en el repo Python, aplica vía `PATCH /api/private/posts/[id]` sólo con
  `--apply` explícito).

Todo detrás de flags con default seguro (`EDITORIAL_CONTEXT_ENABLED`,
`OFFICIAL_SOURCES_ENABLED`, cada fuente con su propio `enabled` en el
registry) siguiendo el patrón ya establecido en AGENTS.md.

## Próximo paso concreto

Esperar el resultado del fork de auditoría de fuentes oficiales (RSS/sitemap/
JSON-LD por sitio). Mientras tanto, empezar a escribir código: primero
`utils/paths.py::derived_dir()` y `editorial_context/db.py` (esquema +
probe FTS5), después `entities.py`, `archive_index.py`, tests en paralelo.
