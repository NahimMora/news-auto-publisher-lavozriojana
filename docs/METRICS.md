# Métricas operativas

Última actualización: 2026-07-30. Este documento define métricas calculables; no
inventa valores ni implica que exista un dashboard.

## Fuentes de verdad

| Dato | Fuente |
|---|---|
| resultado de ciclo/etapa | `data/supervisor_heartbeat.json` y logs estructurados |
| edad del supervisor | `heartbeat_at_ts` |
| colas activas | JSON de staging, rewrite, web, meta y social |
| terminales/fallbacks | `data/queue_events.json` |
| publicaciones confirmadas | `noticias_web_publicadas.json`, `fb_posted.json`, `ig_posted.json` |
| errores externos | logs rotativos de publisher, R2 y clientes Meta |

`python cli.py status --json` es la vista segura y de sólo lectura para heartbeat y
colas.

## Contadores obligatorios por etapa

Cada `StageResult` expone:

- `received`: entradas visibles al inicio;
- `selected`: lote elegido;
- `processed`: intentos ejecutados;
- `succeeded`: resultados con evidencia;
- `failed`: intentos fallidos;
- `deferred`: elementos conservados para otro ciclo;
- `expired`: terminales por antigüedad;
- `duration_seconds`;
- `error_type`, `error_code` y `next_retry_at`.

No se deriva salud a partir de texto de logs. `no_work` es sano; `0/N` no es éxito;
un lote parcial es `degraded`.

## Indicadores calculables

### Tasa de éxito de etapa

```text
succeeded / processed
```

Sólo se calcula cuando `processed > 0`; de lo contrario se informa “sin muestra”.
Debe acompañarse con el status y no usarse para convertir `degraded` en `success`.

### Backlog

```text
pending + processing
```

Se desglosa por rewrite, web, meta, Facebook e Instagram. Para detectar crecimiento
se necesitan al menos dos heartbeats; el repositorio no afirma tendencia a partir de
un único snapshot.

### Antigüedad

- supervisor: ahora menos `heartbeat_at_ts`;
- ciclo: ahora menos `cycle_finished_at_ts`;
- cola: ahora menos el timestamp de encolado del elemento más antiguo.

El supervisor está stale si supera `PIPELINE_24X7_STALE_SECONDS`.

### Fallos por tipo

Agrupar `error_type` y `error_code` por etapa:

- `invalid_credential`;
- `rate_limit`;
- `network_error` / `timeout`;
- `http_4xx` / `server_error`;
- `invalid_json` / `state_error`;
- `selector_mismatch`;
- `ambiguous_external_outcome`.

Los rate limits deben registrar `next_retry_at`.

### Integridad y recuperación

- cantidad en `dead_letter`;
- cantidad `expired`;
- cantidad de cuarentenas JSON;
- trabajos recuperados desde `processing`;
- conflictos de flags editoriales en `reconciliation_required`;
- fallbacks publicados o bloqueados por tipo/categoría.

## Publicaciones

Una publicación cuenta sólo si el historial conserva evidencia externa:

- web: ID, URL o slug verificable;
- Facebook/Instagram: ID de Graph API y, cuando corresponda, URL pública;
- deduplicación por una publicación ya existente: evidencia explícita, nunca un
  booleano fabricado.

Los conteos históricos del documento anterior (~683 Facebook, 245 ciclos) provenían
de una observación puntual de datos/logs operativos del 2026-07-20. No se vuelven a
presentar como métricas actuales porque esta auditoría no leyó ni modificó esos datos
para recalcularlos.

## Métricas fuera de alcance

Visitas, CTR, alcance social, audiencia e ingresos no se recolectan en este
repositorio. Agregarlas sería una funcionalidad de producto y no forma parte de la
línea de base de confiabilidad.

## Alertas operativas

`utils/alerts.py` calcula y persiste eventos sin dashboard. Un operador debe
investigar:

- heartbeat stale;
- cualquier `failed`;
- `degraded` repetido;
- backlog creciente entre ciclos;
- credencial inválida;
- dead-letter nuevo;
- JSON corrupto/cuarentena;
- scraper `selector_mismatch`;
- rate limit después de `next_retry_at`.

La deduplicación usa `ALERT_DEDUP_SECONDS`. Una condición resuelta puede emitir
`recovery`. Dead-letter y cuarentena son eventos irreversibles y no generan una falsa
recuperación. `alert_outbox.json` conserva `delivery_status`, intentos, error y
`next_retry_at`; un webhook fallido no convierte el ciclo del pipeline en fallo.

## Auditoría de conteo de tests (rama `feature/premium-editorial-layer`, 2026-07-30)

Una síntesis previa de esta rama reportó "73 tests nuevos" con un desglose
(router 17, biblioteca 13, premium 28, Remotion 21) que en realidad sumaba 79, no
73 — una contradicción interna nunca verificada contra una corrida real. Esta
sección reemplaza esa cifra con el conteo real, medido con los comandos exactos
indicados, después de la ronda de correcciones (transición automatic↔candidate
completa, política de renderers por workflow).

| Medición | Comando | Resultado |
|---|---|---:|
| Baseline (`main`, sin los 4 archivos de test nuevos) | `python -m unittest discover tests` (con `test_editorial_router.py`, `test_media_library.py`, `test_premium_studio.py`, `test_remotion_visual.py` movidos fuera de `tests/` temporalmente) | **236** |
| Total actual (con todo restaurado) | `python -m unittest discover tests` | **336** |
| Neto agregado | 336 − 236 | **100** |

Desglose por archivo (`python -m unittest tests.<módulo>` individual):

| Archivo | Tests | Comando |
|---|---:|---|
| `tests/test_editorial_router.py` | 29 | `python -m unittest tests.test_editorial_router` |
| `tests/test_media_library.py` | 13 | `python -m unittest tests.test_media_library` |
| `tests/test_premium_studio.py` | 14 | `python -m unittest tests.test_premium_studio` |
| `tests/test_premium_meta_publishing.py` | 14 | `python -m unittest tests.test_premium_meta_publishing` |
| `tests/test_remotion_visual.py` | 30 | `python -m unittest tests.test_remotion_visual` |
| **Total nuevo** | **100** | 29+13+14+14+30 |

Notas de exactitud:

- `pytest` no está instalado en el entorno (`venv/Scripts/python.exe -m pytest
  --version` → `No module named pytest`); el conteo autoritativo usa
  `unittest`, la herramienta que ya documenta `AGENTS.md` para este repositorio.
- Ningún test nuevo usa `@parameterized` ni un patrón que infle el conteo de
  `unittest`; hay un uso de `self.subTest(...)` en
  `test_remotion_visual.py::NoGoldInTokensTests.test_new_compositions_do_not_reference_gold`,
  que cuenta como **un** test en `unittest` (subTest no crea entradas separadas en
  "Ran N tests").
- `tests/test_premium_studio.py` originalmente tenía 28 tests; se separó en dos
  archivos (`test_premium_studio.py` con 14 — contrato/importador/store de
  borradores — y `test_premium_meta_publishing.py` con 14 — clientes Meta +
  orquestador) para que cada commit lógico incluya únicamente sus propias
  pruebas, sin perder ni duplicar ningún caso (28 = 14 + 14, verificado corriendo
  ambos archivos juntos).
- El total de 336 fue confirmado corriendo la suite completa dos veces
  consecutivas con resultado idéntico.

## Auditoría de tests del rediseño Premium Studio UX (2026-07-30)

Baseline de esta rama: `4b8a1c7` con **336 casos**. El rediseño agrega **18** casos
sin retirar ninguno, para un total descubierto de **354**:

| Medición | Comando | Resultado |
|---|---|---:|
| Baseline de la rama | suite de `4b8a1c7` extraída con `git archive`, `python -W error::DeprecationWarning -m unittest discover tests` | **336** |
| Total descubierto actual | `python -c "import unittest; print(unittest.defaultTestLoader.discover('tests').countTestCases())"` | **354** |
| Neto agregado | 354 − 336 | **18** |
| Ejecución local actual | `python -W error::DeprecationWarning -m unittest discover tests` con `PYTHON_DOTENV_DISABLED=1` y todos los directorios `LVR_*` temporales | **350 OK, 1 skip de clase** |

El `Ran 350 tests (skipped=1)` local no contradice los 354 casos descubiertos:
`RemotionLiveRenderTests.setUpClass` detectó `remotion/node_modules`, intentó el CLI
y, como no respondió en este host, elevó un único `SkipTest` de clase que agrupó sus
cuatro métodos de render real. Una auditoría del `TestResult` confirmó que ésos son
exactamente los cuatro IDs no iniciados. En CI no se instala Node y los cuatro quedan
saltados individualmente. Ninguno de los 18 casos de esta rama fue omitido.

Desglose del neto:

| Archivo | Antes | Ahora | Neto | Cobertura |
|---|---:|---:|---:|---|
| `tests/test_premium_package_generator.py` | 0 | 4 | +4 | éxito OpenAI, contrato, reintentos/fallo final, texto vacío, credencial ausente |
| `tests/test_premium_studio_http.py` | 0 | 11 | +11 | descarga SSRF-safe, endpoints generate/link/upload/thumb y estructura UI |
| `tests/test_media_library.py` | 13 | 16 | +3 | lookup inmutable, confinamiento del thumb y URL HTTP en `_asset_row()` |
| **Total** | **13** | **31** | **+18** | todos ejecutados y verdes |

Comandos focalizados:

```powershell
python -m unittest tests.test_premium_package_generator -v  # 4/4
python -m unittest tests.test_premium_studio_http -v         # 11/11
python -m unittest tests.test_media_library -v               # 16/16
```

Las pruebas HTTP levantan `ThreadingHTTPServer` en un puerto loopback efímero, usan
directorios temporales y mocks para OpenAI/descarga remota. No leen secretos, no
llaman publicadores y no tocan estado productivo.

Smoke visual adicional con navegador real: servidor en `127.0.0.1:8766`,
directorios `LVR_*` temporales, `PREMIUM_STATIC_RENDER_ENGINE=pillow` y
`PREMIUM_PUBLISH_DRY_RUN=true`. Resultado: 3 slides editables, 3 tarjetas de assets,
2 uploads promovidos con miniatura HTTP, 3 imágenes de preview y publicación dry-run
`instagram: OK · facebook: OK`; consola del navegador sin errores. Se usó el import
JSON manual para no realizar una llamada OpenAI externa durante QA; la rama de
generación está cubierta con mock tanto en módulo como contra el endpoint HTTP real.

Gates de cierre ejecutados en el mismo workspace:

| Gate | Resultado |
|---|---|
| `python cli.py run-once --dry-run` | **17/17 OK**, `production_calls=false` |
| `python cli.py doctor --scope core --json` | **success 8/8** con modo `observe` y los tres canales apagados sólo para ese proceso |
| `python cli.py doctor --scope all --json` | **success 8/8** con los mismos overrides seguros |
| `python -m compileall -q .` | **OK** |
| chequeo sintáctico del `<script>` embebido con Node | **OK** |
| `git diff --check` | **OK** |

La configuración persistente del host no se modificó: el primer `doctor core` sin
overrides detectó correctamente que `PIPELINE_DEPLOYMENT_MODE=observe` no coincide
con el canal Web habilitado. El gate aislado se repitió con
`WEB_PUBLISH_TARGET=off`, `FB_PUBLISH_ENABLED=false` e
`IG_PUBLISH_ENABLED=false`; no se cambió `.env` ni se presentó el bloqueo original
como éxito.

`python -m pip check` no está verde en el Python global del host por tres
incompatibilidades preexistentes entre paquetes instalados
(`pydantic-settings/pydantic`, `pillow-heif/Pillow` y `fastapi/starlette`). Esta rama
no cambia `requirements.txt`, no instala dependencias y toda la suite del repositorio
pasó con el entorno actual.

## Benchmark Remotion vs Pillow (Fase 4, medido 2026-07-30)

`scripts/benchmark_static_render.py` renderiza 10 paquetes premium de
fixture (títulos cortos/largos, con/sin imagen, título vacío, las tres
plantillas) una vez con cada motor. Resultado real de esta corrida en el
host de desarrollo (Node v22.20.0, Windows):

| Métrica | Pillow | Remotion |
|---|---:|---:|
| Éxito | 10/10 | 10/10 |
| Tiempo promedio por paquete | 0.034s | 19.119s |
| Tiempo total (10 paquetes) | 0.344s | 191.188s |
| Tamaño promedio por paquete (bytes) | 109.499 | 125.983 |
| Dimensiones | 1080×1350 en todos los casos | 1080×1350 en todos los casos |

Causa del tiempo de Remotion: cada `npx remotion still` (uno por slide)
re-bundlea el proyecto desde cero — no hay bundle cacheado ni servidor
persistente en esta implementación. Ver `remotion/README.md` para el
detalle y la mitigación propuesta (servidor de render persistente antes de
usar Remotion en un flujo de alto volumen).

Diferencia funcional detectada: el renderer Pillow detecta y reporta
`titulo_desborda` (overflow) para el único fixture con título largo (~190
caracteres); el path Remotion no genera esa advertencia todavía (no mide la
altura real del texto renderizado) — ver `docs/KNOWN_ISSUES.md`.

No se inventaron valores: esta tabla refleja exactamente la salida de la
corrida documentada; para reproducir, ejecutar
`python scripts/benchmark_static_render.py`.

## Métricas de despliegue

El heartbeat versión 2 agrega:

- `commit_sha`;
- `release_tag`;
- `deployment_mode`;
- `configuration_fingerprint`;
- `operator`;
- `backup_reference`.

El fingerprint omite nombres de variables sensibles y no contiene valores de tokens.
El estado de gates no se infiere de métricas: se registra explícitamente en la
auditoría y el PR.

## Snapshot operativo 2026-07-27

Snapshot puntual después del ciclo #8 en modo `all`:

| Métrica | Valor |
|---|---:|
| ciclo | 8 |
| scraping/rewrite | `success`, 16/16 |
| Web | `degraded`, 24/26; 2 terminales sensibles |
| Facebook | `success`, 8/8; 16 diferidas por cupo |
| Instagram | `success`, 8/8; 5 diferidas |
| cola Web | 0 |
| cola Meta de origen | 26 |
| social Facebook/Instagram pending | 16/3 |
| rewrite pending/processing/failed/dead-letter | 0/0/0/0 |
| heartbeat | `fresh` |
| filesystem libre durante preflight | 34.065 MB |

La ventana inicial quedó en 20 identidades y el scraping del mismo ciclo incorporó
seis nuevas. Web sin cupo procesó las 26 en 1.151,578 segundos: publicó 24, registró
siete publicaciones degradadas y envió dos entradas sensibles a estado terminal. La
cola Web quedó en cero; el resultado general permaneció `degraded`, como exige el
contrato para 24/26.

Facebook respetó exactamente el cupo configurado de ocho. Instagram procesó ocho:
siete publicaciones externas y una deduplicación con evidencia existente; el
`StageResult` las cuenta como ocho resultados aceptables. Lo restante permanece
durable para ciclos posteriores y no se vació.

Durante este ciclo se reprodujeron falsos positivos del validador editorial con
sustantivos/verbos al comienzo de oración y con equivalencias “dos/tres” frente a
`2/3`. `LVR-075` y `LVR-076` conservan la reproducción, corrección y regresiones. Esos
correctivos se cargan en el reinicio controlado posterior al ciclo; la evidencia del
ciclo #8 corresponde al commit registrado por su heartbeat, no al código posterior.

El ciclo #5 fue `degraded`: Instagram rechazó 1/1 mientras Web y Facebook fueron
`success`. El elemento quedó en dead-letter y no se reintentó; el ciclo #6 confirmó
que la integración seguía operable. Los rechazos posteriores a `LVR-069` agregan al
evento terminal `http_status`, código/subcódigo y tipo del proveedor sin copiar el
mensaje ni el cuerpo externo.

Observación posterior con el commit final: ciclo #10 Web 6/6 e Instagram 1/1, pero
Facebook 5/8 porque tres páginas aún no estaban públicamente disponibles para el
prewarm. Las tres quedaron pendientes y Graph no fue llamado. El ciclo #11 terminó
`success` 4/4, Facebook 8/8, Web/Instagram `no_work`, cola Web 0, Facebook pending 3
e Instagram pending 0.
