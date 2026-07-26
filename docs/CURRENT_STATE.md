# Estado actual

Última actualización: 2026-07-26.

## Rama y revisión

- Repositorio: `NahimMora/news-auto-publisher-lavozriojana`.
- Base de `main`: `fbb83eac3cf3ce399dac5a9d778f81a1957d7c2a`.
- Rama: `reliability/baseline-2026-07-23`.
- PR borrador: [#1](https://github.com/NahimMora/news-auto-publisher-lavozriojana/pull/1).
- Estado observado antes de estos cambios: mergeable, 5 commits, 106 archivos, sin
  revisiones, comentarios ni checks.
- Estado actual de CI: `reliability-windows` verde en Actions run
  [`30210229086`](https://github.com/NahimMora/news-auto-publisher-lavozriojana/actions/runs/30210229086).
- `main` exige el check `reliability-windows` en modo strict, resolución de
  conversaciones y aplica la protección también a administradores; force-push y
  borrado están deshabilitados.
- Propuesta de release posterior al merge: `v1.0.0-reliability-baseline`.

El PR permanece en borrador. No se hizo merge ni se creó el tag.

## Estado verificable del código

La línea de base incluye:

- CI Windows reproducible y sin secretos productivos;
- suite completa y E2E local aislado;
- estados `success`, `no_work`, `degraded`, `failed` y `blocked`;
- preflight read-only por integración y prueba reversible de R2;
- canary externo gated, idempotente y fuera de las colas generales;
- reporte y aplicación explícita para conciliación de Facebook;
- alertas con detección, dedupe, outbox y webhook opcional;
- modos `observe`, `web_only`, `web_facebook`, `web_instagram` y `all`;
- kill switches que el modo de despliegue no puede sobrepasar;
- máximo inicial de una publicación por canal y ciclo;
- heartbeat con commit, release declarado, modo, fingerprint, operador y backup;
- persistencia JSON atómica, locks, backup, restore, cuarentena y recuperación;
- contratos mockeados de CMS, Meta, R2 y OpenAI;
- fixtures de las diez secciones de scraping.

La validación local más reciente y sus comandos quedan en
`docs/audits/2026-07-26-preparacion-24x7.md`.

## Verificaciones reales realizadas

Hechos comprobados el 2026-07-26:

- `preflight sources`: 10/10 secciones `success` después de corregir la variante de
  host y slash final de Tiempo Popular;
- `preflight filesystem`: `success` en el volumen `C:`, con 28.628 MB libres al
  medir, dos writers, lock, replace, fsync, backup/restore y cuarentena;
- `preflight supervisor`: `success` en directorios temporales, modo `observe`, sin
  iniciar el supervisor;
- `alert-test`: `success` con outbox local y sin webhook;
- conciliación Facebook sobre copias temporales: 23 entradas clasificadas, sin
  modificar la cola original: 1 `already_published`, 3 `pending_valid` y 19
  `blocked_missing_web_url`.

Información todavía desconocida o bloqueada:

- OpenAI real: no ejecutado con credencial autorizada;
- R2 real: no ejecutado porque crea/elimina un objeto externo;
- CMS real: no existe evidencia de `WEBAPP_PREFLIGHT_PATH` seguro;
- Facebook/Instagram real: identidad y permisos no se consultaron con token;
- canary real: no autorizado ni ejecutado;
- webhook real: no configurado;
- revisión/aprobación humana del PR: pendiente.

Los mocks no se presentan como evidencia real de estas integraciones.

## Estado operativo

El supervisor está detenido durante la preparación.

Se comprobó que antes de esta tarea había quedado un supervisor real ejecutándose por
una orden anterior del operador. Su último ciclo quedó `degraded` y registró
publicaciones reales: web 16 exitosas de 19 procesadas, Facebook 8 de 10 e Instagram
8 de 8. Esta ejecución:

- no fue un canary;
- no satisface los gates de esta preparación;
- contradijo la documentación del 2026-07-23 que decía que producción no se había
  iniciado;
- motivó detener el supervisor antes de modificar contratos.

No se reinició y no se realizaron nuevas publicaciones externas durante este trabajo.

## Modo de despliegue

El default del código y `.env.example` es `observe`, con todos los canales externos
apagados. La configuración productiva existente no se editó; si conserva switches
encendidos sin declarar un modo compatible, `doctor --scope supervisor` falla y
evita el arranque.

No hay escalamiento automático. Los gates se completan en orden: código, entorno,
integraciones read-only, canary, observe, web, Facebook, Instagram y recién después
24/7 completo.

## Backlog de Facebook

El comando read-only quedó implementado. El reporte sobre copia del estado real
clasificó todas las entradas, pero 19 de 23 no tienen URL web. Facebook permanece
bloqueado hasta resolver esas entradas mediante decisiones explícitas y volver a
generar el reporte. No se reencoló, eliminó ni marcó ninguna entrada.

## Gate actual

- Gate A (código): CI remoto verde, suite/compile/doctor/E2E verdes y branch
  protection activa; pendiente de revisión/aprobación humana.
- Gate B (entorno): filesystem temporal pasó; backup productivo y restore operativo
  todavía no fueron autorizados/ensayados.
- Gate C (integraciones): fuentes pasaron; las demás están bloqueadas.
- Gates D a I: no ejecutados.

Por lo tanto, el proyecto **no se declara listo para producción 24/7**. El siguiente
paso seguro es obtener revisión del PR; luego completar Gate B y los preflights
externos autorizados.
