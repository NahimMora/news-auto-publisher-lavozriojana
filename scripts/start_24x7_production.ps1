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
$env:ARTICLE_NOT_BEFORE_DATE = "2026-07-27"
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
