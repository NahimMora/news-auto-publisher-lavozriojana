[CmdletBinding()]
param(
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
$cli = Join-Path $repoRoot "cli.py"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "No existe el entorno virtual esperado: $python"
}

# Perfil operativo explícito. Los secretos permanecen exclusivamente en .env;
# estas variables sólo establecen gates, límites y trazabilidad del despliegue.
$env:PIPELINE_DEPLOYMENT_MODE = "all"
$env:WEB_PUBLISH_TARGET = "node_webapp"
$env:FB_PUBLISH_ENABLED = "true"
$env:IG_PUBLISH_ENABLED = "true"
# La línea de base se decide por timestamp durable de cola, no por la fecha
# editorial (que puede faltar). El cutoff histórico queda explícitamente apagado.
$env:ARTICLE_NOT_BEFORE_DATE = ""
# Reset de cola social del 2026-10-01 (queue-cutover --social-reset): ninguna
# noticia ni promoción manual anterior a este epoch vuelve a entrar a FB/IG.
$env:SOCIAL_BOOTSTRAP_NOT_BEFORE_TS = "1790829319"
$env:EDITORIAL_FINAL_ATTEMPT_ACTION = "publish_last_safe"
$env:FB_LINK_PREWARM_ENABLED = "true"
$env:FB_LINK_PREWARM_TIMEOUT_SECONDS = "20"
$env:FB_LINK_PREWARM_MAX_BYTES = "5242880"
# LVR-086: espaciar posts para no encadenar ráfagas del crawler de Meta sobre el sitio.
$env:FB_INTER_POST_DELAY_SECONDS = "30"
# LVR-IMPROVEMENT-0001: caption de IG/FB desde la versión editorial web (sin IA extra).
$env:IG_CAPTION_FROM_WEB_ENABLED = "true"
# Imágenes estáticas de IG fuera de 0-7 h (alcance mediano de madrugada ~20 vs ~200
# a la tarde); Reels sin cambios. Ver docs/DECISIONS.md (2026-10-04).
$env:IG_STATIC_QUIET_HOURS = "0-7"
# Videos de X enviados por el backend de HolaSalta (C:/sources/x_video_sources.json): sólo Reel.
$env:X_VIDEO_REELS_ENABLED = "true"
$env:X_VIDEO_MAX_PER_CYCLE = "2"
$env:X_VIDEO_MAX_AGE_HOURS = "24"
$env:CANARY_ENABLED = "false"
$env:ALERTS_ENABLED = "true"
$env:ALERT_WEBHOOK_URL = ""
$env:DISK_FREE_MIN_MB = "2048"
$env:LVR_RELEASE_TAG = "unreleased-reliability-baseline"
$env:LVR_DEPLOYED_AT = (Get-Date).ToUniversalTime().ToString("o")
$env:LVR_DEPLOYMENT_OPERATOR = $env:USERNAME
$env:LVR_BACKUP_REFERENCE = "pre-24x7-cutover-2026-07-27"

Set-Location -LiteralPath $repoRoot

& $python $cli doctor --scope supervisor --json
if ($LASTEXITCODE -ne 0) {
    throw "El doctor del supervisor falló; no se inicia el pipeline."
}

if ($ValidateOnly) {
    Write-Output "Perfil 24/7 válido; no se inició el supervisor."
    exit 0
}

& $python $cli start
exit $LASTEXITCODE
