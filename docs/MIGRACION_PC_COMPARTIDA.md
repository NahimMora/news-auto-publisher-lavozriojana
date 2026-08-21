# Migración a PC compartida con WebApp_HolaSalta

Última actualización: 2026-08-21.

Estado: **migración completada el 2026-08-21**. `AutoPublicador_LaVozRiojana` corre
en `C:\LVR` de la PC Windows que ya tenía `WebApp_HolaSalta`
(`C:\HolaSalta\WebApp_HolaSalta`), accedida por SSH con clave
(`PC@192.168.1.150`). Esta PC de desarrollo (`pc10`) ya no ejecuta el servicio —
ver la regla operativa completa más abajo y en `docs/RUNBOOK.md` ("Entorno:
desarrollo vs. producción"). La fase remota tipo `ops.lavozriojana.com` sigue siendo
posterior y está documentada aparte en `docs/PLAN_OPS_LAVOZRIOJANA.md`.

## Regla operativa: esta PC nunca vuelve a correr el servicio

Esta PC (`pc10`, donde se escribe y prueba el código) **no ejecuta el servicio bajo
ningún motivo**, ni siquiera temporalmente para probar algo puntual:

- No correr `python cli.py start`, `python run_24x7.py` ni
  `python video_reel_manager.py` directamente acá.
- No volver a ejecutar `scripts/register_scheduled_tasks.bat` en esta PC.
- Si por algún motivo aparecen las tareas `LaVozRiojana-24x7`/`LaVozRiojana-ManualUI`
  en el Programador de Tareas de esta PC, **borrarlas** (`Unregister-ScheduledTask`,
  no sólo `Disable-ScheduledTask`) — no deberían existir acá.

El único camino para que un cambio de código llegue a producción es:
desarrollar/probar acá → `git push` → PR con CI verde → merge a `main` → conectarse
por SSH a `C:\LVR` → `git pull origin main` → reiniciar el backend
(`cli.py stop`, vuelve a levantarse solo con la tarea programada, o forzarlo con
`Start-ScheduledTask -TaskName 'LaVozRiojana-24x7'`). Procedimiento completo con los
comandos exactos en `docs/RUNBOOK.md`.

**Por qué esta regla es dura y no una preferencia**: el 2026-08-21 esta PC conservaba,
sin que nadie lo recordara, las tareas programadas del arranque productivo original
del 2026-07-27. Relanzaron el pipeline completo con credenciales reales en paralelo a
la instancia ya migrada — mismas cuentas de Facebook/Instagram, mismo OpenAI, sin
compartir historial de deduplicación entre las dos. El detalle completo, con causa
raíz y verificación, está en `docs/KNOWN_ISSUES.md` #84 y la decisión formal en
`docs/DECISIONS.md` (2026-08-21).

## Prerrequisitos en la PC destino

La mayoría ya están instalados porque HolaSalta los exige también
(`WebApp_HolaSalta/README.md`, sección Requisitos):

- Git
- Python 3.10 o superior
- Node.js 18 o superior + npm (para `remotion/`)
- `ffmpeg` y `ffprobe` en `PATH`
- `yt-dlp` (lo instala `pip install -r requirements.txt`, pero conviene
  `pip install -U yt-dlp` seguido — rompe extractors sin aviso)

Verificar antes de clonar nada:

```powershell
git --version
python --version
node --version
npm --version
ffmpeg -version
ffprobe -version
```

## Principio de aislamiento

Un solo principio cubre casi todas las reglas de abajo: **cada proyecto es dueño
exclusivo de su propia carpeta, su propio venv/`node_modules`, sus propios puertos y
sus propias tareas programadas — nunca se apunta un path, puerto o nombre de tarea de
un proyecto hacia el espacio del otro, ni siquiera "temporalmente".**

## Paso a paso

### 1. Conectarse por SSH a la PC destino

```powershell
ssh <usuario>@<host-o-ip-de-la-pc>
```

### 2. Elegir una carpeta hermana, no anidada

HolaSalta vive en `C:\HolaSalta\WebApp_HolaSalta`. LaVozRiojana **no** debe clonarse
dentro de `C:\HolaSalta\` — usar una raíz propia. La instalación real quedó en
`C:\LVR` (repo clonado directo en la raíz de `C:\`, sin subcarpeta adicional):

```powershell
cd C:\
```

Anidarlo adentro de `C:\HolaSalta` no rompe nada técnicamente, pero mezcla
visualmente los dos proyectos en cualquier backup/script que opere sobre
`C:\HolaSalta\*` a futuro (varios `.bat` de HolaSalta ya hacen `cd /d "%~dp0"` y
recorren subcarpetas — más vale no darles motivos para tropezar con este repo).

### 3. Clonar el repo privado

```powershell
git clone https://github.com/NahimMora/news-auto-publisher-lavozriojana.git C:\LVR
cd C:\LVR
```

Requiere que la PC destino tenga acceso configurado al repo privado (SSH key o PAT de
GitHub asociado a esa máquina). Si todavía no está configurado, hacerlo antes de este
paso — no reusar ni copiar la credencial de GitHub que ya tenga configurada HolaSalta
en esa PC; cada proyecto con su propio acceso, mismo criterio que con los `.env`.

### 4. Inicializar el entorno con el script de setup

```powershell
scripts\setup_new_pc.bat
```

Qué hace (ver el script para el detalle exacto, `scripts/setup_new_pc.bat`):

1. Verifica Python/Node/npm/git en `PATH` y avisa (sin cortar) si faltan
   ffmpeg/ffprobe/yt-dlp.
2. Crea `venv\` **propio de este repo** desde cero si no existe — nunca reutiliza ni
   referencia el `.venv` de `WebApp_HolaSalta`.
3. Instala `requirements.txt` dentro de ese venv.
4. Corre `npm i` dentro de `remotion/` — `node_modules` queda local a
   `remotion/node_modules`, sin relación con `backend/whatsapp/node_modules` de
   HolaSalta.
5. Copia `.env.example` → `.env` sólo si `.env` no existe todavía (nunca pisa uno con
   credenciales reales).
6. Corre `python init_data.py` para crear la estructura de `data/`.
7. Corre `python cli.py doctor --scope core --json` como verificación final.

### 5. Completar `.env` con credenciales reales

Editar `.env` (nunca `backend\.env` de HolaSalta, es un archivo distinto de un
proyecto distinto) con las claves de CMS, OpenAI, Cloudflare R2, Facebook e
Instagram **propias de La Voz Riojana**. Las integraciones nacen deshabilitadas
(`README.md`) — habilitarlas recién cuando el resto de la validación pase.

### 6. Checklist de no-colisión antes de habilitar 24/7

Correr esto en la PC destino antes de registrar cualquier tarea programada:

```powershell
# Puertos: LaVozRiojana usa 8765 (UI manual) y un puerto efímero (--port=0) para el
# render server de Remotion. HolaSalta usa 8000. Confirmar que 8765 esté libre:
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue

# Tareas programadas: los nombres deben ser únicos en todo Task Scheduler de la PC.
Get-ScheduledTask -TaskName "LaVozRiojana-24x7","LaVozRiojana-ManualUI" -ErrorAction SilentlyContinue
Get-ScheduledTask | Where-Object { $_.TaskName -like "*HolaSalta*" }
```

Si `Get-NetTCPConnection` devuelve algo en 8765, hay un proceso previo corriendo o el
puerto quedó tomado por otra cosa — investigar antes de seguir, no forzar otro puerto
sin actualizar `scripts/start_manual_video_ui.ps1` y esta documentación a la vez.

### 7. Registrar las tareas programadas

```powershell
scripts\register_scheduled_tasks.bat
```

Crea (o actualiza, es idempotente) `LaVozRiojana-24x7` y `LaVozRiojana-ManualUI`
apuntando a `scripts\start_24x7_production.ps1` y
`scripts\start_manual_video_ui.ps1` respectivamente — los mismos scripts que ya usa
la instalación actual, sin reinventar la lógica de arranque. Ver
`docs/RUNBOOK.md`, sección "Watchdog de Windows", para verificación posterior con
`Get-ScheduledTaskInfo`.

### 8. Validar antes de dejarlo desatendido

```powershell
python cli.py status --json
python cli.py doctor --scope supervisor --json
python cli.py preflight --scope filesystem --json
python cli.py preflight --scope sources --json
```

`blocked` es normal si todavía no completaste alguna credencial en el paso 5 — no es
salud, pero tampoco bloquea el resto (`README.md`, sección "Resultados y
diagnóstico").

### 9. Acceso remoto a la UI manual mientras no exista el panel de la Fase 2/3

`video_reel_manager.py` rechaza por diseño cualquier bind fuera de loopback — la
forma correcta de llegar a `http://127.0.0.1:8765/` desde otra máquina es forwarding
SSH, **no** cambiar el `--host` del script:

```powershell
ssh -L 8765:127.0.0.1:8765 <usuario>@<host-o-ip-de-la-pc>
```

Con el túnel abierto, abrir `http://127.0.0.1:8765/` en el navegador local. Cerrar la
sesión SSH corta el acceso; esto es esperado y es justamente lo que evita tener que
exponer el puerto a la red.

## Buenas prácticas de aislamiento (resumen)

| Qué | Regla |
|---|---|
| Carpeta del repo | hermana de `C:\HolaSalta\`, nunca anidada adentro |
| Entorno Python | `venv\` propio por repo, nunca compartido ni referenciado desde el otro proyecto |
| Dependencias Node | `remotion/node_modules` es local al repo; no tocar `backend/whatsapp/node_modules` de HolaSalta ni viceversa |
| `.env` / credenciales | un archivo por repo, nunca copiado ni reutilizado entre proyectos, ni siquiera para "probar rápido" |
| Variables `LVR_*_DIR` | si se usan para aislar QA (`docs/README.md`, sección Aislamiento), deben apuntar siempre dentro de este repo o a un temp propio — nunca a una carpeta de `WebApp_HolaSalta` |
| Puertos | 8765 (LaVozRiojana UI manual) vs 8000 (HolaSalta backend) ya no colisionan; si alguno cambia, actualizar ambos repos y este documento |
| Tareas programadas | prefijo `LaVozRiojana-*` reservado para este proyecto; HolaSalta usa `HolaSalta Ops Local Agent` y nombres propios — verificar con `Get-ScheduledTask` antes de crear una tarea nueva en cualquiera de los dos repos |
| Binarios de sistema (ffmpeg, node, git) | está bien compartirlos vía `PATH` — son herramientas del sistema operativo, no dependencias de proyecto |

## Rollback

Si algo sale mal durante la migración, no hay estado compartido que limpiar del lado
de HolaSalta — los dos proyectos son independientes por diseño (tabla de arriba).
Para deshacer esta instalación:

```powershell
schtasks /delete /tn "LaVozRiojana-24x7" /f
schtasks /delete /tn "LaVozRiojana-ManualUI" /f
Remove-Item -Recurse -Force C:\LVR
```

Confirmar primero que ninguna tarea siga `Running` (`Get-ScheduledTaskInfo`) antes de
borrar la carpeta, para no interrumpir una publicación en curso a mitad de escritura.
