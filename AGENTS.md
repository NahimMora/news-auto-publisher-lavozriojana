# AGENTS.md

Instrucciones permanentes para agentes de programación en
`AutoPublicador_LaVozRiojana`.

## Contexto obligatorio

Antes de modificar negocio, leer `docs/PRODUCT.md`, `docs/CURRENT_STATE.md`,
`docs/ARCHITECTURE.md`, `docs/KNOWN_ISSUES.md`, `docs/DECISIONS.md` y este archivo.
El sistema scrapea noticias, las reescribe/clasifica y publica en CMS, Facebook e
Instagram. Producción usa cuentas externas reales: no ejecutar publicadores sin
autorización explícita.

## Instalación

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python init_data.py
python cli.py doctor --scope core
```

Python 3.10+ es requerido. `ffmpeg` y `ffprobe` son dependencias del sistema para
video. `psutil` ya está declarado en requirements.

## Tests y QA

```powershell
python -m unittest discover tests -v
python cli.py run-once --dry-run
python cli.py doctor --scope all --json
python -m compileall -q .
```

La suite usa mocks/fixtures y debe ejecutarse con directorios temporales cuando una
prueba manual pueda tocar estado:

```powershell
$env:LVR_DATA_DIR="$env:TEMP\lvr-qa\data"
$env:LVR_LOGS_DIR="$env:TEMP\lvr-qa\logs"
$env:LVR_OUTPUT_DIR="$env:TEMP\lvr-qa\output"
$env:LVR_FOTOS_DIR="$env:TEMP\lvr-qa\fotos"
```

Para scrapers e imágenes existen además `test_scraper.py` y
`preview_pipeline.py --n 5`. Acceden a terceros/datos y generan artefactos: usarlos
sólo como QA read-only controlada, nunca como sustituto de fixtures. No ejecutar
`cli.py run-once` sin `--dry-run` para validar un cambio: puede publicar si hay targets
habilitados.

## Convenciones

- Docstrings, comentarios, logs y mensajes al operador: español de Argentina.
- Entry points standalone: `load_dotenv()` y `sys.path.insert(0, ...)`.
- Logging: `setup_logger(nombre, "archivo.log")`, siempre con archivo.
- Resultados: usar `StageResult`; no inferir salud de texto ni devolver éxito falso.
- `no_work` no es error; parcial o rate limit es `degraded`; credencial inválida es
  `failed`.
- Estado: usar `utils/file_manager.py`; nunca implementar read-modify-write con
  `load_json` seguido de `save_json`. Usar `update_json`/`update_json_files`.
- Un JSON corrupto debe fallar y quedar en cuarentena, no transformarse en `[]`.
- No vaciar una entrada antes de una transferencia durable.
- Toda publicación completada requiere ID/URL/slug o evidencia equivalente.
- Los outcomes externos ambiguos no se reintentan a ciegas.
- Categorías: `policiales`, `interior`, `sociedad`, `economia`, `salud`, `educacion`,
  `deportes`, `cultura`, `espectaculos`, `politica`.
- Prompts nuevos deben decir explícitamente que no se inventen datos, armas, personas
  ni hechos ajenos al original.
- Los scrapers de Tiempo Popular son wrappers de `base_tiempopopular.py`; no duplicar
  parseo.

## Rutas protegidas

- `data/`: estado productivo. No editar, borrar ni migrar manualmente.
- `logs/`: sólo lectura para diagnóstico.
- `output/`, `FotosLVR/`: artefactos no versionados.
- `.env`: secretos reales; no leer completo, imprimir ni commitear.

Para tests y desarrollo use las variables `LVR_DATA_DIR`, `LVR_LOGS_DIR`,
`LVR_OUTPUT_DIR` y `LVR_FOTOS_DIR`.

## Seguridad

- No loguear tokens ni claves; la redacción central no habilita a incluirlos.
- No retirar backoff/retries de Meta/OpenAI/R2.
- Validar URLs no confiables con `utils/safe_http.py`.
- Validar uploads por contenido y ruta; no invocar ffmpeg mediante shell.
- `video_reel_manager.py` permanece sólo en loopback.
- Verificar `git remote -v` y `git status` antes de push: el proyecto tuvo un repo de
  Desktop mezclado históricamente.

## Compatibilidad

- Mantener staging pre-IA separado de `noticias_meta.json` y
  `noticias_web_pending.json`.
- No cambiar forma de JSON sin migración idempotente, backup previo, test y decisión.
- No introducir base de datos por preferencia; registrar evidencia en
  `docs/DECISIONS.md`.
- Mantener los estados Pending/Processing/Completed/Failed/Expired/Dead-letter y el
  journal `queue_events.json`.

## Definition of Done

- Suite completa y E2E local pasan.
- `doctor` y `compileall` pasan para el alcance.
- Tests no usan secretos ni publican.
- Cambios de scraping/imagen/video tienen fixture o criterio visual controlado.
- Contratos externos tienen mocks de éxito y fallos.
- Recuperación, concurrencia y corrupción se prueban si se toca persistencia.
- Sin secretos ni cambios de `data/`, `logs/`, `output/` o `FotosLVR/` en el diff.
- `CURRENT_STATE`, `KNOWN_ISSUES`, `DECISIONS` y runbook reflejan el comportamiento.
- No hay hallazgos críticos/altos reproducibles abiertos sin tratamiento.

## Preparación y despliegue 24/7

- CI autoritativo: `.github/workflows/reliability.yml` sobre `windows-latest`.
- Reproducir CI local con deprecaciones como error, `compileall`, `doctor core`,
  dry-run y `git diff --check`.
- El default es `PIPELINE_DEPLOYMENT_MODE=observe` con web, Facebook e Instagram
  apagados.
- No cambiar automáticamente de modo. Cada modo debe coincidir con
  `WEB_PUBLISH_TARGET`, `FB_PUBLISH_ENABLED` e `IG_PUBLISH_ENABLED`.
- Antes de habilitar un canal, ejecutar su preflight read-only. `blocked` es un gate
  incumplido, no éxito.
- El preflight R2 sólo usa `healthchecks/<timestamp>-<uuid>` y debe confirmar la
  eliminación.
- Un canary externo exige `CANARY_ENABLED=true` y
  `--confirm-external-publication`; sin ambos se niega.
- No ejecutar canary, cleanup externo, merge, tag ni supervisor productivo sin una
  autorización explícita vigente.
- Facebook requiere `reconcile-facebook --report-only` antes de habilitar el canal.
  Aplicar sólo archivos de decisiones aprobadas; no inferir publicación por título.
- Alertas: detección, dedupe, outbox y entrega permanecen separadas. El fallo del
  webhook no puede cambiar el resultado funcional del pipeline.
- La propuesta de tag es `v1.0.0-reliability-baseline`; no crearla antes del merge
  aprobado.
