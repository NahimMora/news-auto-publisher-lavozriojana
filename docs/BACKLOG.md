# Backlog

Última actualización: 2026-07-27. Los ítems resueltos se conservan.

## Cerrado por la línea de base del 2026-07-23

- [x] Contrato estructurado y códigos de salida.
- [x] Heartbeat, stale y métricas de colas.
- [x] Logs rotativos y redacción de secretos.
- [x] `requirements.txt` completo, incluido `psutil`.
- [x] JSON atómico, locks, backup, restore y cuarentena.
- [x] Reescritura recuperable y estados terminales trazables.
- [x] Configuración tipada y `doctor`.
- [x] Contratos mockeados de CMS, Meta y R2.
- [x] Fixtures para diez secciones y E2E local de 17 escenarios.
- [x] Seguridad de UI, uploads, paths y SSRF.

## Cerrado en preparación 24/7 del 2026-07-26

- [x] Workflow CI Windows reproducible y aislado.
- [x] Gate que verifica `production_calls=false`.
- [x] Estado `blocked` no exitoso.
- [x] `preflight` para sources, OpenAI, R2, CMS, Facebook, Instagram, filesystem y
  supervisor.
- [x] Canary gated, una vez por canal, idempotente y sin cola general.
- [x] Conciliación Facebook report-only y aplicación por decisiones.
- [x] Motor de alertas con dedupe, recovery, outbox y webhook opcional.
- [x] Modos `observe`, `web_only`, `web_facebook`, `web_instagram`, `all`.
- [x] Kill switches autoritativos y límites controlados por deployment mode.
- [x] Heartbeat con trazabilidad de despliegue.
- [x] Variante de host/slash final de Tiempo Popular cubierta por test y preflight
  vivo.
- [x] CI remoto verde en PR #1.
- [x] `main` protegido con `reliability-windows` obligatorio y strict.
- [x] Scope `doctor core` separado de binarios multimedia opcionales.
- [x] Carrera transitoria de lock Windows reproducida y corregida.

## Cerrado en la activación controlada del 2026-07-27

- [x] Venv del host instalado y `pip check` limpio.
- [x] Suite ampliada a 217 tests y E2E local verde.
- [x] Backlog anterior al 27/07 archivado sin pérdida ni edición manual.
- [x] Corte inicial por fecha ejecutado y preservado como evidencia histórica.
- [x] Backlog histórico de Facebook sin pendientes ni ambiguos.
- [x] Preflight real de OpenAI, R2, Facebook e Instagram.
- [x] Canary Instagram con permalink y cleanup confirmados.
- [x] Arranque Web y Facebook con evidencia externa.
- [x] Primer ciclo 24/7 completo con cuatro etapas aceptables.
- [x] UI manual restringida a localhost y disponible.
- [x] Watchdog local cada cinco minutos para supervisor y UI.
- [x] Línea de base independiente de fecha: últimas 20 identidades por timestamp
  durable, con backup, archivo y eventos.
- [x] Feedback editorial con intento anterior, detección de cambios materiales y uso
  trazable del sexto resultado seguro.
- [x] Falsos positivos editoriales por sustantivos genéricos y equivalencias
  número-palabra cubiertos por regresiones.
- [x] Facebook con título + caption compartido + URL y prewarm verificable de OG.
- [x] Capacidad operativa ajustada: Web sin límite y Meta 8 por plataforma/ciclo.

## Bloqueos para release oficial 24/7

- [ ] Obtener revisión/aprobación del PR.
- [ ] Definir o implementar un endpoint CMS GET seguro y ejecutar su preflight.
- [ ] Probar webhook real o aceptar formalmente operación con outbox local.
- [ ] Observar varios ciclos adicionales sin fallos ni backlog creciente.
- [ ] Completar una publicación Instagram de noticia nueva no deduplicada.
- [ ] Ensayar un reboot completo y verificar las tareas programadas.
- [ ] Ensayar rollback de modo y release.
- [ ] Merge aprobado y creación posterior del tag propuesto.

## Mantenimiento medio

- [ ] Incorporar un watchdog externo simple para alertar si se apaga todo el host.
- [ ] Definir retención/archivo de logs, eventos y outbox según capacidad del host.
- [ ] Mantener fixtures frente a cambios de HTML.
- [ ] Validar filesystem si el estado se mueve a un share de red.
- [ ] Documentar un staging externo si se crea.

## Riesgos aceptados o fuera de alcance

- [ ] La aprobación editorial humana sigue opcional; no hay decisión que la haga
  obligatoria.
- [ ] No hay staging externo independiente.
- [ ] Analytics, audiencia, monetización y nuevas plataformas siguen fuera de alcance.
- [ ] No se migra JSON a base de datos sin evidencia de insuficiencia.
