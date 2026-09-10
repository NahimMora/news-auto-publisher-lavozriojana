# Cost Model — Editorial Context / Story Engine / Source Registry

Diseño low-cost by design (Parte 44): los únicos costos variables nuevos
son los tokens ya asociados a la llamada editorial existente (más contexto
en el mismo prompt, no llamadas nuevas) y ancho de banda/CPU triviales para
sincronizar fuentes oficiales. Estimación para **50 noticias/día**.

## Confirmación explícita (Parte 44/73)

```
Google Search calls / Search Grounding:  0
Paid embeddings:                          0
Paid search APIs:                         0
Vector DB cloud:                          0
```

Todo el retrieval, scoring, story assignment, context depth y enrichment
slots son determinísticos (regex/SQL/heurísticas sobre texto), sin ninguna
llamada a un proveedor de IA ni de búsqueda. Ver `docs/EDITORIAL_CONTEXT.md`.

## Requests a fuentes oficiales

`editorial_context/refresh_context.py` corre **una vez por ciclo del
supervisor**, no una vez por noticia (Parte 56). Con el intervalo real por
defecto (`PIPELINE_24X7_INTERVAL_SECONDS=3600`, 24 ciclos/día) y el
`poll_ttl` de cada fuente habilitada (`config/official_sources.json`), el
techo real de requests/día es:

```
Σ min(86400 / poll_ttl_fuente, 24)  ≈  168 requests/día
```

(21 fuentes habilitadas con estrategia confirmada; las CRITICAL/HIGH de
ciclo corto —MPF, Función Judicial, gobierno, legislatura, hacienda— topan
en 24/día porque el ciclo de 1h es más lento que su `poll_ttl`; el resto
pesa menos por `poll_ttl` de 6-24h). La mayoría de esos requests después
del primer fetch del día son `304 Not Modified` (ETag/If-Modified-Since,
`sources/http_client.py`) — payload casi nulo.

**MB descargados/día**: asumiendo ~30-80 KB por respuesta HTML/RSS
(páginas de listado, no artículos completos — Part 50 pide no almacenar
páginas enteras), y que buena parte son 304 sin cuerpo:
`168 requests × ~50 KB promedio ≈ 8-10 MB/día`. Trivial para cualquier
conexión.

Esto es independiente del volumen de noticias publicadas: 50 o 200
noticias/día no cambian este número, porque el refresh es por ciclo, no
por noticia (justamente lo que pide evitar la Parte 56).

## Llamadas a Gemini

**Cantidad de llamadas: sin cambios.** Esta etapa no agrega ninguna llamada
nueva a Gemini (Parte 45): sigue siendo una sola llamada editorial por
noticia (`_call_ai_enricher`, más los reintentos/revisiones que ya existían
antes de esta etapa). El contexto se agrega como campos opcionales al mismo
`user_payload`.

**Tokens de entrada, incremento estimado por noticia** (según
`ContextDepth`, ver `docs/EDITORIAL_CONTEXT.md`):

| Depth | Frecuencia esperada (estimación, sin datos reales aún) | Chars extra (archive+official+hints) | Tokens extra aprox. (~4 chars/token) |
|---|---:|---:|---:|
| `NONE` | mayoría de notas sin antecedentes | 0 | 0 |
| `LIGHT` | default cuando hay evidencia débil-media | hasta ~500 | ~125 |
| `STANDARD` | evidencia fuerte, minoría de notas | hasta ~3500-4500 | ~900-1100 |
| `STORY` | historia confirmada con timeline, la menos frecuente | igual que STANDARD | ~900-1100 |

Para 50 noticias/día, con una distribución conservadora estimada (sin datos
reales de producción todavía — la Parte 54 instrumenta exactamente esto
vía `cli.py archive-index stats`) de, por ejemplo, 60% NONE / 30% LIGHT /
10% STANDARD-STORY:

```
50 × (0.6×0 + 0.3×125 + 0.1×1000) ≈ 50 × 137.5 ≈ 6 875 tokens extra/día
```

Al precio de Gemini Flash-lite (modelo default,
`GEMINI_MODEL=gemini-3.1-flash-lite`), esto es un costo adicional
marginal — del orden de fracciones de centavo de dólar por día al volumen
actual. La cifra real se puede confirmar con
`cli.py archive-index stats` (`average_context_chars`) y
`ai_call_metrics` (tokens reales si el SDK los informa, estimados si no —
`editorial_context/instrumentation.py`) una vez en producción.

**Tokens de salida**: sin cambio esperado — el `_SYSTEM_PROMPT` pide una
mención breve (una oración), no una sección extensa; `max_tokens=1800` no
se modificó.

## Almacenamiento SQLite (`data/derived/editorial_context.sqlite3`)

Derivado, reconstruible, no autoritativo (`cli.py archive-index rebuild`).
Estimación de crecimiento a 50 noticias/día:

- `archive_articles`: ~1-2 KB/fila (título, excerpt, entidades/tags JSON) ×
  50/día × 365 ≈ **18-36 MB/año**.
- `archive_fts` (o el fallback plano): duplica aproximadamente el texto
  indexado → similar orden de magnitud, no varios múltiplos.
- `official_content_cache`: acotado por `items_new` real por fuente
  (`source_metrics`), típicamente unas pocas decenas de ítems nuevos/día en
  total entre todas las fuentes → unos pocos MB/año.
- `ai_call_metrics`, `bundle_events`, `story_relations`,
  `source_metrics`: filas pequeñas (decenas de columnas numéricas/texto
  corto), del orden de 1-5 MB/año a este volumen.

**Total estimado: bajas decenas de MB por año** — sin relevancia de costo
ni de performance en disco local.

## Tiempo de ciclo

`editorial_context/refresh_context.py` sólo hace trabajo cuando alguna
fuente está vencida según su `poll_ttl` (`sources/fetch_state.py::is_due`);
en el caso típico (nada vencido) el paso es prácticamente instantáneo. En
el peor caso (todas las fuentes vencen en el mismo ciclo), con
`request_delay` de 1-2s por fuente entre requests (respetuoso, Parte 23) y
~21 fuentes habilitadas, el techo es del orden de **30-60 segundos**
agregados al ciclo — timeout configurado en 900s
(`run_24x7.py::_STEP_TIMEOUTS`) da margen amplio.

`EditorialContextBundle` en sí (retrieval + scoring + story engine, todo
SQL/regex local) agrega milisegundos por noticia, no segundos — no requiere
medición especial más allá de lo que ya cubre
`utils/ai_client.py`/`ai_call_metrics` para la parte de IA.

## Resumen

| Rubro | Costo adicional |
|---|---|
| Google Search / grounding | $0 (no usado) |
| Embeddings pagos | $0 (no usado) |
| APIs de búsqueda pagas | $0 (no usado) |
| Vector DB cloud | $0 (no usado) |
| Requests a fuentes oficiales | ~168/día, ~8-10 MB/día, ancho de banda propio |
| Llamadas Gemini nuevas | 0 (mismo volumen de llamadas que antes) |
| Tokens Gemini extra | ~5 000-8 000 tokens/día estimados a 50 noticias/día (a confirmar con métricas reales) |
| Almacenamiento SQLite | bajas decenas de MB/año |
| Tiempo de ciclo | +0-60s en el peor caso, gated por `poll_ttl` |
