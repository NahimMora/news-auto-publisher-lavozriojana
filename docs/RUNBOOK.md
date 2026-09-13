# Runbook de operación e incidentes

Última actualización: 2026-08-21.

## Principios

- No vaciar, editar ni reemplazar manualmente una cola activa.
- Detener el supervisor antes de una restauración.
- Conservar el archivo corrupto y su cuarentena; no convertirlo en `[]`.
- No probar credenciales o publicaciones contra cuentas reales durante un incidente
  sin autorización explícita del operador.
- Considerar `degraded` como atención requerida, aunque el proceso haya completado
  trabajo parcial.

## Entorno: desarrollo vs. producción (2026-08-21)

Desde el 2026-08-21 hay dos hosts físicamente distintos con roles que no se mezclan.
Ver la decisión completa en `docs/DECISIONS.md` (2026-08-21) y el incidente que la
motivó en `docs/KNOWN_ISSUES.md` #84.

| | Desarrollo (esta PC, `pc10`) | Producción (PC dedicada, `PC@192.168.1.150`, `C:\LVR`) |
|---|---|---|
| Rol | escribir código, correr tests, revisar renders, editar docs | única instancia que publica de verdad |
| `venv`, `.env`, `data/` | propios, aislados; `.env` **sin** credenciales productivas reales para correr el servicio | credenciales reales, `data/` es el historial/dedup autoritativo |
| `python cli.py start` / `run_24x7.py` / `video_reel_manager.py` | **prohibido correrlos directo** | es donde corren, vía las tareas programadas |
| `scripts/register_scheduled_tasks.bat` | **nunca ejecutarlo acá** | ya ejecutado; `LaVozRiojana-24x7`/`LaVozRiojana-ManualUI` viven sólo ahí |
| Acceso | local | SSH con clave (`ssh -i ~/.ssh/id_ed25519_lvr PC@192.168.1.150`) |

**Regla dura: el servicio no se vuelve a levantar en esta PC de desarrollo, bajo
ningún motivo.** El incidente de `docs/KNOWN_ISSUES.md` #84 fue exactamente eso —
tareas programadas locales olvidadas relanzando el pipeline completo con
credenciales reales, en paralelo a la instancia de producción, con riesgo real de
publicar contenido duplicado en Facebook/Instagram.

### Flujo de cambios: acá se prueba, allá se publica

1. **Desarrollar y probar en esta PC** — tests (`python -m unittest discover
   tests`), validación visual de Remotion, smoke test manual de la UI en
   `127.0.0.1:8765` con `.env` de QA (sin credenciales reales o con
   `PIPELINE_DEPLOYMENT_MODE=observe`/kill switches apagados). Nunca contra las
   cuentas reales desde acá.
2. **Commit y push** a una rama, PR contra `main` (branch protection exige el check
   `reliability-windows`).
3. **Merge** una vez que CI pasa y hay revisión.
4. **Desplegar el cambio en producción por SSH**:

   ```powershell
   ssh -i ~/.ssh/id_ed25519_lvr PC@192.168.1.150
   cd C:\LVR
   git pull origin main
   ```

   Si el cambio toca `requirements.txt` o `remotion/package.json`, además:

   ```powershell
   venv\Scripts\python.exe -m pip install -r requirements.txt
   cd remotion && npm i && cd ..
   ```

5. **Reiniciar el backend** para que tome el código nuevo (el proceso corriendo no
   recarga módulos solo):

   ```powershell
   venv\Scripts\python.exe cli.py stop
   ```

   El supervisor detenido vuelve a levantarse solo en el próximo disparo de la tarea
   `LaVozRiojana-24x7` (cada 5 minutos) ya con el código actualizado. Para no esperar:

   ```powershell
   powershell -NoProfile -Command "Start-ScheduledTask -TaskName 'LaVozRiojana-24x7'"
   ```

6. **Verificar** antes de dar el despliegue por bueno:

   ```powershell
   venv\Scripts\python.exe cli.py status --json
   venv\Scripts\python.exe cli.py doctor --scope supervisor --json
   ```

   Confirmar `heartbeat.status: fresh`, `overall_status: success` (o `no_work`, es
   sano), y que `supervisor.pid` sea un único PID coherente — si hay dudas de
   duplicados, ver el chequeo de la siguiente sección antes de asumir que está bien.

### Cómo confirmar que no hay una segunda instancia corriendo

El PID del supervisor vive en `data/.supervisor.pid`. Cualquier operación que
reemplace `data/` completo (una migración, un restore) sin que el supervisor viejo
esté detenido primero rompe ese rastreo — `cli.py start` deja de detectar la
instancia previa y arranca una segunda en paralelo sin avisar (exactamente lo que
pasó en el incidente #84). Antes de cualquier operación así, o ante cualquier duda:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'LVR' } | Select-Object ProcessId,ParentProcessId,Name,CreationDate
```

Una sola cadena de procesos con timestamps de creación coherentes (no dos tandas con
horarios de arranque distintos) es lo esperado. Si aparecen dos generaciones, matar
ambas, borrar `data/.supervisor.pid` y reiniciar una sola vez.

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

## Fuente paparazzi.com.ar (farándula) y cupo 8+2 de Instagram

Ver decisión completa en `docs/DECISIONS.md` (2026-08-05).

1. **Activar**: `SCRAPER_PAPARAZZI_ENABLED=1` habilita el scraping
   (`python main_paparazzi.py` para correrlo suelto). `IG_PAPARAZZI_MAX_PER_RUN`
   (default 2) controla cuántas se publican por ciclo, además — no en vez — de las
   `IG_MAX_PER_RUN` generales.
2. **429 de Cloudflare**: el sitio rate-limitea sin pausa entre requests.
   `PAPARAZZI_REQUEST_DELAY_SECONDS` (default 2.5s) ya lo evita en uso normal; si
   vuelve a aparecer, subir el valor antes que bajar `SCRAPER_MAX_LINKS`.
3. **Nota sin video / video "perdido"**: es esperado — no todas las notas embeben
   JWPlayer, y la resolución contra `cdn.jwplayer.com/v2/media/{id}` puede fallar sin
   romper el scraping (`scraping/base_paparazzi.py::_extract_video` degrada
   silenciosamente). La nota igual se publica, solo con imagen
   (`post_to_instagram_detailed`, no carrusel).
4. **Clip de video no se genera**: revisar `ffmpeg` en PATH
   (`python cli.py doctor --scope all`) y el log de `video_renderer` — un fallo acá
   también cae a imagen sola, nunca bloquea la publicación.
5. **Conteo por ciclo distinto de 8+2**: revisar `meta/run_ig.py::main()` — selecciona
   dos pools (`get_pending(..., exclude_source_prefix="paparazzi")` y
   `get_pending(..., source_prefix="paparazzi")`) y los concatena; si el pool general
   ya trae paparazzi mezclado, algo está mal seteando `noticia["source"]` río arriba
   (debe ser exactamente `"paparazzi"`, ver `scraping/base_paparazzi.py`).

## Reel independiente de paparazzi (video solo), motor 127.0.0.1:8765

Ver decisión completa en `docs/DECISIONS.md` (2026-08-10).

1. **Activar**: `PAPARAZZI_REEL_ENABLED=true` en `.env` (default `false` — no cambia
   nada hasta activación explícita). Además requiere R2 configurado y al menos uno de
   `IG_PUBLISH_ENABLED`/`FB_PUBLISH_ENABLED` en `true`; cada plataforma se publica
   independientemente según su propio switch.
2. **Cuándo dispara**: sólo justo después de que el carrusel estándar de una nota de
   paparazzi con video se publicó con éxito en Instagram (`meta/run_ig.py`, dentro del
   ciclo normal — no es un script/canal separado). Notas sin `video_url` (imagen sola)
   nunca generan Reel.
3. **No se publicó ningún Reel pese al flag activo**: revisar
   `logs/paparazzi_reels.log`. Motivos esperados: el video fuente no se pudo descargar
   al momento de renderizar (cae a imagen/overlay — este flujo nunca publica ese
   fallback, sólo "el video solo"), R2 no configurado, o la nota ya tiene un registro
   en `data/paparazzi_reels_posted.json` (dedup propio, independiente del
   `ig_posted.json`/`fb_posted.json` del carrusel).
4. **Se publicó en una plataforma pero no en la otra**: es un resultado válido
   (`ig_ok`/`fb_ok` independientes) — revisar el `error_type` logueado para esa
   plataforma puntual; no reintenta solo, hay que resolver la causa y re-disparar el
   ciclo.
5. **Verificar sin publicar**: `python -m unittest tests.test_paparazzi_reels -v`
   (mocks — no toca cuentas reales).

## Estadísticas de Instagram y promoción de candidatas por rendimiento

Ver decisión completa en `docs/DECISIONS.md` (2026-08-05).

1. **Ver el snapshot actual**: `data/ig_category_performance.json` — `updated_at`,
   `overall.engagement_rate` y `categories.<categoria>.{engagement_rate,sample_size}`.
   Se actualiza cada ciclo (`meta/ig_insights.py`, solo lectura).
2. **Nada se promueve todavía**: revisar `sample_size` por categoría contra
   `IG_STATS_MIN_SAMPLE_SIZE` (default 5) — con la cuenta joven, la mayoría de las
   categorías no van a alcanzar la muestra mínima hasta acumular más historial.
3. **Apagar solo la promoción sin perder la recolección**:
   `IG_STATS_PROMOTION_ENABLED=false` (mantiene `IG_STATS_ENABLED=true` recolectando
   para cuando haya más historial). Apagar `IG_STATS_ENABLED` detiene también la
   recolección.
4. **Candidata promovida que no debería**: revisar `route_reason` de la noticia
   (`editorial_candidates.json` o `noticias_meta.json`) — debe incluir
   `category_performance:<categoria>`. El tope por tema (`TOPIC_AUTOMATIC_CAP`) sigue
   aplicando igual; si una nota pasó pese a estar sobre el tope, es un bug, no el
   comportamiento esperado de esta función.
5. **Ajustar qué tan exigente es la promoción**: `IG_STATS_PROMOTION_THRESHOLD_RATIO`
   (default 1.0 = igual o mejor que el promedio de la cuenta; subirlo lo hace más
   exigente) y `IG_STATS_MIN_SAMPLE_SIZE` (default 5; subirlo exige más historial antes
   de confiar en una categoría).

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

## Publicación social rechazada

1. No reencole automáticamente un evento `request_rejected`.
2. Revise `logs/run_fb.log` o `logs/run_ig.log` y el evento correspondiente en
   `data/queue_events.json`.
3. Use `http_status`, `provider_code`, `provider_subcode` y `provider_type`; el cuerpo
   arbitrario de Meta no se persiste.
4. Ejecute el preflight read-only del canal. Si el siguiente ciclo vuelve a fallar,
   baje a `web_facebook` o `web_instagram` según corresponda y apague el kill switch
   de la integración afectada.
5. Concilie el ID/estado en Meta antes de cualquier decisión manual de reencolado.

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
4. desactiva el cutoff por fecha editorial y usa la línea de base durable de colas;
5. mantiene `CANARY_ENABLED=false`;
6. habilita alertas con outbox local y sin webhook;
7. registra metadata de despliegue;
8. ejecuta `doctor --scope supervisor`;
9. sólo inicia si el doctor devuelve exit `0`.

El modo `all` inyecta Web sin límite de lote (`0` y sin cupo por categoría) y un
máximo de 8 publicaciones por plataforma Meta y ciclo. Los kill switches siguen
siendo autoritativos.

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

## Línea de base por últimas noticias

Cuando la fecha editorial falta o no es confiable, no se debe inferir antigüedad.
Con el supervisor detenido:

```powershell
python cli.py queue-cutover --keep-latest 20 --report-only --json
python cli.py backup
python cli.py queue-cutover --keep-latest 20 --apply --json
python cli.py queue-cutover --keep-latest 20 --report-only --json
```

El primer reporte no modifica archivos y debe indicar `unknown_order=0`. La
aplicación conserva las 20 identidades más recientes usando `web_queued_at` y
`queued_at`, archiva payloads anteriores y registra eventos. Un timestamp durable
ausente bloquea toda la operación. “Excluido de la línea de base” no equivale a
“publicado”: sin ID o URL externa nunca se crea esa evidencia.

## Feedback editorial y sexto intento

Cada revisión envía a OpenAI los warnings exactos, instrucciones por tipo y el
payload normalizado del intento anterior. `revision_history` registra campos
cambiados y cambios materiales. Cambiar sólo `quality_score` no cuenta como
corrección.

Con `EDITORIAL_FINAL_ATTEMPT_ACTION=publish_last_safe`, el sexto intento se publica
sólo si quedan observaciones de calidad/similitud. Cifras, fechas o nombres
inventados, afirmaciones judiciales inseguras y HTML no permitido siguen bloqueando
el resultado. Una publicación del sexto intento queda `degraded` y genera evento.

## Preview de Facebook

Antes de Graph, Facebook arma:

```text
caption exacto de Instagram

URL pública de la noticia
```

(sin el título de la noticia antepuesto).

Con `FB_LINK_PREWARM_ENABLED=true`, el cliente descarga la nota con user-agent del
crawler de Facebook, exige HTML, extrae un `og:image` público, lo descarga con límite
de tamaño y recién entonces publica. Un timeout, HTTP inválido, Content-Type
incorrecto o imagen ausente deja la noticia pendiente como `degraded`; no se llama a
Graph. Revisar `logs/fb_client.log` y la disponibilidad pública de CMS/R2 antes de
reintentar.

Ese prewarm sólo valida desde la red de la propia app (nunca llama a Facebook), así
que puede pasar aunque el crawler real de Facebook no pueda scrapear la URL todavía.
Por eso, justo antes de publicar un post de tipo link, `force_facebook_rescrape`
llama a Graph (`POST /?id=<url>&scrape=true`) para forzar el mismo refresh que el
botón "Scrape Again" del Sharing Debugger. Es best-effort: si falla, sólo queda un
warning en `logs/fb_client.log` y la publicación sigue igual.

## UI manual de videos

Inicio o comprobación idempotente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\start_manual_video_ui.ps1
```

El script rechaza un listener externo y un servicio desconocido ocupando el puerto.
La URL autorizada es únicamente `http://127.0.0.1:8765/`. Además de las pestañas
Videos y Publicaciones, incluye Estudio Premium y Candidatas (ver más abajo).

### Sistema visual de Reels

`REEL_CINEMATIC_VISUAL_STYLE_ENABLED=false` conserva la composición histórica
`Main`. Para habilitar la versión profesional exclusivamente en la pestaña
**Videos**, fijar el flag en `true` y reiniciar sólo la UI manual para que vuelva a
cargar `.env`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\start_manual_video_ui.ps1
```

La versión nueva informa `visual_style=editorial_cinematic_v2` en la respuesta de
`/api/render-video`, incorpora su cierre de tres segundos en la misma composición y
no usa el outro legacy de `data/media/outro.mp4`. Generar una vista previa no publica
en Meta; el botón **Publicar IG + FB** sigue siendo una acción externa separada. Para
rollback visual, volver el flag a `false` y reiniciar sólo la UI.

La escala activa reserva 164 px para cabecera, 78 px para la bandera de sección y
104 px para la firma inferior. Si se ajustan esos valores en `EditorialReel.tsx`, se
deben renderizar al menos un título largo en el frame de lectura y un frame del cierre;
agrandar fuentes sin mover `REEL_MEDIA_TOP`/`REEL_PANEL_BOTTOM` puede volver a invadir
el título o el footer.

En la fase compacta, sección y titular deben verse como un solo grupo, y el titular
debe terminar cerca del panel/footer sin tocarlo. La regresión mínima requiere un
título largo con frase destacada: revisar un frame antes de compactar, uno durante la
transición y otro después; ninguna línea debe volver a partirse dentro del span
coloreado, cortarse o dejar una franja negra amplia arriba o debajo. El estado final
debe volver a repartir palabras para ocupar el ancho útil; no debe verse como el
layout grande simplemente encogido y cargado hacia la izquierda.

### Publicaciones personalizadas

En la pestaña **Publicaciones**, el título admite de 8 a 120 caracteres. El límite
se valida en el navegador y nuevamente en el backend; un borrador anterior más largo
debe editarse y nunca se trunca en silencio. Use **Vista previa** antes de publicar:
la imagen resultante es la misma que consumirá el publicador de Instagram.

La card ajusta el tamaño del título hasta un piso legible, usa hasta cinco líneas y
reserva el footer. El panel degradado crece o baja según la altura medida del título,
la localidad y la bajada; no requiere que el operador complete espacio manualmente.
La sección aparece dentro de una bandera Premium (azul noche en
Editorial). Una frase de 2 a 4 palabras contiguas del título se destaca automáticamente
en rojo (Crónica) o azul (Editorial). Debe expresar acción + objeto, sujeto + decisión
o resultado principal; no puede ser sólo lugar, fecha ni un cierre genérico. Una frase
al final sólo se admite si allí está el hecho principal. El backend exige copia exacta
del título y aplica estas reglas también cuando usa el selector local sin OpenAI. La
ausencia de localidad o bajada sigue siendo válida y no bloquea la vista previa.

La card manual se genera en **2160×2700 (4:5)**, aunque el navegador la muestre
reducida para entrar en la pantalla. El JPEG usa alta calidad y color 4:4:4 para que
texto y acentos toleren mejor el zoom en PC. No redimensione el preview para
publicar: el botón de publicación vuelve a usar el mismo renderer 2×.

Para que el autopublicador use exactamente ese paquete visual:

```text
AUTOMATIC_MANUAL_VISUAL_STYLE_ENABLED=true
```

El default de código es `false`: un deploy no cambia producción por sí solo. Con el
flag activo, Instagram automático usa el mismo recuadro de sección, panel/título
adaptable, frase relevante y JPEG 2160×2700/4:4:4. La tarjeta OG adopta el recuadro y
el highlight dentro de su proporción 1200×630. Las entradas antiguas sin
`highlight_terms` derivan una frase localmente sin llamar a OpenAI. El costo de render
y transferencia del automático aumenta; apagar el flag restaura 1080×1350 y la
geometría anterior sin migrar colas.

No use el botón **Publicar (Web + IG + FB)** para QA. Para una prueba integral sin
llamadas externas, arranque la UI con `CUSTOM_POST_DRY_RUN=true` y directorios
`LVR_*_DIR` temporales.

## Router editorial (candidatas de Instagram)

Modo report-only, no modifica nada:

```powershell
python cli.py editorial-route --report-only --json
python cli.py editorial-route --report-only --limit 20
```

Muestra, para el historial reciente de `noticias_meta.json`, la ruta propuesta por
canal, el `topic_key`, el motivo y la excepción aplicada (breaking/material_update)
sin tocar `data/topic_publication_state.json` ni `data/editorial_candidates.json`.

El router siempre calcula y persiste metadata de ruteo durante la reescritura
(aditivo, no cambia colas). Sólo la selección automática de Instagram se restringe
de verdad, y sólo si:

```text
EDITORIAL_ROUTER_ENABLED=true
```

Con el flag apagado (default), `meta/run_ig.py` ignora `route_by_channel` y se
comporta exactamente como antes de esta rama. Antes de activar el flag en
producción, correr `editorial-route --report-only` sobre el historial real y
revisar cuántas noticias quedarían como candidatas.

Candidatas: se gestionan desde la pestaña "Candidatas" de la UI manual. La bandeja
muestra primero las entradas pendientes más recientes, con motivo, origen, tema e
identidad. `Enviar a automática` y `Descartar` aplican las transiciones declaradas;
`Enviar a automática` es un override editorial explícito y habilita Instagram aunque
la categoría no figure en `IG_ALLOWED_CATEGORIES` o la noticia todavía no tenga URL
Web. Esta excepción es sólo para Instagram; Facebook y el flujo automático normal
siguen esperando la URL. No saltea deduplicación, validación de imagen, kill switch,
rate limits ni estados ambiguos. Si la rotación ya retiró la noticia de
`noticias_meta.json`, el próximo bootstrap puede restaurarla desde el payload durable
de la candidata; la métrica `restored_from_candidate_store` deja esa ruta visible.
Para una
publicación reutilizada, `Quitar de candidatas` conserva intacta la evidencia histórica
y nunca la republica. El panel secundario permite mover por identidad una automática
pendiente o agregar una ya publicada para reutilización premium. También se pueden
listar directamente:

```powershell
python -c "from utils.editorial_router import list_candidates; import json; print(json.dumps(list_candidates(channel='instagram', status='candidate'), ensure_ascii=False, indent=2))"
```

## Biblioteca multimedia

```powershell
python cli.py media-library search --query incendio --json
python cli.py media-library search --candidatas --publicadas --json
python cli.py media-library cleanup                 # dry-run (default)
python cli.py media-library cleanup --apply          # purga real de assets vencidos
```

El cleanup nunca borra metadata histórica, sólo archivos físicos vencidos y sin
referencias de borradores activos (`files_purged=true` en `data/media_library.json`).
No ejecutar `cleanup --apply` durante una publicación premium activa.

## Estudio Premium (publicaciones sociales sin artículo web)

Pestaña "Estudio Premium" en la UI manual (`http://127.0.0.1:8765/`). El flujo
visible tiene cuatro pasos:

1. Pegar el texto actualizado de la noticia y tocar **Generar estructura con IA**.
   OpenAI sólo estructura ese texto; no investiga ni completa datos. Si falta
   credencial, falla el proveedor o devuelve JSON inválido, se muestra el error y no
   se crea un fallback silencioso. El import JSON manual sigue disponible como
   alternativa secundaria. La generación exige un título informativo de 60 a 80
   caracteres, 3 o 4 slides con contenido suficiente para comprender toda la noticia
   sin leer el caption y un caption con apertura local clara, emojis pertinentes,
   fuente sólo cuando aparece en el original y 3 a 6 hashtags (incluido `#LaRioja`).
   Si la respuesta no cumple, el generador reintenta con una lista concreta de
   correcciones y conserva el JSON erróneo como mensaje anterior de la conversación;
   nunca inventa contexto para alcanzar una extensión. Si se agotan los intentos pero
   existe un JSON parseable, carga el último resultado en el editor con avisos
   `generación IA:` para revisión manual. Los errores de proveedor o una secuencia sin
   ningún JSON parseable siguen bloqueando la operación de forma visible.
2. Revisar título, caption, sección, plantilla y cada slide. Se pueden editar título,
   texto, ítems, highlights, tipo y orden. Cada tipo puede aparecer una sola vez:
   las opciones ya usadas quedan deshabilitadas y no existe duplicación de slides.
   Un JSON importado con tipos repetidos se conserva como borrador inválido para no
   perder texto, pero la publicación requiere corregirlo. La generación IA dispone
   de `impact` como placa textual sin foto para impacto local o próximos pasos; si
   devuelve dos `context`, el segundo pasa a `impact` sin alterar su contenido. La
   vista Remotion usa
   una escala Premium ampliada para que cuerpos, tarjetas, chips, cabecera de sección,
   footer, numeración y citas sigan siendo legibles en pantalla de celular; las cards
   automáticas mantienen su escala previa.
3. Los controles de imagen aparecen sólo para `cover`, `image_text` y `full_image`.
   Tocar **Abrir galería** en uno de esos slides abre un selector compacto dirigido
   a ese slide; un click en una miniatura la ingresa si hace falta, la asigna y guarda
   el borrador en el mismo paso. El panel **Agregar otra imagen** permite link público
   directo o archivo propio. Los links se validan contra SSRF, redirects,
   Content-Type y límite de 20 MB; las subidas se validan por firma/contenido. Ambos
   caminos terminan en `utils.media_library.ingest_image_bytes`, con deduplicación
   por hash. Las miniaturas se sirven sólo por
   `/api/media-library/thumb/{asset_id}`, nunca como rutas locales.
4. Guardar borrador, previsualizar y recién entonces publicar. Preview y publicación
   sincronizan primero el editor actual y usan
   `utils.premium_renderer.render_package_with_engine`; así una imagen recién
   asignada no queda fuera por estar leyendo una versión anterior del borrador.

El flujo nunca crea artículo web ni depende del CMS; Facebook nunca incluye link.
Guardar/generar un borrador tampoco publica nada.

Antes de un canary real:

```powershell
$env:PREMIUM_PUBLISH_DRY_RUN="true"
python cli.py videos
```

Con el dry-run activo, `/api/premium/publish` completa sin llamar a ninguna API real
(`channel_results` queda con IDs `dry-run-<canal>`). Nunca activar publicaciones
premium reales sin autorización explícita del operador, igual que el resto del
pipeline.

Publicación parcial (`degraded`): revisar `channel_results` del paquete en
`data/premium_packages.json`; el canal exitoso conserva su `external_id` y nunca se
reintenta. `failure_metadata` identifica la etapa del carrusel y, cuando Meta los
devuelve, el HTTP y código/subcódigo del proveedor. Instagram espera que cada placa y
el carrusel padre lleguen a `FINISHED` antes de avanzar; la espera usa
`PREMIUM_IG_CONTAINER_PROCESSING_TIMEOUT_SECONDS` (90s) y
`PREMIUM_IG_CONTAINER_PROCESSING_POLL_SECONDS` (2s). Reintentar sólo el canal fallido
y únicamente con autorización operativa vigente:

```powershell
python -c "from utils.premium_publisher import retry_channel; import json; print(json.dumps(retry_channel('<package_id>', '<instagram|facebook>'), ensure_ascii=False, indent=2))"
```

Un resultado con `requires_reconciliation=true` (outcome ambiguo, típicamente
`network_error`) no se reintenta automáticamente; conciliar en la plataforma antes de
usar `force=True` en `retry_channel`.

## Sistema visual Remotion (Fase 4 + rediseño "Editorial Cinemática Riojana")

Política **por workflow** (corrección 2026-07-30 y 2026-07-31, ver `docs/DECISIONS.md`):
cada flujo tiene su propia variable y su propio default seguro. Sin ninguna variable
definida:

| Workflow | Variable | Default |
|---|---|---:|
| Automático (Instagram, alto volumen) | `AUTOMATIC_STATIC_RENDER_ENGINE` | `auto` |
| Estudio Premium (manual, bajo volumen) | `PREMIUM_STATIC_RENDER_ENGINE` | `remotion` |
| OG Facebook/web | `OG_STATIC_RENDER_ENGINE` | `auto` |

Las tres admiten `auto|remotion|pillow`. Precedencia: variable específica del
workflow (si está definida explícitamente) > `STATIC_RENDER_ENGINE` legacy (sólo si
está definida explícitamente) > default seguro del workflow. **No activar
`STATIC_RENDER_ENGINE` sin necesidad**: cambia el motor de cualquier workflow que no
tenga su propia variable definida, incluido el automático.

Los tres flujos con wiring real (Estudio Premium, automático de Instagram y OG de
Facebook/web) pasan por `utils/remotion_renderer.py::render_still()`, que ahora intenta
primero un **servidor de render persistente** (`remotion/render_server.mjs`) antes de
caer al `subprocess` histórico de `npx remotion still` — ver "Servidor de render
persistente" más abajo.

- `utils/premium_renderer.py::render_package_with_engine` — Estudio Premium,
  `workflow="premium"` por defecto.
- `layout/image_generator.py::generate_instagram_with_engine` — card automática de
  Instagram (`workflow="automatic"`), llamada desde `meta/ig_client.py::_prepare_image`,
  `pipeline/custom_post.py::render_preview_image` y `preview_pipeline.py`. Nunca toca
  `generate_post`/`generate_instagram`/`generate_facebook` (Pillow) — quedan intactas
  como fallback, llamadas internamente si Remotion falla o no está disponible.
- `layout/image_generator.py::generate_facebook_with_engine` — tarjeta OG del artículo
  web (`workflow="og"`), con Pillow como fallback si Remotion no está disponible.

```powershell
# Ejemplos
$env:PREMIUM_STATIC_RENDER_ENGINE="pillow"     # fuerza Pillow sólo en premium
$env:AUTOMATIC_STATIC_RENDER_ENGINE="pillow"   # vuelve el automático al comportamiento previo a 2026-07-31
$env:AUTOMATIC_STATIC_RENDER_ENGINE="remotion" # exige Remotion en automático; falla en vez de degradar si no está disponible

# Validación manual del proyecto Remotion (no está en CI: CI es Python-only)
cd remotion
npm i
npx tsc --noEmit
npx eslint src
npx remotion bundle
python ..\scripts\benchmark_static_render.py
python ..\scripts\generate_visual_contact_sheet.py   # fixtures + contact sheet en docs/design/editorial-cinematica/
```

Un fallback de `auto` a Pillow, o un modo `remotion` explícito sin Remotion
disponible, queda registrado en `logs/remotion_renderer.log`
(`workflow=... engine_requested=... engine_used=... fallback_reason=...`) y en
`logs/premium_renderer.log`, además del resultado estructurado
(`engine_used`/`render_engine`). Los tests de render real en
`tests/test_remotion_visual.py::RemotionLiveRenderTests` y
`tests/test_image_pipeline.py::AutomaticInstagramLiveRenderTests` se saltean
automáticamente si `remotion/node_modules` no existe (por ejemplo, en CI, que no
instala Node) — no es un fallo, es el comportamiento esperado sin Node disponible.

### Servidor de render persistente

`remotion/render_server.mjs` bundlea el proyecto **una sola vez por proceso** y reusa
un browser Chromium entre renders (resuelve `docs/KNOWN_ISSUES.md` #69 — cada
`npx remotion still` re-bundleaba desde cero, ~19s/paquete medido; el servidor
persistente midió ~2.9s/paquete, ~1s/slide individual, ver `docs/METRICS.md`).

- Se levanta bajo demanda: la primera llamada a `render_still()` que no encuentra un
  servidor saludable en `remotion/.render-server.json` lo lanza como proceso
  `detached`/background y espera su `/health` (hasta 90s por defecto,
  `REMOTION_RENDER_SERVER_STARTUP_TIMEOUT`).
- Se apaga solo por inactividad (default 20 minutos, `RENDER_SERVER_IDLE_MS`) — no
  requiere registrarse en el supervisor 24/7 ni en las tareas programadas.
- `REMOTION_RENDER_SERVER_DISABLED=true` fuerza a `render_still()` a usar sólo el
  `subprocess` histórico (útil para reproducir el comportamiento anterior o diagnosticar
  un problema puntual del servidor).
- **Si se edita código en `remotion/src/` con el servidor corriendo, hay que
  reiniciarlo manualmente** para que sirva el bundle actualizado — no hay
  invalidación automática todavía (ver Known Issue #69, sección "Riesgo residual").
  En PowerShell:
  ```powershell
  $info = Get-Content remotion\.render-server.json | ConvertFrom-Json
  Stop-Process -Id $info.pid -Force
  Remove-Item remotion\.render-server.json, remotion\.render-cache -Recurse -Force
  ```
  El siguiente render lo vuelve a levantar automáticamente con el bundle nuevo.

## Editorial Context Engine y fuentes oficiales

Ver `docs/EDITORIAL_CONTEXT.md`, `docs/STORY_ENGINE.md` y
`docs/OFFICIAL_SOURCES.md` para el diseño completo. Operación día a día:

```powershell
# Diagnóstico read-only de una fuente (nunca escribe nada, ni publica)
python cli.py source-probe --source mpf_larioja --json

# Reconstruir el índice derivado desde cero (seguro: es reconstruible)
python cli.py archive-index rebuild

# Backfill desde el CMS propio (GET /api/public/posts, paginado)
python cli.py archive-index backfill-cms --max-pages 50

# Métricas editoriales y por fuente (Partes 54/55)
python cli.py archive-index stats --since-hours 24 --since-days 7

# Backfill de story_key para notas publicadas existentes (Parte 43)
python scripts/backfill_story_index.py --report-only
python scripts/backfill_story_index.py --apply --confirm --limit 50
```

`editorial_context/refresh_context.py` corre solo como parte del ciclo del
supervisor (`run_24x7.py`); no hace falta invocarlo manualmente salvo para
depurar (en ese caso, correrlo como script standalone respeta igual
`poll_ttl` por fuente y nunca publica nada).

Variables de entorno nuevas (todas opcionales, con default seguro):

| Variable | Default | Efecto |
|---|---|---|
| `LVR_DERIVED_DIR` | `<data_dir>/derived` | ubicación del índice SQLite derivado |
| `ARCHIVE_CONTEXT_MAX_ITEMS` | `3` | notas previas máximas citadas en el cuerpo |
| `RELATED_ARTICLES_MAX_ITEMS` | `5` | relacionadas máximas en el bundle |
| `TIMELINE_MAX_ITEMS` | `5` | items máximos del timeline |
| `ARCHIVE_CONTEXT_MAX_CHARS` | `3500` | tope de caracteres de contexto propio enviado a Gemini |
| `OFFICIAL_CONTEXT_MAX_CHARS` | `4500` | tope de caracteres de contexto oficial enviado a Gemini |
| `OFFICIAL_SNIPPET_MAX_ITEMS` | `3` | fragmentos oficiales máximos por nota |

Si el índice derivado se corrompe o hay que empezar de cero (por ejemplo,
tras un cambio de esquema), `archive-index rebuild` es seguro: no toca
ninguna cola JSON productiva, sólo el archivo SQLite derivado. Repoblarlo
después con `archive-index backfill-cms` (histórico) — la ingesta en tiempo
real (cada publicación nueva) sigue funcionando sola desde el próximo
ciclo.

**Fuentes oficiales deshabilitadas** (`config/official_sources.json`,
`enabled=false`): no requieren ninguna acción — el `SourceSelector` las
ignora solas. Para reactivar una (por ejemplo, si `anses`/`indec` consiguen
un mecanismo de acceso confirmado), editar su entrada en el JSON
(`enabled: true`, `discovery_strategy`/`fetch_strategy` correctos) y validar
primero con `source-probe --force` (vía `probe_source`, que ya ignora
`enabled` para diagnosticar) antes de habilitarla en el ciclo real.
