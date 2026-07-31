# Runbook de operación e incidentes

Última actualización: 2026-07-30.

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
título

caption exacto de Instagram

URL pública de la noticia
```

Con `FB_LINK_PREWARM_ENABLED=true`, el cliente descarga la nota con user-agent del
crawler de Facebook, exige HTML, extrae un `og:image` público, lo descarga con límite
de tamaño y recién entonces publica. Un timeout, HTTP inválido, Content-Type
incorrecto o imagen ausente deja la noticia pendiente como `degraded`; no se llama a
Graph. Revisar `logs/fb_client.log` y la disponibilidad pública de CMS/R2 antes de
reintentar.

## UI manual de videos

Inicio o comprobación idempotente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\start_manual_video_ui.ps1
```

El script rechaza un listener externo y un servicio desconocido ocupando el puerto.
La URL autorizada es únicamente `http://127.0.0.1:8765/`. Además de las pestañas
Videos y Publicaciones, incluye Estudio Premium y Candidatas (ver más abajo).

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

Candidatas: se gestionan desde la pestaña "Candidatas" de la UI manual, o
directamente:

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
   alternativa secundaria.
2. Revisar título, caption, sección, plantilla y cada slide. Se pueden editar título,
   texto, ítems, highlights, tipo y orden.
3. Asignar una imagen a cada slide: link público directo, archivo propio desde
   **mi galería**, o biblioteca. Los links se validan contra SSRF, redirects,
   Content-Type y límite de 20 MB; las subidas se validan por firma/contenido. Ambos
   caminos terminan en `utils.media_library.ingest_image_bytes`, con deduplicación
   por hash. Las miniaturas de biblioteca se sirven sólo por
   `/api/media-library/thumb/{asset_id}`, nunca como rutas locales.
4. Guardar borrador, previsualizar y recién entonces publicar. Preview y publicación
   siguen usando `utils.premium_renderer.render_package_with_engine`.

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
reintenta. Reintentar sólo el canal fallido:

```powershell
python -c "from utils.premium_publisher import retry_channel; import json; print(json.dumps(retry_channel('<package_id>', 'facebook'), ensure_ascii=False, indent=2))"
```

Un resultado con `requires_reconciliation=true` (outcome ambiguo, típicamente
`network_error`) no se reintenta automáticamente; conciliar en la plataforma antes de
usar `force=True` en `retry_channel`.

## Sistema visual Remotion (Fase 4)

Política **por workflow** (corrección 2026-07-30, ver `docs/DECISIONS.md`): cada
flujo tiene su propia variable y su propio default seguro. Sin ninguna variable
definida:

| Workflow | Variable | Default |
|---|---|---:|
| Automático (Instagram, alto volumen) | `AUTOMATIC_STATIC_RENDER_ENGINE` | `pillow` |
| Estudio Premium (manual, bajo volumen) | `PREMIUM_STATIC_RENDER_ENGINE` | `remotion` |
| OG Facebook/web | `OG_STATIC_RENDER_ENGINE` | `pillow` |

Las tres admiten `auto|remotion|pillow`. Precedencia: variable específica del
workflow (si está definida explícitamente) > `STATIC_RENDER_ENGINE` legacy (sólo si
está definida explícitamente) > default seguro del workflow. **No activar
`STATIC_RENDER_ENGINE` sin necesidad**: cambia el motor de cualquier workflow que no
tenga su propia variable definida, incluido el automático.

Sólo el Estudio Premium tiene wiring real a Remotion en esta entrega
(`utils/premium_renderer.py::render_package_with_engine`, `workflow="premium"` por
defecto). El flujo automático de Instagram y el OG de Facebook/web **no llaman a
Remotion todavía** — sus variables existen para cuando se decida integrarlos, con el
default correcto ya fijado.

```powershell
# Ejemplos
$env:PREMIUM_STATIC_RENDER_ENGINE="pillow"    # fuerza Pillow sólo en premium
$env:AUTOMATIC_STATIC_RENDER_ENGINE="remotion" # habilita Remotion en automático para pruebas controladas (no hay wiring real todavía)

# Validación manual del proyecto Remotion (no está en CI: CI es Python-only)
cd remotion
npm i
npx tsc --noEmit
npx eslint src
npx remotion bundle
python ..\scripts\benchmark_static_render.py
```

Un fallback de `auto` a Pillow, o un modo `remotion` explícito sin Remotion
disponible, queda registrado en `logs/remotion_renderer.log`
(`workflow=... engine_requested=... engine_used=... fallback_reason=...`) y en
`logs/premium_renderer.log`, además del resultado estructurado
(`engine_used`/`render_engine`). Los 4 tests de render real en
`tests/test_remotion_visual.py::RemotionLiveRenderTests` se saltean automáticamente
si `remotion/node_modules` no existe (por ejemplo, en CI, que no instala Node) — no
es un fallo, es el comportamiento esperado sin Node disponible.
