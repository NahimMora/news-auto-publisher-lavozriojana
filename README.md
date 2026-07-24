# La Voz Riojana — publicador automático

Pipeline Python, orientado a Windows, que captura noticias riojanas, las valida y
reescribe, prepara imágenes o videos y las publica en el CMS, Facebook e Instagram.
El estado operativo se conserva en archivos JSON locales; no se requiere una base de
datos.

## Instalación

Requiere Python 3.10 o posterior. `ffmpeg` y `ffprobe` son dependencias del sistema
para render y validación de videos; no se instalan con pip.

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python init_data.py
python cli.py doctor --scope core
```

Las integraciones nacen deshabilitadas en `.env.example`. Antes de activar una,
complete sólo sus credenciales y ejecute `doctor` con el alcance correspondiente.
Nunca use credenciales productivas en tests.

## Validación segura

```powershell
python -m unittest discover tests -v
python cli.py run-once --dry-run
python cli.py doctor --scope all --json
```

`run-once --dry-run` ejecuta 17 escenarios locales con dobles de OpenAI, R2, CMS y
Meta. No lee las colas operativas ni publica contenido. En cambio, `run-once` sin
`--dry-run` sí ejecuta el ciclo configurado y puede publicar si los targets están
habilitados.

Para aislar un ensayo manual de los datos reales:

```powershell
$env:LVR_DATA_DIR="$env:TEMP\lvr-qa\data"
$env:LVR_LOGS_DIR="$env:TEMP\lvr-qa\logs"
$env:LVR_OUTPUT_DIR="$env:TEMP\lvr-qa\output"
$env:LVR_FOTOS_DIR="$env:TEMP\lvr-qa\fotos"
python init_data.py
```

## Operación

```powershell
python cli.py status --json
python cli.py start
python cli.py stop
python cli.py logs supervisor
python cli.py backup
```

El supervisor escribe un heartbeat persistente, el resultado estructurado de cada
etapa y tamaños de cola. Los estados funcionales son `success`, `no_work`,
`degraded` y `failed`; los códigos de salida son 0, 0, 2 y 1 respectivamente.

Lea antes de operar:

- [Estado actual](docs/CURRENT_STATE.md)
- [Arquitectura y flujo](docs/ARCHITECTURE.md)
- [Runbook de incidentes](docs/RUNBOOK.md)
- [Problemas conocidos](docs/KNOWN_ISSUES.md)
- [Auditoría de línea de base](docs/audits/2026-07-23-linea-base.md)
- [Instrucciones para agentes](AGENTS.md)

## Seguridad

No versione `.env`, `data/`, `logs/`, `output/` ni `FotosLVR/`. La interfaz de Reels
sólo acepta loopback por defecto y rechaza exposición externa. Las verificaciones de
contrato no reemplazan una prueba controlada contra un entorno de staging: este
repositorio no incluye cuentas de prueba externas.
