# Activación controlada 24/7 — 2026-07-27

## Alcance

Activación solicitada por el operador para publicar noticias del 27/07/2026 en
adelante, conservar trazabilidad del backlog anterior, mantener la UI manual de
videos en localhost y dejar mecanismos de recuperación de procesos.

No se hizo merge, no se creó un tag y no se editó `.env`. Los secretos no se
imprimieron ni se incorporaron al repositorio.

## Hechos comprobados

- Rama: `reliability/baseline-2026-07-23`.
- Commit registrado: `f90675d62c06a376aca6a798476a59c65a53fb3f`.
- Python 3.10.0 en `venv`.
- `pip check`: sin dependencias rotas.
- Suite: 217 tests, OK, 16,451 segundos.
- E2E local: 17/17, `production_calls=false`.
- `compileall` y `git diff --check`: exit 0.
- Perfil productivo: `doctor supervisor` `success`, 8/8.
- Preflight: sources, OpenAI, R2, Facebook, Instagram, filesystem y supervisor
  `success`.
- CMS preflight: `blocked`, no existe endpoint GET seguro configurado.
- R2 creó, leyó y eliminó un objeto UUID bajo `healthchecks/`; cleanup confirmado.
- Filesystem: 34.065 MB libres, lock, dos writers, `os.replace`, fsync,
  backup/restore y cuarentena.
- Backlog Facebook final: 0 entradas activas, 0 ambiguas y 0 sin clasificar.
- UI manual: HTTP 200 en `127.0.0.1:8765`.
- Supervisor: modo `all`, heartbeat fresco y límites 1/1/1.
- Primer ciclo: scraping/rewrite `no_work`, Web `success 1/1`, Facebook
  `success 1/1`, Instagram `success 1/1` por deduplicación.
- Tareas programadas: dos ejecuciones reales con `LastTaskResult=0`.

## Inferencias

- La ruta de escritura CMS es operable porque tres publicaciones reales devolvieron
  evidencia y sus URLs públicas respondieron HTTP 200. Esto no reemplaza un preflight
  read-only.
- El watchdog reduce el tiempo de recuperación de proceso a cinco minutos mientras
  Windows y Task Scheduler estén disponibles.
- El límite de una publicación por canal reduce el radio de impacto durante la
  observación, pero no elimina el riesgo de un cambio externo de contrato.

## Información desconocida

- Comportamiento de las tareas después de un reboot físico completo.
- Disponibilidad del host ante corte eléctrico o pérdida total de Internet.
- Contrato/versionado read-only del CMS.
- Canal final aprobado para entregar alertas fuera del host.

## Problemas reproducidos

### LVR-061 — Backlog anterior al corte podía salir en producción

- Severidad: alta.
- Archivos/funciones: colas bajo `data/`; `utils.queue_cutover`.
- Síntoma: 60 Web, 425 Meta y 23 estados sociales anteriores al 27/07.
- Causa raíz: faltaba una transición durable de archivo por fecha.
- Reproducción: `python cli.py queue-cutover --from-date 2026-07-27 --report-only`.
- Impacto: publicación de noticias antiguas y duplicados.
- Corrección: archivo durable, eventos, backups y cutoff de ingestión.
- Test: `tests.test_queue_cutover`.
- Evidencia: reporte posterior con Web 25, Meta 25, Social 0 y cero fechas previas.
- Estado: corregido.
- Riesgo residual: conservar y respaldar el archivo histórico.

### LVR-062 — Campo `tasks` roto en Graph API

- Severidad: alta por bloquear una validación previa al despliegue.
- Archivo/función: `utils/preflight.py::check_facebook`.
- Síntoma: HTTP 400 código 100 con token y página válidos.
- Causa raíz: campo removido del contrato actual.
- Reproducción: consulta read-only `fields=id,name,tasks`.
- Corrección: identidad `id,name` y capacidad mediante permisos.
- Test: `tests.test_preflight`.
- Evidencia: preflight Facebook real `success`.
- Estado: corregido.
- Riesgo residual: Meta puede volver a cambiar contratos.

### LVR-063 — Runners sociales recreaban entradas sin URL Web

- Severidad: alta.
- Archivos/funciones: `meta/run_fb.py`, `meta/run_ig.py`.
- Síntoma: una noticia de Meta podía entrar a social antes de sincronizar Web.
- Causa raíz: faltaba gate explícito de `web_url`.
- Reproducción: fixture Meta sin URL.
- Corrección: diferir y contabilizar `blocked_missing_web_url`.
- Test: `tests.test_social_stage_results`.
- Estado: corregido.
- Riesgo residual: una URL externa puede volverse inaccesible después del gate.

### LVR-064 — Verificación Instagram usaba un campo incorrecto

- Severidad: alta por producir resultado externo ambiguo.
- Archivo/función: `utils/canary.py`.
- Síntoma: ID publicado pero verificación `degraded`.
- Causa raíz: se consultaba `permalink_url` en vez de `permalink`.
- Corrección: campo por plataforma.
- Test: `tests.test_canary`.
- Evidencia: permalink verificado y cleanup confirmado.
- Estado: corregido.
- Riesgo residual: ninguno conocido para el campo actual.

### LVR-065 — Arranque no persistía ante caída de proceso

- Severidad: alta operativa.
- Archivos: `scripts/start_24x7_production.ps1`,
  `scripts/start_manual_video_ui.ps1`.
- Síntoma: cierre/crash dejaba el servicio apagado hasta intervención.
- Causa raíz: no había watchdog del host.
- Corrección: dos tareas programadas idempotentes cada cinco minutos.
- Evidencia: `LastTaskResult=0`, PID sin duplicar y UI HTTP 200.
- Estado: mitigado.
- Riesgo residual: reboot real no ensayado y sin watchdog externo al host.

### LVR-067 — Fecha desconocida eludía el cutoff de ingestión

- Severidad: alta.
- Archivo/función: `openIA/rewrite_news.py::_is_too_old`.
- Síntoma: fecha vacía o inválida no se consideraba anterior al corte.
- Causa raíz: tolerancia legacy incompatible con un cutoff estricto.
- Corrección: expirar con motivo explícito cuando la fecha no puede verificarse.
- Test: `tests.test_rewrite_recovery`.
- Estado: corregido.
- Riesgo residual: requiere revisión manual si una fuente deja de publicar fechas.

### LVR-068 — Test de canary no era hermético sin `.env`

- Severidad: alta por bloquear CI y ocultar dependencia en secretos locales.
- Archivo/función: `tests/test_canary.py`.
- Síntoma: local verde, Actions run `30306212406` rojo con URL vacía.
- Causa raíz: faltaba un token ficticio dentro del test de permalink.
- Corrección: entorno mockeado con `IG_ACCESS_TOKEN=test-token`.
- Evidencia: suite de 217 tests con `PYTHON_DOTENV_DISABLED=1`.
- Estado: corregido.
- Riesgo residual: pendiente confirmar el check remoto del nuevo commit.

## Problemas documentados pero no reproducidos

- Outcomes ambiguos reales de CMS/Meta.
- Pérdida de locks sobre un share de red; este host reporta disco local.
- Fallo de cleanup R2; la ejecución real confirmó eliminación.

## Problemas nuevos no corregibles en este repositorio

### LVR-066 — CMS sin preflight read-only

- Severidad: media para la operación actual; alta para un release formal.
- Archivo: configuración `WEBAPP_PREFLIGHT_PATH`.
- Síntoma: `preflight all` exit 3, CMS `blocked`.
- Causa raíz: el CMS no declara un endpoint autenticado de salud/capacidad.
- Solución propuesta: endpoint GET que devuelva JSON, versión y
  `capabilities.posts_create`.
- Test disponible: contrato en `tests.test_preflight`.
- Estado: bloqueado por repositorio/entorno externo.
- Mitigación: publicaciones reales limitadas, IDs/URLs, kill switch y rollback.

## Corte de colas

Comandos:

```powershell
python cli.py stop
python cli.py backup
python cli.py queue-cutover --from-date 2026-07-27 --report-only
python cli.py queue-cutover --from-date 2026-07-27 --apply
python cli.py queue-cutover --from-date 2026-07-27 --report-only
```

Resultado:

| Cola | Antes del corte | Activa al aplicar |
|---|---:|---:|
| Web | 60 archivadas | 28 |
| Meta | 425 archivadas | 25 |
| Social | 23 estados terminales | 0 |

Luego de tres publicaciones Web verificadas, la cola Web quedó en 24.

## Evidencia externa sanitizada

### Web

- Post ID 842:
  `https://lavozriojana.com/noticias/conductor-de-auto-se-da-a-la-fuga-tras-choque-en-av-santa-rosa`.
- Post ID 844:
  `https://lavozriojana.com/noticias/scioli-se-pronuncia-tras-el-intento-de-robo-en-su-casa-de-tigre`.
- Post ID 845:
  `https://lavozriojana.com/noticias/alerta-amarilla-por-viento-zonda-en-la-rioja`.

### Facebook

- ID verificado:
  `1243054632214236_122109833025372360`.
- Permalink:
  `https://www.facebook.com/122109833685372360/posts/122109833025372360`.
- Primer ciclo 24/7:
  `1243054632214236_122109834009372360`.

### Instagram

- Canary ID: `18207194662361611`.
- Se verificó permalink y luego se eliminó.
- La comprobación posterior confirmó que el objeto ya no existía.
- El primer ciclo no duplicó una nota similar ya presente.

## Arranque y recuperación

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\start_24x7_production.ps1 -ValidateOnly

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\start_24x7_production.ps1

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\start_manual_video_ui.ps1
```

Las tareas `LaVozRiojana-24x7` y `LaVozRiojana-ManualUI` ejecutan esos scripts cada
cinco minutos. No contienen tokens ni valores de `.env`.

## Estado de gates

| Gate | Estado | Bloqueo |
|---|---|---|
| Código | parcial | PR/review/merge |
| Host | completo | reboot real pendiente |
| Integraciones | parcial | CMS read-only |
| Canary | parcial | Instagram completo; no canary separado Web/FB |
| Observe | ejecutado | ninguno interno |
| Web | ejecutado | mantener límite |
| Facebook | ejecutado | mantener límite |
| Instagram | parcial | ciclo real deduplicado |
| Release 24/7 | bloqueado | merge/tag/CMS/reboot |

## Rollback

1. `python cli.py stop`.
2. Deshabilitar temporalmente las tareas programadas desde Task Scheduler.
3. Usar modo `observe` y apagar los tres kill switches.
4. Preservar colas, eventos y archivo de corte.
5. Restaurar sólo desde un backup identificado hacia un directorio temporal antes de
   tocar el target.
6. Verificar `doctor`, filesystem y heartbeat.
7. Rehabilitar una plataforma por vez.
