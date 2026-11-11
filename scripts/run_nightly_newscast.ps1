param(
    [switch]$Register
)
# Noticiero de la Noche (docs/NIGHTLY_NEWSCAST.md). Lo lanza la tarea
# programada LaVozRiojana-Noticiero todos los días a las 20:15: arma guion,
# locución y render, y deja el video en output\noticiero\<fecha>\.
# Con NIGHTLY_NEWSCAST_PUBLISH = "true" espera a las 21 y publica en IG y FB.
# Los secretos (GEMINI_API_KEY, Meta, R2) se leen de .env; acá sólo van gates.
#   -Register  crea o actualiza la tarea programada (no la ejecuta).
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

if ($Register) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$repo\scripts\run_nightly_newscast.ps1`""
    $trigger = New-ScheduledTaskTrigger -Daily -At "20:15"
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName "LaVozRiojana-Noticiero" -Action $action -Trigger $trigger -Settings $settings -Description "Noticiero de la Noche (Reel de las 21)" -Force | Out-Null
    Write-Output "Tarea LaVozRiojana-Noticiero registrada (diaria, 20:15)."
    exit 0
}

Set-Location $repo
$python = Join-Path $repo "venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
# Mismo perfil de canales que el supervisor 24/7 (scripts/start_24x7_production.ps1).
$env:PIPELINE_DEPLOYMENT_MODE = "all"
$env:WEB_PUBLISH_TARGET = "node_webapp"
$env:FB_PUBLISH_ENABLED = "true"
$env:IG_PUBLISH_ENABLED = "true"
# Publicación diaria a las 21 activada por el responsable el 2026-10-31
# (V4 policial, todas las noticias con imagen propia). Se arranca 20:15 porque
# una edición en frío tarda ~10 min. Para volver a sólo generar:
# NIGHTLY_NEWSCAST_PUBLISH = "false".
$env:NIGHTLY_NEWSCAST_ENABLED = "true"
$env:NIGHTLY_NEWSCAST_PUBLISH = "true"
$env:NIGHTLY_NEWSCAST_HOUR = "21"
$env:NIGHTLY_NEWSCAST_VOICE = "Orus"
# Voz aprobada el 2026-10-30: Gemini Pro TTS, Orus, ritmo 0.97 (tonada riojana).
$env:NIGHTLY_NEWSCAST_TTS_MODEL = "gemini-2.5-pro-preview-tts"
$env:NIGHTLY_NEWSCAST_TEMPO = "0.97"
# V3 (2026-10-31): plan audiovisual por hechos, subtítulos alineados con
# whisper.cpp local (scripts/install_newscast_aligner.py).
# V5 (2026-11-01): apertura en frío, edición por frases, mapa, portada como
# cover_url y caption sin fuentes (docs/NIGHTLY_NEWSCAST.md § V5).
# Rollback a V4: "v3"; a V2: "v2".
$env:NIGHTLY_NEWSCAST_VISUAL = "v5"
# Ubicación del medio (La Rioja) en el Reel de Instagram, igual que el 24/7.
$env:IG_LOCATION_ENABLED = "true"
& $python meta\run_nightly_newscast.py
exit $LASTEXITCODE
