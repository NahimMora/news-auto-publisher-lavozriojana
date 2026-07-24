# Métricas operativas

Última actualización: 2026-07-23. Este documento define métricas calculables; no
inventa valores ni implica que exista un dashboard.

## Fuentes de verdad

| Dato | Fuente |
|---|---|
| resultado de ciclo/etapa | `data/supervisor_heartbeat.json` y logs estructurados |
| edad del supervisor | `heartbeat_at_ts` |
| colas activas | JSON de staging, rewrite, web, meta y social |
| terminales/fallbacks | `data/queue_events.json` |
| publicaciones confirmadas | `noticias_web_publicadas.json`, `fb_posted.json`, `ig_posted.json` |
| errores externos | logs rotativos de publisher, R2 y clientes Meta |

`python cli.py status --json` es la vista segura y de sólo lectura para heartbeat y
colas.

## Contadores obligatorios por etapa

Cada `StageResult` expone:

- `received`: entradas visibles al inicio;
- `selected`: lote elegido;
- `processed`: intentos ejecutados;
- `succeeded`: resultados con evidencia;
- `failed`: intentos fallidos;
- `deferred`: elementos conservados para otro ciclo;
- `expired`: terminales por antigüedad;
- `duration_seconds`;
- `error_type`, `error_code` y `next_retry_at`.

No se deriva salud a partir de texto de logs. `no_work` es sano; `0/N` no es éxito;
un lote parcial es `degraded`.

## Indicadores calculables

### Tasa de éxito de etapa

```text
succeeded / processed
```

Sólo se calcula cuando `processed > 0`; de lo contrario se informa “sin muestra”.
Debe acompañarse con el status y no usarse para convertir `degraded` en `success`.

### Backlog

```text
pending + processing
```

Se desglosa por rewrite, web, meta, Facebook e Instagram. Para detectar crecimiento
se necesitan al menos dos heartbeats; el repositorio no afirma tendencia a partir de
un único snapshot.

### Antigüedad

- supervisor: ahora menos `heartbeat_at_ts`;
- ciclo: ahora menos `cycle_finished_at_ts`;
- cola: ahora menos el timestamp de encolado del elemento más antiguo.

El supervisor está stale si supera `PIPELINE_24X7_STALE_SECONDS`.

### Fallos por tipo

Agrupar `error_type` y `error_code` por etapa:

- `invalid_credential`;
- `rate_limit`;
- `network_error` / `timeout`;
- `http_4xx` / `server_error`;
- `invalid_json` / `state_error`;
- `selector_mismatch`;
- `ambiguous_external_outcome`.

Los rate limits deben registrar `next_retry_at`.

### Integridad y recuperación

- cantidad en `dead_letter`;
- cantidad `expired`;
- cantidad de cuarentenas JSON;
- trabajos recuperados desde `processing`;
- conflictos de flags editoriales en `reconciliation_required`;
- fallbacks publicados o bloqueados por tipo/categoría.

## Publicaciones

Una publicación cuenta sólo si el historial conserva evidencia externa:

- web: ID, URL o slug verificable;
- Facebook/Instagram: ID de Graph API y, cuando corresponda, URL pública;
- deduplicación por una publicación ya existente: evidencia explícita, nunca un
  booleano fabricado.

Los conteos históricos del documento anterior (~683 Facebook, 245 ciclos) provenían
de una observación puntual de datos/logs operativos del 2026-07-20. No se vuelven a
presentar como métricas actuales porque esta auditoría no leyó ni modificó esos datos
para recalcularlos.

## Métricas fuera de alcance

Visitas, CTR, alcance social, audiencia e ingresos no se recolectan en este
repositorio. Agregarlas sería una funcionalidad de producto y no forma parte de la
línea de base de confiabilidad.

## Alertas operativas sugeridas

No hay motor de alertas implementado. Un operador debería investigar:

- heartbeat stale;
- cualquier `failed`;
- `degraded` repetido;
- backlog creciente entre ciclos;
- credencial inválida;
- dead-letter nuevo;
- JSON corrupto/cuarentena;
- scraper `selector_mismatch`;
- rate limit después de `next_retry_at`.
