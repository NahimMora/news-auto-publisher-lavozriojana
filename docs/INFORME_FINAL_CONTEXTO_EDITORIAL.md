# Informe final — Editorial Context Engine / Story Engine / Source Registry

Fecha: 2026-09-10. Repos: `AutoPublicador_LaVozRiojana` (rama
`feature/editorial-context-story-engine`) y `LaVozRiojana` (misma rama).
Ninguno mergeado a `main`. Producción no fue tocada en ningún momento.

## 1. Estado de producción

- **Qué se detuvo**: nada. No hay acceso remoto (SSH) a la PC de producción
  (`PC@192.168.1.150`) desde esta sesión; todo el trabajo se hizo en la
  máquina de desarrollo (`pc10`), nunca en producción, siguiendo la regla ya
  vigente en `docs/RUNBOOK.md` ("Entorno: desarrollo vs. producción").
- **Qué NO se detuvo**: el supervisor 24/7 productivo real (si está
  corriendo) sigue exactamente igual que antes de esta sesión — no se le
  hizo `git pull` ni restart.
- **Estado de las tareas**: 76 partes del plan cubiertas; el detalle
  completo, tarea por tarea, está en `docs/EDITORIAL_CONTEXT_PROGRESS.md`
  (bitácora de toda la sesión, útil para retomar si hace falta).
- **Estado final**: código completo, testeado y documentado, en dos ramas
  sin mergear, esperando revisión humana antes de cualquier despliegue.

## 2. Arquitectura antes

```
FUENTE (scraper privado)
  → scrape → normalización → reescritura/clasificación (Gemini)
  → publicación CMS/Facebook/Instagram
```

Sin archivo propio consultado, sin fuentes oficiales, sin agrupación en
historias, sin timeline, sin Context Store. `noticias_web_publicadas.json`
era la única noción de "histórico" (en realidad una ventana de 7 días).

## 3. Arquitectura después

```
FUENTES ACTUALES → SCRAPING ACTUAL → NORMALIZACIÓN
  → [refresh_context.py: fuentes oficiales, 1x/ciclo, respeta poll_ttl]
  → ANÁLISIS DEL HECHO (entities.py, determinístico)
  → RECUPERACIÓN DE ARCHIVO LVR (archive_index.py, SQLite FTS derivado)
  → SELECCIÓN DE ENRIQUECEDORES (sources/selector.py)
  → FUENTES OFICIALES RELEVANTES (cache local, nunca red por noticia)
  → CONTEXT BUNDLE (bundle.py, único punto de entrada)
  → HISTORIA / STORY RELATION (story_engine.py, muy conservador)
  → CONTEXT BUDGET (context_depth.py: NONE/LIGHT/STANDARD/STORY)
  → REDACCIÓN (editorial.py, misma llamada de IA, prompt enriquecido)
  → VALIDACIÓN (validator factual existente + factual_basis_text del bundle)
  → PUBLICACIÓN (storyKey/sources[]/archiveContext opcionales en el payload)
```

No se reemplazó nada del pipeline existente — todo es aditivo, detrás de
degradación segura (una falla en cualquier pieza nueva nunca bloquea una
publicación).

## 4. Archivo propio

- **Cómo se indexa**: `editorial_context/archive_index.py::upsert_article`
  en tiempo real tras cada publicación exitosa
  (`publisher.py::_record_archive_article`, best-effort). Extrae entidades
  y localidades del título/excerpt con `entities.py` (regex determinístico,
  sin IA).
- **Cómo se busca**: dos pasos (`docs/EDITORIAL_CONTEXT.md`). Paso A —
  candidate retrieval por FTS/BM25 (o `LIKE` en fallback) sobre
  título+entidades+localidades+categoría+tags, ~20 candidatos baratos.
  Paso B — scoring explicable (`retrieval.score_candidate`, tabla de pesos
  documentada) con umbral más estricto para categorías sensibles
  (policiales/espectáculos/deportes exigen entidad Y término compartido).
- **Qué almacenamiento usa**: SQLite (`data/derived/editorial_context.sqlite3`),
  **derivado, reconstruible, NO autoritativo** — decisión documentada en
  `docs/DECISIONS.md` explicando por qué esto no contradice el rechazo
  previo a migrar las colas JSON a una base de datos.
- **Cómo se reconstruye**: `python cli.py archive-index rebuild` (borra y
  recrea el esquema vacío) + `python cli.py archive-index backfill-cms`
  (repobla desde `GET /api/public/posts` del CMS propio, paginado). La
  ingesta en tiempo real sigue sola desde el próximo ciclo.

## 5. Story Engine

- **Algoritmo**: `editorial_context/story_engine.py::assign_story`. Sin
  candidatos → `None` (una noticia nueva sin antecedentes no es un error).
  Puntúa candidatos, filtra por umbral de categoría, reutiliza `story_key`
  existente si algún candidato calificado ya lo tiene, o crea uno nuevo
  determinístico (`story:<sha1(article_id_predecesor)[:12]>`).
- **Weights** (retrieval.py, `docs/EDITORIAL_CONTEXT.md` tiene la tabla
  completa): same_entity +0.35 c/u (máx 2), same_locality específica +0.15
  c/u (máx 2), same_locality provincia +0.05, same_category +0.10,
  shared_significant_terms +0.05 c/u (máx 3), recencia hasta +0.15
  (decae a 0 en 60 días).
- **Thresholds**: 0.55 + entidad Y término para
  policiales/espectáculos/deportes; 0.45 + entidad O localidad para el
  resto.
- **Ejemplos** (todos con test): obra vial en etapas (interior), ley
  aprobada→promulgada (política), mismo expediente detención→condena
  (policiales), mismo equipo+torneo (deportes), mismo artista+evento
  concreto (espectáculos). Negativos con test: dos causas distintas de la
  misma persona, mismo famoso en eventos sin relación, agrupar sólo por
  categoría.

## 6. Timeline

- **Cuándo aparece**: `story_key` presente + ≥2 notas previas en esa
  historia + al menos una relación de confianza `high` dentro de la
  historia (`editorial_context/timeline.py`).
- **Cuándo no**: cualquier otro caso — devuelve lista vacía, el componente
  web (`<StoryTimeline />`) también se autooculta con `<2` items como
  segunda capa de seguridad.
- **Máximo de items**: 5, orden cronológico, la nota actual nunca aparece
  en su propia lista.
- **Cómo enlaza**: el CMS consulta `getStoryTimeline(storyKey,
  excludePostId)` directamente sobre `Post.storyKey` (columna nueva,
  indexada) en el momento de render — no se duplica el timeline entre el
  índice Python y la base del CMS.

## 7. Context Budget

| Depth | Condición | Límite de palabras/cuerpo | Notas previas |
|---|---|---|---|
| `NONE` | sin archivo ni fuente oficial relevante | 0 | 0 |
| `LIGHT` (default) | evidencia débil-media o sólo fuente oficial | ~120 | 1 |
| `STANDARD` | score ≥0.6, o ≥2 candidatos con score ≥0.45 | ~220 | 3 |
| `STORY` | Story Engine confirmó timeline | ~220 (timeline vive aparte en UI) | 3 |

Límites de tamaño exactos implementados (env-configurables):
`ARCHIVE_CONTEXT_MAX_ITEMS=3`, `RELATED_ARTICLES_MAX_ITEMS=5`,
`TIMELINE_MAX_ITEMS=5`, `ARCHIVE_CONTEXT_MAX_CHARS=3500`,
`OFFICIAL_CONTEXT_MAX_CHARS=4500`, `OFFICIAL_SNIPPET_MAX_ITEMS=3`.

## 8. Context Store

- **Modelo**: `ContextFact` (entity_key, fact, source_kind, source_url,
  source_article_id, observed_at, event_date, expires_at, confidence,
  hash) — `editorial_context/context_store.py`.
- **TTL**: por `fact_type` — hecho_historico sin vencimiento, precio_monto
  3 días, cronograma hasta `event_date`, funcionario_cargo 90 días,
  alerta_meteorologica 6h, resultado_deportivo sin vencimiento, default 30
  días. `get_facts()` filtra vencidos por defecto.
- **Provenance**: todo hecho tiene `source_kind` (OWN_ARCHIVE u
  OFFICIAL_SOURCE) y `source_url`; nunca se guarda "conocimiento general
  del modelo".
- **Cache**: dedup por hash (`entity_key|fact|source_url`), upsert
  idempotente.

## 9. Fuentes oficiales

27 fuentes sembradas con datos reales de un relevamiento técnico (fetch en
vivo, tabla completa y justificación fuente por fuente en
`docs/OFFICIAL_SOURCES.md`):

| source | strategy | enabled | items detected | last item | latency | warnings |
|---|---|:---:|---|---|---|---|
| mpf_larioja | RSS | ✅ | 10 (relevamiento) | fecha real confirmada | baja | — |
| justicia_larioja | RSS (categoría, no `/feed/` raíz) | ✅ | 9 | confirmada | baja | path corregido vs. plan original |
| turismo_larioja | RSS (`/novedades/feed/`, no `/noticias/feed/`) | ✅ | 10 | confirmada | baja | path corregido vs. plan original |
| crilar | RSS | ✅ | confirmado | confirmada | baja | — |
| gobierno_larioja, legislatura_larioja, hacienda_larioja, agua_energia_larioja, estadisticas_larioja | HTML_INDEX genérico | ✅ | confirmado | parcial (heurística) | media | sin fecha en algunos ítems |
| seguridad_nacion, gendarmeria, pfa, vialidad_nacional, salud_nacion, educacion_nacion, arca, senasa, energia_nacion, prefectura, bcra, smn_news | HTML_INDEX genérico | ✅ | confirmado | confirmada/parcial | media | sitemap descartado (índice genérico de portal) |
| policia_larioja | — | ❌ | — | — | — | sin alternativa a Facebook |
| salud_larioja | — | ❌ | — | — | — | sitio caído al relevar |
| secretaria_justicia_larioja | — | ❌ | — | — | — | sin listado real navegable |
| anses, indec | — | ❌ | — | — | — | fetch estático vacío, probar con headers de navegador |
| smn_alerts | — | ❌ | — | — | — | contenido vía JS, sin endpoint visible |
| boletin_oficial_larioja | — | ❌ | — | — | — | provenance no confirmada (2 dominios candidatos) |

Sin métricas de producción reales todavía (no se ejecutó el ciclo en vivo);
`cli.py archive-index stats` las reporta apenas corra.

## 10. Category Enrichers (SourceSelector)

`sources/selector.py`:

| Categoría | Fuentes candidatas |
|---|---|
| policiales | MPF, Función Judicial, Policía (deshabilitada), Gendarmería*, PFA |
| política | Gobierno, Legislatura, Secretaría de Justicia (deshabilitada), Hacienda, MPF, Función Judicial |
| economía | Hacienda, BCRA, INDEC (deshabilitada), ARCA, ANSES (deshabilitada), Energía, SENASA |
| salud | Salud provincial (deshabilitada), Salud Nación, CRILAR |
| educación | Educación Nación, Legislatura |
| interior | Vialidad Nacional, Gobierno, Agua y Energía, SENASA |
| sociedad | Gobierno, SMN noticias/alertas, Estadísticas |
| cultura | Turismo, CRILAR |
| deportes / espectáculos | ninguna (Parte 32/33: sin fuentes oficiales nacionales en esta etapa) |

\* Gendarmería/PFA/Prefectura/Seguridad Nación exigen una localidad riojana
detectada antes de seleccionarse (Parte 19).

## 11. Gemini

- **Llamadas anteriores**: 1 por noticia (`_call_ai_enricher`, más
  reintentos/revisiones que ya existían).
- **Llamadas nuevas**: **0**. El contexto se agrega como campos opcionales
  al mismo prompt existente.
- **Costo estimado**: ~5.000-8.000 tokens de entrada extra/día a 50
  noticias/día (estimación conservadora, sin datos reales de producción
  todavía — `docs/COST_MODEL.md` tiene el detalle y cómo confirmarlo con
  métricas reales una vez en producción).

## 12. CMS/Web (repo `LaVozRiojana`)

- `prisma/schema.prisma`: `Post.storyKey String? @db.VarChar(160)` +
  índice `[storyKey, publishedAt]`.
- `lib/schemas.ts`: `storyKey` opcional en `postCreateSchema`.
- `lib/post-mutations.ts`: `createPost`/`updatePost` lo persisten.
- `lib/posts.ts::getStoryTimeline`.
- `components/news/StoryTimeline.tsx`, `components/news/ArchiveContextNote.tsx`
  (mutuamente excluyentes, insertados en `app/noticias/[slug]/page.tsx`
  entre `Sources` y `AuthorBox`).
- `app/globals.css`: CSS nuevo reusando los design tokens existentes.
- `npm run typecheck`, `npm run lint`, `npm run build`: **todos en verde**.

## 13. Database

- **Migraciones creadas**: `prisma/migrations/20260910130000_add_post_story_key/`
  (aditiva, nullable, backward-compatible).
- **Ejecutada**: **sí, contra el DB local de desarrollo**
  (`lavozriojana_news_app` en `127.0.0.1:3306`), con `npx prisma migrate
  deploy`. **No ejecutada contra ningún DB de producción** — eso requiere
  autorización y acceso que esta sesión no tiene.
- **Hallazgo operativo crítico**: al regenerar el Prisma Client con el
  campo nuevo, `npm run build` reventó con
  `column storyKey does not exist` en **todas** las queries de posts (no
  sólo las nuevas), hasta aplicar la migración. **Esto significa que la
  migración debe aplicarse ANTES o junto con el deploy de este código en
  cualquier ambiente, nunca después**, o el sitio entero sirve contenido
  vacío en home/categorías (los `catch(() => [])` existentes lo esconden
  como "sin resultados" en vez de crashear visiblemente).
- **Estado exacto**: DB local de desarrollo migrado y verificado; DB de
  staging/producción del CMS, sin tocar.

## 14. Tests

Autopublicador:

```
python -m unittest discover tests   →  695/695 OK  (592 antes de esta etapa, +103 nuevos)
python -m compileall -q .           →  limpio
python cli.py doctor --scope core --json     →  status=success, exit_code=0
python cli.py run-once --dry-run --json      →  17/17 escenarios locales OK, production_calls=false
git diff --check                             →  limpio
```

CMS (`LaVozRiojana`, sin suite de tests — confirmado en la auditoría
inicial, no hay script `test` en `package.json`):

```
npm run typecheck   →  limpio
npm run lint        →  "No ESLint warnings or errors"
npm run build       →  32/32 páginas, sin prisma:error (tras aplicar la migración)
```

Cobertura revisada explícitamente contra la lista de 35 casos de la Parte
65 del plan: todos cubiertos salvo "attribution policial" (no
determinístico, depende de la salida de Gemini — la salvaguarda existente
es `_judicial_warnings` en `editorial.py`, ya vigente antes de esta etapa,
no código nuevo).

**Bug real encontrado y corregido durante el desarrollo de tests**:
`retrieval.significant_terms()` no excluía las palabras sueltas de una
entidad ya excluida ("maria"/"becerra" de "Maria Becerra"), permitiendo que
el propio nombre se colara como "término compartido" y rompiera la
exigencia de evidencia doble en categorías estrictas — "mismo famoso pero
eventos distintos" podía agrupar una historia falsa. Corregido y cubierto
con test de regresión (`docs/STORY_ENGINE.md` tiene el detalle).

## 15. Dry run

```
python cli.py run-once --dry-run --json
```
→ `status=success`, `succeeded=17`, `production_calls=false`. Sin llamadas
a integraciones reales (CMS/Facebook/Instagram/Gemini reales).

## 16. Archivos modificados (autopublicador)

`.gitignore`, `AGENTS.md`, `cli.py`, `docs/ARCHITECTURE.md`,
`docs/CURRENT_STATE.md`, `docs/DECISIONS.md`, `docs/RUNBOOK.md`,
`pipeline/node_webapp/editorial.py`, `pipeline/node_webapp/publisher.py`,
`run_24x7.py`, `tests/test_deployment_modes.py`,
`tests/test_node_webapp_publisher.py`, `utils/ai_client.py`,
`utils/paths.py`.

Archivos modificados (CMS): `app/globals.css`,
`app/noticias/[slug]/page.tsx`, `lib/post-mutations.ts`, `lib/posts.ts`,
`lib/schemas.ts`, `prisma/schema.prisma`.

## 17. Archivos nuevos

Autopublicador (paquetes completos): `editorial_context/` (13 módulos),
`sources/` (11 módulos incluyendo `strategies/`), `config/official_sources.json`,
`scripts/backfill_story_index.py`, `docs/COST_MODEL.md`,
`docs/EDITORIAL_CONTEXT.md`, `docs/EDITORIAL_CONTEXT_PROGRESS.md`,
`docs/OFFICIAL_SOURCES.md`, `docs/STORY_ENGINE.md`,
`docs/INFORME_FINAL_CONTEXTO_EDITORIAL.md` (este archivo), 34 archivos de
test nuevos + 3 fixtures (`tests/fixtures/official_sources/`).

CMS: `components/news/ArchiveContextNote.tsx`,
`components/news/StoryTimeline.tsx`,
`prisma/migrations/20260910130000_add_post_story_key/migration.sql`.

## 18. Variables de entorno

Todas opcionales, con default seguro (no cambian el comportamiento actual
si no se configuran):

| Variable | Default | Efecto |
|---|---|---|
| `LVR_DERIVED_DIR` | `<data_dir>/derived` | ubicación del índice SQLite derivado |
| `ARCHIVE_CONTEXT_MAX_ITEMS` | `3` | notas previas máximas citadas |
| `RELATED_ARTICLES_MAX_ITEMS` | `5` | relacionadas máximas en el bundle |
| `TIMELINE_MAX_ITEMS` | `5` | items máximos del timeline |
| `ARCHIVE_CONTEXT_MAX_CHARS` | `3500` | tope de caracteres de contexto propio |
| `OFFICIAL_CONTEXT_MAX_CHARS` | `4500` | tope de caracteres de contexto oficial |
| `OFFICIAL_SNIPPET_MAX_ITEMS` | `3` | fragmentos oficiales máximos por nota |

No se agregó ningún flag "encendido/apagado" global del motor de contexto:
el sistema degrada solo a `ContextDepth.NONE` sin evidencia, así que
comportarse "como antes" es el resultado natural cuando no hay archivo ni
fuentes oficiales pobladas todavía (primera corrida tras el merge).

## 19. Riesgos pendientes (sin ocultar)

- `anses`/`indec` deshabilitadas pese a ser prioridad HIGH del plan
  (fetch estático vacío) — necesitan una prueba real con
  `requests`+headers de navegador, no sólo el fetch usado en el
  relevamiento.
- `editorial_context/archive_backfill.py` asume nombres de campo de
  `GET /api/public/posts` no verificados contra una respuesta real del
  endpoint — confirmar antes de depender de esto en producción.
- No se implementó fetch del cuerpo completo de artículos oficiales (sólo
  título/excerpt del índice/RSS) — decisión consciente de costo/simplicidad,
  no un bug.
- `secretaria_justicia_larioja` sigue deshabilitada sin adapter (home sin
  listado de noticias real en el fetch).
- Sin datos reales de producción: las estimaciones de costo/distribución de
  `ContextDepth` son conservadoras, no medidas — `cli.py archive-index
  stats` las confirma apenas corra el ciclo real.
- El índice derivado nunca se ejecutó contra el volumen real de notas de
  producción (miles) — sólo contra fixtures de test; el rendimiento de FTS5
  a ese volumen no está medido todavía.
- La migración del CMS está aplicada sólo en el DB local de desarrollo, NO
  en producción — ver sección 21.

## 20. Decisiones que tomé y por qué

Todas registradas formalmente en `docs/DECISIONS.md` (entradas del
2026-09-10): SQLite derivado como complemento no reemplazo de JSON;
backfill vía API del CMS en vez de sitemap; `metadata` JSON existente para
"En contexto" en vez de una tabla nueva; HTML_INDEX en vez de sitemap para
`argentina.gob.ar` (el sitemap de ese dominio es un índice genérico de todo
el portal, no filtrable barato); corrección del bug de autoría
(`_CATEGORY_AUTHORS` contradecía la Parte 61); mantener deshabilitadas las
fuentes sin estrategia confirmada en vez de adivinar una.

## 21. Producción — qué falta exactamente antes de reactivar/desplegar

1. **Revisión humana de ambas ramas** (no mergeadas a `main` en ninguno de
   los dos repos).
2. **CMS**: aplicar la migración `20260910130000_add_post_story_key` al DB
   de producción **antes o junto con** el deploy del código nuevo (ver
   hallazgo crítico, sección 13) — con `npx prisma migrate deploy` u
   ordenado por quien opera el despliegue.
3. **Autopublicador**: mergear a `main`, `git pull` en
   `PC@192.168.1.150` por SSH (procedimiento ya documentado en
   `docs/RUNBOOK.md`), y reinicio del supervisor — el mismo procedimiento
   que ya existía, ningún paso nuevo de infraestructura.
4. **Primera corrida en producción**: el índice derivado se autogenera
   solo (vacío) en el primer ciclo; recomendado correr
   `python cli.py archive-index backfill-cms` una vez, manualmente, para
   poblar el archivo histórico antes de depender del retrieval.
5. **Confirmar** `GET /api/public/posts` contra una respuesta real de
   producción antes de confiar en el backfill (riesgo #19).
6. **No hace falta** activar ningún flag nuevo — todo funciona con
   defaults seguros y degrada solo sin evidencia.

## 22. Commits / PR

Autopublicador (`NahimMora/news-auto-publisher-lavozriojana`), rama
`feature/editorial-context-story-engine` (creada desde
`feature/editorial-cinematica-riojana`), 8 commits, sin pushear todavía:

```
c6accde docs: documentar Editorial Context Engine, Story Engine, fuentes oficiales y modelo de costo
d81a39d feat(editorial-context): sources[] del CMS (Parte 62) + fix de falso positivo en Story Engine
da8cea5 feat(editorial-context): backfill_story_index.py (Parte 43)
82246c2 feat(editorial-context): archiveContext para el modulo web "En contexto" (Parte 38)
ee287fa feat(cli+editorial-context): source-probe/archive-index CLI y SourceSelector conectado al bundle
ebcbb1d feat(sources): Source Registry de fuentes oficiales (Partes 17-24, 50-58)
ace1b12 feat(editorial-context): integrar el ContextBundle en editorial.py/publisher.py y corregir bug de autor (Parte 61)
b141ff3 feat(editorial-context): Archive Context Engine + Story Engine + Context Store (base)
```

CMS (`NahimMora/lavozriojana-news-app`), rama
`feature/editorial-context-story-engine` (creada desde `main`), 1 commit,
sin pushear todavía:

```
9adcbb8 feat: soporte de storyKey y modulos "Segui esta historia" / "En contexto"
```

Ambas ramas fueron pusheadas y ambas PR quedaron abiertas (sin mergear),
con autorización explícita del usuario:

- Autopublicador: https://github.com/NahimMora/news-auto-publisher-lavozriojana/pull/6
  (base: `feature/editorial-cinematica-riojana`, que a su vez sigue sin
  mergear a `main`).
- CMS: https://github.com/NahimMora/lavozriojana-news-app/pull/1
  (base: `main`).
