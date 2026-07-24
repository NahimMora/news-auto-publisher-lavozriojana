# Estado actual

Última actualización: 2026-07-23. Línea de base:
`reliability/baseline-2026-07-23`, creada desde
`fbb83eac3cf3ce399dac5a9d778f81a1957d7c2a`.

## Estado verificable

El repositorio quedó preparado como línea de base para nuevas actualizaciones, no
declarado “sin errores”. La evidencia local disponible demuestra:

- instalación Python basada sólo en `requirements.txt`, incluido `psutil`;
- 147 pruebas automatizadas sin llamadas a producción;
- 17 escenarios end-to-end completamente locales;
- resultados funcionales uniformes: `success`, `no_work`, `degraded`, `failed`;
- heartbeat persistente, antigüedad del ciclo y tamaños de cola;
- escrituras JSON atómicas, locks interproceso, backups y cuarentena;
- reanudación de reescritura con Pending/Processing/Completed/Failed/Expired/Dead-letter;
- publicación web sólo confirmada con ID, URL o slug verificable;
- errores y rate limits tipados para CMS, Facebook, Instagram y R2;
- fixtures representativas para las diez secciones de scraping;
- política explícita y medible de fallbacks editoriales;
- interfaz manual limitada a loopback y validaciones de URL/upload.

No se publicaron contenidos, no se usaron credenciales productivas y no se modificó
deliberadamente el estado de producción. Los tests usan `LVR_DATA_DIR`,
`LVR_LOGS_DIR`, `LVR_OUTPUT_DIR` y `LVR_FOTOS_DIR` temporales.

## Operación actual

El supervisor ejecuta scraping/rewrite, web, Facebook e Instagram como etapas
aisladas. “El proceso terminó” ya no equivale a “la etapa funcionó”: cada hijo emite
un resultado JSON y el supervisor rechaza una salida cero sin contrato.

`python cli.py status --json` es de sólo lectura. Informa:

- identidad y estado del PID;
- heartbeat ausente, fresco, stale, inválido o corrupto;
- edad del último ciclo;
- último resultado por etapa;
- tamaño y legibilidad de las colas.

`python cli.py doctor --scope ...` valida configuración sin publicar.
`python cli.py run-once --dry-run` ejecuta sólo el E2E local. El comando sin
`--dry-run` puede ejecutar integraciones habilitadas y debe tratarse como operación
real.

## Persistencia y compatibilidad

Se mantienen los JSON legacy y sus nombres. Los scrapers persisten primero la cola y
después el historial. La reescritura transfiere staging a
`rewrite_queue_state.json` antes de vaciarlo; una transferencia repetida es
idempotente. Los estados terminales y descartes se registran en
`queue_events.json`.

Los archivos existentes no requieren migración masiva. Al primer ciclo:

1. los elementos de staging se incorporan a la cola durable;
2. los IDs ya conocidos no se duplican;
3. un `processing` interrumpido vuelve a `pending`;
4. las salidas web/meta conservan sus contratos legacy.

Un JSON corrupto no se interpreta como vacío, se conserva en origen, se copia a
`quarantine/` y levanta un error explícito. Las escrituras usan temporal único,
flush/fsync, reemplazo atómico y lock.

## Integraciones externas

Los contratos están probados mediante mocks para 200, 201, 400, 401, 409, 429, 500,
red, no-JSON y `ok:false`, además de reintentos/backoff y evidencia externa. No se
verificó el estado real actual de:

- tokens y cuentas de Meta;
- bucket y credenciales de Cloudflare R2;
- API desplegada del CMS;
- cuota de OpenAI;
- HTML vivo de los sitios fuente.

Esas verificaciones quedan **bloqueadas por entorno** y no se sustituyen por una
afirmación de salud. Antes de habilitar producción se necesita un smoke test
controlado con credenciales no productivas o una ventana autorizada.

## Riesgo residual

- Los JSON seguros reducen pérdida y corrupción, pero siguen dependiendo de la
  semántica de locks/reemplazo atómico del filesystem local. No se validó un share de
  red.
- No existe staging externo independiente.
- Una respuesta social ambigua no se reintenta automáticamente: pasa a dead-letter
  para conciliación, priorizando no duplicar.
- Los cambios futuros de selectores HTML requieren actualizar fixtures y una prueba
  read-only contra el tercero.
- La verificación editorial humana continúa siendo opcional; la política actual
  bloquea fallbacks sensibles pero no cambia la línea editorial.

## Próximo objetivo

Revisar el PR de esta línea de base, ejecutar un smoke test contra entornos de prueba
de CMS/Meta/R2 y recién después comenzar funcionalidades nuevas. El runbook operativo
está en `docs/RUNBOOK.md` y la evidencia detallada en
`docs/audits/2026-07-23-linea-base.md`.
