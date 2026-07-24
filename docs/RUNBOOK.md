# Runbook de operación e incidentes

Última actualización: 2026-07-23.

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
