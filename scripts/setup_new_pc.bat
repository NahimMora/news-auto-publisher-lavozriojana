@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0\.."

echo ======================================================
echo   AutoPublicador La Voz Riojana - Setup PC nueva
echo ======================================================
echo.
echo Repo: %CD%
echo.

echo [1/7] Verificando herramientas base...
where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] git no esta instalado o no esta en PATH.
  goto :fail
)
where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python no esta instalado o no esta en PATH.
  goto :fail
)
where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js no esta instalado o no esta en PATH ^(requerido por remotion/^).
  goto :fail
)
where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm no esta instalado o no esta en PATH.
  goto :fail
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python 3.10 o superior es requerido.
  goto :fail
)

for /f %%V in ('node -p "process.versions.node.split(\".\")[0]"') do set "NODE_MAJOR=%%V"
if "%NODE_MAJOR%"=="" (
  echo [ERROR] No se pudo detectar version de Node.js.
  goto :fail
)
if %NODE_MAJOR% LSS 18 (
  echo [ERROR] Node.js 18 o superior es requerido.
  goto :fail
)

rem ffmpeg/ffprobe/yt-dlp solo hacen falta para el pipeline de video. Se avisa
rem pero no se corta el resto de la instalacion - igual que setup_local_env.bat
rem de WebApp_HolaSalta con el mismo caso.
where ffmpeg >nul 2>&1 || echo [WARN] ffmpeg no esta en PATH ^(necesario para render/descarga de video^).
where ffprobe >nul 2>&1 || echo [WARN] ffprobe no esta en PATH ^(necesario para render/descarga de video^).
echo   OK.
echo.

echo [2/7] Confirmando que este repo no vive dentro de C:\HolaSalta...
echo %CD% | findstr /I /C:"\HolaSalta\" >nul 2>&1
if not errorlevel 1 (
  echo [ERROR] Este repo esta anidado dentro de C:\HolaSalta - ver docs\MIGRACION_PC_COMPARTIDA.md paso 2.
  echo         Clonar en una carpeta hermana, ej. C:\AutoPublicadores\AutoPublicador_LaVozRiojana.
  goto :fail
)
echo   OK ^(%CD%^).
echo.

echo [3/7] Verificando .env...
if not exist ".env" (
  if exist ".env.example" (
    echo   [INFO] .env no existe. Copiando desde .env.example...
    copy /Y ".env.example" ".env" >nul
  ) else (
    echo [ERROR] Falta .env y .env.example.
    goto :fail
  )
) else (
  echo   .env ya existe - no se toca su contenido.
)
echo.

echo [4/7] Preparando entorno Python ^(venv^)...
if exist "venv\Scripts\python.exe" (
  echo   [INFO] venv ya existe, se reutiliza. Para recrearlo desde cero, borrar
  echo          la carpeta venv\ manualmente y volver a correr este script.
) else (
  echo   [INFO] Creando venv nuevo...
  python -m venv venv
  if errorlevel 1 (
    echo [ERROR] No se pudo crear el venv.
    goto :fail
  )
)

set "PYTHON_EXE=%CD%\venv\Scripts\python.exe"
set "PIP_EXE=%CD%\venv\Scripts\pip.exe"

echo   [INFO] Actualizando pip...
"%PYTHON_EXE%" -m pip install --upgrade pip >nul
if errorlevel 1 (
  echo   [WARN] No se pudo actualizar pip, continuo con la version actual.
)

echo   [INFO] Instalando dependencias Python ^(requirements.txt^)...
"%PIP_EXE%" install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Fallo instalacion de requirements Python.
  goto :fail
)
echo.

echo [5/7] Instalando dependencias de remotion\ ^(npm i^)...
if exist "remotion\package.json" (
  pushd remotion
  call npm i
  if errorlevel 1 (
    popd
    echo [ERROR] npm i fallo en remotion\.
    goto :fail
  )
  popd
) else (
  echo   [WARN] No se encontro remotion\package.json - salteado.
)
echo.

echo [6/7] Inicializando estructura de datos...
"%PYTHON_EXE%" init_data.py
if errorlevel 1 (
  echo [ERROR] init_data.py fallo.
  goto :fail
)
echo.

echo [7/7] Verificando el entorno con doctor...
"%PYTHON_EXE%" cli.py doctor --scope core --json
if errorlevel 1 (
  echo [ERROR] doctor --scope core fallo. Revisar salida de arriba.
  goto :fail
)
echo.

echo ======================================================
echo   [OK] Entorno listo.
echo ======================================================
echo.
echo Siguiente paso: completar .env con credenciales reales, despues
echo   scripts\register_scheduled_tasks.bat
echo Ver docs\MIGRACION_PC_COMPARTIDA.md para el detalle completo.
echo.
exit /b 0

:fail
echo.
echo [FAIL] Setup incompleto.
echo.
exit /b 1
