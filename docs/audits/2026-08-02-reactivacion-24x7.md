# Reactivación controlada 24/7 — 2026-08-02

## Alcance

Reactivar el autopublicador de Web, Facebook e Instagram con las noticias de hoy o,
si las fuentes no tenían publicaciones del 02/08, las 20 más recientes disponibles;
dejar el servicio habilitado para ciclos futuros.

## Preparación sin publicación

- Supervisor inexistente y tarea `LaVozRiojana-24x7` deshabilitada al iniciar.
- `preflight`: fuentes 10/10, OpenAI, R2 con cleanup confirmado, Facebook, Instagram
  y filesystem `success`.
- CMS: `blocked` por ausencia de `WEBAPP_PREFLIGHT_PATH`; no se falseó como éxito.
- Conciliación Facebook report-only: 0 ambiguos, 0 inválidos, 0 pendientes válidos y
  8 entradas vencidas por TTL.
- Primer reporte de corte: 214 Meta, 20 retenibles y `unknown_order=0`; se respaldó y
  archivó el backlog, pero la inspección mostró que esas entradas eran del 30/07.
- Refresco controlado con `PIPELINE_DEPLOYMENT_MODE=observe` y los tres kill switches
  apagados: 100 noticias procesadas, 0 fallos, 39 expiradas, 58 Web y 54 Meta nuevas.

## Corte final

- Reporte final previo: 78 identidades, `unknown_order=0`.
- Se creó un segundo backup completo.
- Corte aplicado: 38 Web, 58 Meta y 8 estados sociales archivados/excluidos.
- Estado inicial productivo: 20 identidades únicas del 01/08, encoladas el 02/08;
  20 Web, 16 Meta y 0 estados sociales activos.

## Activación

- `start_24x7_production.ps1 -ValidateOnly`: `doctor supervisor` 8/8 `success`.
- Perfil: modo `all`, Web/Facebook/Instagram encendidos, canary apagado, Web sin cupo
  y Meta acotado por ciclo.
- Tarea `LaVozRiojana-24x7`: habilitada, `LastTaskResult=0`.
- Supervisor: heartbeat fresco y proceso coincidente.
- UI manual: HTTP 200, listener sólo en `127.0.0.1:8765`.

## Primer ciclo productivo (#81)

| Etapa | Resultado | Evidencia |
|---|---:|---|
| Scraping/reescritura | `no_work` | la ingesta previa ya había consumido las fuentes |
| Web | `degraded`, 17/17 | 3 duplicados, 0 terminales, 5 sextos intentos seguros |
| Facebook | `success`, 5/5 | 5 IDs externos, preview de nota y OG verificados |
| Instagram | `success`, 2/2 | 2 IDs externos, Remotion automático con paridad 2× |

El ciclo global quedó `degraded` exclusivamente por
`editorial_final_attempt_published`. Esos cinco casos conservaban warnings de
similitud/revisión sin cambio material; ninguna publicación atravesó warnings
factuales, judiciales o de HTML. `ambiguous_to_dead_letter=0` en ambas plataformas
Meta.

## Riesgo conocido

El CMS continúa sin endpoint read-only autenticado de capacidad. Las 17 publicaciones
de este ciclo aportan ID/URL y escritura operable, pero no reemplazan ese preflight.
La activación se realizó bajo la excepción ya documentada y una autorización
operativa explícita vigente.
