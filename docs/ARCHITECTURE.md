# Arquitectura

Última actualización: 2026-07-26.

## Stack y límites

- Python 3.10+, Windows-first.
- `requests`, BeautifulSoup/lxml, Pillow, OpenAI SDK, boto3/botocore y psutil.
- `ffmpeg` y `ffprobe` son binarios externos requeridos para video; `yt-dlp` (declarado
  en `requirements.txt`) descarga el video fuente de YouTube/Instagram/TikTok/X/
  Facebook/Vimeo y otros sitios — scraping no oficial de cada plataforma, sujeto a
  requerir actualización cuando cambian sus reproductores.
- Persistencia local en JSON; no hay base de datos ni microservicios propios.
- Integraciones externas: sitios fuente, OpenAI, Cloudflare R2, CMS y Meta Graph API.
- Interfaz manual de Reels en HTTP local, restringida a loopback.

Las rutas operativas se resuelven con `utils/paths.py`. Producción usa por defecto
`data/`, `logs/`, `output/` y `FotosLVR/`; QA puede aislarlas con variables
`LVR_*_DIR`.

## Componentes

| Componente | Responsabilidad |
|---|---|
| `cli.py` | start/stop/status, doctor, preflight, canary, conciliación, alertas, backup y restore |
| `run_24x7.py` | loop, señales, modo progresivo, heartbeat, alertas y agregación |
| `run_all.py` | scrapers y reescritura como subetapas estructuradas |
| `scraping/base_*.py`, `scraping/runner.py` | contrato de fuente, parseo, persistencia cola-antes-historial |
| `openIA/rewrite_news.py` | cola durable, reescritura, clasificación, captions y fan-out web/meta |
| `utils/editorial_policy.py` | política explícita de fallbacks y sensibilidad |
| `pipeline/node_webapp/*` | validación editorial, medios R2, payload, contrato CMS y URL web |
| `utils/social_caption.py` | caption único compartido por Instagram y Facebook |
| `utils/social_queue.py` | estados independientes de Facebook/Instagram |
| `utils/editorial_router.py` | router determinístico automatic/candidate/suppressed por canal; gate y cap de tema para Instagram (opt-in vía `EDITORIAL_ROUTER_ENABLED`) |
| `utils/media_library.py` | biblioteca multimedia de diez días: ingesta de imágenes (hash, master, thumb), búsqueda unificada local (candidatas + publicadas + premium + assets) y cleanup seguro |
| `utils/premium_contract.py` | contrato versionado de publicaciones premium: validación, edición de slides (mover/duplicar/eliminar/cambiar tipo), validación de highlight_terms |
| `utils/premium_importer.py` | importa el paquete pegado de ChatGPT; nunca pierde el contenido pegado ni asigna imágenes en firme (sólo sugerencias) |
| `utils/premium_post_queue.py` | store único de paquetes premium (`data/premium_packages.json`); borradores recuperables aunque tengan errores de validación |
| `utils/premium_renderer.py` | renderer Pillow interino (mismo renderer para preview y publicación); la Fase 4 reemplaza el cuerpo por Remotion sin cambiar la firma pública |
| `utils/premium_publisher.py` | orquestador social-only: nunca crea artículo web ni llama al CMS; degraded/retry por canal; ambiguos no se reintentan solos |
| `meta/ig_client.py::post_premium_carousel_to_instagram` | carrusel premium (2-10 slides), dedup y estado propios (`data/premium_ig_posted.json`), mismo backoff de cuenta que el flujo automático |
| `meta/fb_client.py::post_premium_direct_media_to_facebook` | foto única o álbum multi-foto sin link, activado sólo con `publish_mode=direct_media` + `workflow=manual_premium` explícitos; backoff compartido con `fb_posted.json`, dedup propio (`data/premium_fb_posted.json`) |
| `utils/remotion_renderer.py` | wrapper de `npx remotion still`; detección de disponibilidad cacheada, copia de assets a `remotion/public/tmp/` y limpieza |
| `remotion/src/{PremiumSlide,AutomaticInstagramCard,FacebookOgCard}.tsx` | composiciones still de Remotion (Fase 4); paleta compartida sin dorado (`constants.ts`), highlight terms compartidos (`shared/HighlightedTitle.tsx`) |

`utils/premium_renderer.py::render_package_with_engine` es el punto de entrada real
para preview/publicación del Estudio Premium: resuelve el motor vía
`utils/remotion_renderer.py::resolve_engine("premium")`, intenta Remotion primero
(default de ese workflow), y cae a Pillow (`render_package_bytes`, sin cambios) si
Remotion no está disponible en modo `auto`. La política de motor es **por
workflow** (`AUTOMATIC_STATIC_RENDER_ENGINE`, `PREMIUM_STATIC_RENDER_ENGINE`,
`OG_STATIC_RENDER_ENGINE`, cada una con su propio default seguro) — no una única
variable global; `STATIC_RENDER_ENGINE` sigue existiendo sólo como override legacy
explícito. Ver `docs/DECISIONS.md`.
| `meta/run_*.py`, `meta/*_client.py` | claims, Graph API, evidencia y backoff |
| `utils/file_manager.py` | locks, lectura estricta, atomicidad, backups, cuarentena y restore |
| `utils/stage_result.py` | contrato `success/no_work/degraded/failed/blocked` |
| `utils/heartbeat.py` | estado del supervisor y métricas de colas |
| `utils/queue_events.py` | trazabilidad terminal y de fallbacks |
| `utils/config.py` | validación y diagnóstico seguro |
| `utils/deployment.py` | modos progresivos, kill switches, límites y fingerprint |
| `utils/preflight.py` | verificaciones read-only y prueba reversible de R2 |
| `utils/canary.py` | una publicación aislada, gated e idempotente |
| `utils/facebook_reconcile.py` | reporte conservador y decisiones explícitas |
| `utils/alerts.py` | detección, dedupe, outbox y entrega opcional |
| `video_reel_manager.py` | UI manual local y uploads controlados |
| `utils/video_renderer.py` | Descarga de video fuente (MP4 directo o yt-dlp: YouTube, Instagram, TikTok, X, Facebook, Vimeo y otros sitios vía extractor genérico) y composición ffmpeg del reel |

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
| `blocked` | faltó credencial, endpoint, entorno o autorización | 3 |

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

Un fallo de Meta registra en el log rotativo y, si termina en dead-letter, en
`queue_events.json` únicamente diagnóstico estructurado seguro: tipo interno,
HTTP/código/subcódigo/tipo del proveedor, retry y outcome. No persiste el cuerpo
arbitrario de la respuesta ni su mensaje, para evitar copiar tokens devueltos por un
tercero.

### Revisión editorial verificable

El enriquecedor conserva el resultado normalizado de cada intento. Una revisión
recibe los warnings exactos y el intento anterior, y registra qué campos cambiaron.
Sólo cambios en contenido, estructura o metadata editorial cuentan como materiales;
un cambio aislado del score autodeclarado no se considera corrección.

Al agotar seis intentos se conserva el último resultado únicamente cuando no contiene
warnings factuales, judiciales o de HTML. Se marca
`editorialFinalAttemptUsed=true`, se publica como `degraded` y se registra el
historial de revisión. Los bloqueos duros conservan la política de fallback segura.

### Publicación Facebook y preview

Facebook reutiliza exactamente el caption de Instagram y construye el mensaje con
título, caption y URL Web. Antes de llamar a Graph, el prewarm valida mediante GET
SSRF-safe que la página sea HTML pública y que `og:image` sea una imagen pública
descargable dentro del límite configurado. Un prewarm fallido es `degraded`,
`publication_outcome=not_published`; el claim queda recuperable.

### Línea de base de colas

`queue-cutover --keep-latest N` ordena identidades cross-channel mediante timestamps
durables de encolado. La operación multiarchivo conserva las últimas N, archiva el
resto con payload completo y transiciona estados sociales antiguos a `excluded` o
dead-letter si estaban en `processing`. No usa `fecha` ni fabrica evidencia externa.

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

Hay CI de validación, pero no despliegue automático ni staging externo. El
procedimiento de backup, restore y rollback está en `docs/RUNBOOK.md`.

### Control de canales

```text
PIPELINE_DEPLOYMENT_MODE
  → canales solicitados
  → intersección con kill switches individuales
  → máximo 1 por canal/ciclo
  → StageResult + heartbeat
```

`observe` ejecuta scraping y reescritura, pero no llama publicadores ni consume
permanentemente las colas de publicación. Cualquier contradicción entre modo y kill
switch falla antes del arranque.

### Preflight

```text
sources ─┐
openai ──┤
r2 ──────┤
cms ─────┼→ aggregate_preflight → success/degraded/failed/blocked
facebook ┤
instagram┤
filesystem
supervisor
```

Las fuentes se parsean en memoria. OpenAI usa un prompt mínimo sanitizado. CMS y Meta
son GET read-only. R2 crea un objeto único bajo `healthchecks/`, verifica lectura,
elimina y confirma ausencia. El filesystem opera sólo en un temporal del mismo
volumen.

### Canary

El canary no entra en las colas generales. `canary_runs.json` reserva cada canal
antes de la llamada. Si el proceso se corta con outcome desconocido, el estado queda
`ambiguous` y una repetición se niega a publicar. Los IDs y URLs externos son la
evidencia de completitud.

### Conciliación Facebook

El reporte combina cola, `fb_posted.json`, keys canónicas, estados y evidencia
externa. El título no es identidad. La aplicación exige un `report_id` vigente y
decisiones por elemento; no elimina entradas.

### Alertas

```text
snapshot/queue_events/quarantine
  → condiciones
  → dedupe + recovery
  → alert_outbox.json
  → webhook público opcional
```

El fallo del notificador queda diferenciado y no cambia el resultado del pipeline.
Un watchdog externo todavía es necesario para alertar si el proceso completo muere y
ya no puede ejecutar su propio detector.
