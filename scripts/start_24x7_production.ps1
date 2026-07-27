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
$env:EDITORIAL_FINAL_ATTEMPT_ACTION = "publish_last_safe"
$env:FB_LINK_PREWARM_ENABLED = "true"
$env:FB_LINK_PREWARM_TIMEOUT_SECONDS = "20"
$env:FB_LINK_PREWARM_MAX_BYTES = "5242880"
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
