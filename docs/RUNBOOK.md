# Runbook de operación e incidentes

Última actualización: 2026-07-26.

## Principios

- No vaciar, editar ni reemplazar manualmente una cola activa.
- Detener el supervisor antes de una restauración.
- Conservar el archivo corrupto y su cuarentena; no convertirlo en `[]`.
- No probar credenciales o publicaciones contra cuentas reales durante un incidente
  sin autorización explícita del operador.
- Considerar `degraded` como atención requerida, aunque el proceso haya completado
  trabajo parcial.

## Diagnóstico inicial

```powershell
python cli.py status --json
python cli.py doctor --scope supervisor --json
python cli.py logs supervisor
```

Verifique:

1. identidad del PID;
2. `heartbeat.status` y `age_seconds`;
3. resultado de la última etapa;
4. tamaños y estado de lectura de las colas;
5. `error_type`, `error_code` y `next_retry_at`;
6. logs específicos de `scrapers`, `rewrite_news`, `publish_web`, `run_fb`,
   `fb_client`, `run_ig`, `ig_client` y `r2_storage`.

Un log inexistente es “sin evidencia”, no “sano”.

## Supervisor stale o detenido

1. Ejecute `status`; el comando es de sólo lectura y no elimina PIDs.
2. Si el PID pertenece a otro proceso o no existe, revise el heartbeat y el último
   log antes de retirar manualmente el archivo stale.
3. Ejecute `doctor --scope supervisor`.
4. Corrija configuración o corrupción antes de reiniciar.
5. Inicie con `python cli.py start` y confirme que el heartbeat cambia dentro de
   `PIPELINE_24X7_HEARTBEAT_SECONDS`.
6. Si vuelve a quedar stale, conserve heartbeat y logs para diagnóstico.

## Cola creciente

1. Identifique la cola y plataforma en `status --json`.
2. Compare `received`, `selected`, `succeeded`, `failed` y `deferred`.
3. Si hay rate limit, respete `next_retry_at`; no fuerce ciclos.
4. Si hay credencial inválida, deshabilite esa integración hasta rotarla.
5. Si existe `processing` tras un corte:
   - reescritura: el arranque recupera a `pending`;
   - social: un resultado externo ambiguo va a dead-letter para conciliación manual,
     evitando duplicar una publicación posiblemente realizada.
6. No elimine expirados ni dead-letter. Revise `data/queue_events.json` y el motivo.

## Token inválido

1. El resultado debe ser `failed` con `error_type=invalid_credential`.
2. Deshabilite temporalmente `FB_PUBLISH_ENABLED` o `IG_PUBLISH_ENABLED`.
3. Rote el token fuera de logs y git.
4. Ejecute `doctor --scope facebook` o `doctor --scope instagram`.
5. Use un comando de verificación seguro en un entorno de prueba. No publique para
   comprobar un token.
6. Rehabilite la etapa y observe un ciclo. El fallback directo de Facebook permanece
   deshabilitado salvo opt-in consciente.

## Rate limit

1. No reintente antes de `next_retry_at`.
2. Confirme el backoff persistido en el estado de la plataforma.
3. Reduzca temporalmente el tamaño del lote si el patrón se repite.
4. Un lote parcial debe quedar `degraded`; las entradas no procesadas permanecen
   pendientes.

## Scraper roto

1. Distinga `no_work` de `failed`; HTTP, timeout y mismatch de selectores son fallos.
2. Reproduzca primero con la fixture correspondiente.
3. Guarde una fixture HTML sanitizada del nuevo contrato.
4. Agregue un test que falle y recién después ajuste selectores compartidos.
5. Ejecute `python -m unittest tests.test_scraper_fixtures -v`.
6. La prueba manual contra el tercero es read-only y complementaria; su
   disponibilidad no se confunde con el contrato local.

## JSON corrupto

1. Detenga el supervisor.
2. No abra y guarde el archivo con herramientas que lo sobrescriban.
3. Confirme la copia en `data/quarantine/`.
4. Liste backups:

   ```powershell
   Get-ChildItem data\backups
   ```

5. Valide el backup fuera de `data/`.
6. Restaure con:

   ```powershell
   python cli.py restore --backup <ruta-backup> --target <archivo.json>
   ```

   El comando valida nombres/rutas y respalda el estado actual antes de reemplazarlo.
7. Ejecute `status` y los tests específicos de persistencia antes de reiniciar.

## Backup y restauración

Las escrituras crean backups configurables con `JSON_BACKUP_ENABLED`,
`JSON_BACKUP_MIN_INTERVAL_SECONDS` y `JSON_BACKUP_RETENTION_COUNT`.

```powershell
python cli.py backup
python cli.py backup --file noticias_web_pending.json
```

Pruebe restauraciones sobre un `LVR_DATA_DIR` temporal. Un backup no está validado
hasta que se pudo leer y restaurar.

## Rollback de código

1. Detenga el supervisor.
2. Cree un backup completo de los JSON válidos.
3. Registre commit, heartbeat y tamaños de cola.
4. Revierta al commit anterior mediante un commit de reversión; no use
   `git reset --hard` sobre el host operativo.
5. Si el formato de estado cambió, use la migración/rollback documentada. Esta línea
   de base mantiene los JSON legacy y agrega `rewrite_queue_state.json`; no requiere
   reescribir datos existentes.
6. Ejecute `doctor --scope supervisor`, suite local y `run-once --dry-run`.
7. Reinicie y controle el primer ciclo sin forzar publicaciones.

## Publicación ambigua

Si una llamada social se cortó luego de ser aceptada pero antes de devolver ID, no
republique automáticamente. La entrada debe quedar en dead-letter con motivo
`ambiguous_external_outcome`. Concilie en la plataforma, registre ID/URL si existe y
recién entonces complete o reencole la entrada.

## CI fallido

1. Reproduzca exactamente los comandos de `README.md`.
2. Si falla instalación o `pip check`, corrija `requirements.txt`; no instale una
   dependencia suelta sólo en el runner.
3. Si falla el dry-run, confirme `details.production_calls=false`.
4. Si el árbol queda dirty, identifique el artefacto y rediríjalo a `runner.temp`.
5. No ignore deprecaciones ni convierta `degraded` en éxito.

## Preflight fallido o bloqueado

```powershell
python cli.py preflight --scope <scope> --json
```

- `blocked`: falta credencial, endpoint o autorización; no habilite el canal.
- `failed`: corrija identidad, permiso, contrato, selector o filesystem.
- `degraded`: atienda cleanup, permiso incompleto, rate limit o fuente parcial.
- R2 con `cleanup_error`: conserve el object key, elimínelo manualmente y verifique la
  ausencia antes de repetir.
- CMS sin endpoint GET seguro: mantenga web apagada y coordine el cambio en el
  repositorio del CMS.

## Canary parcial o cleanup fallido

1. No repita el comando si figura `ambiguous_external_outcome`.
2. Busque `canary_id`, `external_id` y `public_url` en la plataforma.
3. Concilie primero; no cambie `canary_runs.json` a mano.
4. Si el proveedor admite cleanup:

   ```powershell
   python cli.py canary --input <fixture> --channels <canales> --cleanup `
     --confirm-external-publication --json
   ```

5. Si `cleanup_supported=false`, retire la pieza manualmente y registre evidencia.
6. Un canary parcial impide avanzar el gate del canal.

## Webhook de alertas caído

1. El pipeline continúa; revise `alert_outbox.json`.
2. Corrija DNS/TLS/URL o respete `next_retry_at`.
3. Ejecute `python cli.py alert-check --json`.
4. No borre eventos fallidos. Rote la URL si contiene un secreto.
5. Si no hay proveedor aprobado, opere con outbox local y un procedimiento de
   revisión; documente el riesgo de no tener watchdog externo.

## Conciliación Facebook

1. Detenga Facebook con `FB_PUBLISH_ENABLED=false`.
2. Genere reporte:

   ```powershell
   python cli.py reconcile-facebook --report-only --output fb-report.json --json
   ```

3. Revise `already_published`, `pending_valid`, `expired`, `duplicate`, `ambiguous`,
   `invalid` y `blocked_missing_web_url`.
4. Prepare un archivo con el mismo `report_id` y decisiones por `item_id`.
5. `mark_published` requiere `external_id`; no use título como evidencia.
6. Aplique:

   ```powershell
   python cli.py reconcile-facebook --apply fb-decisions.json --json
   ```

7. Regenere el reporte. No habilite Facebook si quedan entradas sin clasificar o
   decisiones pendientes.

## Cambio o rollback de deployment mode

1. Detenga el supervisor.
2. Registre commit, modo, fingerprint, colas y backup.
3. Para rollback inmediato, configure `PIPELINE_DEPLOYMENT_MODE=observe` y apague:

   ```text
   WEB_PUBLISH_TARGET=off
   FB_PUBLISH_ENABLED=false
   IG_PUBLISH_ENABLED=false
   ```

4. Ejecute `doctor --scope supervisor` y `preflight supervisor`.
5. Reinicie sólo si la configuración es coherente.
6. No salte de `observe` a `all`; avance un canal por vez.

## Deshabilitar una plataforma

1. Detenga el supervisor.
2. Baje su kill switch y seleccione un modo que no solicite ese canal.
3. Ejecute `doctor`.
4. Reinicie y verifique que el heartbeat muestre el canal `no_work` con
   `disabled=true`.
5. No elimine pendientes; permanecen para conciliación/reanudación.

## Espacio bajo

1. `disk_space_low` usa `DISK_FREE_MIN_MB`.
2. Detenga publicación antes de quedar sin espacio.
3. Archive logs/backups según retención; no borre colas ni cuarentenas sin análisis.
4. Ejecute `preflight filesystem` y una restauración temporal antes de reiniciar.

## Rotación de credenciales

1. Apague el kill switch del canal.
2. Rote la credencial fuera de git y logs.
3. Ejecute el preflight read-only del canal.
4. Verifique permisos e identidad esperada.
5. Rehabilite sólo tras canary autorizado y gate aprobado.

## Descarga de video fuente falla o cae a imagen (yt-dlp)

1. En la UI manual de reels (`python cli.py videos`), el resultado de
   `/api/render-video` incluye `source_used` y, si cayó a imagen, `fallback_reason`
   con `error_type`. Revíselo antes de asumir que la plataforma bloqueó la descarga.
2. `error_type=not_installed`: `yt-dlp` no está en el PATH del entorno que corre el
   proceso. Confirme con `python cli.py doctor --scope all` (sección "Binarios de
   sistema"/`yt-dlp version`); reinstale con `pip install -r requirements.txt` dentro
   del venv activado.
3. `error_type=extractor_error`: la plataforma cambió algo y el extractor de yt-dlp
   quedó desactualizado. Ejecute `pip install -U yt-dlp` y reintente manualmente antes
   de escalar — suele resolverse en horas/días porque el proyecto libera fixes seguido.
4. `error_type=auth_required`: la plataforma pide sesión iniciada para ese contenido
   (típico en Instagram/TikTok). Exporte cookies de una sesión de navegador
   autenticada con una **cuenta dedicada** (no la cuenta editorial principal), guarde
   el archivo `cookies.txt` fuera del repo y configure `YTDLP_COOKIES_FILE` con su
   ruta. No automatice el login (usuario/contraseña por script): aumenta el riesgo de
   bloqueo de esa cuenta. Renueve el archivo de cookies cuando vuelva a fallar.
5. `error_type=rate_limit`/`network_error`: son transitorios (`degraded`); reintente
   más tarde, no hace falta acción de configuración.
6. `error_type=unsupported_url`/`file_too_large`: son definitivos para ese link — no
   reintente sin cambiar la URL o el límite (`VIDEO_DOWNLOAD_MAX_BYTES`).
7. El fallback a imagen (Ken Burns) o a overlay solo nunca es un error del sistema:
   es el comportamiento esperado cuando no hay video disponible; el objetivo de este
   runbook es distinguir "no había video" de "había video pero la descarga falló".

## Rollback de release

1. No borre el tag ni reescriba `main`.
2. Detenga el supervisor y ponga modo `observe`.
3. Cree backup y pruebe restore temporal.
4. Despliegue un commit de reversión aprobado.
5. Registre nuevo `commit_sha`, `release_tag`, operador y backup.
6. Repita Gate B y preflight antes de iniciar.

## Arranque operativo del host 2026-07-27

El `.env` histórico no se modifica ni se imprime. El perfil operativo está en un
script sin secretos:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\start_24x7_production.ps1 -ValidateOnly

powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\start_24x7_production.ps1
```

El script:

1. exige el `venv` del repositorio;
2. fija `PIPELINE_DEPLOYMENT_MODE=all`;
3. enciende los tres kill switches de forma explícita;
4. fija `ARTICLE_NOT_BEFORE_DATE=2026-07-27`;
5. mantiene `CANARY_ENABLED=false`;
6. habilita alertas con outbox local y sin webhook;
7. registra metadata de despliegue;
8. ejecuta `doctor --scope supervisor`;
9. sólo inicia si el doctor devuelve exit `0`.

El modo `all` inyecta un máximo de una publicación por canal y ciclo. No aumentar
los límites legacy del `.env` durante la observación inicial.

Verificación:

```powershell
python cli.py status --json
Get-Content logs\run_24x7.log -Tail 40
```

El estado esperado es heartbeat `fresh`, proceso coincidente, modo `all` y colas sin
estado `corrupt`/`error`. `no_work` es aceptable.

## Watchdog de Windows

El host usa dos tareas cada cinco minutos:

- `LaVozRiojana-24x7`;
- `LaVozRiojana-ManualUI`.

Ambas son idempotentes. Comprobar:

```powershell
Get-ScheduledTask -TaskName LaVozRiojana-24x7,LaVozRiojana-ManualUI
Get-ScheduledTaskInfo -TaskName LaVozRiojana-24x7
Get-ScheduledTaskInfo -TaskName LaVozRiojana-ManualUI
```

`LastTaskResult=0` es el resultado esperado. Después de un reinicio real:

1. confirmar que ambas tareas volvieron a ejecutar;
2. verificar PID/heartbeat;
3. abrir `http://127.0.0.1:8765/`;
4. confirmar que el puerto 8765 escucha sólo en `127.0.0.1` o `::1`;
5. no habilitar exposición externa para la UI.

Si una tarea se elimina accidentalmente, volver a registrarla con una acción que
invoque el script correspondiente bajo `scripts/`. No incluir secretos en la acción.

## Corte de colas por fecha

Nunca edite ni vacíe los JSON manualmente. Para inspeccionar:

```powershell
python cli.py queue-cutover --from-date 2026-07-27 --report-only
```

La aplicación requiere supervisor detenido y autorización operativa:

```powershell
python cli.py stop
python cli.py backup
python cli.py queue-cutover --from-date 2026-07-27 --apply
```

El comando archiva payloads completos, registra eventos y conserva backups. Una fecha
desconocida bloquea el corte; no se interpreta como noticia vieja ni se descarta.

## UI manual de videos

Inicio o comprobación idempotente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\start_manual_video_ui.ps1
```

El script rechaza un listener externo y un servicio desconocido ocupando el puerto.
La URL autorizada es únicamente `http://127.0.0.1:8765/`.
