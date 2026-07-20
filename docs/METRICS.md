# METRICS.md

> Este documento define qué métricas importan y de dónde salen (o deberían salir) hoy.
> Ninguna de estas métricas tiene un dashboard centralizado todavía — se calculan a
> mano a partir de los archivos en `data/` y `logs/`, o directamente no se está
> midiendo aún. Cada sección lo indica.

## Publicaciones diarias

- **Estado**: no hay un contador agregado por día; se puede reconstruir contando
  entradas por timestamp en `data/fb_posted.json`, `data/ig_posted.json` y
  `data/noticias_web_publicadas.json`.
- **Snapshot conocido**: `data/fb_posted.json` registra ~683 publicaciones históricas en
  Facebook a la fecha de este documento (2026-07-20). No se relevó el conteo equivalente
  de Instagram ni web en este corte.
- **Pendiente**: script simple que agrupe estos JSON por fecha y calcule publicaciones/día
  por plataforma.

## Porcentaje de publicaciones exitosas

- **Estado**: se puede leer del log de cada corrida (`logs/run_fb.log`,
  `logs/run_ig.log`, `logs/publish_web.log`), que reportan "X/Y" publicados por ciclo.
- **Dato conocido/alerta**: en los ciclos del 2026-07-13 visibles en `run_fb.log`, la
  tasa fue baja (0/6, 1/7, 4/10) — ver `KNOWN_ISSUES.md` y `CURRENT_STATE.md`.
- **Pendiente**: no hay agregación histórica de tasa de éxito, solo el log crudo por
  ciclo.

## Fallos por plataforma

- **Estado**: parcialmente disponible. `run_24x7.log` marca qué paso del ciclo
  (scraping / rewrite / web / facebook / instagram) falló o completó OK por corrida.
  Pero los clientes de Facebook (`fb_client.py`, `facebook_token_manager.py`) solo
  loguean a **consola**, no a archivo, y el proceso corre con stdout/stderr
  redirigidos a `DEVNULL` — es decir, el detalle del error real de Graph API se pierde
  (bug conocido, ver `KNOWN_ISSUES.md`).
- **Pendiente**: enrutar esos loggers a archivo para poder contar fallos por tipo de
  error (rate limit, token expirado, contenido rechazado, etc.).

## Tiempo manual ahorrado

- **Estado**: no medido formalmente (no hay baseline documentado de "cuánto tardaba
  hacer esto a mano").
- **Estimación cualitativa**: el pipeline reemplaza, por cada nota, el trabajo manual de
  buscarla, reescribirla, clasificarla, diseñar la imagen y publicarla en 3 canales —
  tareas que a mano tomarían varios minutos cada una, multiplicado por el volumen de
  ~683+ publicaciones históricas solo en Facebook.
- **Pendiente**: si se quiere una cifra real, definir un tiempo estimado por publicación
  manual (ej. minutos) y multiplicarlo por el volumen mensual del sistema.

## Visitas (al sitio web)

- **Estado**: no trackeado desde este repo. `lavozriojana.com` es una app externa
  (Node.js) fuera de este código; cualquier analítica de tráfico vive ahí (o en
  Google Analytics / similar, si está configurado del lado del CMS).
- **Pendiente**: documentar en el repo del CMS o acá una vez que se confirme la fuente
  de analítica del sitio.

## CTR

- **Estado**: no trackeado. Requeriría integración con Meta Insights (para posts de
  Facebook/Instagram) y analítica del sitio (para notas web) — ninguna está conectada a
  este pipeline hoy.

## Alcance social

- **Estado**: no trackeado desde este repo. Se podría obtener vía Meta Graph API
  Insights (endpoints de `page_impressions`, `ig_media` insights) reusando las mismas
  credenciales de `FB_PAGE_ACCESS_TOKEN` / `IG_ACCESS_TOKEN` ya configuradas, pero no
  hay código que lo consulte todavía.

## Ingresos

- **Estado**: no aplica / no trackeado. El sistema no gestiona pauta publicitaria ni
  monetización directa (ver `PRODUCT.md` → "Qué NO intenta resolver").

## Resumen de brechas de medición

La brecha más grande hoy no es la falta de dashboards, sino la falta de **logging de
errores accionable** para Facebook (bloquea calcular "fallos por plataforma" con
precisión) y la ausencia total de conexión con **Meta Insights** o **analítica del
sitio** para medir alcance/CTR/visitas. Priorizar esto antes de invertir en un
dashboard agregado.
