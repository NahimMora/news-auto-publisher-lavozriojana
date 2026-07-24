# Arquitectura

Última actualización: 2026-07-23.

## Stack y límites

- Python 3.10+, Windows-first.
- `requests`, BeautifulSoup/lxml, Pillow, OpenAI SDK, boto3/botocore y psutil.
- `ffmpeg` y `ffprobe` son binarios externos requeridos para video.
- Persistencia local en JSON; no hay base de datos ni microservicios propios.
- Integraciones externas: sitios fuente, OpenAI, Cloudflare R2, CMS y Meta Graph API.
- Interfaz manual de Reels en HTTP local, restringida a loopback.

Las rutas operativas se resuelven con `utils/paths.py`. Producción usa por defecto
`data/`, `logs/`, `output/` y `FotosLVR/`; QA puede aislarlas con variables
`LVR_*_DIR`.

## Componentes

| Componente | Responsabilidad |
|---|---|
| `cli.py` | start/stop/status, diagnóstico, dry-run local, backup y restore |
| `run_24x7.py` | loop, señales, heartbeat, agregación de resultados |
| `run_all.py` | scrapers y reescritura como subetapas estructuradas |
| `scraping/base_*.py`, `scraping/runner.py` | contrato de fuente, parseo, persistencia cola-antes-historial |
| `openIA/rewrite_news.py` | cola durable, reescritura, clasificación, captions y fan-out web/meta |
| `utils/editorial_policy.py` | política explícita de fallbacks y sensibilidad |
| `pipeline/node_webapp/*` | validación editorial, medios R2, payload, contrato CMS y URL web |
| `utils/social_queue.py` | estados independientes de Facebook/Instagram |
| `meta/run_*.py`, `meta/*_client.py` | claims, Graph API, evidencia y backoff |
| `utils/file_manager.py` | locks, lectura estricta, atomicidad, backups, cuarentena y restore |
| `utils/stage_result.py` | contrato `success/no_work/degraded/failed` |
| `utils/heartbeat.py` | estado del supervisor y métricas de colas |
| `utils/queue_events.py` | trazabilidad terminal y de fallbacks |
| `utils/config.py` | validación y diagnóstico seguro |
| `video_reel_manager.py` | UI manual local y uploads controlados |

## Contrato de resultados

Toda etapa ejecutada por el supervisor produce:

```text
stage, status,
received, selected, processed, succeeded, failed, deferred, expired,
duration_seconds, error_type, error_code, next_retry_at, details, exit_code
```

| Estado | Semántica | Exit |
|---|---|---:|
| `success` | todo el trabajo seleccionado terminó con evidencia | 0 |
| `no_work` | ejecución sana sin elementos seleccionables | 0 |
| `degraded` | éxito parcial, rate limit o capacidad reducida | 2 |
| `failed` | fallo funcional sin resultado aceptable | 1 |

`0/N` con `N > 0` no puede ser `success`. El runner también rechaza un proceso que
sale 0 sin emitir resultado estructurado.

## Flujo end-to-end

```text
HTML fuente
  → capturada/validada
  → data/noticias_norewrite_*.json
  → data/rewrite_queue_state.json: pending → processing
  → reescrita/clasificada/caption
  ├→ data/noticias_web_pending.json
  └→ data/noticias_meta.json
       ↓
CMS + R2 ← web pending
  → data/noticias_web_publicadas.json
  → URL web sincronizada en meta/social
       ↓
data/noticias_sociales_pendientes.json
  ├→ Facebook → data/fb_posted.json
  └→ Instagram → data/ig_posted.json
       ↓
completed / failed / expired / dead_letter
  → data/queue_events.json
```

### Transiciones y recuperación

| Transición | Entrada → salida | Identidad | Sin trabajo / degradado / fallo | Recuperación y riesgo |
|---|---|---|---|---|
| capturada → validada | HTML → `ArticleScrapeResult` | URL canónica | página sana vacía=`no_work`; imagen ausente=`degraded`; HTTP/timeout/selectores=`failed` | retry en ciclo siguiente; no se historiza un fallo |
| validada → pre-IA | artículo → `noticias_norewrite_*.json` | hash de URL canónica | duplicado trazado; error de escritura=`failed` | cola se escribe antes del historial; operación idempotente |
| pre-IA → pending | staging → `rewrite_queue_state.json` | queue key/hash | vacío=`no_work`; estado corrupto=`failed` | durable primero, recién después vacía staging |
| pending → processing | cola durable | ID estable | sin pending=`no_work` | claim bajo lock; al reiniciar vuelve a pending |
| processing → reescrita | OpenAI/fallback → payload | mismo ID | fallback permitido=`degraded`; excepción retryable=`failed/deferred` | intentos limitados; luego dead-letter |
| reescrita → clasificada/caption | payload → campos editoriales | mismo ID | fallback sensible bloqueado=`failed` terminal | política y motivo en payload/eventos |
| clasificada → web/meta | durable → dos JSON | `web_queue_key` / `meta_queue_key` | duplicado idempotente; error de estado=`failed` | escribe salidas antes de completed; retry seguro |
| web pending → imagen | local/remota → R2 | digest/key | fallback de imagen=`degraded`; URL insegura/R2=`failed` | límites de tamaño, SSRF y retry R2 |
| imagen → web | payload → CMS/historial | queue key + external ID/URL | 429=`degraded`; 401=`failed`; parcial=`degraded` | conserva retryables; 409 sólo éxito con evidencia |
| web → URL sincronizada | respuesta CMS → meta/social | queue keys | falta de evidencia=`failed` | update multiarchivo bajo locks |
| meta → social | meta → cola social | dedup/canonical URL | ya presente=`no_work` | estados por plataforma, update atómico |
| social → API | pending → processing → evidencia | dedup key | rate=`degraded`; credencial=`failed` | claim antes de API; outcome ambiguo a dead-letter |
| API → completed | ID/URL → posted/social | external ID | sin evidencia=`failed` | sincroniza posted previo; evita doble publicación |
| expirado/descartado | activo → terminal/evento | misma identidad | cuenta como `expired` o terminal explícito | `queue_events.json` conserva motivo/payload |

Los timeouts y reintentos son configurables por integración. Los logs rotativos por
módulo incluyen contexto y aplican redacción central de secretos.

## Persistencia

`utils/file_manager.py` ofrece:

- lectura estricta con validación de tipo;
- `FileLock`/`MultiFileLock` interproceso;
- temporales únicos en el mismo directorio;
- flush, `fsync` y `os.replace`;
- `update_json` y `update_json_files` para read-modify-write;
- backup automático configurable y retención;
- cuarentena sin borrar el original corrupto;
- restauración validada.

La cola durable de reescritura usa `pending`, `processing`, `completed`, `failed`,
`expired` y `dead_letter`. La cola social mantiene esos estados por plataforma para
no asumir que el éxito de Facebook implica el de Instagram.

## Compatibilidad y migración

- Se conservan los nombres y listas JSON que consumía el sistema anterior.
- `rewrite_queue_state.json` se agrega como journal durable; `init_data.py` lo crea
  con buckets válidos.
- Entradas legacy completas en `noticias_meta.json` se copian idempotentemente a web y
  luego se normalizan.
- `utils/pipeline_resume.py` se eliminó porque no estaba conectado; la recuperación
  real vive en la cola durable.
- No se necesita migración destructiva ni base de datos.

## Seguridad

- Descargas controladas por usuario rechazan loopback, IPs privadas, link-local,
  credenciales embebidas y redirects a destinos no públicos.
- Uploads validan nombre, tamaño y firma/contenido.
- Paths manuales sólo pueden referir archivos propios dentro del directorio de uploads.
- La UI manual no inicia en interfaces externas.
- El render pasa argumentos a ffmpeg como lista, no como shell.
- Los secretos se redactan en logs y nunca aparecen en snapshots de configuración.

## Despliegue y rollback

No hay CI/CD ni staging externo dentro de este repositorio. El procedimiento de
backup, restore y rollback está en `docs/RUNBOOK.md`. Antes de habilitar un target
externo, `doctor` debe validar su alcance y se requiere un smoke test controlado fuera
de producción.
