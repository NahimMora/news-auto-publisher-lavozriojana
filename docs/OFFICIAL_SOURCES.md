# Fuentes oficiales

Source Registry configurable (`config/official_sources.json`, cargado por
`sources/registry.py`) — contrato común, no un script por sitio. Ver
`docs/EDITORIAL_CONTEXT.md` para cómo se consumen (`SourceSelector`, caché,
`EditorialContextBundle`).

## Cómo se relevó (Parte 21/72)

Cada fuente se investigó con un fetch real (no se infirió nada) contra el
sitio en vivo, en este orden de preferencia: RSS/Atom → endpoint
JSON/WordPress (`wp-json`) → sitemap → HTML index server-rendered →
JSON-LD → HTML de artículo → headless (nunca usado). El
`sitemap.xml` de `argentina.gob.ar` existe pero es un índice genérico de
**todo el portal** (miles de URLs sin filtrar por sección) — no es viable
como estrategia de discovery barata para ese dominio, así que HTML_INDEX
por sección le gana a sitemap ahí pese al orden de preferencia genérico
(decisión documentada en `docs/DECISIONS.md`).

## Tabla completa

| source_id | host | prioridad | modo | estrategia | habilitada | poll_ttl |
|---|---|---|---|---|:---:|---:|
| `policia_larioja` | www.facebook.com | CRITICAL | DISCOVERY | DISABLED | ❌ | — |
| `mpf_larioja` | www.mpflarioja.gob.ar | CRITICAL | BOTH | RSS | ✅ | 30 min |
| `justicia_larioja` | www.justicialarioja.gob.ar | CRITICAL | BOTH | RSS | ✅ | 30 min |
| `gobierno_larioja` | larioja.gob.ar | HIGH | BOTH | HTML_INDEX | ✅ | 1 h |
| `secretaria_justicia_larioja` | secretariadejusticia.larioja.gob.ar | HIGH | BOTH | UNCONFIRMED | ❌ | 1 h |
| `legislatura_larioja` | legislaturalarioja.gob.ar | HIGH | BOTH | HTML_INDEX | ✅ | 1 h |
| `salud_larioja` | salud.larioja.gob.ar | HIGH | BOTH | DISABLED | ❌ | 1 h |
| `hacienda_larioja` | hacienda.larioja.gob.ar | HIGH | BOTH | HTML_INDEX | ✅ | 1 h |
| `turismo_larioja` | turismo.larioja.gob.ar | MEDIUM | BOTH | RSS | ✅ | 6 h |
| `agua_energia_larioja` | aguayenergia.larioja.gob.ar | MEDIUM | BOTH | HTML_INDEX | ✅ | 6 h |
| `estadisticas_larioja` | estadisticas.larioja.gob.ar | MEDIUM | REFERENCE_ONLY | HTML_INDEX | ✅ | 1 d |
| `crilar` | crilar.conicet.gov.ar | MEDIUM | BOTH | RSS | ✅ | 12 h |
| `seguridad_nacion` | www.argentina.gob.ar | HIGH | ENRICHMENT | HTML_INDEX | ✅ | 6 h |
| `gendarmeria` | www.argentina.gob.ar | CRITICAL* | ENRICHMENT | HTML_INDEX | ✅ | 6 h |
| `pfa` | www.argentina.gob.ar | MEDIUM | ENRICHMENT | HTML_INDEX | ✅ | 12 h |
| `vialidad_nacional` | www.argentina.gob.ar | HIGH | ENRICHMENT | HTML_INDEX | ✅ | 6 h |
| `salud_nacion` | www.argentina.gob.ar | HIGH | ENRICHMENT | HTML_INDEX | ✅ | 6 h |
| `educacion_nacion` | www.argentina.gob.ar | MEDIUM | ENRICHMENT | HTML_INDEX | ✅ | 12 h |
| `anses` | www.anses.gob.ar | HIGH | ENRICHMENT | UNCONFIRMED | ❌ | 6 h |
| `bcra` | www.bcra.gob.ar | HIGH | ENRICHMENT | HTML_INDEX | ✅ | 6 h |
| `indec` | www.indec.gob.ar | HIGH | BOTH | UNCONFIRMED | ❌ | 6 h |
| `arca` | www.argentina.gob.ar | HIGH | ENRICHMENT | HTML_INDEX | ✅ | 6 h |
| `senasa` | www.argentina.gob.ar | HIGH | ENRICHMENT | HTML_INDEX | ✅ | 12 h |
| `smn_news` | ws2.smn.gob.ar | MEDIUM | ENRICHMENT | HTML_INDEX | ✅ | 6 h |
| `smn_alerts` | ws2.smn.gob.ar | CRITICAL* | ENRICHMENT | UNCONFIRMED | ❌ | 15 min |
| `energia_nacion` | www.argentina.gob.ar | MEDIUM | ENRICHMENT | HTML_INDEX | ✅ | 12 h |
| `prefectura` | www.argentina.gob.ar | LOW | ENRICHMENT | HTML_INDEX | ✅ | 1 d |
| `boletin_oficial_larioja` | boletinoflarioja.com.ar | LOW | REFERENCE_ONLY | UNCONFIRMED | ❌ | 1 d |

\* CRITICAL condicionado a relevancia riojana real (ver `SourceSelector`,
`REQUIRES_RIOJAN_LOCALITY` en `sources/selector.py`) — nunca se publica
automáticamente contenido de todo el país.

## Detalle fuente por fuente

### Provinciales

**`policia_larioja`** — objetivo: policiales/sociedad. Único canal
encontrado es la página de Facebook (`/612033808661501/`); el sitio propio
`policiadelarioja.gob.ar` es de trámites (PoliBot, Comisaría Digital), sin
sección de prensa. Estrategia elegida: **ninguna** (deshabilitada,
`reason=no_stable_supported_access`) — el plan pide explícitamente no
depender de scraping de Facebook como dependencia productiva. Riesgo: sin
adapter, se pierde la fuente más directa de policiales locales; mitigado
parcialmente por MPF/Función Judicial. Alternativas descartadas: mirrors
tipo GovServ/FindGlocal (prohibidos explícitamente por el plan).

**`mpf_larioja`** — Ministerio Público Fiscal. RSS de WordPress confirmado
en `/feed/` (10 items, `pubDate` real). Elegido por ser la opción A del
orden de preferencia (más barato/estable). Sin alternativas necesarias.

**`justicia_larioja`** — Función Judicial. Sitio Joomla: el `/feed/`
genérico da 404; el feed real vive en la categoría de noticias
(`?format=feed&type=rss`, confirmado con 9 items). El plan original decía
`path=/`; corregido con evidencia real.

**`gobierno_larioja`** — sin RSS (`/feed/` → 404). HTML_INDEX confirmado
sobre `/noticias/`. Alternativa descartada: sitemap (no hay uno específico
de noticias visible, y el genérico no es más barato que el índice HTML).

**`secretaria_justicia_larioja`** — la home no expone un listado de
noticias real navegable en el fetch (sólo un anchor `#actividades`).
Deshabilitada hasta revisión manual (posible contenido cargado por JS, o
la sección vive en otra URL del mismo sitio) — no se inventó una estructura
sin confirmarla.

**`legislatura_larioja`** — URLs reales con patrón
`/noticias/2026/Slug.php` confirmadas sobre `/noticias.php`. Paginación
"cargar más noticias" parece depender de JS; la primera página ya trae
ítems recientes con fecha, suficiente para el ciclo (no se implementó
paginación adicional por simplicidad/costo).

**`salud_larioja`** — sitio caído ("en mantenimiento") al momento del
relevamiento. No es un problema de estrategia sino de disponibilidad del
sitio; deshabilitada con `reason=site_under_maintenance`. Reintentar el
probe (`cli.py source-probe --source salud_larioja --json`) periódicamente
antes de habilitar.

**`hacienda_larioja`** — WordPress con RSS aparentemente desactivado
(`/feed/` devuelve el HTML de la home en vez de XML). HTML_INDEX
confirmado sobre la home.

**`turismo_larioja`** — el plan original decía `path=/noticias/feed/`; el
custom post type real con contenido vive en `/novedades/` (RSS confirmado
con 10 items, `pubDate` real). El feed raíz `/feed/` está vacío porque sólo
cubre el post type "post" default de WordPress. Corregido con evidencia.

**`agua_energia_larioja`** — WordPress sin feed funcional. El listado no
siempre muestra fecha visible en el índice; el adapter genérico puede
devolver `published_at` vacío para algunos ítems (no se implementó lectura
de fecha desde el artículo individual, por costo/simplicidad — limitación
conocida).

**`estadisticas_larioja`** — confirmado que no es un sitio de noticias sino
de indicadores/informes → `mode=REFERENCE_ONLY` tal como pedía el plan.

**`crilar`** — CONICET. RSS confirmado con `pubDate` real sobre
`/categoria/noticias/feed/`.

### Nacionales (`www.argentina.gob.ar`, `bcra.gob.ar`, `ws2.smn.gob.ar`)

Todo el clúster `argentina.gob.ar` (`seguridad_nacion`, `gendarmeria`,
`pfa`, `vialidad_nacional`, `salud_nacion`, `educacion_nacion`, `arca`,
`senasa`, `energia_nacion`, `prefectura`) comparte plataforma: sin
RSS/JSON-LD detectado, HTML_INDEX confirmado por sección
(`gendarmeria` con paginación `?page=N` confirmada). El `sitemap.xml` de
ese dominio es un índice genérico de todo el portal — no filtrable barato
por sección, así que se descartó como estrategia pese a estar más arriba en
el orden de preferencia genérico (ver nota al inicio de este documento).

**`gendarmeria`** — CRITICAL sólo para coincidencias reales con La Rioja
(localidades riojanas, Escuadrón 58 La Rioja, Escuadrón 24 Chilecito,
rutas/procedimientos en la provincia); el `SourceSelector` exige una
localidad riojana detectada antes de incluirla — nunca se publica
automáticamente contenido de todo el país (Parte 19).

**`bcra`** — HTML_INDEX confirmado sobre `/Noticias/`, sin RSS detectado.

**`anses`** e **`indec`** — el fetch estático no trajo contenido en 2
intentos cada uno: probable render client-side o bloqueo a fetch
automatizado. Son prioridad HIGH del plan (ANSES para beneficios, INDEC
para inflación) — **quedan deshabilitadas** con `discovery_strategy:
UNCONFIRMED` en vez de forzar una estrategia sin confirmar. Antes de
descartarlas del todo, un próximo paso es probar con `requests` +
User-Agent de navegador real desde `sources/http_client.py` (no sólo el
fetch usado para este relevamiento).

**`smn_news`** — HTML_INDEX confirmado, paginado, fechas visibles en el
listado.

**`smn_alerts`** — el contenido de alertas se carga vía JS; no hay
endpoint JSON público visible en el HTML estático. CRITICAL sólo cuando
haya alerta vigente en La Rioja (Parte 19/31, TTL de 15 min por ser dato
altamente temporal), pero no se inventó un endpoint sin confirmarlo:
deshabilitada hasta encontrar un mecanismo estable (requiere inspeccionar
el tráfico de red real de la página, no sólo su HTML).

**`prefectura`** — prioridad LOW para audiencia riojana (Parte 19); no
gastar recursos frecuentes si no demuestra utilidad, de ahí el `poll_ttl`
de 1 día.

### Boletín Oficial (candidata, Parte 20)

**`boletin_oficial_larioja`** — existen al menos dos dominios candidatos
sin provenance confirmada desde infraestructura oficial provincial:
`boletinoflarioja.com.ar` y `web.larioja.org/bor-portada`. Ninguno es
`.gob.ar`, y no se encontró un enlace directo desde `larioja.gob.ar` hacia
ninguno de los dos en este relevamiento (puede estar en un submenú no
capturado). **No confundir** con `municipiolarioja.gob.ar/boletinOficial`,
que es el boletín **municipal**, no el provincial. Sembrada como candidate
source `disabled` tal como pide el plan, hasta confirmación manual
explícita de cuál dominio (si alguno) es el vigente.

## Diagnóstico read-only

```powershell
python cli.py source-probe --source mpf_larioja --json
```

Nunca escribe caché, métricas ni estado — sólo hace el GET real (incluso
para una fuente deshabilitada, vía `force=True` interno) y reporta
`reachable`, `strategy`, `http_status`, `items_found`, `newest_item_date`,
`latency_ms`, `etag_available`, `last_modified_available`, `parse_status`,
`warnings` (Parte 22).

## Ciclo real (Parte 56/57)

`editorial_context/refresh_context.py` corre una vez por ciclo del
supervisor (`run_24x7.py::CYCLE_STEPS`, entre `run_all.py` y
`pipeline/publish_web.py`, sin canal — no sujeto a los kill switches de
web/Facebook/Instagram). Sólo sincroniza fuentes cuyo `poll_ttl` venció
(`sources/fetch_state.py::is_due`); reutiliza ETag/If-Modified-Since del
fetch anterior cuando el servidor los soporta. Un fallo en una fuente se
loguea y no rompe el ciclo ni las demás fuentes.

Todas las noticias de un mismo ciclo consultan la caché local
(`sources/cache.py`, `official_content_cache`) — nunca se vuelve a pegar a
una fuente por cada noticia (Parte 56).

## Métricas por fuente (Parte 55)

```powershell
python cli.py archive-index stats --since-days 7
```

Por fuente: `requests`, `not_modified_304`, `items_discovered`,
`items_new`, `parse_failures`, `timeouts`, `avg_latency_ms`,
`last_success`, `last_item_date` — para poder eliminar fuentes inútiles con
evidencia en vez de intuición.
