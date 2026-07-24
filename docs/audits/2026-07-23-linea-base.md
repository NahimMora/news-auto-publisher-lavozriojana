# Auditoría de confiabilidad LVR — línea de base 2026-07-23

## Alcance y resguardo

- Repositorio verificado mediante la aplicación conectada de GitHub:
  `NahimMora/news-auto-publisher-lavozriojana`.
- Rama principal remota: `main`.
- Commit inicial: `fbb83eac3cf3ce399dac5a9d778f81a1957d7c2a`.
- Rama de trabajo: `reliability/baseline-2026-07-23`.
- Checkout inicial: limpio y sincronizado con `origin/main`.
- No se iniciaron publicadores ni se hicieron llamadas deliberadas a OpenAI, Meta,
  Cloudflare R2 o el CMS.
- Los tests se ejecutaron con un virtualenv temporal y mocks. La primera ejecución de
  los tests heredados escribió líneas de diagnóstico en los logs locales porque el
  código no permitía aislar `logs/`; esto queda registrado como LVR-020 y no se borró
  historial para ocultarlo.
- `python cli.py status` se ejecutó como diagnóstico, pero el comando resultó no ser de
  solo lectura: eliminó un PID stale. Se restauró inmediatamente el valor exacto
  observado (`42272`) y no se volvió a operar sobre `data/` real.

## Evidencia inicial

```text
GitHub App: acceso real, permisos pull/push/maintain/admin
remote: https://github.com/NahimMora/news-auto-publisher-lavozriojana.git
branch: main
commit: fbb83eac3cf3ce399dac5a9d778f81a1957d7c2a
python: 3.10.0
pip install -r requirements.txt: OK
pip check: No broken requirements found
python -m compileall -q -f .: OK
python -m unittest discover tests -v: 35 tests, OK
```

Advertencias observadas:

- Pillow informa que `Image.Image.getdata` será removido en Pillow 14.
- `psutil` es importado dinámicamente por `cli.py`, pero no está declarado.
- El CLI observó un supervisor caído, con último ciclo del 2026-07-13.
- El CLI presentó Facebook como `OK` para un resultado `4/10`.

## Separación de evidencia

### Hechos comprobados

- `load_json` transforma JSON inválido o errores de lectura en el valor por defecto.
- `save_json` usa un nombre temporal fijo, no hace `fsync` y no bloquea escritores.
- `rewrite_news.main` vacía cada staging antes de reescribir o transferir sus noticias.
- `main_nuevarioja.main` guarda el histórico antes de guardar la cola unificada.
- `run_all.py`, `run_fb.py`, `run_ig.py` y `pipeline/publish_web.py` terminan con código
  cero aunque el trabajo funcional falle total o parcialmente.
- `cli.py status` infiere salud buscando palabras en texto y modifica el PID stale.
- `PIPELINE_24X7_STALE_SECONDS` está declarado pero no se usa.
- No existe un heartbeat persistente.
- Los clientes de Facebook, Instagram y el token manager crean loggers sin archivo.
- Scrapers convierten errores HTTP/red en `[]`, indistinguibles de una fuente sana sin
  artículos para sus consumidores.
- Expiraciones sociales se marcan como `done` y luego se compactan sin archivo terminal
  que preserve motivo y payload.
- El enriquecimiento editorial y captions usan fallback automáticamente, sin una
  política de publicación configurable ni métrica uniforme.
- La mini interfaz acepta `--host` arbitrario, no autentica y valida uploads por
  extensión/tamaño, no por contenido.
- Varias descargas de URL no bloquean loopback, redes privadas ni redirecciones a
  destinos internos.
- `pipeline_resume_state.json` tiene utilidades, pero el pipeline automático no las usa.
- Los backups existentes son manuales y no hay restauración validada en código.

### Inferencias

- Un corte después de vaciar staging y antes de terminar el lote puede perder noticias.
- Dos procesos que hagan read-modify-write sobre la misma cola pueden eliminar cambios
  entre sí.
- Una fuente caída puede producir un falso `no_work` y un ciclo global falsamente sano.
- La falta de logs de cliente explica parte de la imposibilidad de diagnosticar el
  backlog de Facebook, pero no demuestra la causa externa original.

### Información desconocida

- Causa externa exacta de los fallos históricos de Facebook.
- Estado real actual de tokens, cuentas de Meta, bucket R2 y contrato desplegado del
  CMS; no se validarán con secretos productivos.
- Estructura HTML actual de terceros en producción; se cubrirá con fixtures y quedará
  una verificación externa segura separada.
- Capacidad y espacio libre reales del host productivo.

### Problemas documentados pero no reproducidos

- Fallo actual de Meta/Cloudflare/CMS con credenciales reales: bloqueado por entorno y
  por la prohibición de usar producción.
- Exactitud editorial de publicaciones reales: no se ensaya contra cuentas ni CMS.

### Problemas nuevos encontrados

- Diagnóstico `status` mutante.
- Falso `OK` por análisis de texto.
- Pérdida por orden histórico/cola en Nueva Rioja.
- SSRF en herramientas manuales y descargas de medios.
- Exposición insegura posible del Reel Manager.
- Tests heredados no aislaban logs.
- Publicación web puede darse por completada sin URL pública sincronizable.

## Matriz inicial de hallazgos

### LVR-001 — Pérdida de staging durante reescritura

- Severidad: crítica.
- Archivo y función: `openIA/rewrite_news.py::main`.
- Síntoma: las entradas se reemplazan por `[]` antes de procesar.
- Causa raíz: no existe transferencia durable Pending → Processing.
- Reproducción: cargar diez elementos, interrumpir después del tercero y reiniciar.
- Impacto: hasta siete noticias pueden desaparecer.
- Solución propuesta: cola durable con claim, recuperación e idempotencia.
- Test: interrupción 3/10, reinicio y diez completadas exactamente una vez.
- Estado inicial: abierto.

### LVR-002 — JSON corrupto interpretado como cola vacía

- Severidad: alta.
- Archivo y función: `utils/file_manager.py::load_json`.
- Síntoma: `JSONDecodeError` retorna el default.
- Causa raíz: captura silenciosa de errores de parseo/IO.
- Reproducción: truncar una copia temporal de una cola y leerla.
- Impacto: falso `no_work` y posterior sobrescritura de datos recuperables.
- Solución propuesta: error explícito, copia en cuarentena y bloqueo de sobrescritura.
- Test: JSON truncado preservado y `JsonCorruptionError`.
- Estado inicial: abierto.

### LVR-003 — Actualizaciones concurrentes perdidas

- Severidad: alta.
- Archivo y función: `utils/file_manager.py::save_json` y consumidores.
- Síntoma: read-modify-write sin lock; temporal compartido `path.tmp`.
- Causa raíz: ausencia de exclusión mutua y operación update atómica.
- Reproducción: dos escritores agregan elementos simultáneamente.
- Impacto: pérdida de colas, historiales o estados publicados.
- Solución propuesta: lock interproceso, temporales únicos, `fsync`, `os.replace` y
  `update_json`.
- Test: dos escritores concurrentes sin pérdida.
- Estado inicial: abierto.

### LVR-004 — Falsos positivos de salud y códigos de salida

- Severidad: alta.
- Archivo y función: `run_all.py::main`, `meta/run_fb.py::main`,
  `meta/run_ig.py::main`, `pipeline/publish_web.py::main`, `cli.py::cmd_status`.
- Síntoma: `0/N`, credenciales inválidas y target desconocido terminan en cero; el CLI
  busca palabras como `publicadas`.
- Causa raíz: no hay contrato de resultado estructurado.
- Reproducción: salida histórica `Facebook: 4/10 publicadas` mostrada como `OK`.
- Impacto: supervisor y operador creen sano un sistema degradado.
- Solución propuesta: `success/no_work/degraded/failed`, contadores y exit codes.
- Test: matriz completa de estados, incluido `0/N`.
- Estado inicial: abierto.

### LVR-005 — Heartbeat/stale no implementados

- Severidad: alta.
- Archivo y función: `run_24x7.py`, `cli.py`.
- Síntoma: heartbeat sólo controla el `sleep`; stale declarado no se usa.
- Causa raíz: falta de estado persistente del supervisor.
- Reproducción: PID stale y log antiguo sin evaluación de antigüedad.
- Impacto: caída prolongada sin señal verificable.
- Solución propuesta: heartbeat atómico con ciclo, etapa, antigüedad y colas.
- Test: heartbeat fresco, stale y PID ajeno.
- Estado inicial: abierto.

### LVR-006 — Errores de integraciones sin archivo de log

- Severidad: alta.
- Archivo y función: `meta/fb_client.py`, `meta/ig_client.py`,
  `meta/facebook_token_manager.py` y loggers de scraping.
- Síntoma: `setup_logger` sin segundo argumento.
- Causa raíz: logging sólo a consola bajo supervisor con `DEVNULL`.
- Reproducción: inspección y logs históricos sin detalle del cliente.
- Impacto: fallos externos no diagnosticables.
- Solución propuesta: archivos rotativos y redacción central de secretos.
- Test: handler rotativo presente y secretos redactados.
- Estado inicial: abierto.

### LVR-007 — Scraper caído indistinguible de fuente sin noticias

- Severidad: alta.
- Archivo y función: `scraping/base_*.py::scrap_links`, entrypoints `main_*.py`.
- Síntoma: errores HTTP/red retornan `[]`.
- Causa raíz: contrato de retorno ambiguo.
- Reproducción: mock de timeout/HTTP 500.
- Impacto: falso `no_work` y falso positivo del ciclo.
- Solución propuesta: resultado de fuente explícito y fallo propagado.
- Test: vacío sano versus HTTP error versus timeout.
- Estado inicial: abierto.

### LVR-008 — Dependencia `psutil` ausente

- Severidad: media.
- Archivo y función: `cli.py::_is_running/cmd_stop`.
- Síntoma: import dinámico no declarado.
- Causa raíz: `requirements.txt` incompleto.
- Reproducción: instalación limpia basada sólo en requirements.
- Impacto: fallback puede aceptar un PID ajeno y `stop` pierde control de hijos.
- Solución propuesta: declarar `psutil`.
- Test: import limpio y test de identidad de proceso.
- Estado inicial: abierto.

### LVR-009 — Expiraciones y descartes sin trazabilidad

- Severidad: alta.
- Archivo y función: `utils/social_queue.py::get_pending/compact_queue`,
  `openIA/rewrite_news.py::_prune_queue`.
- Síntoma: elementos se eliminan o se marcan `done` sin terminal state durable.
- Causa raíz: listas activas usadas también como historial.
- Reproducción: elemento con TTL vencido.
- Impacto: imposibilidad de explicar pérdidas operativas.
- Solución propuesta: eventos y estados Expired/Failed/Dead-letter.
- Test: expirado preservado con motivo y timestamps.
- Estado inicial: abierto.

### LVR-010 — Publicación web sin evidencia pública suficiente

- Severidad: alta.
- Archivo y función: `pipeline/node_webapp/publisher.py::publish_one_detailed`.
- Síntoma: `ok:true` puede remover la noticia aunque no haya ID ni URL/slug.
- Causa raíz: éxito HTTP confundido con publicación sincronizable.
- Reproducción: mock 201 `{"ok": true}`.
- Impacto: web marcada completa y redes bloqueadas por falta de enlace.
- Solución propuesta: exigir ID o URL verificable según contrato y conservar pending.
- Test: respuesta sin evidencia no completa la cola.
- Estado inicial: abierto.

### LVR-011 — Política de fallbacks implícita

- Severidad: alta.
- Archivo y función: `rewrite_news.py`, `caption_generator.py`, `classifier.py`,
  `pipeline/node_webapp/editorial.py`.
- Síntoma: fallbacks se publican sin política por categoría o registro uniforme.
- Causa raíz: fallback mezclado con retorno exitoso.
- Reproducción: OpenAI no configurado o error simulado.
- Impacto: contenido degradado puede publicarse silenciosamente.
- Solución propuesta: política configurable, registro y bloqueo por sensibilidad.
- Test: fallback permitido/bloqueado, policial/judicial/menores/breaking.
- Estado inicial: abierto.

### LVR-012 — Deriva de configuración

- Severidad: media.
- Archivo y función: `.env.example` y lecturas `os.getenv`.
- Síntoma: variables declaradas sin efecto, activas no declaradas y valores sin validar.
- Causa raíz: no existe esquema central.
- Reproducción: inventario AST y búsqueda de nombres dinámicos.
- Impacto: parámetros aparentan funcionar; fallos tardíos.
- Solución propuesta: validador y comando `doctor` sin publicación.
- Test: booleanos, números, URLs, rutas, rangos y placeholders.
- Estado inicial: abierto.

### LVR-013 — SSRF en URLs provistas manualmente

- Severidad: alta.
- Archivo y función: `openIA/reel_generator.py::scrape_url`,
  `pipeline/custom_post.py::fetch_image_from_url`, `media.py::_download_remote_image`,
  descargadores de imagen/video.
- Síntoma: acepta destinos HTTP arbitrarios y redirecciones.
- Causa raíz: sólo se valida esquema/host textual.
- Reproducción: URL a loopback o IP privada.
- Impacto: lectura/sondeo de servicios internos desde el host.
- Solución propuesta: validador DNS/IP y revalidación de redirecciones.
- Test: loopback, RFC1918, link-local, IPv6 privada y redirect.
- Estado inicial: abierto.

### LVR-014 — Reel Manager puede exponerse inseguro

- Severidad: alta.
- Archivo y función: `video_reel_manager.py::main/VideoReelHandler`.
- Síntoma: `--host 0.0.0.0`, sin autenticación y CORS `*`.
- Causa raíz: no hay guard de loopback/origen.
- Reproducción: iniciar con host externo.
- Impacto: terceros podrían cargar archivos o disparar operaciones reales.
- Solución propuesta: rechazar bind no loopback y limitar orígenes.
- Test: localhost aceptado, bind externo rechazado.
- Estado inicial: abierto.

### LVR-015 — Upload validado sólo por extensión

- Severidad: alta.
- Archivo y función: `video_reel_manager.py::_handle_upload`.
- Síntoma: bytes arbitrarios con extensión permitida se guardan.
- Causa raíz: no hay inspección de contenido.
- Reproducción: texto renombrado a `.jpg`/`.mp4`.
- Impacto: archivos no confiables y fallos posteriores.
- Solución propuesta: Pillow para imágenes y firmas/ffprobe razonable para video.
- Test: imagen válida, corrupta, extensión falsa, tamaño y traversal.
- Estado inicial: abierto.

### LVR-016 — Backup/restauración no operacional

- Severidad: media.
- Archivo y función: `utils/file_manager.py::backup_json`.
- Síntoma: función manual sin scheduling, retención ni restore.
- Causa raíz: backup no integrado a escrituras.
- Reproducción: inspección de tres snapshots históricos.
- Impacto: recuperación incierta.
- Solución propuesta: backup configurable, retención y restore validado.
- Test: backup previo y restauración.
- Estado inicial: abierto.

### LVR-017 — Estado de reanudación no integrado

- Severidad: media.
- Archivo y función: `utils/pipeline_resume.py`.
- Síntoma: ningún entrypoint automático llama sus funciones.
- Causa raíz: implementación aislada.
- Reproducción: búsqueda de referencias.
- Impacto: falsa expectativa de recovery.
- Solución propuesta: reemplazar por cola durable integrada o eliminar el módulo.
- Test: interrupción/reinicio real del flujo.
- Estado inicial: abierto.

### LVR-018 — Nueva Rioja puede historizar antes de encolar

- Severidad: alta.
- Archivo y función: `main_nuevarioja.py::main`.
- Síntoma: guarda histórico por sección antes de `OUTPUT`.
- Causa raíz: orden no transaccional entre archivos.
- Reproducción: fallo al guardar la cola unificada.
- Impacto: la URL ya no se captura en el siguiente ciclo y la noticia se pierde.
- Solución propuesta: cola primero, histórico después, con deduplicación idempotente.
- Test: fallo entre ambas escrituras y recuperación.
- Estado inicial: abierto.

### LVR-019 — Fallback inseguro del token de Facebook

- Severidad: media.
- Archivo y función: `meta/facebook_token_manager.py::get_page_token`.
- Síntoma: ante cualquier excepción de red usa silenciosamente el token del `.env`.
- Causa raíz: fallback no distingue red, respuesta inválida o credencial.
- Reproducción: mock de timeout de `/me/accounts`.
- Impacto: reintentos con token incorrecto y diagnóstico confuso.
- Solución propuesta: error tipado/degradado; fallback sólo si se configuró
  explícitamente.
- Test: token inválido, red caída y fallback opt-in.
- Estado inicial: abierto.

### LVR-020 — Tests no aislados de logs operativos

- Severidad: media.
- Archivo y función: `utils/logging_setup.py` y suite heredada.
- Síntoma: tests del virtualenv escribieron `logs/publish_web.log` y
  `logs/rewrite_news.log`.
- Causa raíz: `LOGS_DIR` fijo al importar.
- Reproducción: ejecutar suite y observar timestamps.
- Impacto: evidencia operativa contaminada por QA.
- Solución propuesta: directorios configurables y entorno temporal obligatorio.
- Test: suite con `LVR_LOGS_DIR` temporal.
- Estado inicial: abierto.

### LVR-021 — Respuestas externas insuficientemente tipadas

- Severidad: media.
- Archivo y función: clientes CMS/Meta/R2.
- Síntoma: varios fallos retornan `False/None` sin código, retry-after o error_type.
- Causa raíz: contratos booleanos.
- Reproducción: mocks 400/409/429/500/no-JSON.
- Impacto: supervisor no distingue credencial, rate limit y fallo transitorio.
- Solución propuesta: resultados tipados y contract tests.
- Test: matriz HTTP requerida.
- Estado inicial: abierto.

### LVR-022 — Cobertura automatizada insuficiente

- Severidad: media.
- Archivo y función: `tests/`.
- Síntoma: 35 tests concentrados en un archivo; sin supervisor, CLI, fixtures de
  scrapers, recuperación ni concurrencia.
- Causa raíz: QA predominantemente manual.
- Reproducción: inventario de tests.
- Impacto: regresiones de confiabilidad no detectadas.
- Solución propuesta: pirámide mínima y E2E local.
- Test: suite ampliada y ejecución limpia.
- Estado inicial: abierto.

## Mapa end-to-end inicial

| Transición | Entrada | Salida | Identidad | Riesgo inicial |
|---|---|---|---|---|
| capturada → validada | HTML remoto | `noticia` dict | URL canónica | caída se confunde con vacío |
| validada → pre-IA | scraper | `noticias_norewrite_*.json` | URL/hash | carreras; orden cola/histórico |
| pre-IA → processing | staging | inexistente | URL/hash | LVR-001: se vacía antes |
| processing → reescrita | OpenAI | dict mutado | URL/hash | fallback implícito |
| reescrita → clasificada | OpenAI | `seccion` | URL/hash | `Sociedad` silencioso |
| clasificada → web/meta | dicts | dos JSON | queue key | no transacción multiarchivo |
| meta → social | `noticias_meta.json` | cola social | dedup key | carreras y descarte similar |
| web pending → imagen | archivo/URL | R2 | digest | SSRF/R2/OG fallback |
| imagen → web | payload | CMS + history | externalId | éxito sin ID/URL |
| web → URL sincronizada | respuesta CMS | meta/social | queue key | puede faltar URL |
| social → Facebook | cola + URL web | Graph + state | dedup key | booleano, logs perdidos |
| social → Instagram | cola + imagen | Graph + state | dedup key | rate limit código cero |
| canales → completada | flags `*_done` | compactación | dedup key | expirado/descartado invisible |

Estados iniciales:

- Éxito: inferido por booleano o texto.
- Sin trabajo: retorno normal sin estructura.
- Degradado: no representado uniformemente.
- Fallido: a menudo sólo un log; varios entrypoints salen con cero.
- Reintentos/timeouts: parciales y definidos por módulo.
- Recuperación: dedup parcial, sin processing durable.

Este documento se actualizará con causa definitiva, corrección, archivos, tests,
evidencia y estado final de cada LVR.

## Hallazgos nuevos durante la corrección

### LVR-023 — Deduplicación cruzada por boilerplate común

- Severidad: alta.
- Archivo y función: `utils/news_dedup.py::duplicate_reason`.
- Síntoma: dos títulos diferentes se consideraban duplicados si compartían un extracto
  genérico de fuente/crédito.
- Causa raíz: el cuerpo tenía el mismo peso aunque ambas noticias tuvieran título.
- Reproducción: dos payloads con títulos distintos y boilerplate idéntico.
- Impacto: descarte permanente de una noticia válida.
- Solución: priorizar títulos cuando ambos existen.
- Test: `test_shared_boilerplate_excerpt_does_not_merge_distinct_titles`.
- Estado final: **corregido**.

### LVR-024 — Ícono social ausente derribaba el render

- Severidad: media.
- Archivo y función: `layout/image_generator.py`.
- Síntoma: un asset de ícono inexistente/dañado abortaba la imagen.
- Causa raíz: carga no tolerante de un elemento decorativo.
- Reproducción: paths de ícono inexistentes.
- Impacto: nota retenida por un asset no esencial.
- Solución: omitir el ícono con warning y conservar el render.
- Test: `LayoutTests.test_instagram_and_facebook_dimensions_with_long_or_empty_title`.
- Estado final: **corregido**.

### LVR-025 — Fallo al limpiar flags editoriales quedaba olvidado

- Severidad: alta.
- Archivo y función:
  `pipeline/node_webapp/editorial_flags.py::reconcile_after_publish`.
- Síntoma: si fallaba el PATCH del breaking/featured anterior, el estado local avanzaba
  sin registrar conflicto.
- Causa raíz: clear y registro no eran una transición conciliable.
- Reproducción: PATCH anterior falla y publicación nueva se confirma.
- Impacto: más de un destacado activo y falso éxito editorial.
- Solución: serializar y persistir `reconciliation_required`; resultado degradado.
- Test: `EditorialFlagContractTests.test_failed_clear_is_persisted_for_reconciliation`.
- Estado final: **mitigado**; conciliación externa manual.

### LVR-026 — Dry-run manual fabricaba éxito

- Severidad: alta.
- Archivo y función: `pipeline/custom_post.py`.
- Síntoma: podía retornar canales exitosos/URL ficticia y registrar una publicación.
- Causa raíz: simulación mezclada con semántica de evidencia.
- Reproducción: `CUSTOM_POST_DRY_RUN=true`.
- Impacto: historial y operador creen que hubo publicación.
- Solución: devolver plan/validación, nunca evidencia ni estado completado.
- Test: `test_manual_dry_run_never_returns_fake_publication_success`.
- Estado final: **corregido**.

### LVR-027 — Upload local podía escapar o borrarse después del render

- Severidad: alta.
- Archivo y función: `video_reel_manager.py`, `utils/video_renderer.py`.
- Síntoma: paths y cleanup no distinguían upload propio de descarga temporal.
- Causa raíz: confianza en strings de ruta y cleanup amplio.
- Reproducción: nombre con traversal o video subido usado como fuente.
- Impacto: lectura/borrado no autorizado o pérdida del upload.
- Solución: IDs, confinamiento al directorio propio y cleanup sólo de `_src_`.
- Test: `tests.test_security_controls.ManualInterfaceSecurityTests`.
- Estado final: **corregido**.

### LVR-028 — Canonicalización no unificaba barra antes del query

- Severidad: media.
- Archivo y función: `utils/url_normalization.py::canonical_url`.
- Síntoma: `/nota/?a=1` y `/nota?a=1` tenían identidades distintas.
- Causa raíz: el slash se quitaba después de reconstruir la URL.
- Reproducción: misma URL con barra antes de query.
- Impacto: duplicado posible y dedup inconsistente.
- Solución: normalizar path antes de reconstruir.
- Test:
  `UrlNormalizationTests.test_scheme_host_query_order_fragment_and_trailing_slash`.
- Estado final: **corregido**.

### LVR-029 — Bootstrap creaba cola durable con tipos inválidos

- Severidad: alta.
- Archivo y función: `init_data.py::FILES`.
- Síntoma: `processing` y `completed` nacían como objetos, no listas.
- Causa raíz: bootstrap desalineado con `DurableQueue`.
- Reproducción: `init_data.py` nuevo seguido por `DurableQueue.snapshot()`.
- Impacto: instalación limpia fallaba al primer rewrite.
- Solución: seis buckets como listas y nombre de cola.
- Test: `BootstrapTests.test_init_data_creates_a_valid_durable_rewrite_queue`.
- Estado final: **corregido**.

### LVR-030 — Contención de lock en Windows podía verse como permiso denegado

- Severidad: alta.
- Archivo y función: `utils/file_manager.py::FileLock.acquire`.
- Síntoma: bajo carga, Windows devolvió `PermissionError` en vez de
  `FileExistsError` para un lock ya abierto.
- Causa raíz: se asumía una traducción POSIX uniforme de `O_EXCL`.
- Reproducción: 100 updates con ocho workers en el virtualenv limpio.
- Impacto: una actualización concurrente fallaba aunque el filesystem fuera escribible.
- Solución: tratar `PermissionError` como contención sólo cuando el lock existe; un
  permiso real sigue siendo error explícito.
- Test: test concurrente ejecutado cinco veces seguidas y suite limpia.
- Estado final: **corregido**.

### LVR-031 — Instagram ignoraba la política de fallback si R2 no estaba configurado

- Severidad: alta.
- Archivo y función: `meta/ig_client.py::_prepare_image`.
- Síntoma: sin R2, se usaba la imagen original aunque
  `IG_ALLOW_ORIGINAL_IMAGE_FALLBACK=false`.
- Causa raíz: el flag sólo se evaluaba cuando R2 fallaba después de estar configurado.
- Reproducción: R2 ausente, URL original presente y flag deshabilitado.
- Impacto: publicación con fallback expresamente prohibido.
- Solución: fallo `missing_r2_configuration`; uso de original sólo con opt-in. `doctor`
  exige R2 cuando Instagram está activo sin ese opt-in.
- Test: `test_missing_r2_does_not_silently_use_original_image` y validación de config.
- Estado final: **corregido**.

### LVR-032 — Lock válido podía eliminarse sólo por antigüedad

- Severidad: alta.
- Archivo y función: `utils/file_manager.py::FileLock.acquire`.
- Síntoma: un lock con más de `JSON_LOCK_STALE_SECONDS` se borraba sin comprobar owner.
- Causa raíz: stale se infería exclusivamente del mtime.
- Reproducción: lock viejo cuyo PID corresponde al proceso vivo actual.
- Impacto: dos writers podían entrar simultáneamente durante una operación larga.
- Solución: comprobar PID y tiempo de creación del proceso; retirar sólo owner muerto,
  PID reutilizado o metadata inválida.
- Test: `test_old_lock_owned_by_live_process_is_not_stolen` y
  `test_old_lock_from_dead_process_is_recovered`.
- Estado final: **corregido**.

### LVR-033 — Fallo parcial de MultiFileLock dejaba locks huérfanos

- Severidad: alta.
- Archivo y función: `utils/file_manager.py::MultiFileLock.__enter__`.
- Síntoma: si el segundo lock fallaba, el primero no se liberaba.
- Causa raíz: `ExitStack` no se cerraba durante una excepción de `__enter__`.
- Reproducción: primer path libre, segundo con lock vivo y timeout corto.
- Impacto: bloqueo posterior de colas y posible indisponibilidad hasta stale.
- Solución: cerrar el stack en la ruta de excepción.
- Test: `test_multifile_partial_acquire_releases_previous_locks`.
- Estado final: **corregido**.

### LVR-034 — Fallo al escribir metadata dejaba un lock huérfano

- Severidad: alta.
- Archivo y función: `utils/file_manager.py::FileLock.acquire`.
- Síntoma: si `os.write`/`fsync` fallaba después de crear el lock, el archivo quedaba.
- Causa raíz: la ruta de error cerraba el descriptor pero no limpiaba ownership.
- Reproducción: mock de `os.write` con error de disco.
- Impacto: cola bloqueada hasta recuperación stale.
- Solución: cerrar descriptor y borrar el lock antes de propagar `JsonWriteError`.
- Test: `test_lock_metadata_write_failure_does_not_leave_orphan`.
- Estado final: **corregido**.

### LVR-035 — Texto persistido podía inyectar HTML en la UI manual

- Severidad: media.
- Archivo y función: HTML de `video_reel_manager.py::renderList/renderCustomList` e
  `instagram_layout_designer.py::draw`.
- Síntoma: títulos, secciones y URLs se interpolaban con `innerHTML`.
- Causa raíz: templates de strings con datos persistidos no escapados.
- Reproducción: título que contiene una etiqueta HTML.
- Impacto: ejecución de markup/script al abrir la UI local.
- Solución: crear nodos DOM y asignar sólo con `textContent`.
- Test: `test_manual_ui_renders_persisted_text_with_text_content`.
- Estado final: **corregido**.

### LVR-036 — DNS rebinding/cross-origin contra la UI loopback

- Severidad: alta.
- Archivo y función: `video_reel_manager.py::VideoReelHandler`.
- Síntoma: el bind era loopback pero no se validaban `Host` ni `Origin`.
- Causa raíz: se asumía que loopback por sí solo autenticaba al navegador.
- Reproducción: request con Host u Origin de un dominio atacante.
- Impacto: un sitio externo podía intentar alcanzar endpoints locales con capacidad
  de upload/publicación.
- Solución: exigir Host y Origin loopback, agregar CSP/frame protection y restringir
  los nombres servidos desde uploads.
- Test: `test_dns_rebinding_and_cross_origin_requests_are_rejected`.
- Estado final: **corregido**.

### LVR-037 — Cleanup R2 reportaba éxito sin verificarlo

- Severidad: media.
- Archivo y función: `utils/r2_storage.py::delete`,
  `video_reel_manager.py::_publish_background`.
- Síntoma: se mostraba “Video eliminado” aunque `delete_object` fallara.
- Causa raíz: el wrapper descartaba `OperationResult`.
- Reproducción: mock `ClientError` al borrar el temporal.
- Impacto: objeto temporal huérfano y falso positivo operativo.
- Solución: propagar resultado, registrar `cleanup_error` y mensaje real.
- Test: `test_delete_failure_is_visible_and_retryable`.
- Estado final: **corregido**.

### LVR-038 — Publicación manual parcial se mostraba como éxito

- Severidad: alta.
- Archivo y función: `pipeline/custom_post.py::publish_custom_post` y polling de
  `video_reel_manager.py`.
- Síntoma: web exitosa, o una sola red exitosa, pintaba el job como OK.
- Causa raíz: la UI usaba booleanos con OR y no un status agregado.
- Reproducción: Instagram éxito y Facebook credencial inválida.
- Impacto: operador cree completados tres canales.
- Solución: resultados detallados, `degraded` para cualquier parcial y verde sólo para
  `status=success`.
- Test: `test_manual_partial_publication_is_degraded`.
- Estado final: **corregido**.

### LVR-039 — URL web sin post ID ocultaba falta de tracking editorial

- Severidad: alta.
- Archivo y función: `pipeline/node_webapp/publisher.py::publish_one_detailed`.
- Síntoma: una nota featured/breaking con URL pero sin ID se reportaba como éxito
  completo, aunque no podía rotar flags.
- Causa raíz: la degradación sólo contemplaba fallo de PATCH con ID presente.
- Reproducción: respuesta CMS con URL pública, sin ID, y featured activo.
- Impacto: flags duplicados o no conciliables y falso positivo.
- Solución: conservar evidencia de publicación pero marcar `degraded`, registrar
  evento y propagarlo al flujo manual.
- Test:
  `test_public_url_without_post_id_is_degraded_when_flags_need_tracking`.
- Estado final: **mitigado**; requiere ID del CMS para reparación automática.

### LVR-040 — Descarga de imágenes de scraper permitía destinos privados

- Severidad: alta.
- Archivo y función: `scraping/base_tiempopopular.py::_download_image` y
  `scraping/base_nuevarioja.py::_download_image`.
- Síntoma: el valor remoto de `og:image` se descargaba con `requests.get` sin
  validar destino ni redirects.
- Causa raíz: el cliente HTTP seguro ya existía, pero no estaba conectado a los
  scrapers.
- Reproducción: imagen `http://169.254.169.254/latest/meta-data`.
- Impacto: SSRF desde una fuente comprometida hacia servicios locales/link-local.
- Solución: `safe_get`, validación DNS/IP y redirects antes de la conexión.
- Test: `test_scrapers_do_not_fetch_private_image_urls`.
- Estado final: **corregido**.

### LVR-041 — Test del dry-run no estaba aislado

- Severidad: baja.
- Archivo y función:
  `tests/test_supervisor_cli.py::test_run_once_dry_run_executes_only_local_e2e_suite`.
- Síntoma: la suite limpia terminó 146/147 por un `AttributeError`.
- Causa raíz: la aserción referenciaba `self.data`, atributo de otra fixture.
- Reproducción: `python -m unittest discover tests`.
- Impacto: gate final rojo pese a que el comportamiento probado era correcto.
- Solución: comparar con el directorio temporal propio de la clase.
- Test: segunda ejecución completa de 147 casos.
- Estado final: **corregido**.

### LVR-042 — Render usaba una API de Pillow deprecada

- Severidad: baja.
- Archivo y función: `layout/image_generator.py::_svg_icon` y helper equivalente de
  `utils/video_renderer.py`.
- Síntoma: `DeprecationWarning` en la suite; `getdata` será removido en Pillow 14.
- Causa raíz: cálculo del mínimo alfa mediante una API con retiro anunciado.
- Reproducción: tests de layout con la versión instalada de Pillow.
- Impacto: incompatibilidad futura del render.
- Solución: usar `getextrema()[0]`.
- Test: tests de layout con `-W error::DeprecationWarning`.
- Estado final: **corregido**.

## Mapa end-to-end final

La definición completa de transición, input/output, identidad, estados, timeout,
reintentos, logs y recuperación está en `docs/ARCHITECTURE.md`.

| Riesgo | Tratamiento comprobado |
|---|---|
| pérdida antes de reescritura | transferencia durable antes de vaciar staging |
| pérdida cola/histórico scraper | salida antes de historizar |
| sobrescritura concurrente | locks + update atómico |
| JSON truncado leído vacío | excepción + cuarentena |
| doble rewrite tras corte | ID estable + completed idempotente |
| doble social por outcome ambiguo | processing a dead-letter |
| éxito web sin publicación | exigir ID/URL/slug |
| 0/N falso sano | failed y exit 1 |
| rate limit | degraded, deferred y `next_retry_at` |
| expirado invisible | estado terminal + `queue_events.json` |
| fallback no deseado | política sensible + dead-letter |
| supervisor falso sano | heartbeat, stale y StageResult |

Éxito requiere evidencia durable; ausencia sana de trabajo es `no_work`;
parcial/rate limit es `degraded`; credencial, contrato, corrupción o fuente
inaccesible es `failed`. La recuperación automática sólo ocurre cuando no hay un
outcome externo ambiguo.

## Matriz final de hallazgos

| ID | Sev. | Causa y corrección | Archivos principales | Evidencia / test | Estado |
|---|---|---|---|---|---|
| LVR-001 | crítica | clear-before-transfer → cola durable | rewrite, durable queue | interrupción 3/10 | corregido |
| LVR-002 | alta | parseo silencioso → cuarentena/error | file manager | JSON truncado | corregido |
| LVR-003 | alta | RMW sin lock → locks/update | file manager | 100 updates | corregido |
| LVR-004 | alta | booleanos/texto → StageResult | runners, CLI | estados/exit/0-N | corregido |
| LVR-005 | alta | sin heartbeat → age/colas/stale | supervisor, CLI | fresh/stale | corregido |
| LVR-006 | alta | consola DEVNULL → log rotativo | logging/clientes | redacción | corregido |
| LVR-007 | alta | `[]` ambiguo → contrato scraper | scraping | vacío/HTTP/timeout | corregido |
| LVR-008 | media | dependencia ausente → requirements | requirements | clean install | corregido |
| LVR-009 | alta | terminales borrados → journal | colas/eventos | expired/dead-letter | corregido |
| LVR-010 | alta | HTTP ok sin evidencia → ID/URL | publisher | 201 sin evidencia | corregido |
| LVR-011 | alta | fallback implícito → política | editorial/rewrite | sensible/permitido | corregido |
| LVR-012 | media | env drift → schema/doctor | config/env | inputs inválidos | corregido |
| LVR-013 | alta | URL arbitraria → validación | safe HTTP/medios | SSRF | corregido |
| LVR-014 | alta | bind externo → loopback | Reel Manager | bind rechazado | corregido |
| LVR-015 | alta | extensión sola → magic/content | uploads | falso jpg/mp4 | corregido |
| LVR-016 | media | backup manual → auto/restore | file manager/CLI | restore | corregido |
| LVR-017 | media | resume no usado → durable real | rewrite | recovery | corregido |
| LVR-018 | alta | historial antes de cola → orden | scraper runner | persistencia | corregido |
| LVR-019 | media | fallback token → opt-in | token manager | contratos Meta | corregido |
| LVR-020 | media | paths fijos → `LVR_*_DIR` | paths/logging | suite aislada | corregido |
| LVR-021 | media | False/None → resultado tipado | CMS/Meta/R2 | matriz API | corregido |
| LVR-022 | media | cobertura 35 → pirámide/E2E | tests | 147 tests | corregido |
| LVR-023 | alta | boilerplate dedup → título | news dedup | títulos distintos | corregido |
| LVR-024 | media | asset decorativo fatal → warning | image generator | ícono ausente | corregido |
| LVR-025 | alta | flag clear olvidado → conciliación | editorial flags | PATCH fallido | mitigado |
| LVR-026 | alta | fake dry-run → sin evidencia | custom post | dry-run | corregido |
| LVR-027 | alta | path/cleanup amplio → ownership | video/UI | traversal/upload | corregido |
| LVR-028 | media | path/query distinto → canonical | URL util | equivalencia | corregido |
| LVR-029 | alta | bootstrap inválido → buckets list | init data | bootstrap limpio | corregido |
| LVR-030 | alta | lock Windows → contención portable | file manager | 5× concurrencia | corregido |
| LVR-031 | alta | fallback IG implícito → opt-in/R2 | IG/config | contrato/config | corregido |
| LVR-032 | alta | stale por edad → validar owner | file manager | live/dead PID | corregido |
| LVR-033 | alta | acquire parcial → cerrar stack | file manager | multi-lock timeout | corregido |
| LVR-034 | alta | metadata fallida → limpiar lock | file manager | write failure | corregido |
| LVR-035 | media | `innerHTML` → DOM/textContent | Reel Manager | stored text | corregido |
| LVR-036 | alta | Host/Origin libre → loopback guard | Reel Manager | rebinding/origin | corregido |
| LVR-037 | media | delete ignorado → resultado tipado | R2/UI | delete failure | corregido |
| LVR-038 | alta | OR booleano → status agregado | custom/UI | parcial manual | corregido |
| LVR-039 | alta | URL sin ID → degradación/evento | web/custom | flag tracking | mitigado |
| LVR-040 | alta | imagen remota libre → safe HTTP | scrapers/safe HTTP | SSRF link-local | corregido |
| LVR-041 | baja | fixture ajena → temp propio | test CLI | suite completa | corregido |
| LVR-042 | baja | API Pillow deprecada → getextrema | imagen/video | warnings como error | corregido |

No queda un hallazgo crítico abierto ni un hallazgo alto reproducible sin corrección
o mitigación. LVR-025 conserva el conflicto y exige conciliación; no reporta éxito
completo.

## Cambios técnicos

### Observabilidad

- StageResult y exit codes.
- Runner que verifica contrato funcional.
- Heartbeat, stale, edad de ciclo y colas.
- Logs rotativos con redacción y errores tipados.

### Persistencia y recuperación

- Lectura estricta, locks, fsync, replace y multiarchivo.
- Cuarentena, backup/restore y retención.
- Rewrite durable y terminales trazables.
- Social claim-before-call y cuarentena de outcomes ambiguos.

### Configuración y dependencias

- `psutil` declarado.
- Variables clasificadas y `.env.example` alineado.
- `doctor` seguro; integraciones deshabilitadas por defecto.
- ffmpeg/ffprobe documentados como dependencias del sistema.

### Tests

- Unitarios, contratos, scrapers, imágenes, supervisor/CLI.
- Corrupción, permisos, escritura fallida, concurrencia y recovery.
- E2E local de los 17 escenarios requeridos.

### Seguridad

- SSRF/redirects, content validation, límites y path ownership.
- Las imágenes declaradas por fuentes también pasan por validación DNS/IP.
- UI loopback-only.
- Sin shell para ffmpeg y sin secretos en logs/snapshot.

### Documentación

- README, arquitectura, estado, métricas, backlog, decisiones, known issues, AGENTS,
  `.env.example`, runbook y esta auditoría.

## Evidencia de validación

Ejecuciones en directorios temporales, sin secretos:

```text
python -m venv %TEMP%\lvr-clean-final-20260723
%TEMP%\lvr-clean-final-20260723\Scripts\python -m pip install -r requirements.txt
instalación OK

%TEMP%\lvr-clean-final-20260723\Scripts\python -m pip check
No broken requirements found.

python -W error::DeprecationWarning -m unittest discover tests
147 tests, OK

python cli.py run-once --dry-run --json
17/17 escenarios locales; status=success; exit_code=0; production_calls=false

python -m compileall -q .
exit_code=0

python cli.py doctor --scope core --json
8/8 dependencias Python; configuración segura; status=success; exit_code=0

interrupción y reinicio
10/10 completed exactamente una vez

concurrencia
100/100 updates preservados; claims únicos; CMS falso crea 1 vez y deduplica el retry

corrupción
original preservado + quarantine + excepción

bootstrap
cola durable compatible, OK

revisión de secretos y artefactos
105 archivos revisados; 0 patrones de secreto; 0 archivos prohibidos versionados o modificados
```

Todos los comandos se ejecutaron con directorios temporales, credenciales vacías o
ficticias e integraciones deshabilitadas.

## Riesgos residuales

### Internos

- dead-letter social ambiguo requiere procedimiento manual;
- falta CI y staging propio;
- filesystem de red no validado.

### Terceros

- disponibilidad/cambios HTML de fuentes;
- cuota y comportamiento real de OpenAI;
- tokens/rate limits de Meta;
- contrato desplegado del CMS;
- disponibilidad/configuración R2.

### No reproducibles

- causa original del backlog Facebook;
- estado actual del supervisor productivo.

### Información desconocida

- capacidad/espacio/retención adecuados del host;
- compatibilidad de locks si producción usa storage remoto;
- credenciales y endpoints de prueba externos.

## Pull request

La GitHub App y `gh auth status` confirmaron acceso de `NahimMora` al repositorio. La
línea de base se dividió en commits de núcleo, integraciones/seguridad, pruebas y
documentación. La URL del PR borrador se agrega en el commit final de publicación,
con alcance, motivación, compatibilidad, migración, rollback, evidencia, checklist
de seguridad y exclusiones.
