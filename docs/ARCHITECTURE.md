# ARCHITECTURE.md

## Stack

- **Lenguaje/runtime**: Python 3.10, orientado a Windows (paths de fuentes tipo
  `C:\Windows\Fonts\...`, manejo de procesos con `DETACHED_PROCESS` /
  `CREATE_NEW_PROCESS_GROUP`).
- **Dependencias principales** (`requirements.txt`):
  - `requests` — HTTP para scraping y llamadas a Graph API.
  - `beautifulsoup4` + `lxml` — parseo de HTML de los sitios scrapeados.
  - `pillow` (PIL) — generación/edición de imágenes para posts y frames de video.
  - `python-dotenv` — carga de configuración desde `.env`.
  - `openai` — SDK oficial para reescritura, clasificación y generación de captions.
  - `boto3` / `botocore` — cliente S3-compatible usado contra Cloudflare R2.
  - `psutil` — usado en `cli.py` para gestión de procesos (falta en `requirements.txt`,
    ver `KNOWN_ISSUES.md`).
  - `ffmpeg` — binario externo (no pip), requerido para renderizar los videos Reel.
- **Sin base de datos**: no hay SQL/NoSQL. Todo el estado persiste como **archivos JSON
  planos en `data/`**, funcionando como colas productor/consumidor en disco.
- **No hay frontend propio**: la única "UI" es local y de uso interno
  (`video_reel_manager.py`, servidor HTTP stdlib en `127.0.0.1:8765`, y páginas HTML
  estáticas generadas por `preview_pipeline.py` / `instagram_layout_designer.py`).

## Componentes

| Componente | Archivo(s) | Responsabilidad |
|---|---|---|
| CLI | `cli.py` | `start/stop/status/logs/run-once/videos` — punto de entrada del operador |
| Supervisor 24/7 | `run_24x7.py` | Loop principal: ejecuta el ciclo completo cada N segundos, maneja apagado prolijo (SIGTERM), aísla fallos por paso |
| Orquestador de scraping | `run_all.py` | Corre los 5 scrapers + la reescritura en secuencia, cada uno activable/desactivable por env var |
| Scrapers | `scraping/base_tiempopopular.py`, `scraping/base_nuevarioja.py`, `scraping/{deportes,interior,locales,policiales}/` | Bajan links + contenido de cada sección de cada sitio fuente |
| Reescritura/IA | `openIA/rewrite_news.py`, `caption_generator.py`, `reel_generator.py` | Reescribe títulos con OpenAI, clasifica categoría, genera captions estructurados |
| Clasificador | `utils/classifier.py` | Clasifica una nota en una de 10 categorías editoriales vía OpenAI, con fallback a "Sociedad" |
| Generación de imágenes | `layout/image_generator.py`, `instagram_layout_designer.py` | Genera imágenes de post (Instagram 1080x1350, Facebook/OG 1200x630) con paleta por sección, logo y watermark |
| Generación de video | `video_reel_manager.py`, `utils/video_renderer.py` | UI local + render de Reels (PIL + ffmpeg) |
| Publicación web | `pipeline/publish_web.py`, `pipeline/node_webapp/*` | Arma y envía el payload de la nota al CMS externo (Node.js) vía API privada |
| Publicación Facebook | `meta/fb_client.py`, `meta/facebook_token_manager.py`, `meta/run_fb.py` | Publica en el feed de la página de Facebook vía Graph API v19.0 |
| Publicación Instagram | `meta/ig_client.py`, `meta/run_ig.py` | Publica posts de imagen y Reels en Instagram Business vía Graph API v19.0 |
| Publicación manual | `pipeline/custom_post.py` | Permite publicar una nota "a mano" reusando el mismo pipeline |
| Utilidades compartidas | `utils/*.py` | Colas (`social_queue.py`), dedup (`news_dedup.py`), filtros (`news_filters.py`), throttling (`publish_throttle.py`), almacenamiento R2 (`r2_storage.py`), logging (`logging_setup.py`), etc. |
| Herramientas de QA manual | `preview_pipeline.py`, `test_scraper.py` | Generan reportes HTML para revisar visualmente imágenes generadas y salud de los scrapers antes/independiente de la corrida automática |
| Setup inicial | `init_data.py` | Crea los ~16 archivos JSON vacíos de estado/colas si no existen |

## Flujo de datos

```
[tiempopopular.com.ar]     [nuevarioja.com.ar]
        |                          |
   scraping/*  ────────────────────┘
        |
        v
data/noticias_norewrite_<sección>.json   (staging por sección)
data/noticias_ejecutadas_<sección>.json  (historial de dedup)
FotosLVR/*_raw / *_opt                   (imágenes descargadas/optimizadas)
        |
        v
openIA/rewrite_news.py
  - reescribe título (OpenAI)
  - clasifica categoría (utils/classifier.py)
  - genera caption estructurado (caption_generator.py)
  - aplica orden editorial (utils/editorial_priority.py)
        |
        ├──────────────► data/noticias_web_pending.json ───► pipeline/publish_web.py
        |                                                          |
        |                                                          v
        |                                          CMS externo Node.js (lavozriojana.com)
        |                                          data/noticias_web_publicadas.json (historial)
        |
        └──────────────► data/noticias_meta.json
                                |
                                v
                    utils/social_queue.py
                data/noticias_sociales_pendientes.json
                        |               |
                        v               v
                meta/run_fb.py    meta/run_ig.py
                        |               |
                        v               v
                Facebook Graph API   Instagram Graph API
                data/fb_posted.json  data/ig_posted.json
```

Todo el ciclo se dispara desde `run_24x7.py` una vez por hora (configurable), y cada
paso corre con timeout propio y manejo de error aislado (un scraper caído no bloquea la
publicación de lo que ya está en cola).

Flujo manual paralelo: `video_reel_manager.py` / `pipeline/custom_post.py` alimentan las
mismas colas (`data/videos_manuales_borradores.json`,
`data/publicaciones_manuales_publicadas.json`) para publicaciones que no vienen de un
scraper.

## Servicios externos

- **OpenAI API** — reescritura de títulos, clasificación de categoría, generación de
  captions y (opcional) "enriquecedor editorial" para el contenido web
  (`gpt-4o` / `gpt-4o-mini`, configurable).
- **Meta Graph API v19.0** — Facebook Page (posts de feed y video nativo) e Instagram
  Business (posts de imagen y Reels vía flujo de contenedor + publish), bajo la misma
  app de Meta.
- **Cloudflare R2** (S3-compatible, vía `boto3`) — hosting temporal/permanente de
  imágenes para que Instagram, Facebook y el CMS puedan referenciarlas por URL pública.
- **CMS externo (Node.js "WebApp")** — `lavozriojana.com`, repositorio separado (no
  incluido acá); este proyecto le habla por API REST privada (`PRIVATE_API_KEY`).
- **Sitios fuente scrapeados**: `tiempopopular.com.ar` y `nuevarioja.com.ar` — terceros,
  sin API oficial, se depende de la estructura HTML actual del sitio.
- **ffmpeg** — binario del sistema para renderizar video, no gestionado por pip.

## Dependencias críticas

- **Disponibilidad y estructura HTML de los sitios fuente**: cualquier rediseño de
  `tiempopopular.com.ar` o `nuevarioja.com.ar` puede romper el scraping sin aviso
  (scrapers basados en selectores CSS/HTML fijos, sin tests automatizados de esta capa).
- **Cuota y límites de OpenAI**: sin reescritura no hay contenido publicable; hay
  reintentos configurables (`OPENAI_RETRY_COUNT`, `OPENAI_TIMEOUT`) pero no fallback a
  otro proveedor.
- **Tokens de Meta**: el token de página de Facebook se genera/cachea vía
  `facebook_token_manager.py`; si expira o Meta bloquea temporalmente la cuenta
  (rate limit / revisión), la publicación se frena silenciosamente (ver
  `KNOWN_ISSUES.md`).
- **Credenciales R2**: si fallan, no hay URL pública para las imágenes y por lo tanto
  no se puede publicar en Instagram/Facebook/web (dependen de imagen accesible por URL).
- **El CMS externo (Node.js)**: este repo asume que existe y expone la API privada
  esperada; un cambio de contrato ahí rompe `pipeline/node_webapp/publisher.py` sin que
  se note en este repositorio.
- **Sistema de archivos local como "base de datos"**: no hay backups automáticos
  robustos (solo se vieron 3 snapshots manuales en `data/backups/`); corrupción o
  pérdida de los JSON en `data/` significa pérdida de colas/histórico de dedup.

## Entornos de producción

- **Producción única**: no hay entornos separados de staging/producción documentados.
  El `.env` real apunta directo a `https://lavozriojana.com` y a cuentas reales de
  Facebook/Instagram/R2.
- **Ejecución**: proceso Python de larga duración en una máquina (aparentemente Windows,
  posiblemente la máquina de desarrollo/operador), lanzado como proceso desatachado vía
  `cli.py start`, con un PID file (`data/.supervisor.pid`) como lock de instancia única.
- **Observabilidad**: logs rotativos por módulo en `logs/*.log` (5MB, 3 backups),
  sin integración con un sistema centralizado de logs/alertas externo.
- **No hay CI/CD** documentado ni pipeline de despliegue automatizado para este repo.
