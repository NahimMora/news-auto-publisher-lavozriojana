@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0\.."

set "REPO_ROOT=%CD%"
set "TASK_24X7=LaVozRiojana-24x7"
set "TASK_UI=LaVozRiojana-ManualUI"

echo ======================================================
echo   AutoPublicador La Voz Riojana - Tareas programadas
echo ======================================================
echo.
echo Repo: %REPO_ROOT%
echo.

if not exist "venv\Scripts\python.exe" (
  echo [ERROR] No existe venv\Scripts\python.exe - correr scripts\setup_new_pc.bat primero.
  goto :fail
)
if not exist "scripts\start_24x7_production.ps1" (
  echo [ERROR] Falta scripts\start_24x7_production.ps1.
  goto :fail
)
if not exist "scripts\start_manual_video_ui.ps1" (
  echo [ERROR] Falta scripts\start_manual_video_ui.ps1.
  goto :fail
)

echo [1/3] Comprobando que no exista una tarea de otro proyecto con estos nombres...
rem Solo defensivo: los nombres LaVozRiojana-* son propios de este repo. HolaSalta
rem Ops usa "HolaSalta Ops Local Agent" y nombres propios (ver
rem docs\MIGRACION_PC_COMPARTIDA.md). Esto no debería dispararse nunca; si lo hace,
rem investigar antes de continuar en vez de pisarlo con /F a ciegas.
schtasks /query /tn "%TASK_24X7%" >nul 2>&1
if not errorlevel 1 (
  echo   [INFO] "%TASK_24X7%" ya existe - se va a actualizar ^(/F^).
)
schtasks /query /tn "%TASK_UI%" >nul 2>&1
if not errorlevel 1 (
  echo   [INFO] "%TASK_UI%" ya existe - se va a actualizar ^(/F^).
)
echo.

echo [2/3] Registrando %TASK_24X7% ^(cada 5 minutos, idempotente^)...
schtasks /create /F ^
  /tn "%TASK_24X7%" ^
  /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%REPO_ROOT%\scripts\start_24x7_production.ps1\"" ^
  /sc minute /mo 5 ^
  /rl limited
if errorlevel 1 (
  echo [ERROR] No se pudo crear/actualizar %TASK_24X7%.
  goto :fail
)
echo.

echo [3/3] Registrando %TASK_UI% ^(cada 5 minutos, idempotente^)...
schtasks /create /F ^
  /tn "%TASK_UI%" ^
  /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%REPO_ROOT%\scripts\start_manual_video_ui.ps1\"" ^
  /sc minute /mo 5 ^
  /rl limited
if errorlevel 1 (
  echo [ERROR] No se pudo crear/actualizar %TASK_UI%.
  goto :fail
)
echo.

echo ======================================================
echo   [OK] Tareas registradas.
echo ======================================================
echo.
echo IMPORTANTE: schtasks registra estas tareas para el usuario actual ^(sin /RU^).
echo Si Windows pide credenciales al ejecutarlas la primera vez, es porque el
echo Programador de Tareas necesita guardar la contrasena de esta cuenta para
echo poder correrlas sin sesion interactiva - hacerlo una vez desde el panel
echo grafico (taskschd.msc) si schtasks no lo resuelve solo.
echo.
echo Verificar con:
echo   Get-ScheduledTask -TaskName %TASK_24X7%,%TASK_UI%
echo   Get-ScheduledTaskInfo -TaskName %TASK_24X7%
echo   Get-ScheduledTaskInfo -TaskName %TASK_UI%
echo.
exit /b 0

:fail
echo.
echo [FAIL] Registro de tareas incompleto.
echo.
exit /b 1
