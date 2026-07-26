# Auditoría de preparación 24/7

Fecha: 2026-07-26

Repositorio: `NahimMora/news-auto-publisher-lavozriojana`

Rama: `reliability/baseline-2026-07-23`

PR: [#1](https://github.com/NahimMora/news-auto-publisher-lavozriojana/pull/1)
Base verificada: `fbb83eac3cf3ce399dac5a9d778f81a1957d7c2a`

## Resumen ejecutivo

La línea de base anterior tenía persistencia y contratos locales saneados, pero no
era operable con un rollout controlado: faltaban CI, preflight real, canary,
conciliación de Facebook, alertas y modos progresivos. Además, los runners Meta
tenían defaults efectivos inseguros y el scraper de Tiempo Popular no reconocía una
variante viva de host/slash.

Se implementaron y probaron los controles dentro del repositorio. Las diez fuentes
vivas y el filesystem del host pasaron preflight read-only/temporal. El backlog de
Facebook se clasificó sobre copias sin modificar producción.

El sistema **no se declara listo para producción 24/7** porque todavía faltan CI
remoto verde y revisión, backup/restore productivo, preflight real de OpenAI/R2/CMS/
Meta, canary autorizado y los ciclos progresivos de Gates E–I.

El cuello de botella principal ya no es el código local: es la validación coordinada
de terceros y la resolución de 19 entradas Facebook sin URL web.

## Separación de evidencia

### Hechos comprobados

- Acceso real al repositorio y PR mediante GitHub App/CLI autenticada.
- PR #1 abierto, draft y mergeable antes de los cambios.
- 5 commits, 106 archivos modificados, sin reviews, comentarios ni checks.
- `main` sin protección verificable.
- Instalación limpia desde `requirements.txt` con Python 3.10.
- Suite final local: 193 tests OK con deprecaciones como error.
- E2E local: 17 escenarios, `production_calls=false`.
- Fuentes vivas: 10/10 `success`.
- Filesystem temporal en el mismo volumen: `success`.
- Supervisor preflight temporal: `success`, sin iniciar proceso.
- Alerta local: evento creado y persistido sin webhook.
- Facebook sobre copias: 23 entradas clasificadas; cero cambios a la cola original.
- El supervisor real encontrado al inicio fue detenido antes de cambiar contratos.

### Inferencias

- El cambio de host/slash de Tiempo Popular explica el `no_work` falso observado en
  el primer preflight; se confirmó al corregir el filtro y obtener 4/4 `success`.
- El backlog Facebook no puede habilitarse de forma segura mientras 19 entradas no
  tengan URL web; no se infiere que estén publicadas.
- El volumen inspeccionado parece local porque no es UNC. No se infiere soporte para
  un share de red distinto.

### Información desconocida

- Vigencia/cuota real de OpenAI.
- Identidad, permisos y rate limits reales de Meta.
- Contrato de salud/capacidad read-only del CMS.
- Escritura/lectura/cleanup real de R2.
- Comportamiento durante varios ciclos en cada modo progresivo.
- Proveedor definitivo de alertas.

### Problemas reproducidos

- Suite no hermética con `LVR_QUARANTINE_DIR`.
- Defaults de runners Meta distintos de la configuración documentada.
- `.env` cargado después de imports con rutas fijadas.
- Ausencia de CI/checks/protección.
- Ausencia de preflight/canary/alertas/modos/conciliación.
- Tiempo Popular sin `www` y sin slash final.
- Documentación que contradecía un supervisor real activo.

### Problemas no reproducidos

- No se reprodujo pérdida de datos, corrupción concurrente o doble publicación en la
  suite final.
- No se reprodujo un outcome ambiguo real de Meta; el contrato sí está probado.
- No se reprodujo el fallo histórico que originó el backlog de Facebook.

### Bloqueos externos

- Credenciales/autorización para OpenAI, R2 y Meta.
- Endpoint CMS read-only.
- Canary externo y cleanup.
- CI remoto y branch protection hasta publicar commits.
- Decisiones humanas para las entradas Facebook bloqueadas.

## Estado inicial del PR

| Dato | Valor comprobado |
|---|---|
| base | `main` |
| SHA base | `fbb83eac3cf3ce399dac5a9d778f81a1957d7c2a` |
| SHA inicial del PR | `e91de85d2baf29188b908a2ec66fe1f21c539626` |
| commits | 5 |
| changed files | 106 |
| mergeable | sí |
| draft | sí |
| checks | ninguno |
| reviews | ninguna |
| comentarios | ninguno |
| branch protection | no configurada/verificable |

La descripción del PR decía revertir cuatro commits, aunque el PR ya tenía cinco.
Debe actualizarse junto con esta evidencia.

## Línea de base limpia

Entorno: Microsoft Windows 10.0.26200, Python 3.10.0, pip 26.1.2.

| Comando | Resultado inicial |
|---|---|
| `python -m pip install --upgrade pip` | OK |
| `pip install -r requirements.txt` | OK |
| `pip check` | OK, sin requirements rotos |
| `python -W error::DeprecationWarning -m unittest discover tests` | 146/147; 1 fallo de aislamiento |
| `python -m compileall -q .` | OK |
| `python cli.py doctor --scope core --json` | `success` en entorno sin secretos |
| `python cli.py run-once --dry-run --json` | 17/17, `production_calls=false` |
| `git diff --check` | OK |

El fallo 147 se reprodujo sólo al declarar una cuarentena global, se corrigió en el
test y luego la suite completa pasó.

## Cambios técnicos

### CI

- Workflow Windows para PR a `main`, push a `main` y ejecución manual.
- Venv del runner, directorios bajo `runner.temp`, integraciones apagadas.
- Gate explícito del JSON dry-run y revisión de artefactos/secretos obvios.
- Sin deploy automático ni secretos de Actions.

### Preflight

- Scopes: sources, OpenAI, R2, CMS, Facebook, Instagram, filesystem, supervisor y all.
- `blocked` con exit 3.
- Sources: DNS, HTTP, content type, enlaces, contrato de artículo e imagen pública.
- OpenAI: prompt mínimo sanitizado y respuesta JSON exacta.
- R2: objeto UUID en `healthchecks/`, lectura pública, delete y `head` 404 confirmado.
- CMS: sólo GET autenticado en path configurado y capacidad declarada.
- Meta: identidad, relación y permisos de publicación, sin crear contenido.
- Filesystem: dos writers, lock, backup/restore, truncado/cuarentena, replace, fsync y
  espacio.
- Supervisor: configuración, modo, directorios, PID/heartbeat/logs, sin iniciar.

### Canary

- Gate por env y argumento.
- Una noticia no sensible/no breaking, máximo una vez por canal.
- Reserva durable antes de la llamada.
- IDs/URLs externos y dedupe.
- Outcome ambiguo sin retry automático.
- Cleanup separado y soporte manual explícito.

### Conciliación

- Report-only no modifica.
- Identidad por keys/URL, nunca por título.
- Clasificaciones obligatorias y motivos.
- Aplicación sólo con `report_id` vigente.
- No elimina ni marca publicado sin `external_id`.

### Alertas

- Detectores obligatorios, dedupe temporal y recovery.
- Dead-letter/cuarentena como eventos sin falsa recuperación.
- Outbox durable con estado de entrega.
- Webhook público opcional con retries limitados y rate-limit.
- Redacción recursiva de secretos.
- El notificador no bloquea ni falsea el pipeline.

### Deployment mode

- `observe`, `web_only`, `web_facebook`, `web_instagram`, `all`.
- Kill switches individuales conservan autoridad.
- Contradicciones fallan en `doctor`.
- Una publicación por canal/ciclo.
- Heartbeat y journal registran modo/cambio.
- Sin transición automática.

### Seguridad

- Meta apagado salvo opt-in booleano verdadero.
- Webhook pasa validación SSRF/redirect.
- Preflight y canary no registran tokens.
- CI no carga `.env`.
- R2 no sobrescribe keys existentes.

### Tests

Nuevas suites:

- `tests/test_ci_safety.py`;
- `tests/test_preflight.py`;
- `tests/test_canary.py`;
- `tests/test_facebook_reconcile.py`;
- `tests/test_alerts.py`;
- `tests/test_deployment_modes.py`;
- regresión de URL viva en `tests/test_scraper_fixtures.py`.

## Matriz de hallazgos

### LVR-043 — CI inexistente

- Severidad: alta.
- Archivo/función: repositorio, workflows/checks.
- Síntoma: PR mergeable sin validación automática.
- Causa raíz: no había workflow ni check requerido.
- Reproducción: `gh pr checks 1` devolvió “no checks”.
- Impacto: una regresión podía llegar a `main`.
- Corrección: `.github/workflows/reliability.yml` y gate de seguridad.
- Test: `tests.test_ci_safety`.
- Evidencia: workflow local inspeccionado; CI remoto pendiente.
- Estado: mitigado, bloqueado hasta check verde/protección.
- Riesgo residual: un workflow no es obligatorio hasta proteger `main`.

### LVR-044 — Meta habilitado por default efectivo

- Severidad: alta.
- Archivo/función: `meta/run_fb.py::main`, `meta/run_ig.py::main`.
- Síntoma: variable ausente equivalía a publicar.
- Causa raíz: defaults `"true"` distintos de config/docs.
- Reproducción: inspección y test sin variable.
- Impacto: publicación accidental.
- Corrección: sólo verdadero explícito habilita.
- Test: `test_runners_are_disabled_when_switch_is_missing`.
- Estado: corregido.
- Riesgo residual: ninguno reproducible con el gate actual.

### LVR-045 — Carga tardía de `.env`

- Severidad: alta.
- Archivo/función: `cli.py` imports/main.
- Síntoma: rutas/clientes podían fijarse antes de cargar configuración.
- Causa raíz: `load_dotenv()` dentro de `main`.
- Reproducción: orden de imports.
- Impacto: aislamiento y configuración aparentes.
- Corrección: carga antes de módulos operativos; CI deshabilita dotenv.
- Test/evidencia: dry-run y doctor aislados.
- Estado: corregido.
- Riesgo residual: módulos standalone deben mantener el mismo patrón.

### LVR-046 — Test de cuarentena no hermético

- Severidad: media.
- Archivo/función: `tests/test_reliability_core.py`.
- Síntoma: 1/147 falló con cuarentena global.
- Causa raíz: asunción de path implícito.
- Corrección: path temporal explícito.
- Test: suite completa.
- Estado: corregido.
- Riesgo residual: ninguno.

### LVR-047 — Sin preflight real

- Severidad: alta.
- Archivo/función: nuevo `utils/preflight.py`.
- Síntoma: mocks podían confundirse con salud real.
- Causa raíz: no existía comando externo seguro.
- Corrección: ocho scopes y `blocked`.
- Tests: `tests.test_preflight`.
- Evidencia: sources/filesystem/supervisor reales.
- Estado: mitigado.
- Riesgo residual: cuatro integraciones externas bloqueadas.

### LVR-048 — Sin arranque progresivo

- Severidad: alta.
- Archivo/función: `run_24x7.py`, `cli.py`, `utils/deployment.py`.
- Síntoma: supervisor ejecutaba todas las etapas configuradas.
- Causa raíz: lista fija sin política de rollout.
- Corrección: modos, switches, límites y validación.
- Tests: `tests.test_deployment_modes`.
- Estado: corregido en código.
- Riesgo residual: ciclos reales todavía no observados.

### LVR-049 — Sin canary aislado

- Severidad: alta.
- Archivo/función: nuevo `utils/canary.py`.
- Síntoma: validar escritura exigía usar cola/ciclo real.
- Causa raíz: no había entrypoint dedicado.
- Corrección: gate doble, idempotencia, evidencia y cleanup.
- Tests: `tests.test_canary`.
- Estado: corregido en código, bloqueado externamente.
- Riesgo residual: cleanup depende de capacidades del proveedor.

### LVR-050 — Backlog Facebook sin conciliación

- Severidad: alta.
- Archivo/función: nuevo `utils/facebook_reconcile.py`.
- Síntoma: riesgo de reencolar historial ambiguo.
- Causa raíz: faltaba clasificación por evidencia.
- Corrección: reporte y decisiones.
- Tests: `tests.test_facebook_reconcile`.
- Evidencia real: copia de 23 entradas, `modified_queue=false`.
- Estado: mitigado.
- Riesgo residual: 19 sin URL web; Facebook bloqueado.

### LVR-051 — Sin alertas mínimas

- Severidad: alta.
- Archivo/función: nuevo `utils/alerts.py`.
- Síntoma: operación desatendida dependía de inspección manual.
- Causa raíz: no había detector/outbox.
- Corrección: diez detectores, dedupe, recovery y entrega opcional.
- Tests: `tests.test_alerts`.
- Evidencia: `alert-test` local.
- Estado: corregido en código.
- Riesgo residual: falta webhook/watchdog real.

### LVR-052 — URL viva de Tiempo Popular rechazada

- Severidad: alta.
- Archivo/función: `scraping/base_tiempopopular.py::_is_article_url`.
- Síntoma: cuatro secciones accesibles informaban `no_work`.
- Causa raíz: requería `www` y slash final.
- Reproducción: preflight vivo del 2026-07-26.
- Impacto: pérdida silenciosa de captura.
- Corrección: host normalizado y slash opcional.
- Test: fixture de variante viva.
- Evidencia: preflight posterior 4/4 y total 10/10.
- Estado: corregido.
- Riesgo residual: HTML de terceros sigue mutable.

### LVR-053 — Supervisor activo y documentación contradictoria

- Severidad: alta.
- Archivo/función: estado operativo/documentación.
- Síntoma: heartbeat con publicaciones mientras docs decían “no iniciado”.
- Causa raíz: una ejecución anterior no se reflejó en estado.
- Reproducción: PID, heartbeat y conteos leídos.
- Corrección: stop seguro, docs y default `observe`.
- Test/evidencia: proceso detenido; no se reinició.
- Estado: mitigado.
- Riesgo residual: las publicaciones previas no son canary ni gate.

### LVR-054 — Release no identificable

- Severidad: media.
- Archivo/función: heartbeat/deployment metadata.
- Síntoma: no había commit/tag/fingerprint/operador/backup juntos.
- Corrección: metadata versión 2 y propuesta de tag.
- Test: heartbeat y deployment tests.
- Estado: corregido en código, tag bloqueado hasta merge.
- Riesgo residual: operador debe completar variables en host.

### LVR-055 — CMS sin endpoint seguro confirmado

- Severidad: alta.
- Archivo/función: integración CMS externa.
- Síntoma: no se puede validar capacidad sin crear post.
- Corrección: preflight exige `WEBAPP_PREFLIGHT_PATH` y declara `blocked`.
- Test: contratos CMS de preflight.
- Estado: bloqueado por entorno/repositorio CMS.
- Riesgo residual: web no puede habilitarse.

### LVR-056 — Watchdog externo ausente

- Severidad: media.
- Archivo/función: operación del host.
- Síntoma: un proceso muerto no puede enviar su propia alerta stale.
- Mitigación: `alert-check` para scheduler externo y outbox.
- Test: heartbeat stale.
- Estado: abierto mitigado.
- Riesgo residual: requiere Task Scheduler/servicio externo simple.

### LVR-057 — Workflow rechazado antes de crear jobs

- Severidad: alta.
- Archivo/función: `.github/workflows/reliability.yml`,
  `jobs.reliability-windows.env`.
- Síntoma: la primera ejecución remota terminó en `failure`, sin jobs ni logs.
- Causa raíz: `runner.temp` se evaluaba dentro de `jobs.<job>.env`, contexto no
  disponible antes de asignar el runner.
- Reproducción: Actions run `30209150539`, con `jobs=[]` y nombre igual a la ruta
  del workflow.
- Corrección: las rutas temporales se escriben en `$GITHUB_ENV` desde un step
  `pwsh` posterior a la asignación del runner.
- Test: `test_workflow_contains_required_windows_gates` impide reintroducir
  `${{ runner.temp }}` en el bloque de entorno del job.
- Evidencia: Actions run `30209610342` creó el job Windows; instalación, suite y
  `compileall` pasaron.
- Estado: corregido y verificado; el mismo run encontró LVR-058 en `doctor core`.
- Riesgo residual: ninguno específico a la disponibilidad de `runner.temp`.

### LVR-058 — `doctor core` exigía binarios opcionales

- Severidad: alta.
- Archivo/función: `utils/config.py::diagnose_environment`.
- Síntoma: Actions run `30209610342` falló en `doctor core` aunque configuración y
  ocho dependencias Python estaban correctas.
- Causa raíz: la ausencia de `ffmpeg`/`ffprobe` degradaba todos los scopes, incluido
  `core`, pese a ser dependencias de sistema separadas.
- Reproducción: mock de `shutil.which` sin binarios o runner Windows limpio.
- Corrección: `core` valida configuración y dependencias Python; `doctor all`
  conserva el aviso no exitoso por binarios opcionales ausentes.
- Test: `DoctorScopeTests.
  test_core_does_not_require_optional_system_binaries`.
- Evidencia: test focal verde y `doctor core` local con exit 0.
- Estado: corregido; revalidación remota pendiente.
- Riesgo residual: el host debe ejecutar `doctor all` antes de funciones multimedia.

### LVR-059 — El mínimo de dotenv no garantizaba aislamiento

- Severidad: alta.
- Archivo/función: `requirements.txt`, carga inicial de `cli.py`.
- Síntoma: con `python-dotenv 1.0.0`, `PYTHON_DOTENV_DISABLED=1` no evitó cargar el
  `.env` local; el snapshot seguro mostró credenciales configuradas, siempre
  redactadas.
- Causa raíz: `requirements.txt` permitía una versión anterior a la barrera usada
  por CI.
- Reproducción: ejecutar `doctor core` con 1.0.0 y la variable de aislamiento.
- Corrección: mínimo `python-dotenv>=1.2.2`.
- Test: `test_requirements_support_explicit_dotenv_isolation` y ejecución limpia
  con 1.2.2.
- Evidencia: el entorno limpio no carga `.env` con la barrera activa.
- Estado: corregido; instalación limpia final pendiente.
- Riesgo residual: entornos existentes deben reinstalar `requirements.txt`.

### LVR-060 — Carrera de lock Windows informada como permiso inválido

- Severidad: alta.
- Archivo/función: `utils/file_manager.py::FileLock.acquire`.
- Síntoma: Actions run `30209866700` falló durante 100 writers concurrentes con
  `PermissionError` sobre `state.json.lock`.
- Causa raíz: Windows puede devolver `PermissionError` por sharing violation; si el
  dueño libera el lock antes de `exists()`, el código lo confundía con permisos
  permanentes.
- Reproducción: suite Windows y test que inyecta `PermissionError` transitorio sin
  lock visible.
- Corrección: tolerar dos carreras transitorias; el tercer permiso consecutivo sin
  lock visible sigue generando `JsonWriteError` explícito.
- Test: `test_windows_permission_race_retries_but_persistent_denial_fails` y 25
  repeticiones de `test_concurrent_updates_do_not_lose_data`.
- Evidencia: 2.500 actualizaciones acumuladas sin pérdida en el stress local.
- Estado: corregido; revalidación remota pendiente.
- Riesgo residual: validar también sobre el filesystem real del host antes de deploy.

## Priorización de hallazgos nuevos

Escala 1–5. Puntaje:
`impacto × confianza × alineación × reutilización / (esfuerzo × riesgo)`.

| ID | Imp. | Conf. | Alin. | Reut. | Ahorro | Esf. | Riesgo | Mant. | Puntaje |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LVR-043 | 5 | 5 | 5 | 5 | 5 | 2 | 1 | 1 | 312,5 |
| LVR-044 | 5 | 5 | 5 | 5 | 5 | 1 | 1 | 1 | 625,0 |
| LVR-045 | 4 | 5 | 5 | 4 | 4 | 1 | 1 | 1 | 400,0 |
| LVR-046 | 3 | 5 | 4 | 3 | 3 | 1 | 1 | 1 | 180,0 |
| LVR-047 | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 3 | 52,1 |
| LVR-048 | 5 | 5 | 5 | 5 | 5 | 3 | 2 | 2 | 104,2 |
| LVR-049 | 5 | 5 | 5 | 4 | 5 | 4 | 3 | 3 | 41,7 |
| LVR-050 | 5 | 5 | 5 | 3 | 5 | 3 | 2 | 2 | 62,5 |
| LVR-051 | 5 | 5 | 5 | 5 | 5 | 4 | 2 | 3 | 78,1 |
| LVR-052 | 5 | 5 | 5 | 4 | 4 | 1 | 1 | 1 | 500,0 |
| LVR-053 | 5 | 5 | 5 | 3 | 5 | 1 | 1 | 2 | 375,0 |
| LVR-054 | 4 | 5 | 4 | 4 | 4 | 2 | 1 | 1 | 160,0 |
| LVR-055 | 5 | 4 | 5 | 3 | 5 | 2 | 2 | 2 | 75,0 |
| LVR-056 | 4 | 5 | 4 | 4 | 4 | 2 | 2 | 2 | 80,0 |
| LVR-057 | 5 | 5 | 5 | 4 | 4 | 1 | 1 | 1 | 500,0 |
| LVR-058 | 5 | 5 | 5 | 4 | 4 | 1 | 1 | 1 | 500,0 |
| LVR-059 | 5 | 5 | 5 | 4 | 5 | 1 | 1 | 1 | 500,0 |
| LVR-060 | 5 | 5 | 5 | 5 | 5 | 1 | 2 | 2 | 312,5 |

## Evidencia de validación

| Validación | Resultado |
|---|---|
| instalación limpia | OK |
| `pip check` | OK |
| suite final | 193 tests, OK, 17,568 s |
| E2E local | 17/17, `production_calls=false` |
| `compileall` | OK |
| doctor core | `success` |
| sources live | 10/10 `success`, 12,656 s |
| filesystem host | 7/7, 28.628 MB libres |
| supervisor preflight | 2/2, no proceso iniciado |
| alert test | outbox local, sin secretos |
| Facebook report-only | 23/23 clasificadas sobre copia |
| secret/path scan | OK |
| `git diff --check` | OK |

Los logs de tests que dicen “Publicado” son ejecuciones contra mocks. El gate E2E
confirma `production_calls=false`.

## Estado de integraciones

| Integración | Estado | Evidencia | Bloqueo | Próximo paso |
|---|---|---|---|---|
| Fuentes | success | 10/10 live | ninguno actual | monitorear selectores |
| Filesystem | success | preflight temporal | sólo share futuro | repetir en deploy |
| Supervisor | success temporal | PID/heartbeat/log write | no ciclos observe | Gate E |
| OpenAI | blocked | contratos locales | credencial/autorización | preflight real |
| R2 | blocked | contrato reversible | autorización | healthchecks real |
| CMS | blocked | mocks | endpoint GET seguro | coordinar CMS |
| Facebook | blocked | reporte 23 items | 19 sin URL + token/canary | decisiones/preflight |
| Instagram | blocked | mocks | token/permisos/canary | preflight y canary |
| Alertas | success local | outbox | webhook/watchdog | prueba real |

## Gates

| Gate | Estado | Evidencia | Bloqueos |
|---|---|---|---|
| A Código | parcial | suite/compile/doctor/E2E | CI remoto y review |
| B Entorno | parcial | filesystem temporal | backup/restore productivo |
| C Read-only | parcial | fuentes | OpenAI/R2/CMS/Meta |
| D Canary | bloqueado | tests | autorización/terceros |
| E Observe | no ejecutado | — | Gates A–D |
| F Web | no ejecutado | — | CMS/R2/canary |
| G Facebook | bloqueado | reporte | backlog/token/canary |
| H Instagram | bloqueado | mocks | R2/permisos/canary |
| I 24/7 | bloqueado | — | Gates anteriores/merge/tag |

## Migración y compatibilidad

- No se cambia el formato de las colas legacy.
- Se agregan JSON operativos independientes: `canary_runs.json`,
  `alert_state.json`, `alert_outbox.json`.
- Heartbeat pasa a versión 2 agregando `deployment`; los lectores previos pueden
  ignorar el campo.
- `blocked` se agrega al contrato; sólo comandos de preflight/canary lo emiten.
- Defaults de Meta cambian de habilitación implícita a opt-in explícito.
- La migración de `.env` exige declarar modo coherente; no se edita el archivo real.

## Rollback

1. Detener supervisor.
2. Poner `PIPELINE_DEPLOYMENT_MODE=observe`.
3. Apagar los tres kill switches.
4. Crear backup y probar restore temporal.
5. Revertir mediante commit, no reescribir historia.
6. Ejecutar CI local, doctor y preflight supervisor.
7. Registrar commit/tag/operador/backup en el heartbeat.

Los nuevos archivos de alertas/canary pueden conservarse al rollback; no interfieren
con colas legacy. No deben borrarse porque contienen evidencia.

## Riesgos residuales

### Internos

- Falta validar CI después de publicar.
- Falta un watchdog externo.
- El rollout real no fue observado.

### Externos

- Tokens, cuota, permisos, endpoint CMS y R2.
- HTML de fuentes mutable.
- Cleanup canary puede requerir operación manual.

### Operativos

- 19 entradas Facebook sin URL.
- Backup/restore productivo no ensayado.
- El `.env` real debe migrarse a una combinación de modo/switches coherente.

### Editoriales

- `allow_non_sensitive` permanece vigente.
- No se agregó aprobación humana obligatoria.
- Canary rechaza policiales, judiciales, menores y breaking.

### No reproducidos

- Causa histórica original del backlog Facebook.
- Outcomes ambiguos reales.
- Locks sobre un share de red.

### Bloqueados por entorno

- OpenAI, R2, CMS, Facebook, Instagram, canary, webhook y gates progresivos.

## Contenido requerido del PR

El PR debe permanecer draft e incluir:

- alcance y motivación;
- matriz LVR-043–LVR-060;
- CI y comandos exactos;
- compatibilidad/migración;
- rollback;
- seguridad y ausencia de secretos;
- resultados locales y preflight live;
- bloqueos externos;
- acciones que requieren autorización humana;
- propuesta de tag, sin crearla;
- checklist de Gates A–I.
