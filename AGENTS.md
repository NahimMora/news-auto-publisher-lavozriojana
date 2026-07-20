# AGENTS.md

Instrucciones permanentes para Codex u otro agente de programación que trabaje en este
repositorio (`AutoPublicador_LaVozRiojana`). Ver también `/docs` para contexto de
producto, arquitectura y estado actual.

## Qué es este proyecto

Pipeline Python 24/7 que scrapea noticias de La Rioja, las reescribe/clasifica con
OpenAI, genera imágenes/videos, y las publica en el sitio (`lavozriojana.com`),
Facebook e Instagram. Ver `docs/PRODUCT.md` y `docs/ARCHITECTURE.md` para el detalle
completo antes de tocar código de negocio.

## Comandos de instalación

```bash
python -m venv venv
venv\Scripts\activate          # Windows (este proyecto es Windows-first)
pip install -r requirements.txt
pip install psutil              # usado en cli.py pero falta en requirements.txt (deuda conocida)
cp .env.example .env            # completar credenciales reales, NUNCA commitear .env
python init_data.py             # crea los JSON de estado/colas vacíos en data/
```

## Comandos de prueba

```bash
python -m unittest discover tests          # suite automatizada (cobertura limitada, ver docs/KNOWN_ISSUES.md)
python -m unittest tests.test_node_webapp_publisher   # test específico
python test_scraper.py                      # chequeo manual de salud de scrapers (genera output/scraper_report.html)
python preview_pipeline.py --n 5            # QA visual de imágenes generadas antes de ir a producción
python cli.py run-once                      # corre un ciclo completo sin loop, útil para probar cambios end-to-end
```

No hay linter/formatter configurado en el repo (no `pyproject.toml`/`.flake8`/`ruff` a
la fecha). Si se agrega uno, actualizar esta sección.

## Convenciones

- **Idioma**: docstrings, comentarios, logs y mensajes al usuario van en español
  (Argentina). Mantener esa convención en código nuevo.
- **Entry points**: cada script de nivel raíz (`main_*.py`, `run_*.py`, `cli.py`) hace
  `load_dotenv()` y `sys.path.insert(0, ...)` al principio — replicar ese patrón en
  scripts nuevos que se ejecuten standalone.
- **Logging**: usar `utils/logging_setup.py::setup_logger(name, "archivo.log")`
  **siempre con el segundo argumento** (archivo de log). Loggers sin archivo se pierden
  en producción porque el supervisor corre con `stdout=DEVNULL` (ver
  `docs/KNOWN_ISSUES.md` #1 — no repetir ese bug en código nuevo).
- **Estado y colas**: todo el estado persiste en JSON planos bajo `data/`, vía
  `utils/file_manager.py` (`load_json`/`save_json`). No introducir una base de datos sin
  antes registrar la decisión en `docs/DECISIONS.md`.
- **Categorías editoriales**: usar los nombres ya establecidos en español
  (`policiales`, `interior`, `sociedad`, `economia`, `salud`, `educacion`, `deportes`,
  `cultura`, `espectaculos`, `politica`) — están hardcodeados en varios módulos
  (`utils/classifier.py`, `utils/editorial_priority.py`, `pipeline/node_webapp/editorial.py`).
  Si se agrega una categoría nueva, actualizar los tres lugares.
- **Prompts de OpenAI**: mantener la regla explícita de "no inventar datos, armas,
  personas ni hechos que no estén en el texto original" en cualquier prompt nuevo de
  reescritura/generación de contenido.
- **Módulos por sección**: los scrapers de `scraping/{deportes,interior,locales,policiales}/`
  son wrappers delgados sobre `scraping/base_tiempopopular.py`. Una sección nueva de ese
  sitio se agrega como carpeta nueva reusando la base, no duplicando lógica de parseo.

## Qué carpetas NO tocar sin confirmar con el operador

- `data/` — es estado de producción (colas, historial, tokens cacheados). No editar ni
  borrar archivos ahí manualmente salvo que se sepa exactamente qué se está haciendo;
  usar `init_data.py` solo para bootstrap inicial en un entorno nuevo.
- `logs/` — solo lectura para diagnóstico. No hace falta versionar ni limpiar a mano.
- `FotosLVR/`, `output/` — artefactos generados, no versionados (ver `.gitignore`).
- `.env` — **nunca** commitear ni imprimir su contenido completo en logs, PRs o
  respuestas. Contiene credenciales reales de OpenAI, Meta (Facebook/Instagram) y
  Cloudflare R2. Usar `.env.example` como referencia de qué variables existen.

## Cómo validar cambios

1. Correr `python -m unittest discover tests` — debe seguir pasando.
2. Para cambios en scrapers: correr `python test_scraper.py` y revisar
   `output/scraper_report.html` para confirmar que sigue extrayendo notas reales.
3. Para cambios en generación de imagen/video: correr `python preview_pipeline.py --n 5`
   (o usar `video_reel_manager.py` para Reels) y revisar visualmente el resultado antes
   de asumir que está bien.
4. Para cambios en publicación (web/Facebook/Instagram): probar primero con
   `python cli.py run-once` en un entorno con credenciales de prueba si es posible; si
   se prueba contra las cuentas reales, avisar al operador antes, dado que publica en
   vivo.
5. Nunca asumir que un cambio en `meta/` o `pipeline/node_webapp/` es seguro solo porque
   pasa los tests mockeados — son mocks de la API, no la API real.

## Arquitectura esperada (no romper estos contratos)

- Ver `docs/ARCHITECTURE.md` para el diagrama de flujo completo. En resumen: scraping →
  reescritura/IA → colas JSON → publicación web/Facebook/Instagram, todo orquestado por
  `run_24x7.py` con pasos aislados (un paso fallido no debe frenar los demás).
- No romper la separación entre `data/noticias_norewrite_*.json` (staging pre-IA) y
  `data/noticias_meta.json` / `data/noticias_web_pending.json` (post-IA, listas para
  publicar) — otros módulos asumen ese contrato.
- No cambiar la forma de los JSON de estado sin migrar los archivos existentes en
  `data/` (son producción real, no fixtures de test).

## Reglas de seguridad

- No commitear secretos: `.env`, tokens, API keys. `.gitignore` ya excluye `.env`,
  `data/`, `logs/`, `output/`, `FotosLVR/` — no revertir eso.
- No loguear valores completos de tokens/API keys, ni siquiera en logs de debug.
- Las llamadas a Graph API (Meta) y OpenAI deben mantener manejo de rate limit/backoff
  existente (`IG_RATE_LIMIT_BACKOFF_SECONDS`, `FB_TEMP_BLOCK_BACKOFF_SECONDS`,
  `OPENAI_RETRY_COUNT`) — no quitar reintentos/backoff para "simplificar" sin entender
  por qué están.
- Este repo tuvo históricamente un `.git` roto que apuntaba, por herencia de carpeta, a
  un repositorio de Desktop compartido con archivos personales ajenos a este proyecto.
  Verificar siempre `git remote -v` y `git status` antes de un push si algo se ve raro
  (archivos ajenos a este proyecto apareciendo en `git status`).

## Definition of Done

Un cambio se considera terminado cuando:

- [ ] El código sigue las convenciones de este archivo (idioma, logging con archivo,
      categorías editoriales, contratos de `data/`).
- [ ] Los tests existentes pasan (`python -m unittest discover tests`).
- [ ] Si se tocó scraping, imagen o video: se validó manualmente con las herramientas de
      QA correspondientes (`test_scraper.py`, `preview_pipeline.py`,
      `video_reel_manager.py`).
- [ ] No se commiteó ningún secreto (`.env`, tokens) ni archivo de `data/`/`logs/`
      generado en producción.
- [ ] Si el cambio afecta una decisión de arquitectura o de proceso editorial, se
      agregó una entrada en `docs/DECISIONS.md`.
- [ ] Si el cambio resuelve o introduce un problema conocido, se actualizó
      `docs/KNOWN_ISSUES.md`.
- [ ] `docs/CURRENT_STATE.md` refleja el estado real después del cambio (qué funciona,
      qué no, próximo objetivo).
