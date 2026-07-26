# Backlog

Última actualización: 2026-07-26. Los ítems resueltos se conservan.

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
- [x] Kill switches autoritativos y límite inicial de uno por ciclo.
- [x] Heartbeat con trazabilidad de despliegue.
- [x] Variante de host/slash final de Tiempo Popular cubierta por test y preflight
  vivo.

## Bloqueos para habilitar producción

- [ ] Publicar la rama y obtener CI verde en PR #1.
- [ ] Obtener revisión/aprobación del PR.
- [ ] Configurar branch protection para exigir el check de confiabilidad.
- [ ] Crear backup productivo completo y probar restore en temporal.
- [ ] Ejecutar `preflight openai` con credencial autorizada.
- [ ] Probar R2 reversible bajo `healthchecks/`.
- [ ] Definir o implementar un endpoint CMS GET seguro y ejecutar su preflight.
- [ ] Ejecutar preflight read-only de Facebook e Instagram.
- [ ] Resolver 19 entradas Facebook sin URL web y aprobar las 3 pendientes válidas.
- [ ] Ejecutar un canary exactamente una vez durante una ventana autorizada.
- [ ] Probar webhook real o aceptar formalmente operación con outbox local.
- [ ] Completar varios ciclos sanos en `observe`.
- [ ] Completar varios ciclos sanos en `web_only`.
- [ ] Habilitar Facebook e Instagram por separado y observar varios ciclos.
- [ ] Ensayar rollback de modo y release.
- [ ] Merge aprobado y creación posterior del tag propuesto.

## Mantenimiento medio

- [ ] Incorporar un watchdog externo simple para alertar si muere todo el proceso.
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
