# CURRENT_STATE.md

**Última actualización de este documento**: 2026-07-20 (generado a partir de código,
`.env`, `data/` y `logs/` — el repo no tenía documentación previa ni historial de git
propio, ver nota abajo).

## Qué funciona

- Scraping de las 4 secciones de `tiempopopular.com.ar` (locales, policiales, interior,
  deportes) y las 6 secciones de `nuevarioja.com.ar` (política, sociedad, policiales,
  deportes, interior, internacionales), con deduplicación por URL canónica e historial
  por sección.
- Reescritura de títulos, clasificación de categoría y generación de captions
  estructurados vía OpenAI (`openIA/rewrite_news.py`).
- Generación de imágenes de post para Instagram y Facebook/OG con diseño propio
  (`layout/image_generator.py`).
- Publicación al CMS externo (`lavozriojana.com`) vía API privada.
- Publicación en Facebook (feed) y en Instagram (posts + Reels) vía Graph API.
- Supervisor 24/7 con ciclos horarios estables: los logs muestran al menos **245 ciclos
  completados** (`logs/run_24x7.log`), 4/4 pasos OK por ciclo, hasta el último registro
  visible (2026-07-13 20:11:15).
- CLI de operación (`start/stop/status/logs/run-once/videos`) funcional.
- Herramientas manuales de publicación y QA visual (`video_reel_manager.py`,
  `pipeline/custom_post.py`, `preview_pipeline.py`).

## Qué funciona parcialmente

- **Publicación en Facebook**: en los últimos ciclos visibles en el log (2026-07-13), la
  cola de Facebook **crecía en vez de bajar** (ej. 127 → 134 en cola en ciclos
  consecutivos), con tasas de éxito bajas por ciclo (0/6, 1/7, 4/10) y **cero líneas de
  ERROR** en `logs/run_fb.log` — es decir, algo está fallando pero no queda registrado
  con detalle suficiente para diagnosticar (ver `KNOWN_ISSUES.md`).
- **Cobertura de tests**: solo `tests/test_node_webapp_publisher.py` (mockeado) cubre
  publisher/editorial/media/fb_client/ig_client/rewrite_news/social_queue. No hay tests
  automatizados para scrapers, generación de imagen/video, ni para el supervisor/CLI —
  esas capas dependen de verificación manual (`test_scraper.py`, `preview_pipeline.py`).
- **Backups de `data/`**: existen (`data/backups/`) pero son manuales/ad hoc (solo 3
  snapshots, todos del 2026-07-01), no un proceso automatizado y periódico.

## Qué está roto o requiere atención inmediata

- **Sin visibilidad de si el supervisor está corriendo ahora mismo**: los logs no tienen
  entradas después del 2026-07-13 20:11, y hoy es 2026-07-20 — una semana sin evidencia
  de actividad. Esto puede significar que el proceso está parado, o simplemente que no
  se revisó el log más reciente al momento de escribir este documento. **Verificar con
  `python cli.py status` es el primer paso operativo pendiente.**
- **`.git` de este proyecto está roto/vacío** (`.git/info` sin `HEAD` ni `objects`): no
  hay historial de versiones real de este código hasta este commit. Este documento y el
  resto de `/docs` se generaron leyendo el código y los datos directamente, no a partir
  de `git log`.
- **`psutil` se usa en `cli.py` pero no está en `requirements.txt`** — instalar
  dependencias desde cero (`pip install -r requirements.txt`) puede no ser suficiente
  para correr el CLI.
- **Backlog de Facebook** (ver arriba) sin causa raíz confirmada por falta de logging
  de errores de Graph API.

## Próximo objetivo operativo

1. Confirmar si el supervisor 24/7 está corriendo (`python cli.py status`); si no,
   levantarlo y verificar que los 4 pasos del ciclo vuelvan a completar OK.
2. Diagnosticar y resolver el backlog creciente de publicaciones en Facebook, empezando
   por habilitar logging a archivo en `fb_client.py` / `facebook_token_manager.py` (hoy
   solo loguean a consola, que se descarta porque el proceso corre con
   `stdout=DEVNULL`).
3. Agregar `psutil` a `requirements.txt`.
4. Establecer un mecanismo de backup automático y periódico de `data/` (hoy es manual).
