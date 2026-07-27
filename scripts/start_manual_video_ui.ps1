[CmdletBinding()]
param(
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
$manager = Join-Path $repoRoot "video_reel_manager.py"
$port = 8765

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "No existe el entorno virtual esperado: $python"
}

$listeners = @(
    netstat.exe -ano -p tcp |
        Select-String -Pattern ":$port\s+.*LISTENING" |
        ForEach-Object { (($_.Line -split "\s+")[2]) }
)
$unsafe = @(
    $listeners | Where-Object {
        $_ -notin @("127.0.0.1:$port", "[::1]:$port")
    }
)
if ($unsafe.Count -gt 0) {
    throw "El puerto $port está expuesto fuera de localhost; no se inicia otra instancia."
}
if ($listeners.Count -gt 0) {
    $response = Invoke-WebRequest `
        -UseBasicParsing `
        -Uri "http://127.0.0.1:$port/" `
        -TimeoutSec 5
    if (
        $response.StatusCode -ne 200 -or
        $response.Content -notmatch "Videos Reel.+La Voz Riojana"
    ) {
        throw "El puerto $port está ocupado por un servicio no reconocido."
    }
    Write-Output "La interfaz manual ya está disponible en http://127.0.0.1:$port/."
    exit 0
}

if ($ValidateOnly) {
    Write-Output "La interfaz manual puede iniciarse de forma segura en localhost."
    exit 0
}

$process = Start-Process `
    -FilePath $python `
    -ArgumentList @($manager, "--host", "127.0.0.1", "--port", "$port", "--no-open") `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -PassThru

$deadline = (Get-Date).AddSeconds(10)
do {
    Start-Sleep -Milliseconds 250
    $listener = netstat.exe -ano -p tcp |
        Select-String -Pattern "127\.0\.0\.1:$port\s+.*LISTENING" |
        Select-Object -First 1
} while (-not $listener -and (Get-Date) -lt $deadline -and -not $process.HasExited)

if (-not $listener) {
    throw "La interfaz manual no quedó escuchando en localhost."
}

Write-Output "Interfaz manual iniciada (PID $($process.Id)): http://127.0.0.1:$port/."
