# Formatos sociales (2026-10-18)

Formatos propios para Instagram y Facebook, aprobados por el responsable del
medio el 2026-10-18. Ninguno usa IA salvo las respuestas a comentarios (una
llamada corta por pregunta) y el resumen del reporte (una llamada cada 3
días). Cada uno tiene interruptor propio (apagado por defecto en el código,
encendido en `scripts/start_24x7_production.ps1`) y estado propio: no comparten
cupos ni dedup con el feed. El backoff de rate limit de Meta sí se comparte.

| Formato | Dónde | Cuándo | Módulo | Estado |
|---|---|---|---|---|
| Historia de cada publicación de Instagram | IG + FB (misma imagen) | cada ciclo, 7–24 h | `utils/story_publisher.py`, `meta/run_stories.py` | `data/stories_state.json` |
| Historias de servicio: clima SMN, alertas, dólar, feriados, cortes de luz/agua, rutas | IG + FB | clima 7–11 h; dólar 11–13 y 16–18 h hábiles si cambió; feriado 7 y 1 día antes; alertas y avisos cuando aparecen | `utils/social_formats.py`, `utils/service_data.py` | ídem |
| "Lo que tenés que saber hoy" | carrusel IG (7 láminas) + álbum FB | desde las 8 (`MORNING_BRIEF_HOUR`), una vez por día | `utils/social_formats.py`, `meta/run_social_formats.py` | `data/social_formats_state.json` |
| "La semana en cinco" | Reel IG + video FB | domingos desde las 20 (`WEEKLY_RECAP_HOUR`) | ídem | ídem |
| Seguimiento de noticias en desarrollo | historia IG + FB, comentario en el post de IG, texto editado en FB | cada ciclo | `utils/story_updates.py` | ídem (`updates`) |
| Respuestas a preguntas | IG + FB | cada ciclo, 7–24 h | `utils/comment_replies.py`, `meta/run_comment_replies.py` | `data/comment_replies.json` |
| Placas de servicio: cronograma de pagos de Hacienda y sismos con epicentro en La Rioja (INPRES) | pagos: historia cada día de pago, post IG sólo el primer día del cronograma, post FB todos los días; sismos: post IG + FB y historia (más historia ACTUALIZADO si INPRES lo corrige) | pagos: día de pago, 7–22 h; sismos: magnitud ≥ 4,0 (`QUAKE_MIN_MAGNITUDE`) de las últimas 12 h, a cualquier hora | `utils/service_posts.py`, `meta/run_social_formats.py` | `data/social_formats_state.json` (`service_posts`) |
| Reporte cada 3 días + vigilante | correo | tareas `LaVozRiojana-Report` (9 h cada 3 días) y `LaVozRiojana-Watchdog` (15 min) | `utils/ops_report.py`, `utils/mailer.py`, `cli.py report/watchdog` | `data/ops_report_state.json` |

## Diseño (Remotion, `remotion/src/v2/social/`)

- `StoryV2` (1080×1920): `post`, `breaking`, `reel`, `update`, `weather`,
  `alert`, `dollar`, `notice`, `holidays`. Marca (sello + wordmark) arriba;
  todo el contenido propio entre y=250 y y=1650 (barra de progreso y caja de
  respuesta de las historias quedan libres). La historia de un post muestra la
  publicación tal cual salió (la API no permite adjuntar el post como sticker
  ni agregar stickers de link).
- `MorningBriefV2` (1080×1350, render 2×): tapa de diario (sello, doble
  filete, fecha y clima, título en serif, sumario numerado), una lámina por
  nota con su foto original y una lámina "Para organizar tu día".
- `WeeklyRecapV2` (Reel 1080×1920, 30 fps, ~28 s): apertura, puestos 5→1 con
  la foto en un panel (nunca se estira una foto chica), número grande,
  sección, alcance real y titular; cierre con el sello.

Las piezas usan la foto original de la nota (`utils/article_media.py`): la
imagen OG del sitio ya trae el titular escrito.

## Reglas editoriales

- "Último momento" en la historia sólo si el título lo dice ("último
  momento", "urgente"); la urgencia amplia del feed sólo ordena.
- Carrusel de la mañana: últimas 24 h, locales primero, sin temas repetidos,
  sin notas sensibles (abuso, femicidio, suicidio, contenido íntimo) ni notas
  de clima (el clima ya va en la tapa). Sin 3 notas con foto, no sale.
- Resumen semanal: alcance real de Instagram (`ig_media_insights.json`), una
  nota por tema (mismo `story_key`/`topic_key` o nombres propios en común).
- Seguimiento: mismo hecho = al menos dos palabras distintivas en común que
  cubren el 60 % del título más corto (sin genéricas como "choque" o
  "heridos"), y la cifra nueva escrita en el título de la nota nueva. Ante
  cualquier ambigüedad no se publica.
- Respuestas: nunca en policiales, política ni espectáculos; sólo preguntas
  reales (filtro sin IA); Gemini responde sólo con lo que dice la nota y toda
  cifra de la respuesta tiene que estar en la nota. Tope 15 por día, 3 por
  publicación. `COMMENT_REPLIES_MODE=suggest` (primera semana) guarda la
  respuesta para revisar: `python cli.py comment-replies list|approve|reject`.
- Avisos de cortes y rutas: salen de notas propias publicadas (EDELaR y Aguas
  Riojanas no tienen un listado de cortes en sus sitios).
  La historia muestra la zona que dice la nota (`notice_zone`): barrio,
  localidad o ruta; el alcance si es amplio ("Gran parte de la Capital", "Varias
  zonas de la provincia"); y "No especificada en el aviso original" si la nota no
  la dice. Nunca se supone un lugar. Los cortes de luz o agua sin señal riojana
  (EDELaR, Aguas Riojanas o una localidad; p. ej. un apagón en el AMBA) no salen.

## Fuentes de servicio

| Dato | Fuente |
|---|---|
| Tiempo presente y pronóstico 5 días | datos abiertos del SMN: `ssl.smn.gob.ar/dpd/zipopendata.php?dato=tiepre|pron5d` (estación "La Rioja" / "LA_RIOJA_AERO") |
| Alertas y avisos a muy corto plazo | feed CAP del SMN: índice `ssl.smn.gob.ar/CAP/AR.php` y un XML por emisión (caché por URL). Nivel por `severity`/titular; departamentos por el texto ("LA RIOJA: …") o por puntos de cada departamento dentro del polígono. `dato=alertas` de los datos abiertos viene vacío |
| Dólar | `dolarapi.com/v1/dolares` (oficial, blue, MEP, CCL) |
| Feriados | JSON oficial `argentina.gob.ar/sites/default/files/holidays-<año>-es.json` (se excluyen los "especiales" de otras provincias) |
| Cortes y rutas | notas propias del archivo editorial (`classify_notice`) |
| Cronograma de pagos | `hacienda.larioja.gob.ar/wp-json/wp/v2/posts`: posts "QUINCENA/HABERES <MES> – <DÍA> dd/mm" con la lista de organismos (por banco si la separa) |
| Sismos | `contenidos.inpres.gob.ar/mapa/sismos.xml` (sólo HTTP, el listado inmediato: `color_link` 00f = automático, 000 = revisado, f00 = sentido) + `epicentro3.php?s=<id>` (distancias a localidades tal como las informa INPRES, la más cercana primero). Entran sólo los de `prov` LA RIOJA |

Las placas de servicio usan una sola plantilla para post y historia
(`ServicePlate` en `remotion/src/v2/social/ServicePieces.tsx`, usada por
`ServiceCardV2` y `StoryV2` kinds `payments`/`quake`):

- zonas libres de 250 px arriba y 350 px abajo (sólo fondo);
- etiqueta de estado con color fijo: HOY rojo, MAÑANA azul, ACTUALIZADO ámbar,
  CANCELADO gris;
- un dato protagonista (pagos: "Cobran estatales" + fecha; sismo: magnitud) y
  hasta tres renglones de apoyo;
- pie "Fuente · actualizado HH:MM";
- como máximo 25 palabras (`service_posts.plate_words`): si sobran, se quitan
  renglones opcionales; si aun así no entra, la placa no sale.

Pagos: la placa dice "Cobran estatales", la fecha, el concepto y el próximo
pago si Hacienda ya lo anunció; la lista de organismos va en el texto del post.
Sismos: si el dato es automático la placa lo dice ("Dato automático"); si INPRES
lo revisa con otra magnitud o localidad (el id puede correrse unos segundos: se
empareja por hora con 3 min de margen), sale una historia ACTUALIZADO con el
valor anterior. El texto del post pregunta "¿Lo sentiste? ¿Desde dónde?". La
historia de servicio cubre la historia automática del post ("Nueva
publicación"), que no se duplica.

Una alerta del SMN que menciona La Rioja pero cuyo formato no se reconoce no
se publica: queda en `logs/social_formats.log` y en el reporte.

## Reporte y vigilante

`python cli.py report` muestra el reporte; `--send` lo manda (con resguardo de
período, `--force` para reenviar); `--no-ai` sin resumen de Gemini.
`python cli.py watchdog` manda un correo cuando el heartbeat del supervisor
tiene más de 2 horas (un aviso por incidente) y otro cuando vuelve.

Configuración del correo en `.env` (nunca en el repo):
`REPORT_EMAIL_TO`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`
(con Gmail, una contraseña de aplicación). Sin esos datos el reporte devuelve
`smtp_not_configured` y no falla nada más.

## Rollback

Apagar el interruptor del formato en `scripts/start_24x7_production.ps1`
(`IG_STORIES_ENABLED`, `FB_STORIES_ENABLED`, `MORNING_BRIEF_ENABLED`,
`WEEKLY_RECAP_ENABLED`, `STORY_UPDATES_ENABLED`, `PAYMENT_POSTS_ENABLED`,
`QUAKE_POSTS_ENABLED`, `COMMENT_REPLIES_MODE=off`, o
`SOCIAL_FORMATS_INSTAGRAM_ENABLED`/`SOCIAL_FORMATS_FACEBOOK_ENABLED`) y
reiniciar el supervisor. Las tareas de reporte y vigilante se quitan con
`schtasks /delete /tn LaVozRiojana-Report` y `LaVozRiojana-Watchdog`.

## Mismo hecho y actualizaciones (2026-10-23)

- Antes de la reescritura, `utils/same_event.py` compara la nota con lo encolado
  en las últimas 36 h que comparte alguna palabra (sólo fuentes locales). Una
  llamada a Gemini decide: otro hecho, mismo hecho sin nada nuevo (no sale) o
  mismo hecho con un dato nuevo (sale como actualización). Exige un "ancla"
  concreta escrita en las dos notas (lugar, ruta con número, nombre propio); si
  no la hay o Gemini falla, la nota sigue como nueva.
- Actualización: el título empieza por la novedad; la placa de IG lleva la
  pestaña "ACTUALIZACIÓN" y el texto empieza con "🔄 ACTUALIZACIÓN" en cada red
  donde la nota anterior ya salió. Además: historia "Actualización" (antes /
  ahora), comentario en el post original de IG (la API no deja editar su texto)
  y el post original de FB editado con "🔄 Actualización HH:MM". En la web, la
  nota nueva queda en la misma historia (`storyKey`) que la anterior.
- Si las dos versiones esperan juntas (horario de silencio), en esa red sale
  sólo la más nueva (`policy_superseded_by_update`).
- La placa admite hasta dos lugares ("Capital · Chilecito"), verificados contra
  el texto, y saca del título el lugar que ya dice la pestaña cuando se puede
  sin dejar conectores colgando (`strip_places`).
- Alertas meteorológicas: sólo del SMN. Con `WEATHER_ALERT_NEWS_SMN_ONLY` las
  notas de otros medios sobre alertas no se publican.
