param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("report", "watchdog")]
    [string]$Task
)
# Tareas programadas de supervisión (independientes del supervisor 24/7):
#   report   -> LaVozRiojana-Report   (cada 3 días a las 9): reporte por correo.
#   watchdog -> LaVozRiojana-Watchdog (cada 15 minutos): aviso si el supervisor se cae.
# Los datos de correo (SMTP_USER/SMTP_PASSWORD/REPORT_EMAIL_TO) se leen de .env.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$python = Join-Path $repo "venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
if ($Task -eq "report") {
    & $python cli.py report --send
} else {
    & $python cli.py watchdog
}
exit $LASTEXITCODE
