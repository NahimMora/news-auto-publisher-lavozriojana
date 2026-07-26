# La Voz Riojana — publicador automático

Pipeline Python, Windows-first, que captura noticias riojanas, las valida y
reescribe, prepara imágenes o videos y publica en el CMS, Facebook e Instagram. El
estado operativo se conserva en JSON locales; no requiere una base de datos.

Esta rama es una preparación de confiabilidad. No está habilitada para producción
24/7: los gates externos, canary, observación progresiva y aprobación del PR todavía
deben completarse.

## Instalación

Requiere Python 3.10 o posterior. `ffmpeg` y `ffprobe` son dependencias del sistema
para video y no se instalan con pip.

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python init_data.py
python cli.py doctor --scope core --json
```

Las integraciones nacen deshabilitadas. Nunca use credenciales productivas en tests.

## CI y validación local

El workflow `.github/workflows/reliability.yml` reproduce en `windows-latest`:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
pip check
python -W error::DeprecationWarning -m unittest discover tests
python -m compileall -q .
python cli.py doctor --scope core --json
python cli.py run-once --dry-run --json
git diff --check
```

El dry-run ejecuta 17 escenarios end-to-end locales con dobles de OpenAI, R2, CMS y
Meta, directorios temporales y `production_calls=false`. No lee colas operativas ni
publica. `run-once` sin `--dry-run` sí puede publicar y requiere una ventana
autorizada.

## Aislamiento

```powershell
$env:LVR_DATA_DIR="$env:TEMP\lvr-qa\data"
$env:LVR_LOGS_DIR="$env:TEMP\lvr-qa\logs"
$env:LVR_OUTPUT_DIR="$env:TEMP\lvr-qa\output"
$env:LVR_FOTOS_DIR="$env:TEMP\lvr-qa\fotos"
$env:LVR_BACKUP_DIR="$env:TEMP\lvr-qa\backups"
$env:LVR_QUARANTINE_DIR="$env:TEMP\lvr-qa\quarantine"
python init_data.py
```

## Resultados y diagnóstico

Los estados son:

| Estado | Significado | Exit |
|---|---|---:|
| `success` | trabajo seleccionado completado con evidencia | 0 |
| `no_work` | ejecución sana sin trabajo | 0 |
| `degraded` | parcial, rate limit o capacidad reducida | 2 |
| `failed` | fallo funcional | 1 |
| `blocked` | faltó credencial, endpoint, entorno o autorización | 3 |

```powershell
python cli.py status --json
python cli.py doctor --scope supervisor --json
python cli.py preflight --scope filesystem --json
python cli.py preflight --scope sources --json
python cli.py preflight --scope all --json
```

`blocked` nunca equivale a salud. El preflight general no publica. R2 es la única
verificación reversible: crea un objeto UUID bajo `healthchecks/`, confirma lectura,
lo elimina y confirma el cleanup.

## Despliegue progresivo

`PIPELINE_DEPLOYMENT_MODE` admite `observe`, `web_only`, `web_facebook`,
`web_instagram` y `all`; su default es `observe`.

Los kill switches siguen siendo autoridad:

- web: `WEB_PUBLISH_TARGET=off|node_webapp`;
- Facebook: `FB_PUBLISH_ENABLED=false|true`;
- Instagram: `IG_PUBLISH_ENABLED=false|true`.

El modo nunca enciende un switch apagado. Una contradicción falla en `doctor`. Los
modos con publicación inyectan un máximo inicial de una publicación por canal y
ciclo. No existe escalamiento de modo ni deploy automático.

## Canary controlado

```powershell
python cli.py canary --input <fixture.json> --channels web --dry-run --json

# Publicación externa real: sólo con autorización explícita.
$env:CANARY_ENABLED="true"
python cli.py canary --input <fixture.json> --channels web `
  --confirm-external-publication --json
```

El canary no consume la cola general, rechaza categorías sensibles y breaking,
publica como máximo una vez por canal y persiste evidencia idempotente. Un outcome
ambiguo no se reintenta automáticamente. `--cleanup` usa el mismo gate y puede
informar cleanup manual si el proveedor no ofrece un endpoint seguro.

## Conciliación de Facebook

```powershell
python cli.py reconcile-facebook --report-only --json
python cli.py reconcile-facebook --apply <decisiones-aprobadas.json> --json
```

El reporte no modifica la cola y clasifica por identidad estable y evidencia, nunca
por similitud de título. `--apply` exige el `report_id` vigente, sólo toca elementos
aprobados y no marca publicado sin `external_id`.

## Alertas

La arquitectura mínima es detección → dedupe → outbox durable → adaptador webhook.
La entrega queda deshabilitada por defecto y nunca bloquea el pipeline.

```powershell
python cli.py alert-test --json
python cli.py alert-check --json
```

Sin webhook, el evento queda en el outbox local. Se detectan heartbeat stale, etapas
fallidas, tres degradaciones consecutivas, dead-letter nuevo, backlog creciente,
credencial inválida, JSON en cuarentena, selector roto, rate limit vencido y poco
espacio.

## Operación, backup y rollback

```powershell
python cli.py start
python cli.py stop
python cli.py logs supervisor
python cli.py backup
```

El heartbeat registra resultados, colas, commit, release declarado, modo,
fingerprint sin secretos, operador y referencia de backup. Lea
[el runbook](docs/RUNBOOK.md) antes de cambiar de modo o restaurar.

## Release

La propuesta es `v1.0.0-reliability-baseline`. No se debe crear ni publicar el tag
antes del merge aprobado.

## Documentación

- [Estado actual](docs/CURRENT_STATE.md)
- [Arquitectura](docs/ARCHITECTURE.md)
- [Métricas](docs/METRICS.md)
- [Backlog](docs/BACKLOG.md)
- [Decisiones](docs/DECISIONS.md)
- [Runbook](docs/RUNBOOK.md)
- [Problemas conocidos](docs/KNOWN_ISSUES.md)
- [Auditoría 24/7](docs/audits/2026-07-26-preparacion-24x7.md)
- [Instrucciones para agentes](AGENTS.md)

## Seguridad

No versione `.env`, `data/`, `logs/`, `output/` ni `FotosLVR/`. La UI de Reels sólo
acepta loopback. Las verificaciones mockeadas prueban contratos, no la salud real de
terceros.
