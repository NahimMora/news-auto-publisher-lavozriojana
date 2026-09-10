# Estado actual

Última actualización: 2026-09-10 (Editorial Context Engine / Story Engine / Source
Registry; el resto del documento describe el estado previo y sigue vigente).

## Editorial Context Engine, Story Engine y Source Registry (rama `feature/editorial-context-story-engine`, no mergeada, 2026-09-10)

Nueva capa aditiva que enriquece la redacción editorial existente con
antecedentes del archivo propio y de fuentes oficiales, sin reemplazar el
pipeline actual. Detalle técnico completo en `docs/EDITORIAL_CONTEXT.md`,
`docs/STORY_ENGINE.md`, `docs/OFFICIAL_SOURCES.md` y `docs/COST_MODEL.md`;
bitácora completa de la construcción de esta etapa en
`docs/EDITORIAL_CONTEXT_PROGRESS.md`.

Resumen de lo que cambia en el flujo real:

- Nuevo índice derivado `data/derived/editorial_context.sqlite3`
  (reconstruible, gitignored, no autoritativo) con búsqueda full-text
  (FTS5 con fallback) sobre el archivo propio de notas publicadas.
- Nueva etapa de ciclo `editorial_context/refresh_context.py` en
  `run_24x7.py::CYCLE_STEPS` (entre `run_all.py` y
  `pipeline/publish_web.py`): sincroniza fuentes oficiales habilitadas una
  vez por ciclo, respetando `poll_ttl` por fuente.
- `pipeline/node_webapp/publisher.py` arma un `EditorialContextBundle`
  antes de `prepare_editorial` (contexto 100% opcional, nunca bloquea la
  publicación) y, si corresponde, agrega `storyKey`, `sources[]` y
  `metadata.archiveContext` al payload del CMS.
- **Bug corregido en el mismo paso**: `_CATEGORY_AUTHORS` mandaba
  `authorName` fijo por categoría ("Redacción Política", etc.),
  contradiciendo la política real del CMS (Fernando Nahim Mora). Eliminado;
  ver `docs/DECISIONS.md` (2026-09-10).
- CMS (`LaVozRiojana`, rama propia con el mismo nombre): `Post.storyKey`
  (migración aditiva nullable, ya aplicada al DB local de desarrollo),
  módulos `<StoryTimeline />` / `<ArchiveContextNote />` en la página de
  nota.

Nada de esto está activo en producción todavía: la rama no está mergeada a
`main` en ninguno de los dos repos, y el índice derivado no existe hasta la
primera ejecución real (se autogenera solo). No requiere pausar el
supervisor productivo para desarrollarse ni testearse — todo el trabajo de
esta etapa se hizo en la máquina de desarrollo, nunca en la PC de
producción (ver sección siguiente).

## Separación dev/producción: el servicio corre en una PC dedicada (2026-08-21)

El supervisor 24/7, la UI manual y las tareas programadas dejaron de correr en esta
máquina de desarrollo (`pc10`). Producción es ahora exclusivamente
`PC@192.168.1.150`, `C:\LVR`, accedida por SSH con clave dedicada
(`~/.ssh/id_ed25519_lvr`). Esta PC conserva el repo únicamente para escribir código,
correr tests y validar renders — nunca para ejecutar el servicio, ni de forma
puntual. Detalle completo, procedimiento de despliegue por SSH y la regla operativa
en `docs/RUNBOOK.md` ("Entorno: desarrollo vs. producción") y
`docs/MIGRACION_PC_COMPARTIDA.md`.

La migración incluyó el historial real de deduplicación/publicación (`data/`
completo: `fb_posted.json`, `ig_posted.json`, `media_library.json`, colas de
rewrite/web/social) para que la nueva instancia continuara sin re-publicar contenido
ya publicado desde `pc10`.

Durante la migración se detectó y corrigió un incidente de instancias duplicadas —
tareas programadas olvidadas en dev relanzando el pipeline con credenciales reales
en paralelo a producción, y una segunda generación del supervisor en producción por
pérdida del `data/.supervisor.pid` durante el traspaso del historial. Ninguna llegó
a publicar contenido duplicado (se detuvieron antes de alcanzar las etapas de
Facebook/Instagram). Detalle completo en `docs/KNOWN_ISSUES.md` #84 y la decisión
formal en `docs/DECISIONS.md` (2026-08-21).

## Reel independiente de paparazzi, motor 127.0.0.1:8765 (2026-08-10)

Nueva capa opcional, **apagada por defecto** (`PAPARAZZI_REEL_ENABLED=false`; no
cambia nada hasta activación explícita). Con el flag encendido: cuando una nota de
paparazzi.com.ar con video fuente ya se publicó con éxito como carrusel de Instagram
(`meta.ig_client.post_paparazzi_carousel_to_instagram`, ver `docs/DECISIONS.md`
2026-08-05), `meta/run_ig.py` dispara además, best-effort,
`utils.paparazzi_reels.publish_paparazzi_reel`: genera un Reel con el mismo motor que
la UI manual de Reels (127.0.0.1:8765 — `utils.video_renderer.render_video`, título
superpuesto vía Remotion `EditorialReel`/`Main`, distinto del clip sin título del
carrusel) y lo publica como segunda publicación independiente en Instagram
(`media_type: REELS`) y Facebook (`/videos`), cada una respetando su propio
`IG_PUBLISH_ENABLED`/`FB_PUBLISH_ENABLED`. Dedup y estado propios
(`data/paparazzi_reels_posted.json`), separados de `ig_posted.json`/`fb_posted.json`
a propósito — ver la decisión completa (motivo, alternativas, consecuencias) en
`docs/DECISIONS.md` (2026-08-10).

Para activarlo en producción: `PAPARAZZI_REEL_ENABLED=true` en `.env` (requiere R2
configurado y al menos uno de `IG_PUBLISH_ENABLED`/`FB_PUBLISH_ENABLED` en `true`).
Tests: `tests/test_paparazzi_reels.py`.

## Corrección de la bandeja de candidatas (2026-08-03)

La pestaña `Candidatas` de la UI loopback dejó de heredar la grilla de tres columnas
de Videos, que confinaba todo su contenido a una franja de 370 px y dejaba el resto
del viewport vacío. Ahora usa el ancho disponible, separa la gestión manual de la
bandeja pendiente, presenta las candidatas en cards responsivas y prioriza la lista
antes del formulario en pantallas angostas.

La carga muestra estados explícitos de espera, vacío y error; valida el HTTP antes de
presentar resultados, ordena las candidatas más recientes primero y diferencia en la
acción principal una candidata del router de una publicación ya reutilizada. El
render continúa construyendo el DOM con `textContent`: no interpola título, identidad,
tema ni motivo como HTML. No cambió el router, la persistencia ni las transiciones
`candidate↔automatic`/`candidate↔discarded`.

QA aislado sin publicación externa: prueba unitaria del contrato HTML/DOM, chequeo de
sintaxis del JavaScript embebido y smoke visual con tres candidatas simuladas en
1440×1000 y 620×1000; la pestaña ocupó el ancho completo y no emitió errores de
consola.

## “Enviar a automática” es autoritativo para Instagram (2026-08-03)

La transición manual `candidate→automatic` dejó de estar subordinada a
`IG_ALLOWED_CATEGORIES`. `meta/run_ig.py` cruza la identidad de la noticia con el
historial durable de `editorial_candidates.json`; si el operador la promovió, la
incorpora a la cola de Instagram aunque su categoría no sea una de las habituales y
aunque el título no active `breaking`. La promoción conserva su efecto aunque se haya
hecho antes de desplegar esta corrección.

Para Instagram, el override manual tampoco espera una URL Web: una publicación de
Instagram no la incorpora a su payload y la instrucción del operador es explícita. El
flujo automático normal y Facebook siguen exigiendo URL Web. La excepción conserva el
kill switch, deduplicación, evidencia de publicación, validación de imagen,
backoff/rate limit y no revive a ciegas un `processing` o `dead_letter`. Las entradas
`published_reuse` quedan
excluidas del override porque “Quitar de candidatas” nunca significa republicar una
pieza ya confirmada. El resultado de bootstrap informa
`included_by_manual_override`, `manual_override_without_web_url` y
`restored_from_candidate_store`.

La candidata guarda el payload editorial que motivó la decisión. Si una promoción
manual sigue en `automatic` pero la rotación sacó la noticia de
`noticias_meta.json` antes del siguiente ciclo, `run_ig` la recupera desde esa copia
durable y la encola con la misma identidad. El dedup y los estados
`completed`/`processing`/`dead_letter` siguen impidiendo una republicación a ciegas.

La UI ahora confirma el alcance antes de promover y muestra una respuesta persistente
que aclara que la noticia quedó habilitada para el siguiente ciclo. QA aislado cubrió
una categoría `deportes` fuera de política, reactivación `excluded→pending` sin
duplicar, promoción sin URL Web, ruta todavía candidata y publicación reutilizada.
También cubre la recuperación desde candidatas cuando el ítem ya no está en Meta.

## Reactivación productiva 24/7 (2026-08-02)

Por autorización explícita del operador se reactivó el autopublicador con la línea de
base durable de las 20 noticias más recientes. El primer reporte encontró que el lote
anterior era del 30/07, por lo que se ejecutó únicamente scraping + reescritura con
Web/Facebook/Instagram forzados a `off`: 100 candidatas procesadas, 0 fallos, 39
expiradas por política, 58 agregadas a Web y 54 a Meta. Después de un segundo backup,
`queue-cutover --keep-latest 20 --apply` dejó 20 identidades únicas fechadas 01/08 y
encoladas el 02/08: 20 Web, 16 Meta y 0 sociales activas; archivó 38 Web, 58 Meta y 8
estados sociales vencidos. `unknown_order=0` antes y después del corte.

El preflight vivo confirmó fuentes 10/10, OpenAI, R2 con cleanup, Facebook,
Instagram y filesystem. `preflight_cms` continúa correctamente `blocked` porque el
CMS externo todavía no ofrece `WEBAPP_PREFLIGHT_PATH`; no se lo presenta como éxito.
La reactivación conserva la excepción operativa documentada desde el 27/07: escritura
CMS limitada y evidenciada, kill switches, rollback y autorización explícita. No se
ejecutó canary. La conciliación Facebook previa reportó 0 ambiguos, 0 inválidos y 0
pendientes válidos; sus 8 entradas históricas estaban vencidas.

`scripts/start_24x7_production.ps1 -ValidateOnly` pasó `doctor supervisor` 8/8. La
tarea `LaVozRiojana-24x7` quedó habilitada, con `LastTaskResult=0`, y el supervisor
corre en modo `all`, heartbeat fresco, intervalo de una hora y watchdog cada cinco
minutos. La UI manual sigue HTTP 200 sólo en `127.0.0.1:8765`.

El ciclo productivo #81 cerró `degraded` sin fallos externos: Web publicó 17/17,
descartó 3 duplicados, dejó 0 pendientes y marcó 5 resultados degradados por usar el
sexto intento seguro sólo con warnings de similitud; Facebook publicó 5/5 e Instagram
2/2, todos con ID externo durable y `ambiguous_to_dead_letter=0`. Facebook conserva
10 pendientes para ciclos posteriores por límites/política; Instagram no conserva
pendientes elegibles. Los dos posts de Instagram usaron Remotion automático con la
paridad visual 2× activa.

## Reels con movimiento editorial profesional (2026-08-02)

El generador manual de la pestaña `Videos` dispone de la composición aditiva
`EditorialReel` (1080×1920, 30 fps), activada en este host mediante
`REEL_CINEMATIC_VISUAL_STYLE_ENABLED=true`. El default del código y de
`.env.example` sigue siendo `false`: `Main` y su outro cacheado continúan disponibles
como rollback, y el flag no afecta las cards automáticas, Premium, CMS ni Meta.

La composición lleva al video el sistema "Editorial Cinemática Riojana": Archivo y
Source Serif 4 locales, rojo para Crónica y azul noche para Editorial, una frase
relevante copiada literalmente del título, medio con reveal/Ken Burns/parallax,
titular por renglones, reflejos, textura, barra de progreso, fase compacta y cierre de
marca integrado. El selector local de destaque reutiliza las reglas verificables de
Publicaciones y no agrega una llamada a OpenAI. Título, sección, asset, duración y
`highlightTerms` siguen usando el esquema compatible de `Main`.

QA controlado sin publicación externa: TypeScript y ESLint sin errores; renders reales
con foto, sin foto, secciones roja/azul y fotogramas de entrada, lectura, compactación
y cierre. El MP4 completo de prueba resultó H.264 1080×1920, 30 fps, 11,05 s y 3,8 MB
(8 s de contenido + 3 s de cierre), validado con `ffprobe` y una plancha temporal de
un fotograma por segundo.

Ajuste de legibilidad posterior: la cabecera reserva 164 px y usa logo de 74 px,
nombre de 35 px y metadata de 24 px; la bandera de sección reserva 78 px, con logo de
42 px y etiqueta de 31 px; el footer reserva 104 px, con texto de 33 px e íconos de
38 px. El área del medio y el panel del titular se recalcularon contra esas reservas.
Un render real con título largo confirmó que los tres niveles se leen claramente sin
superponer ni cortar el titular.

La fase compacta usa un segundo layout tipográfico, medido a fuente menor sobre todo
el ancho útil; ya no escala horizontalmente los mismos renglones del estado grande.
Un crossfade frame-driven recompone las palabras y el alto medido determina la
posición final del panel completo. Así, sección, título y footer quedan agrupados sin
franjas grandes ni texto cargado hacia la izquierda. Cada renglón queda fijado por
`fitText` y no vuelve a partirse dentro de los spans coloreados. Fotogramas reales
antes, durante y después de la transición verificaron reparto, safe areas y recorte.

## Ajuste de la card de Publicaciones (2026-08-02)

La pestaña `Publicaciones` de la UI loopback conserva el título completo: el campo
manual acepta hasta 120 caracteres y el backend aplica el mismo límite. Cuando el
origen es `manual_custom_post` —o el automático tiene
`AUTOMATIC_MANUAL_VISUAL_STYLE_ENABLED=true`— `AutomaticInstagramCard` mide el título
con la fuente real y ajusta el panel degradado entre 260 y 554 px según líneas,
localidad y bajada.
El aire vertical equivale al 7,5% del panel, acotado a 36–48 px por lado; permite cinco
líneas y reduce la tipografía hasta 32 px en el caso patológico antes de considerar
overflow. Se eliminó así el caso
reproducido donde un título válido terminaba en `...` o se acercaba al footer.

La sección usa en esas cards manuales la bandera/recuadro de la portada Premium:
rojo para el modo Crónica y azul noche `#0B2F4F` para Editorial; el destaque del
título conserva el azul más luminoso. La misma llamada de contexto visual, activada
con `include_highlight=True` en ambos workflows cuando está habilitada la paridad,
propone una frase
relevante de 2 a 4 palabras contiguas. El prompt prioriza el núcleo de la noticia y
la primera mitad del título; prohíbe elegir sólo lugares, fechas o cierres genéricos.
El backend aplica las mismas reglas, además de exigir palabras copiadas del título;
ante una salida inválida o falta de OpenAI usa una selección local sin inventar texto.
Esa frase viaja como
`highlight_terms` y se dibuja con el color de acento de la card. Las entradas
automáticas anteriores al flag, que todavía no traen esa metadata, usan el mismo
selector local verificable al renderizar. El host actual tiene la paridad activada.

Para evitar pixelado al ampliar la pieza en una PC, las cards manuales y las
automáticas con paridad activa se renderizan a escala 2×: el lienzo lógico sigue siendo 1080×1350
pero el archivo final es 2160×2700. La conversión usa JPEG calidad 95 con submuestreo
4:4:4, que preserva mejor los bordes de tipografía y los acentos de color. El lote
automático sólo conserva 1080×1350 cuando el flag está apagado. Con el flag activo
acepta el mayor costo, tiempo y tamaño de archivo para igualar el resultado manual.
Preview, publicación manual y autopublicación consumen el mismo paquete visual.

Validación controlada: 413/413 tests Python, incluidos renders Remotion reales en 1×
y 2×; `npx tsc --noEmit` y ESLint sin errores (dos warnings preexistentes sobre
`objectFit` en Video). Dos renders reales con título de 119 caracteres, localidad y bajada
confirmaron el título completo, el footer libre y los acentos azul/rojo; un tercer
render con una palabra única de 120 caracteres confirmó el caso patológico sin
elipsis. No se ejecutó ninguna publicación externa durante ese QA visual; la
reactivación productiva posterior está documentada arriba.

## Editorial Cinemática Riojana (rama `feature/editorial-cinematica-riojana`, no mergeada)

Construida sobre `feature/premium-studio-ux` (limpia al momento de partir). No se
modificó `main`, `.env`, `data/`, `logs/`, `output/` ni `FotosLVR/` (sólo lectura de
fotos existentes para fixtures), y no se ejecutó ninguna publicación real.

Rediseño visual completo de las dos piezas estáticas del proyecto (carrusel premium y
card automática de Instagram) bajo un sistema compartido, "Editorial Cinemática
Riojana": 3 modos de composición (Crónica/Editorial/Datos), tipografía Archivo + Source
Serif 4 cargada localmente (sin Arial), gradientes por capas, textura sutil y auto-fit
de texto que nunca desborda. Ver `docs/DECISIONS.md` 2026-07-31 para el detalle
completo de la decisión.

- Se agregó un servidor de render persistente (`remotion/render_server.mjs`) que
  bundlea una sola vez por proceso en vez de re-bundlear en cada render — cierra
  `docs/KNOWN_ISSUES.md` #69. Benchmark re-medido con los mismos 10 fixtures que la
  corrida original: **19.119s → 2.373s promedio por paquete (~8.1x más rápido)**, ver
  `docs/METRICS.md`. `utils/remotion_renderer.py::render_still()` lo usa primero y cae
  al `subprocess` histórico si no está disponible — mismo contrato de retorno, ningún
  caller (tests incluidos) cambió.
- Con esa mejora de performance, el flujo automático de Instagram —que hasta esta
  entrega renderizaba 100% en Pillow, sin wiring real a Remotion— ahora intenta
  Remotion primero vía la función nueva `layout/image_generator.py::generate_instagram_with_engine`
  (aditiva; `generate_post`/`generate_instagram`/`generate_facebook` quedan intactas
  como fallback). `AUTOMATIC_STATIC_RENDER_ENGINE` cambia su default de `pillow` a
  `auto` — intenta Remotion, cae a Pillow sin bloquear una publicación real. Este es el
  único cambio de comportamiento de producción de esta rama y requiere revisión
  explícita antes de mergear.
- Auto-fit de texto medido con Canvas 2D real (`remotion/src/shared/fitText.ts`) cierra
  `docs/KNOWN_ISSUES.md` #70 — ningún título observado se desborda del lienzo en los
  fixtures probados, incluidos casos pathológicos (palabras sin espacios más anchas que
  el lienzo, términos resaltados con puntuación pegada).
- Fixtures reales (fotografía de `FotosLVR/`, títulos corto/largo, horizontal/vertical/
  clara/oscura, sin foto, policiales/política/deportes, carrusel de 5 slides en los 3
  modos) y contact sheets comparando diseño actual vs nuevo en
  `docs/design/editorial-cinematica/` (`scripts/generate_visual_contact_sheet.py`).
- Validación: 379/379 tests Python OK (43 nuevos frente a la línea de base de 336),
  `npx tsc --noEmit`/`npx eslint src`/`npx remotion bundle` sin errores nuevos,
  `compileall`/`git diff --check` OK. No se tocó scraping, colas, límites ni contratos
  de publicación de Meta — sólo generación/render visual y el punto donde
  `meta/ig_client.py::_prepare_image` elige qué función de imagen llamar.

Requiere revisión y aprobación explícita antes de mergear, en particular el cambio de
default de `AUTOMATIC_STATIC_RENDER_ENGINE` descrito arriba.

## Rediseño del Estudio Premium (rama `feature/premium-studio-ux`, no mergeada)

Construido sobre `main` en `4b8a1c7`, después del merge del PR #2 de la capa
editorial premium. No se modificó `main`, `.env`, `data/`, `logs/`, `output/` ni
`FotosLVR/`, y no se ejecutó ninguna publicación real.

PR draft: [#3](https://github.com/NahimMora/news-auto-publisher-lavozriojana/pull/3),
abierto contra `main`, sin merge. CI autoritativo `reliability-windows`: verde.

- El operador puede pegar el texto actualizado de una noticia y generar con OpenAI
  el JSON del paquete. La salida reutiliza `import_chatgpt_package`; no hay un segundo
  contrato ni fallback silencioso. El prompt prohíbe investigar o inventar datos,
  personas, armas y hechos ajenos al texto.
- La generación automática aplica un contrato editorial adicional antes de importar:
  título informativo de 60 a 80 caracteres, 3 o 4 slides sustantivos que cuentan la
  noticia completa, y caption local con apertura informativa, emojis, fuente sólo si
  consta y 3 a 6 hashtags relevantes (siempre `#LaRioja`). Si el modelo no cumple,
  el reintento recibe el texto original, el JSON erróneo como respuesta anterior y
  los errores concretos como feedback, sin poder completar datos desde afuera. Si se
  agotan los intentos, se importa el último JSON parseable con avisos para corrección
  manual; sólo se bloquea cuando no hubo ningún JSON utilizable. Este gate no cambia
  la compatibilidad de borradores creados o editados a mano.
- La UI quedó ordenada en cuatro pasos: generar/importar, revisar slides, asignar
  imágenes y guardar/previsualizar/publicar. El import JSON manual sigue disponible.
- Cada tipo de slide es único dentro del carrusel. El selector deshabilita los tipos
  ya usados, agregar elige el siguiente disponible, duplicar queda bloqueado y el
  contrato rechaza repeticiones también en imports/API. El generador recibe el mismo
  criterio. `impact` aporta una segunda placa textual sin foto para consecuencias
  locales o próximos pasos; si la IA devuelve dos `context`, el segundo se normaliza
  a `impact` sin modificar título, texto ni ítems, evitando guardar un draft fallido.
- La composición Remotion de Premium aumentó de forma acotada la escala de titulares,
  cuerpos, puntos clave, citas, cifras, chips y cierre, y amplió cabecera, sección,
  footer y numeración para sostener la lectura al reducir 1080x1350 en un celular.
  `AutomaticInstagramCard` (publicaciones manuales y automáticas de una sola imagen)
  comparte esa misma escala de masthead/footer/titular — no la de cuerpo/puntos
  clave/citas, que no tiene. Sigue sin señal de deslizamiento ni numeración (no es un
  carrusel).
- `FacebookOgCard` (tarjeta Open Graph del artículo web) dejó `LegacyStillLayout`/Arial y
  pasó al mismo sistema editorial (masthead de marca, foto + panel de tinta, titular con
  auto-fit), con constantes propias `OG_*` porque su lienzo 1200x630 es mucho más bajo.
  `resolve_engine("og")` pasa de `"pillow"` a `"auto"` por defecto: `generate_og_image`
  ahora usa `generate_facebook_with_engine` (Remotion primero, Pillow si falla, nunca
  bloquea la publicación web). Sólo se ve al visitar/compartir la URL del artículo, no
  hay botón de vista previa de esta pieza en la UI de `video_reel_manager.py`.
- `AutomaticInstagramCard` corrigió ancho/posición del título (Editorial ya no lo
  achica a 80%/alinea a la derecha; `maxHeight` resta el padding real de ambos lados
  para que no quede pegado contra la foto) y sumó chip de localidad + bajada antes del
  título, completados por IA (`openIA/caption_generator.py::generate_locality_and_deck`,
  vacíos y sin bloquear la publicación si el texto no trae lugar/contexto claro o si
  OpenAI falla). Se llama desde el flujo automático (`rewrite_news.py`) y el manual
  (`pipeline/custom_post.py`). El footer de `AutomaticInstagramCard`/`FacebookOgCard`
  muestra ahora íconos FB/IG + `lavozriojana.com` (`StillLayout` prop
  `showSocialFooter`, opcional — `PremiumSlide` no lo activa).
- Se corrigió un desborde real donde el título podía superponerse al footer:
  `FacebookOgCard` (lienzo 1200x630, mucho más bajo) usa ahora escala tipográfica y
  padding propios en vez de heredar los de Premium/Automatic, y subió su chrome
  (masthead/footer/logo/sección) de 0.82x a 1.05x para verse en línea con el resto del
  sistema. `AutomaticInstagramCard` reserva el alto del chip de localidad + el gap
  antes de calcular el presupuesto del título, y suma `overflow:hidden` como red de
  seguridad. `SocialFooter` (íconos + url) subió de tamaño base en ambas piezas.
- Cada slide acepta imagen por link público SSRF-safe, subida propia validada o
  biblioteca local. Los dos primeros caminos convergen en `ingest_image_bytes` y no
  crean un store paralelo.
- La asignación visual usa una galería modal compacta abierta desde el slide de
  destino: un click aplica y guarda la imagen directamente, sin el paso global
  ambiguo "seleccionar y después asignar". Sólo `cover`, `image_text` y
  `full_image` muestran controles de foto; los demás tipos eliminan cualquier
  `asset_id` residual. Preview y publicación sincronizan primero la versión actual
  del editor para no renderizar un borrador anterior sin la imagen recién elegida.
- El publicador Premium de Instagram espera `FINISHED` en cada contenedor hijo y en
  el contenedor padre antes de armar/publicar el carrusel. Los rechazos conservan
  código HTTP, código/subcódigo seguro de Meta y etapa (`child`, padre o publish) en
  `channel_results.failure_metadata`; la UI los muestra sin persistir el mensaje
  externo completo. Facebook exitoso nunca se reintenta durante esta recuperación.
- La biblioteca ya no expone `thumb_path` de filesystem: devuelve una URL relativa y
  `/api/media-library/thumb/{asset_id}` sirve únicamente JPEGs confinados al
  directorio de miniaturas. Assets purgados, IDs inválidos y paths fuera del
  directorio se rechazan.
- Validación al cierre: 354 casos descubiertos (baseline `4b8a1c7`: 336; neto
  agregado: 18). En este host se ejecutaron 350 y cuatro casos de render real
  Remotion quedaron agrupados bajo un `SkipTest` de clase porque el CLI no respondió;
  los 18 casos nuevos sí se ejecutaron y pasaron. Ver `docs/METRICS.md` para el
  desglose y los comandos exactos.
- Smoke visual E2E en `127.0.0.1:8766`, con directorios temporales,
  `PREMIUM_STATIC_RENDER_ENGINE=pillow` y `PREMIUM_PUBLISH_DRY_RUN=true`: importó
  tres slides, promovió dos uploads propios, sirvió sus miniaturas, guardó el
  borrador, renderizó tres previews y devolvió Instagram/Facebook `OK` de dry-run.
  La consola del navegador terminó sin errores y no hubo llamadas externas.
- Gates finales: 17/17 E2E local dry-run, `doctor core` y `doctor all` 8/8 con
  overrides `observe`/canales apagados sólo para QA, `compileall`, sintaxis JS y
  `git diff --check` OK. El `doctor` sin overrides conserva visible una contradicción
  preexistente del host (`observe` con Web habilitada); no se tocó `.env`.

Requiere review y merge explícitamente aprobados. No autoriza desactivar
`PREMIUM_PUBLISH_DRY_RUN` ni publicar en Meta.

## Capa editorial premium (rama `feature/premium-editorial-layer`, no mergeada)

Construida sobre `main` (`dd9b7fe`) en cinco fases, cada una con pruebas propias.
No se hizo merge, no se tocó `.env` productivo ni `data/` real, y no se ejecutó
ninguna publicación real (todos los clientes Meta se probaron con mocks/dry-run).

- **Fase 1 — Router editorial**: `utils/editorial_router.py` clasifica cada noticia
  en `automatic|candidate|suppressed` por canal. Sólo restringe Instagram, y sólo si
  `EDITORIAL_ROUTER_ENABLED=true` (default `false` — comportamiento actual sin
  cambios hasta activación explícita). Modo report-only:
  `python cli.py editorial-route --report-only`. Overrides manuales completos
  (corrección 2026-07-30): `demote_automatic_to_candidate` (automática pendiente →
  candidata), `add_published_to_candidates` (automática ya publicada → candidata
  premium sin alterar el historial), `update_candidate_status` candidate↔automatic/
  discarded — todas atómicas, con lock e idempotentes.
- **Fase 2 — Biblioteca multimedia**: `utils/media_library.py` agrega candidatas,
  publicadas (con evidencia real), premium y assets de imagen en una búsqueda local
  de diez días. `python cli.py media-library search/cleanup`.
- **Fase 3 — Estudio Premium**: contrato versionado (`utils/premium_contract.py`),
  importador de ChatGPT, orquestador social-only (`utils/premium_publisher.py`,
  nunca crea artículo web ni llama al CMS), carrusel nuevo en
  `meta/ig_client.py::post_premium_carousel_to_instagram`, media directa sin link
  nueva en `meta/fb_client.py::post_premium_direct_media_to_facebook`. Pestañas
  "Estudio Premium" y "Candidatas" en la UI manual (`video_reel_manager.py`).
- **Fase 4 — Sistema visual Remotion**: composiciones still `PremiumSlide`,
  `AutomaticInstagramCard`, `FacebookOgCard`; paleta de marca sin dorado; highlight
  terms compartido con Reels (`Main`, compatible hacia atrás). Política de motor
  **por workflow** (corrección 2026-07-30): `PREMIUM_STATIC_RENDER_ENGINE=remotion`
  por defecto (Estudio Premium, manual y bajo volumen);
  `AUTOMATIC_STATIC_RENDER_ENGINE=pillow` y `OG_STATIC_RENDER_ENGINE=pillow` por
  defecto (sin wiring real a Remotion todavía); `STATIC_RENDER_ENGINE` legacy sólo
  como override explícito. Benchmark real en `docs/METRICS.md` (Remotion es ~560x
  más lento que Pillow por re-bundling por slide — ver Known Issue #69).
- **Fase 5 — Validación**: **336/336 tests Python OK** (236 preexistentes en `main`
  + 100 nuevos: router 29, biblioteca 13, premium 14, meta premium 14, Remotion 30 —
  ver `docs/METRICS.md` para el detalle exacto de esta cuenta, incluida la
  reconciliación de una cifra incorrecta reportada en una síntesis previa de esta
  misma rama), 17/17 E2E dry-run OK, `compileall`/`pip check`/`doctor core` OK,
  `npx tsc --noEmit`/`npx eslint src` sin errores nuevos, `npx remotion bundle` OK,
  `git diff --check` OK, sin secretos en el diff. CI (`reliability-windows`) es
  Python-only: no instala Node, por lo que los 4 tests de render Remotion real se
  saltean ahí automáticamente (no es un fallo).

Requiere autorización explícita antes de: activar `EDITORIAL_ROUTER_ENABLED=true` en
producción, desactivar `PREMIUM_PUBLISH_DRY_RUN`, o mergear esta rama a `main`.

## Rama, revisión y release

- Repositorio: `NahimMora/news-auto-publisher-lavozriojana`.
- Rama desplegada: `reliability/baseline-2026-07-23`.
- Commit de código identificado por el heartbeat al iniciar el ciclo #8:
  `e6b0459d3944c6a2a702062c1a3af1afd981b484`.
- Commit desplegado y verificado por heartbeat:
  `ef91a675e64f908136ea2fc9ae30bb12df35a864`.
- PR borrador: [#1](https://github.com/NahimMora/news-auto-publisher-lavozriojana/pull/1).
- CI remoto conocido: `reliability-windows` verde en Actions run
  [`30308227631`](https://github.com/NahimMora/news-auto-publisher-lavozriojana/actions/runs/30308227631).
- Propuesta posterior al merge: `v1.0.0-reliability-baseline`.

El PR sigue en borrador. No se hizo merge ni se creó el tag. El proceso activo usa
el identificador `unreleased-reliability-baseline`; no se presenta como release
oficial.

## Validación local

Verificaciones ejecutadas en el host Windows con el venv del repositorio:

| Verificación | Resultado |
|---|---|
| Python | 3.10.0 |
| `pip check` | sin dependencias rotas |
| suite | 235 tests, OK, `.env` deshabilitado y directorios temporales |
| E2E local | 17/17, `production_calls=false` |
| `compileall` | OK |
| `git diff --check` | OK |
| `doctor supervisor` con perfil operativo | `success`, 8/8 |
| dry-run CI | `success`, `production_calls=false` |
| filesystem del host | `success`, 7/7, 34.065 MB libres |

`doctor core` sin overrides sigue fallando correctamente porque el `.env` histórico
tiene Web encendida mientras el modo por default es `observe`. El arranque productivo
no oculta esa contradicción: usa
[`scripts/start_24x7_production.ps1`](../scripts/start_24x7_production.ps1), que fija
un perfil explícito y exige que `doctor supervisor` pase antes de iniciar.

## Corte y estado de colas

El 2026-07-27 se aplicó `queue-cutover --from-date 2026-07-27 --apply` con el
supervisor detenido:

- Web: 60 entradas anteriores al corte archivadas.
- Meta: 425 entradas anteriores al corte archivadas.
- Social: 23 estados históricos pasaron a `expired` o dead-letter según su estado.
- Archivo durable: `data/queue_cutover_archive.json`, 485 payloads completos.
- Eventos y motivos: `data/queue_events.json`.
- Backups previos: `data/backups/`.

El operador reemplazó la distinción por fecha por una línea de base de orden durable.
Con backup previo y supervisor detenido se aplicó:

```text
queue-cutover --keep-latest 20 --apply
```

Resultado:

- Web: 33→20; 13 payloads de canal archivados.
- Meta: 37→20; 17 payloads de canal archivados.
- Social activa: 0.
- Identidades únicas activas: 20, presentes en ambos canales.
- Orden desconocido: 0.

Los elementos anteriores se registraron como
`operator_baseline_older_than_latest_window`; no se marcaron como publicaciones
externas sin ID/URL.

Snapshot al iniciar el ciclo #8:

- Web: 20 pendientes de la ventana más reciente.
- Meta: 20 entradas de las mismas identidades.
- Social activa: 0.
- Rewrite: 0 pending, 0 processing, 0 failed, 0 dead-letter.
- Backlog histórico de Facebook: 0 pendientes sin clasificar, 0 ambiguos.

No se borró ni sobrescribió el historial para “limpiar” las colas.
`ARTICLE_NOT_BEFORE_DATE` queda desactivado en el perfil operativo porque una noticia
válida puede no traer fecha.

## Integraciones reales

Preflight externo del 2026-07-27:

| Integración | Estado | Evidencia |
|---|---|---|
| Fuentes | `success` | 10/10 secciones vivas reconocidas |
| OpenAI | `success` | autenticación, modelo y respuesta controlada |
| R2 | `success` | create/head/read/delete bajo `healthchecks/`, cleanup confirmado |
| Facebook | `success` | identidad, permisos y capacidad de publicación |
| Instagram | `success` | cuenta, relación con página y permiso de publicación |
| Filesystem | `success` | lock, dos writers, replace, fsync, backup/restore y cuarentena |
| Supervisor | `success` | configuración, PID, heartbeat y logs escribibles |
| CMS read-only | `blocked` | falta `WEBAPP_PREFLIGHT_PATH` seguro |

El bloqueo del preflight CMS no se convirtió en éxito. La ruta de escritura quedó
verificada por tres publicaciones Web reales con ID/URL y HTTP público 200; la más
reciente fue:

`https://lavozriojana.com/noticias/alerta-amarilla-por-viento-zonda-en-la-rioja`

Facebook quedó verificado con publicaciones reales y consulta posterior read-only.
La última evidencia del primer ciclo es el ID
`1243054632214236_122109834009372360`.

Instagram tuvo un canary controlado, verificable e idempotente:

- ID: `18207194662361611`.
- Permalink verificado antes del cleanup.
- Cleanup confirmado; la consulta posterior devolvió objeto inexistente.

Durante el primer ciclo 24/7, Instagram deduplicó de forma segura la nota seleccionada
contra su historial y no creó una copia.

El ciclo #5 publicó Web y Facebook, pero Instagram recibió `request_rejected` para una
nota de abigeato. La entrada quedó en dead-letter y no se reintentó automáticamente.
El proveedor no dejó código/subcódigo en el evento histórico, por lo que la causa
externa exacta quedó desconocida. El ciclo #6 publicó correctamente en las tres
integraciones; Instagram devolvió ID `18177266845418088`. Desde el ajuste
`LVR-069`, los rechazos futuros conservan HTTP/código/subcódigo/tipo sanitizados en el
journal y en el log rotativo.

El gate local también se validó desde Windows PowerShell 5.1. `LVR-070` permite que
el verificador lea el BOM que esa consola agrega con `Out-File -Encoding utf8`, sin
relajar ninguna comprobación del contenido.

El ciclo #7 terminó `degraded` porque Web rechazó una nota de `policiales` tras seis
intentos editoriales y bloqueó el fallback mediante `strict_category_policiales`.
No hubo publicación externa ni falso éxito: el elemento pasó a dead-letter con título,
motivo y política; Facebook e Instagram reportaron `no_work` porque no apareció una
URL Web nueva. Es el comportamiento conservador configurado para una categoría
sensible, no una caída de CMS/Meta.

## Estado operativo

- Supervisor: activo, PID registrado `52088` al iniciar el ciclo #8.
- Modo: `all`.
- Canales solicitados/habilitados: Web, Facebook e Instagram.
- Límite efectivo: Web sin límite; Facebook 8 e Instagram 8 por ciclo.
- Intervalo: 3.600 segundos.
- Heartbeat: fresco y persistente.
- Último ciclo: #11 `success`, 4/4 etapas aceptables.
- Ciclo #11: scraping/reescritura `no_work`, Web `no_work`, Facebook `success` 8/8 e
  Instagram `no_work`.
- Ciclo #10: Web `success` 6/6, Instagram `success` 1/1 y Facebook `degraded` 5/8
  porque tres páginas todavía no devolvían HTTP válido durante el prewarm. No se
  llamó a Graph para esas tres; permanecieron en cola.
- Ciclo #8: Web `degraded` 24/26, siete publicaciones degradadas, dos terminales
  sensibles y cola final 0; Facebook e Instagram `success` 8/8.
- El feedback produjo revisiones materiales y el sexto resultado seguro se publicó
  como `degraded`. Los falsos positivos observados con comienzos de oración y
  equivalencias número-palabra quedaron corregidos en `LVR-075`/`LVR-076`.
- Ciclo #7 Web: `failed` 0/1 por `strict_category_policiales`, terminal trazable y
  sin publicación; Facebook/Instagram `no_work`.
- Ciclo #5: `degraded`, 3/4; rechazo Instagram aislado y no reintentado.
- Alertas: detección y outbox durable habilitados; webhook externo no configurado.
- UI manual: `http://127.0.0.1:8765/`, HTTP 200, sólo loopback.
- Watchdog: tareas `LaVozRiojana-24x7` y `LaVozRiojana-ManualUI` cada cinco minutos;
  ambas devolvieron resultado `0` y no duplicaron procesos.

El arranque se hizo por autorización explícita del operador. No equivale a aprobación
del PR, merge, tag ni declaración de release listo para producción.

## Gates

| Gate | Estado | Evidencia o bloqueo |
|---|---|---|
| A Código | parcial | suite/compile/E2E verdes; falta CI del commit final, review y merge |
| B Entorno | completo para este host | backup, restore temporal, filesystem y heartbeat |
| C Read-only | parcial | todo verde salvo endpoint CMS seguro |
| D Canary | parcial | Instagram completo; Web/FB se validaron con publicaciones reales autorizadas |
| E Observe | ejecutado | ciclos previos sanos, sin publicación |
| F Web | ejecutado | publicaciones verificables y rechazo editorial seguro en ciclo #7 |
| G Facebook | ejecutado | backlog conciliado, token/página y publicaciones verificadas |
| H Instagram | ejecutado con incidente aislado | preflight/canary y ciclo #6 reales; un rechazo previo quedó en dead-letter |
| I Release 24/7 | bloqueado | PR no aprobado/mergeado, tag ausente y CMS read-only bloqueado |

Por estos bloqueos el repositorio no se declara “release listo para 24/7”, aunque el
servicio solicitado por el operador está activo con límites y watchdog.

## Riesgo residual y próximo paso

- El CMS no expone un preflight GET autenticado con versión/capacidades.
- No hay webhook aprobado; las alertas quedan en outbox local.
- Las tareas programadas deben volver a verificarse después de un reinicio real del
  host.
- Las tareas usan la sesión interactiva de `pc10`; no cubren el intervalo anterior al
  inicio de sesión de Windows.
- El commit activo tiene cambios de trabajo todavía no integrados en `main`.
- La causa exacta del rechazo Instagram del ciclo #5 no puede reconstruirse porque
  ocurrió antes de persistir metadatos sanitizados; no se reprodujo en el ciclo #6.
- El backlog Web creció 24→26→29→33 bajo el límite anterior. Con Web ilimitada quedó
  en cero y se mantuvo en cero al finalizar el ciclo #11.
- Facebook conserva 3 pendientes e Instagram 0. El ciclo #11 confirmó recuperación
  posterior al prewarm transitorio de ciclo #10; no hubo pérdida ni reintento ciego.
- El contenido y selectores de terceros pueden cambiar sin aviso.

Próximo gate: obtener review/aprobación, agregar un endpoint CMS read-only y ensayar
reboot/rollback antes de mergear o crear el tag oficial.
