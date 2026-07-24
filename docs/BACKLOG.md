# Backlog

Última actualización: 2026-07-23. Los ítems resueltos se conservan para mantener
trazabilidad.

## Cerrado por la línea de base de confiabilidad

- [x] Contrato estructurado de etapas y códigos de salida.
- [x] Eliminar falso `OK` de `0/N` y del parsing de palabras del CLI.
- [x] Heartbeat persistente, detección stale y tamaños de cola.
- [x] Logs rotativos para todos los clientes externos con redacción de secretos.
- [x] `psutil` declarado en `requirements.txt`.
- [x] JSON atómico, locks interproceso, cuarentena, backup y restore.
- [x] Reescritura recuperable después de interrupción.
- [x] Estados Pending/Processing/Completed/Failed/Expired/Dead-letter.
- [x] Trazabilidad de expiraciones, descartes y fallbacks.
- [x] Configuración tipada y comando `doctor`.
- [x] Contratos mockeados de CMS, Facebook, Instagram y R2.
- [x] Fixtures/tests para diez secciones de scraping.
- [x] E2E local de 17 escenarios sin producción.
- [x] Seguridad de UI manual, uploads, paths y SSRF.
- [x] README y runbook operativo.

## Alta prioridad antes de habilitar producción

- [ ] Ejecutar smoke tests con cuentas y endpoints **de prueba** para CMS, Meta, R2 y
  OpenAI. Estado: bloqueado por falta de infraestructura/credenciales no productivas.
- [ ] Conciliar el backlog histórico de Facebook con la cuenta real. El código ahora
  registra causa y evidencia, pero la causa externa original no puede inferirse de los
  logs perdidos.
- [ ] Verificar el primer despliegue operativo: backup, `doctor`, heartbeat y un ciclo
  observado sin forzar publicaciones.

## Media prioridad de mantenimiento

- [x] Reemplazar `Image.Image.getdata` antes de Pillow 14.
- [ ] Agregar CI que cree un venv limpio y ejecute suite, compileall, dry-run y
  `git diff --check`.
- [ ] Probar explícitamente locks y reemplazo atómico sobre el filesystem real de
  producción si no es disco local.
- [ ] Definir retención/archivo externo de `queue_events.json` y logs según capacidad
  real del host.
- [ ] Agregar un comando de conciliación asistida para publicaciones sociales
  ambiguas; hasta entonces se resuelven con el runbook.
- [ ] Mantener fixtures cuando cambie el HTML vivo de terceros.

## Riesgos aceptados o bloqueados

- [ ] La aprobación editorial humana sigue siendo opcional. No existe una decisión
  vigente que autorice volverla obligatoria.
- [ ] No hay entorno de staging externo documentado.
- [ ] Visitas, CTR, alcance y monetización permanecen fuera de alcance.
- [ ] No migrar JSON a base de datos mientras las pruebas de integridad y volumen no
  demuestren que la solución actual es insuficiente.

## No incluido en esta etapa

Nuevas fuentes, nuevas redes, dashboard visual, analítica de audiencia, monetización,
multi-tenancy, cambio de CMS, microservicios, automatización masiva de Reels y
funcionalidades para otros medios.
