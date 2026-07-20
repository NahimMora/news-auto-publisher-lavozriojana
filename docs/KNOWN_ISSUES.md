# KNOWN_ISSUES.md

Problemas conocidos a la fecha de este documento (2026-07-20), detectados por
inspección de código, logs y datos. Marcar como resuelto (con fecha) en vez de borrar,
para mantener historial.

## 1. Publicaciones en Facebook fallan sin registrar el error real

- **Síntoma**: en los ciclos del 2026-07-13 visibles en `logs/run_fb.log`, la cola de
  Facebook crecía en vez de bajar (ej. 127 → 134 en cola entre ciclos consecutivos),
  con tasas de éxito bajas (0/6, 1/7, 4/10) y **cero líneas `ERROR`** en el log.
- **Causa probable**: `meta/fb_client.py` y `meta/facebook_token_manager.py` inicializan
  su logger sin archivo de salida (`setup_logger("fb_client")` sin segundo argumento),
  es decir loguean solo a consola. El supervisor (`run_24x7.py`), lanzado vía
  `cli.py start`, corre desatachado con `stdout=DEVNULL, stderr=DEVNULL` — el detalle
  del error de Graph API (rate limit, token inválido, contenido rechazado, etc.) se
  descarta antes de poder verlo.
- **Impacto**: imposible diagnosticar por qué crece el backlog sin reproducir el
  problema manualmente o instrumentar logging a archivo primero.
- **Estado**: abierto. Ver acción propuesta en `BACKLOG.md` (alta prioridad).

## 2. `psutil` no está declarado en `requirements.txt`

- **Síntoma**: `cli.py` importa `psutil` (usado para gestión de procesos del
  supervisor), pero el paquete no aparece en `requirements.txt`.
- **Impacto**: un `pip install -r requirements.txt` limpio puede no dejar el entorno
  funcional para el CLI.
- **Estado**: abierto.

## 3. Sin evidencia de actividad del supervisor en la última semana

- **Síntoma**: `logs/run_24x7.log` no tiene entradas después de 2026-07-13 20:11:15
  (ciclo #245). Hoy es 2026-07-20.
- **Impacto**: no se puede confirmar desde los archivos estáticos si el proceso sigue
  corriendo o se detuvo; requiere verificación directa (`python cli.py status`) en la
  máquina donde corre.
- **Estado**: abierto — verificar como primer paso operativo.

## 4. `.git` de este proyecto estaba roto y mezclado con otro repo

- **Síntoma**: la carpeta tenía un `.git/` local incompleto (sin `HEAD` ni `objects`),
  por lo que git resolvía la raíz del repo hacia `C:\Users\pc10\Desktop`, un repo
  compartido con proyectos y archivos personales no relacionados, con remotes que no
  correspondían a este proyecto (`duo-news-app`, `migration-wix-to-wordpress`).
- **Impacto**: no había historial de versiones real de este código; riesgo de exponer
  archivos ajenos si se hacía push desde ese repo sin cuidado.
- **Estado**: resuelto el 2026-07-20 — se inicializó un repo git dedicado en esta
  carpeta con remote propio (`news-auto-publisher-lavozriojana`). Ver `DECISIONS.md`.

## 5. Cobertura de tests limitada

- **Síntoma**: solo existe `tests/test_node_webapp_publisher.py` (mockeado, cubre
  publisher/editorial/media/fb_client/ig_client/rewrite_news/social_queue). Scrapers,
  generación de imagen/video y el CLI/supervisor no tienen tests automatizados.
- **Impacto**: cambios en `scraping/`, `layout/`, o `video_reel_manager.py` pueden
  romper silenciosamente hasta que se note en producción o vía las herramientas de QA
  manual (`test_scraper.py`, `preview_pipeline.py`).
- **Estado**: abierto.

## 6. Backups de `data/` manuales y esporádicos

- **Síntoma**: `data/backups/` solo tiene 3 snapshots, todos del 2026-07-01. No hay
  proceso automatizado de backup periódico.
- **Impacto**: pérdida o corrupción de los JSON en `data/` (colas, historial de dedup,
  tokens cacheados) implicaría pérdida de estado sin forma de recuperarlo más allá de
  ese snapshot puntual.
- **Estado**: abierto.

## 7. Falta de verificación editorial humana antes de publicar

- **Síntoma**: el pipeline publica automáticamente en los 3 canales apenas una nota
  pasa el filtro y la reescritura de OpenAI; no hay paso de aprobación manual
  obligatorio.
- **Impacto**: aunque el prompt de reescritura instruye explícitamente "no inventar
  datos", un error del modelo o una mala clasificación se publica igual sin que nadie
  lo revise antes.
- **Estado**: abierto — riesgo aceptado implícitamente por el diseño actual; evaluar
  si vale la pena un paso de aprobación opcional (ver `BACKLOG.md`).
