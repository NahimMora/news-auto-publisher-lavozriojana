# Problemas conocidos

Última actualización: 2026-07-26. Los problemas resueltos no se borran.

## 1. Fallos de Facebook sin detalle

- Estado anterior: abierto; el backlog crecía y los clientes no escribían archivo.
- Corrección 2026-07-23: log rotativo para runner, cliente y token manager, redacción
  de secretos y resultados tipados para credencial, rate limit, servidor y red.
- Evidencia: `tests.test_meta_contracts.FacebookContractTests`,
  `tests.test_logging_security`.
- Estado actual: **mitigado**. La observabilidad quedó corregida; la causa histórica
  externa sigue bloqueada por falta de logs originales y acceso a cuenta de prueba.

## 2. `psutil` ausente de requirements

- Corrección 2026-07-23: agregado a `requirements.txt`; instalación limpia y
  `pip check`.
- Evidencia: suite de supervisor/CLI e instalación registrada en la auditoría.
- Estado actual: **resuelto**.

## 3. Sin evidencia de actividad del supervisor

- Corrección 2026-07-23: heartbeat atómico con antigüedad, ciclo, PID, etapas y colas;
  stale configurado y `status` de sólo lectura.
- Evidencia: `tests.test_supervisor_cli.HeartbeatTests` y `CliStatusTests`.
- Estado actual: **resuelto en código**. El estado del host productivo sigue
  desconocido porque no se inició ni modificó producción.

## 4. Repositorio git roto/mezclado

- Corrección 2026-07-20: repositorio dedicado y remote propio.
- Verificación 2026-07-23: GitHub App confirmó
  `NahimMora/news-auto-publisher-lavozriojana`; branch principal `main`.
- Estado actual: **resuelto**.

## 5. Cobertura automatizada limitada

- Corrección 2026-07-23: suite ampliada de 35 a 147 pruebas, con persistencia,
  reanudación, concurrencia, configuración, scrapers, imágenes, contratos externos,
  seguridad, supervisor/CLI y 17 escenarios E2E.
- Evidencia: `python -m unittest discover tests -v`.
- Estado actual: **resuelto para la línea de base**. Video visual completo y smoke
  externo continúan requiriendo QA controlada.

## 6. Backups manuales y restauración no probada

- Corrección 2026-07-23: backup configurable integrado a escrituras, retención,
  comandos CLI y restore validado con backup previo.
- Evidencia: `SafeJsonTests.test_backup_can_be_restored`.
- Estado actual: **resuelto en código**; falta validar política/capacidad en el host.

## 7. Sin aprobación editorial humana obligatoria

- Tratamiento 2026-07-23: política de fallback explícita; contenidos sensibles no
  publican fallback por defecto y cada decisión queda trazada.
- Evidencia: `tests.test_editorial_policy` y
  `RewriteRecoveryTests.test_disallowed_fallback_goes_to_dead_letter_not_output`.
- Estado actual: **riesgo aceptado/documentado**. No se agregó aprobación obligatoria
  porque no existe una decisión editorial que la requiera.

## 8. Pérdida de staging por interrupción

- Corrección 2026-07-23: cola durable y transferencia output-before-clear.
- Evidencia: diez noticias, corte después de la tercera, reinicio y diez completadas
  exactamente una vez en `test_rewrite_recovery`.
- Estado actual: **resuelto**.

## 9. JSON corrupto interpretado como vacío

- Corrección 2026-07-23: error explícito, preservación en origen, cuarentena y bloqueo
  de sobrescritura.
- Evidencia: `SafeJsonTests.test_truncated_json_is_quarantined_and_never_becomes_empty`.
- Estado actual: **resuelto**.

## 10. Escrituras concurrentes perdidas

- Corrección 2026-07-23: locks, temporales únicos, fsync, replace, `update_json` y
  `update_json_files`.
- Evidencia: 100 updates concurrentes y claims únicos en `test_reliability_core`.
- Estado actual: **resuelto para filesystem local**. Un share de red no fue validado.

## 11. Falsos positivos de salud

- Corrección 2026-07-23: contrato estructurado, códigos de salida y runner que exige
  resultado funcional.
- Evidencia: tests de `StageResult`, social stages y `ProcessResultTests`.
- Estado actual: **resuelto**.

## 12. Scraper caído confundido con fuente vacía

- Corrección 2026-07-23: `ArticleScrapeResult`/`LinkScrapeResult`; HTTP, timeout y
  selector mismatch son fallos.
- Evidencia: fixtures de las diez secciones y pruebas negativas.
- Estado actual: **resuelto en contrato local**; el HTML vivo sigue siendo externo.

## 13. Expiraciones/descartes sin trazabilidad

- Corrección 2026-07-23: estados terminales y `queue_events.json`.
- Evidencia: tests de expiración social, fallback bloqueado y escenario E2E expirado.
- Estado actual: **resuelto**.

## 14. Publicación confirmada sin evidencia

- Corrección 2026-07-23: CMS/Meta requieren ID, URL o slug verificable; 409 sólo es
  idempotente con evidencia.
- Evidencia: `tests.test_external_contracts`.
- Estado actual: **resuelto**.

## 15. SSRF, exposición manual y uploads débiles

- Corrección 2026-07-23: validación DNS/IP y redirects, loopback-only, paths propios,
  límites y firmas de contenido.
- Evidencia: `tests.test_security_controls`.
- Estado actual: **resuelto para vectores reproducidos**.

## 16. Estado de reanudación aparente pero no usado

- Corrección 2026-07-23: eliminado `utils/pipeline_resume.py`; reemplazado por la cola
  durable realmente integrada.
- Evidencia: recuperación real del pipeline en `test_rewrite_recovery`.
- Estado actual: **resuelto**. Un archivo legacy existente no se borra automáticamente.

## 17. Configuración declarada sin efecto

- Corrección 2026-07-23: inventario obligatorio/opcional/desarrollo/obsoleto,
  `.env.example` alineado, variables visuales activas conectadas y `doctor`.
- Evidencia: `tests.test_config_validation`.
- Estado actual: **resuelto**. `IG_CHROME_PROFILE_DIR` y variables visuales legacy se
  documentan como obsoletas, no se simula soporte.

## 18. Riesgos residuales abiertos

- Smoke externo de CMS, Meta, R2 y OpenAI: **bloqueado por entorno**.
- Causa del backlog histórico de Facebook: **no reproducida**.
- Lock/reemplazo sobre filesystem de red: **desconocido**.
- Staging externo/CI: **mejora operativa**, pendiente.
- Publicación social ambigua requiere conciliación manual: **mitigada por
  dead-letter**, no automatizada.

## 19. Contención de locks en Windows

- Reproducción 2026-07-23: bajo ocho writers, Windows devolvió `PermissionError` para
  un archivo de lock contendiente.
- Corrección: se espera/reintenta sólo si el lock existe; un permiso real sigue
  fallando explícitamente.
- Evidencia: test de 100 updates repetido cinco veces y suite limpia.
- Estado actual: **resuelto**.

## 20. Fallback original de Instagram sin opt-in

- Reproducción 2026-07-23: con R2 ausente, Instagram usaba la URL original aunque el
  flag estuviera en false.
- Corrección: fallo explícito y `doctor` exige R2; la imagen original requiere opt-in.
- Evidencia: contrato Instagram y tests de configuración.
- Estado actual: **resuelto**.

## 21. Lock válido podía considerarse stale sólo por antigüedad

- Reproducción 2026-07-23: un lock de un proceso vivo con mtime antiguo era removible.
- Corrección: el owner PID y su fecha de creación se verifican antes de retirar un
  lock; un PID reutilizado se distingue del owner original.
- Evidencia: tests de lock viejo con proceso vivo y proceso muerto.
- Estado actual: **resuelto**.

## 22. Adquisición multiarchivo parcial podía dejar un lock tomado

- Reproducción 2026-07-23: timeout en el segundo path de `MultiFileLock`.
- Corrección: cerrar el `ExitStack` si `__enter__` falla.
- Evidencia: `test_multifile_partial_acquire_releases_previous_locks`.
- Estado actual: **resuelto**.

## 23. Fallo al escribir metadata del lock dejaba un huérfano

- Reproducción 2026-07-23: mock de escritura fallida inmediatamente después de crear
  el archivo exclusivo.
- Corrección: cerrar el descriptor y retirar el lock antes de propagar el error.
- Evidencia: `test_lock_metadata_write_failure_does_not_leave_orphan`.
- Estado actual: **resuelto**.

## 24. Texto persistido se interpolaba como HTML en la UI manual

- Reproducción 2026-07-23: título/URL con markup en listas de cola o borradores.
- Corrección: construcción DOM y `textContent` en Reel Manager y diseñador; no se usa
  `innerHTML` con datos.
- Evidencia: `test_manual_ui_renders_persisted_text_with_text_content`.
- Estado actual: **resuelto**.

## 25. UI loopback aceptaba Host/Origin externos

- Reproducción 2026-07-23: request a loopback con `Host`/`Origin` atacante.
- Corrección: validación loopback de ambos headers, CSP, frame denial y nombres de
  upload estrictos.
- Evidencia: `test_dns_rebinding_and_cross_origin_requests_are_rejected`.
- Estado actual: **resuelto**.

## 26. Cleanup R2 informaba eliminado sin verificar resultado

- Reproducción 2026-07-23: `delete_object` falla después de dos publicaciones fallidas.
- Corrección: `delete` devuelve resultado tipado y el job conserva `cleanup_error`.
- Evidencia: `test_delete_failure_is_visible_and_retryable`.
- Estado actual: **resuelto**.

## 27. Publicación manual parcial se mostraba como OK

- Reproducción 2026-07-23: web/Instagram exitosos y Facebook fallido.
- Corrección: clientes detallados, status `degraded` y UI verde sólo en `success`.
- Evidencia: `test_manual_partial_publication_is_degraded`.
- Estado actual: **resuelto**.

## 28. Web sin post ID no podía rastrear flags editoriales

- Reproducción 2026-07-23: CMS devuelve URL pero no ID para un nuevo featured.
- Corrección: publicación preservada pero `degraded`, evento de conciliación y
  propagación al flujo manual.
- Evidencia:
  `test_public_url_without_post_id_is_degraded_when_flags_need_tracking`.
- Estado actual: **mitigado**; requiere que el CMS entregue ID para conciliación
  automática.

## 29. Imágenes declaradas por scrapers podían apuntar a redes privadas

- Reproducción 2026-07-23: un `og:image` con destino link-local llegaba al cliente
  HTTP directo de ambos scrapers base.
- Corrección: descarga mediante el cliente seguro con validación DNS/IP y
  revalidación de redirects antes de abrir la conexión.
- Evidencia: `test_scrapers_do_not_fetch_private_image_urls`.
- Estado actual: **resuelto para los vectores reproducidos**.

## 30. Un test de aislamiento del dry-run dependía de un atributo inexistente

- Reproducción 2026-07-23: suite limpia de 147 casos; 146 pasaron y
  `test_run_once_dry_run_executes_only_local_e2e_suite` terminó con
  `AttributeError`.
- Corrección: la aserción usa el directorio temporal propio de `CliStatusTests`.
- Evidencia: segunda ejecución completa, 147 pruebas OK.
- Estado actual: **resuelto**.

## 31. API de Pillow deprecada en el render de íconos

- Reproducción 2026-07-23: la suite emitió `DeprecationWarning` porque
  `Image.Image.getdata` será removido en Pillow 14.
- Corrección: lectura del mínimo alfa mediante `getextrema`, API vigente.
- Evidencia: tests de layout ejecutados con `DeprecationWarning` tratado como error.
- Estado actual: **resuelto**.

## 32. CI y checks obligatorios ausentes

- Reproducción 2026-07-26: PR #1 sin `statusCheckRollup`; `main` sin protección.
- Corrección: `.github/workflows/reliability.yml` y gate local de seguridad.
- Evidencia: `tests.test_ci_safety`, Actions run `30210229086` y protección strict
  de `main`.
- Estado actual: **resuelto**.

## 33. Facebook e Instagram habilitados por default efectivo

- Reproducción: sin la variable, ambos runners usaban default `"true"`, distinto de
  `utils/config.py` y `.env.example`.
- Corrección: sólo publican ante un valor booleano verdadero explícito.
- Evidencia: `DeploymentModeTests.test_runners_are_disabled_when_switch_is_missing`.
- Estado actual: **resuelto**.

## 34. `.env` se cargaba después de fijar rutas del CLI

- Reproducción: `cli.py` importaba `utils.paths` antes de `load_dotenv()`.
- Corrección: carga del entorno antes de cualquier módulo operativo.
- Evidencia: orden de imports, CI con `PYTHON_DOTENV_DISABLED=1` y pruebas aisladas.
- Estado actual: **resuelto**.

## 35. Suite no era hermética con cuarentena global

- Reproducción: 146/147 tests; el test de JSON truncado asumía cuarentena vecina aun
  con `LVR_QUARANTINE_DIR` configurado.
- Corrección: el test declara su cuarentena temporal.
- Evidencia: suite completa aislada.
- Estado actual: **resuelto**.

## 36. No existía preflight real seguro

- Corrección: scopes sources/OpenAI/R2/CMS/Facebook/Instagram/filesystem/supervisor y
  estado `blocked`.
- Evidencia: `tests.test_preflight`; fuentes 10/10, filesystem y supervisor reales
  pasaron en modo seguro.
- Estado actual: **parcialmente resuelto**. OpenAI, R2, CMS y Meta siguen bloqueados
  por autorización, credenciales o endpoint.

## 37. No había arranque progresivo

- Corrección: modos explícitos, contradicciones fatales, límites de uno por ciclo y
  kill switches autoritativos.
- Evidencia: `tests.test_deployment_modes`.
- Estado actual: **resuelto en código**; los ciclos de observación no se ejecutaron.

## 38. No existía canary aislado

- Corrección: gate doble, categorías seguras, un elemento, idempotencia, evidencia y
  cleanup separado.
- Evidencia: `tests.test_canary`.
- Estado actual: **resuelto en código, bloqueado externamente** hasta una ventana
  autorizada.

## 39. Backlog Facebook sin clasificación reproducible

- Corrección: reporte read-only y aplicación por decisiones.
- Evidencia: tests y reporte sobre copia: 23 total, 1 publicada, 3 pendientes válidas,
  19 sin URL web, cero ambiguas/inválidas; cola original intacta.
- Estado actual: **mitigado**. Facebook sigue bloqueado hasta resolver las 19 URLs y
  aprobar decisiones.

## 40. Sin alertas operativas mínimas

- Corrección: detector, dedupe, recovery, outbox y webhook público opcional.
- Evidencia: `tests.test_alerts` y `alert-test` local.
- Estado actual: **resuelto en código**. Falta proveedor real y watchdog externo.

## 41. Tiempo Popular cambió variante de host/slash

- Reproducción: preflight vivo devolvió cero enlaces para las cuatro secciones al
  encontrar URLs sin `www` y sin slash final.
- Corrección: validación por host normalizado y slash opcional en el scraper
  compartido.
- Evidencia: test específico y segundo preflight 4/4 `success`; total fuentes 10/10.
- Estado actual: **resuelto**.

## 42. Documentación contradecía una ejecución productiva previa

- Reproducción: supervisor real activo y heartbeat con publicaciones, mientras
  `CURRENT_STATE.md` decía que producción no se había iniciado.
- Tratamiento: supervisor detenido antes de cambios, hecho documentado y defaults
  seguros de `observe`.
- Estado actual: **mitigado**. La ejecución previa no es evidencia de canary ni de
  readiness.

## 43. CMS sin endpoint read-only confirmado

- El código exige `WEBAPP_PREFLIGHT_PATH` y capacidad declarada.
- Estado actual: **bloqueado por entorno/repositorio externo**. No se simula éxito ni
  se crea una publicación durante el preflight general.

## 44. Release pendiente y branch protection resuelta

- Propuesta: `v1.0.0-reliability-baseline` después de merge aprobado.
- Branch protection: **resuelta**; `main` exige `reliability-windows` strict y
  resolución de conversaciones, también para administradores.
- Estado actual: el release sigue **bloqueado por proceso externo**. No se creó tag,
  no se hizo merge y no se declaró producción lista.

## 45. El primer workflow remoto fue rechazado antes de crear jobs

- Reproducción: Actions run `30209150539` finalizó en `failure` con `jobs=[]`.
- Causa raíz: `runner.temp` se había usado en `jobs.<job>.env`, donde el contexto
  todavía no está disponible.
- Corrección: las rutas aisladas se exportan a `$GITHUB_ENV` desde un step PowerShell
  ejecutado después de asignar `windows-latest`.
- Evidencia: `tests.test_ci_safety.CiSafetyTests.
  test_workflow_contains_required_windows_gates`.
- Estado actual: **resuelto**. Actions run `30209610342` creó y ejecutó el job
  Windows; ese run detectó el problema independiente #46.
- Riesgo residual: ninguno específico a la disponibilidad de `runner.temp`.

## 46. `doctor core` degradaba por binarios multimedia opcionales

- Reproducción: Actions run `30209610342`; configuración y dependencias Python
  correctas, pero `ffmpeg`/`ffprobe` ausentes produjeron exit no cero.
- Causa raíz: `diagnose_environment` no separaba el scope Python core de
  dependencias de sistema.
- Corrección: `core` ya no exige binarios multimedia; `all` conserva el diagnóstico.
- Evidencia: `DoctorScopeTests.
  test_core_does_not_require_optional_system_binaries`.
- Estado actual: **resuelto**; Actions run `30210229086` pasó `doctor core`.
- Riesgo residual: ejecutar `doctor all` en el host antes de usar imagen/video.

## 47. El mínimo de python-dotenv no garantizaba aislamiento de `.env`

- Reproducción: `python-dotenv 1.0.0`, permitido por el requirements anterior, no
  respetó `PYTHON_DOTENV_DISABLED=1`; el diagnóstico sólo mostró valores sensibles
  como `[CONFIGURADO]`.
- Corrección: `requirements.txt` exige `python-dotenv>=1.2.2`.
- Evidencia: `test_requirements_support_explicit_dotenv_isolation` y entorno limpio
  con 1.2.2.
- Estado actual: **resuelto en código**; los entornos existentes deben reinstalar
  requirements.
- Riesgo residual: una instalación no actualizada podría seguir cargando `.env`.

## 48. Carrera de lock Windows podía parecer un permiso permanente

- Reproducción: Actions run `30209866700`; el test de 100 actualizaciones
  concurrentes recibió `PermissionError` sobre un lock que otro thread estaba
  liberando.
- Causa raíz: la comprobación `exists()` corría después de la liberación y convertía
  una sharing violation transitoria en `JsonWriteError`.
- Corrección: dos reintentos acotados para esa carrera; un permiso persistente sigue
  siendo error explícito.
- Evidencia: test determinista y 25 repeticiones/2.500 actualizaciones sin pérdida.
- Estado actual: **resuelto**; Actions run `30210229086` pasó la suite Windows.
- Riesgo residual: repetir `preflight filesystem` en el volumen del despliegue.
