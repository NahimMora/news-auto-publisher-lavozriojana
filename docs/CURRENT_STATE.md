# Estado actual

Última actualización: 2026-07-27 19:16 ART.

## Rama, revisión y release

- Repositorio: `NahimMora/news-auto-publisher-lavozriojana`.
- Rama desplegada: `reliability/baseline-2026-07-23`.
- Commit de código identificado por el heartbeat:
  `1fe63cc018a52fa66f8f454cf87c4f40c4995068`.
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
| suite | 220 tests, OK, `.env` deshabilitado |
| E2E local | 17/17, `production_calls=false` |
| `compileall` | OK |
| `git diff --check` | OK |
| `doctor supervisor` con perfil operativo | `success`, 8/8 |
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

Snapshot después del ciclo #7:

- Web: 33 pendientes, todas del corte en adelante.
- Meta: 37 entradas del corte en adelante.
- Social activa: 0.
- Rewrite: 0 pending, 0 processing, 0 failed, 0 dead-letter.
- Backlog histórico de Facebook: 0 pendientes sin clasificar, 0 ambiguos.

No se borró ni sobrescribió el historial para “limpiar” las colas. La fecha mínima
de ingreso queda fijada por `ARTICLE_NOT_BEFORE_DATE=2026-07-27`.

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

- Supervisor: activo, PID registrado `29276` al actualizar este documento.
- Modo: `all`.
- Canales solicitados/habilitados: Web, Facebook e Instagram.
- Límite efectivo: una publicación por canal y ciclo.
- Intervalo: 3.600 segundos.
- Heartbeat: fresco y persistente.
- Último ciclo observado: #7 `degraded`, 3/4 etapas aceptables.
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
- El backlog Web creció 24→26→29 y llegó a 33; el límite inicial de una publicación
  por ciclo es menor que el ingreso observado. La alerta `backlog_growing` se emitió
  localmente. No se aumenta volumen hasta completar más ciclos sanos.
- El contenido y selectores de terceros pueden cambiar sin aviso.

Próximo gate: revisar y subir el diff sin secretos, obtener CI/review del PR y agregar
un endpoint CMS read-only antes de crear el tag oficial.
