# Estado actual

Última actualización: 2026-07-30 (agrega la capa editorial premium; el resto del
documento describe el estado previo de la rama de confiabilidad y sigue vigente).

## Rediseño del Estudio Premium (rama `feature/premium-studio-ux`, no mergeada)

Construido sobre `main` en `4b8a1c7`, después del merge del PR #2 de la capa
editorial premium. No se modificó `main`, `.env`, `data/`, `logs/`, `output/` ni
`FotosLVR/`, y no se ejecutó ninguna publicación real.

- El operador puede pegar el texto actualizado de una noticia y generar con OpenAI
  el JSON del paquete. La salida reutiliza `import_chatgpt_package`; no hay un segundo
  contrato ni fallback silencioso. El prompt prohíbe investigar o inventar datos,
  personas, armas y hechos ajenos al texto.
- La UI quedó ordenada en cuatro pasos: generar/importar, revisar slides, asignar
  imágenes y guardar/previsualizar/publicar. El import JSON manual sigue disponible.
- Cada slide acepta imagen por link público SSRF-safe, subida propia validada o
  biblioteca local. Los dos primeros caminos convergen en `ingest_image_bytes` y no
  crean un store paralelo.
- La biblioteca ya no expone `thumb_path` de filesystem: devuelve una URL relativa y
  `/api/media-library/thumb/{asset_id}` sirve únicamente JPEGs confinados al
  directorio de miniaturas. Assets purgados, IDs inválidos y paths fuera del
  directorio se rechazan.
- Validación al cierre: 354 casos descubiertos (baseline `4b8a1c7`: 336; neto
  agregado: 18). En este host se ejecutaron 350 y cuatro casos de render real
  Remotion quedaron agrupados bajo un `SkipTest` de clase porque el CLI no respondió;
  los 18 casos nuevos sí se ejecutaron y pasaron. Ver `docs/METRICS.md` para el
  desglose y los comandos exactos.
- Smoke visual E2E en `127.0.0.1:8766`, con directorios temporales,
  `PREMIUM_STATIC_RENDER_ENGINE=pillow` y `PREMIUM_PUBLISH_DRY_RUN=true`: importó
  tres slides, promovió dos uploads propios, sirvió sus miniaturas, guardó el
  borrador, renderizó tres previews y devolvió Instagram/Facebook `OK` de dry-run.
  La consola del navegador terminó sin errores y no hubo llamadas externas.
- Gates finales: 17/17 E2E local dry-run, `doctor core` y `doctor all` 8/8 con
  overrides `observe`/canales apagados sólo para QA, `compileall`, sintaxis JS y
  `git diff --check` OK. El `doctor` sin overrides conserva visible una contradicción
  preexistente del host (`observe` con Web habilitada); no se tocó `.env`.

Requiere review y merge explícitamente aprobados. No autoriza desactivar
`PREMIUM_PUBLISH_DRY_RUN` ni publicar en Meta.

## Capa editorial premium (rama `feature/premium-editorial-layer`, no mergeada)

Construida sobre `main` (`dd9b7fe`) en cinco fases, cada una con pruebas propias.
No se hizo merge, no se tocó `.env` productivo ni `data/` real, y no se ejecutó
ninguna publicación real (todos los clientes Meta se probaron con mocks/dry-run).

- **Fase 1 — Router editorial**: `utils/editorial_router.py` clasifica cada noticia
  en `automatic|candidate|suppressed` por canal. Sólo restringe Instagram, y sólo si
  `EDITORIAL_ROUTER_ENABLED=true` (default `false` — comportamiento actual sin
  cambios hasta activación explícita). Modo report-only:
  `python cli.py editorial-route --report-only`. Overrides manuales completos
  (corrección 2026-07-30): `demote_automatic_to_candidate` (automática pendiente →
  candidata), `add_published_to_candidates` (automática ya publicada → candidata
  premium sin alterar el historial), `update_candidate_status` candidate↔automatic/
  discarded — todas atómicas, con lock e idempotentes.
- **Fase 2 — Biblioteca multimedia**: `utils/media_library.py` agrega candidatas,
  publicadas (con evidencia real), premium y assets de imagen en una búsqueda local
  de diez días. `python cli.py media-library search/cleanup`.
- **Fase 3 — Estudio Premium**: contrato versionado (`utils/premium_contract.py`),
  importador de ChatGPT, orquestador social-only (`utils/premium_publisher.py`,
  nunca crea artículo web ni llama al CMS), carrusel nuevo en
  `meta/ig_client.py::post_premium_carousel_to_instagram`, media directa sin link
  nueva en `meta/fb_client.py::post_premium_direct_media_to_facebook`. Pestañas
  "Estudio Premium" y "Candidatas" en la UI manual (`video_reel_manager.py`).
- **Fase 4 — Sistema visual Remotion**: composiciones still `PremiumSlide`,
  `AutomaticInstagramCard`, `FacebookOgCard`; paleta de marca sin dorado; highlight
  terms compartido con Reels (`Main`, compatible hacia atrás). Política de motor
  **por workflow** (corrección 2026-07-30): `PREMIUM_STATIC_RENDER_ENGINE=remotion`
  por defecto (Estudio Premium, manual y bajo volumen);
  `AUTOMATIC_STATIC_RENDER_ENGINE=pillow` y `OG_STATIC_RENDER_ENGINE=pillow` por
  defecto (sin wiring real a Remotion todavía); `STATIC_RENDER_ENGINE` legacy sólo
  como override explícito. Benchmark real en `docs/METRICS.md` (Remotion es ~560x
  más lento que Pillow por re-bundling por slide — ver Known Issue #69).
- **Fase 5 — Validación**: **336/336 tests Python OK** (236 preexistentes en `main`
  + 100 nuevos: router 29, biblioteca 13, premium 14, meta premium 14, Remotion 30 —
  ver `docs/METRICS.md` para el detalle exacto de esta cuenta, incluida la
  reconciliación de una cifra incorrecta reportada en una síntesis previa de esta
  misma rama), 17/17 E2E dry-run OK, `compileall`/`pip check`/`doctor core` OK,
  `npx tsc --noEmit`/`npx eslint src` sin errores nuevos, `npx remotion bundle` OK,
  `git diff --check` OK, sin secretos en el diff. CI (`reliability-windows`) es
  Python-only: no instala Node, por lo que los 4 tests de render Remotion real se
  saltean ahí automáticamente (no es un fallo).

Requiere autorización explícita antes de: activar `EDITORIAL_ROUTER_ENABLED=true` en
producción, desactivar `PREMIUM_PUBLISH_DRY_RUN`, o mergear esta rama a `main`.

## Rama, revisión y release

- Repositorio: `NahimMora/news-auto-publisher-lavozriojana`.
- Rama desplegada: `reliability/baseline-2026-07-23`.
- Commit de código identificado por el heartbeat al iniciar el ciclo #8:
  `e6b0459d3944c6a2a702062c1a3af1afd981b484`.
- Commit desplegado y verificado por heartbeat:
  `ef91a675e64f908136ea2fc9ae30bb12df35a864`.
- PR borrador: [#1](https://github.com/NahimMora/news-auto-publisher-lavozriojana/pull/1).
- CI remoto conocido: `reliability-windows` verde en Actions run
  [`30308227631`](https://github.com/NahimMora/news-auto-publisher-lavozriojana/actions/runs/30308227631).
- Propuesta posterior al merge: `v1.0.0-reliability-baseline`.

El PR sigue en borrador. No se hizo merge ni se creó el tag. El proceso activo usa
el identificador `unreleased-reliability-baseline`; no se presenta como release
oficial.

## Validación local

Verificaciones ejecutadas en el host Windows con el venv del repositorio:

| Verificación | Resultado |
|---|---|
| Python | 3.10.0 |
| `pip check` | sin dependencias rotas |
| suite | 235 tests, OK, `.env` deshabilitado y directorios temporales |
| E2E local | 17/17, `production_calls=false` |
| `compileall` | OK |
| `git diff --check` | OK |
| `doctor supervisor` con perfil operativo | `success`, 8/8 |
| dry-run CI | `success`, `production_calls=false` |
| filesystem del host | `success`, 7/7, 34.065 MB libres |

`doctor core` sin overrides sigue fallando correctamente porque el `.env` histórico
tiene Web encendida mientras el modo por default es `observe`. El arranque productivo
no oculta esa contradicción: usa
[`scripts/start_24x7_production.ps1`](../scripts/start_24x7_production.ps1), que fija
un perfil explícito y exige que `doctor supervisor` pase antes de iniciar.

## Corte y estado de colas

El 2026-07-27 se aplicó `queue-cutover --from-date 2026-07-27 --apply` con el
supervisor detenido:

- Web: 60 entradas anteriores al corte archivadas.
- Meta: 425 entradas anteriores al corte archivadas.
- Social: 23 estados históricos pasaron a `expired` o dead-letter según su estado.
- Archivo durable: `data/queue_cutover_archive.json`, 485 payloads completos.
- Eventos y motivos: `data/queue_events.json`.
- Backups previos: `data/backups/`.

El operador reemplazó la distinción por fecha por una línea de base de orden durable.
Con backup previo y supervisor detenido se aplicó:

```text
queue-cutover --keep-latest 20 --apply
```

Resultado:

- Web: 33→20; 13 payloads de canal archivados.
- Meta: 37→20; 17 payloads de canal archivados.
- Social activa: 0.
- Identidades únicas activas: 20, presentes en ambos canales.
- Orden desconocido: 0.

Los elementos anteriores se registraron como
`operator_baseline_older_than_latest_window`; no se marcaron como publicaciones
externas sin ID/URL.

Snapshot al iniciar el ciclo #8:

- Web: 20 pendientes de la ventana más reciente.
- Meta: 20 entradas de las mismas identidades.
- Social activa: 0.
- Rewrite: 0 pending, 0 processing, 0 failed, 0 dead-letter.
- Backlog histórico de Facebook: 0 pendientes sin clasificar, 0 ambiguos.

No se borró ni sobrescribió el historial para “limpiar” las colas.
`ARTICLE_NOT_BEFORE_DATE` queda desactivado en el perfil operativo porque una noticia
válida puede no traer fecha.

## Integraciones reales

Preflight externo del 2026-07-27:

| Integración | Estado | Evidencia |
|---|---|---|
| Fuentes | `success` | 10/10 secciones vivas reconocidas |
| OpenAI | `success` | autenticación, modelo y respuesta controlada |
| R2 | `success` | create/head/read/delete bajo `healthchecks/`, cleanup confirmado |
| Facebook | `success` | identidad, permisos y capacidad de publicación |
| Instagram | `success` | cuenta, relación con página y permiso de publicación |
| Filesystem | `success` | lock, dos writers, replace, fsync, backup/restore y cuarentena |
| Supervisor | `success` | configuración, PID, heartbeat y logs escribibles |
| CMS read-only | `blocked` | falta `WEBAPP_PREFLIGHT_PATH` seguro |

El bloqueo del preflight CMS no se convirtió en éxito. La ruta de escritura quedó
verificada por tres publicaciones Web reales con ID/URL y HTTP público 200; la más
reciente fue:

`https://lavozriojana.com/noticias/alerta-amarilla-por-viento-zonda-en-la-rioja`

Facebook quedó verificado con publicaciones reales y consulta posterior read-only.
La última evidencia del primer ciclo es el ID
`1243054632214236_122109834009372360`.

Instagram tuvo un canary controlado, verificable e idempotente:

- ID: `18207194662361611`.
- Permalink verificado antes del cleanup.
- Cleanup confirmado; la consulta posterior devolvió objeto inexistente.

Durante el primer ciclo 24/7, Instagram deduplicó de forma segura la nota seleccionada
contra su historial y no creó una copia.

El ciclo #5 publicó Web y Facebook, pero Instagram recibió `request_rejected` para una
nota de abigeato. La entrada quedó en dead-letter y no se reintentó automáticamente.
El proveedor no dejó código/subcódigo en el evento histórico, por lo que la causa
externa exacta quedó desconocida. El ciclo #6 publicó correctamente en las tres
integraciones; Instagram devolvió ID `18177266845418088`. Desde el ajuste
`LVR-069`, los rechazos futuros conservan HTTP/código/subcódigo/tipo sanitizados en el
journal y en el log rotativo.

El gate local también se validó desde Windows PowerShell 5.1. `LVR-070` permite que
el verificador lea el BOM que esa consola agrega con `Out-File -Encoding utf8`, sin
relajar ninguna comprobación del contenido.

El ciclo #7 terminó `degraded` porque Web rechazó una nota de `policiales` tras seis
intentos editoriales y bloqueó el fallback mediante `strict_category_policiales`.
No hubo publicación externa ni falso éxito: el elemento pasó a dead-letter con título,
motivo y política; Facebook e Instagram reportaron `no_work` porque no apareció una
URL Web nueva. Es el comportamiento conservador configurado para una categoría
sensible, no una caída de CMS/Meta.

## Estado operativo

- Supervisor: activo, PID registrado `52088` al iniciar el ciclo #8.
- Modo: `all`.
- Canales solicitados/habilitados: Web, Facebook e Instagram.
- Límite efectivo: Web sin límite; Facebook 8 e Instagram 8 por ciclo.
- Intervalo: 3.600 segundos.
- Heartbeat: fresco y persistente.
- Último ciclo: #11 `success`, 4/4 etapas aceptables.
- Ciclo #11: scraping/reescritura `no_work`, Web `no_work`, Facebook `success` 8/8 e
  Instagram `no_work`.
- Ciclo #10: Web `success` 6/6, Instagram `success` 1/1 y Facebook `degraded` 5/8
  porque tres páginas todavía no devolvían HTTP válido durante el prewarm. No se
  llamó a Graph para esas tres; permanecieron en cola.
- Ciclo #8: Web `degraded` 24/26, siete publicaciones degradadas, dos terminales
  sensibles y cola final 0; Facebook e Instagram `success` 8/8.
- El feedback produjo revisiones materiales y el sexto resultado seguro se publicó
  como `degraded`. Los falsos positivos observados con comienzos de oración y
  equivalencias número-palabra quedaron corregidos en `LVR-075`/`LVR-076`.
- Ciclo #7 Web: `failed` 0/1 por `strict_category_policiales`, terminal trazable y
  sin publicación; Facebook/Instagram `no_work`.
- Ciclo #5: `degraded`, 3/4; rechazo Instagram aislado y no reintentado.
- Alertas: detección y outbox durable habilitados; webhook externo no configurado.
- UI manual: `http://127.0.0.1:8765/`, HTTP 200, sólo loopback.
- Watchdog: tareas `LaVozRiojana-24x7` y `LaVozRiojana-ManualUI` cada cinco minutos;
  ambas devolvieron resultado `0` y no duplicaron procesos.

El arranque se hizo por autorización explícita del operador. No equivale a aprobación
del PR, merge, tag ni declaración de release listo para producción.

## Gates

| Gate | Estado | Evidencia o bloqueo |
|---|---|---|
| A Código | parcial | suite/compile/E2E verdes; falta CI del commit final, review y merge |
| B Entorno | completo para este host | backup, restore temporal, filesystem y heartbeat |
| C Read-only | parcial | todo verde salvo endpoint CMS seguro |
| D Canary | parcial | Instagram completo; Web/FB se validaron con publicaciones reales autorizadas |
| E Observe | ejecutado | ciclos previos sanos, sin publicación |
| F Web | ejecutado | publicaciones verificables y rechazo editorial seguro en ciclo #7 |
| G Facebook | ejecutado | backlog conciliado, token/página y publicaciones verificadas |
| H Instagram | ejecutado con incidente aislado | preflight/canary y ciclo #6 reales; un rechazo previo quedó en dead-letter |
| I Release 24/7 | bloqueado | PR no aprobado/mergeado, tag ausente y CMS read-only bloqueado |

Por estos bloqueos el repositorio no se declara “release listo para 24/7”, aunque el
servicio solicitado por el operador está activo con límites y watchdog.

## Riesgo residual y próximo paso

- El CMS no expone un preflight GET autenticado con versión/capacidades.
- No hay webhook aprobado; las alertas quedan en outbox local.
- Las tareas programadas deben volver a verificarse después de un reinicio real del
  host.
- Las tareas usan la sesión interactiva de `pc10`; no cubren el intervalo anterior al
  inicio de sesión de Windows.
- El commit activo tiene cambios de trabajo todavía no integrados en `main`.
- La causa exacta del rechazo Instagram del ciclo #5 no puede reconstruirse porque
  ocurrió antes de persistir metadatos sanitizados; no se reprodujo en el ciclo #6.
- El backlog Web creció 24→26→29→33 bajo el límite anterior. Con Web ilimitada quedó
  en cero y se mantuvo en cero al finalizar el ciclo #11.
- Facebook conserva 3 pendientes e Instagram 0. El ciclo #11 confirmó recuperación
  posterior al prewarm transitorio de ciclo #10; no hubo pérdida ni reintento ciego.
- El contenido y selectores de terceros pueden cambiar sin aviso.

Próximo gate: obtener review/aprobación, agregar un endpoint CMS read-only y ensayar
reboot/rollback antes de mergear o crear el tag oficial.
