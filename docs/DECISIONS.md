# DECISIONS.md

Registro de decisiones importantes del proyecto. Formato por entrada:

```
### YYYY-MM-DD — Título corto de la decisión

**Decisión**: qué se decidió.
**Motivo**: por qué.
**Alternativas rechazadas**: qué otras opciones se consideraron y por qué no se
eligieron.
**Consecuencias**: qué implica esta decisión (positivo y negativo).
**Revisar nuevamente cuando**: condición o fecha que debería disparar una revisión.
```

Agregar una entrada nueva por decisión relevante (arquitectura, proveedor externo,
cambio de proceso editorial, etc.), no por cada commit.

---

### 2026-07-20 — Repositorio git dedicado para AutoPublicador_LaVozRiojana

**Decisión**: crear un repositorio git propio para esta carpeta
(`AutoPublicadores/AutoPublicador_LaVozRiojana`) con remote en GitHub
(`news-auto-publisher-lavozriojana`), en lugar de seguir usando el repo git existente a
nivel `C:\Users\pc10\Desktop`.

**Motivo**: el repo de Desktop tenía su raíz en una carpeta compartida con decenas de
proyectos y archivos personales no relacionados (PDFs personales, otros repos,
accesos directos), y su `.git` dentro de esta carpeta estaba corrupto/incompleto (sin
`HEAD` ni `objects`). Publicar el histórico completo de Desktop a GitHub habría
expuesto contenido sensible sin relación con este proyecto.

**Alternativas rechazadas**:
- Usar el repo de Desktop existente agregando solo estos archivos al commit: descartado
  porque los remotes configurados ahí (`duo-news-app`, `migration-wix-to-wordpress`) no
  corresponden a este proyecto, y el riesgo de arrastrar accidentalmente archivos no
  relacionados en commits futuros era alto.

**Consecuencias**: este proyecto ahora tiene control de versiones real y aislado;
requiere que futuras tareas de git se ejecuten dentro de esta carpeta específicamente
(no asumir que el repo "padre" de Desktop aplica acá).

**Revisar nuevamente cuando**: si se decide consolidar todos los proyectos del
operador en un monorepo, o si se detecta que sigue habiendo cruce accidental entre
repos.

---

### Decisiones de arquitectura inferidas del código existente (sin fecha ni motivo confirmado)

> Estas no son decisiones registradas formalmente — se infieren de la implementación
> actual. Se listan acá como punto de partida; conviene confirmarlas con quien las tomó
> y completar fecha/motivo/alternativas reales, o descartarlas si ya no aplican.

- **Persistencia en archivos JSON planos en vez de una base de datos**: todo el estado
  (colas, historial, dedup) vive en `data/*.json`. Simplifica el deploy (sin servidor de
  DB) a costa de integridad transaccional y backups automáticos. Revisar si el volumen
  de datos empieza a generar problemas de performance o corrupción.
- **Cloudflare R2 como storage de imágenes en vez de servir imágenes desde disco
  local**: necesario porque Instagram/Facebook requieren URLs públicas para las
  imágenes al publicar vía Graph API.
- **Un mismo app de Meta para Facebook e Instagram** (`FB_APP_ID`/`FB_APP_SECRET` =
  `IG_APP_ID`/`IG_APP_SECRET`): simplifica la gestión de credenciales; implica que un
  problema con la app de Meta afecta ambas plataformas a la vez.
- **Instagram restringido a categorías `interior, sociedad, politica` + breaking**
  (`IG_ALLOWED_CATEGORIES`), a diferencia de Facebook que aparentemente publica más
  categorías: sugiere una decisión editorial de mantener el feed de Instagram más
  curado. Confirmar el criterio real.

---

### 2026-07-23 — Mantener JSON y endurecer su integridad

**Decisión**: mantener los contratos JSON existentes e incorporar locks interproceso,
escritura atómica, cuarentena, backups y operaciones read-modify-write protegidas.

**Motivo**: las pruebas reprodujeron pérdida concurrente y corrupción silenciosa, pero
también demostraron que el almacenamiento por archivos puede cumplir la línea de base
sin una migración de infraestructura.

**Alternativas rechazadas**: migrar inmediatamente a SQLite o servicios de colas. No
había evidencia de volumen o rendimiento que justificara el cambio y habría aumentado
el riesgo de compatibilidad con datos productivos.

**Consecuencias**: se conserva el deploy simple y los nombres existentes. Todo
consumidor debe usar `file_manager`; el filesystem debe soportar locks y reemplazo
atómico.

**Revisar nuevamente cuando**: las pruebas de volumen, latencia o filesystem muestren
que estas garantías no alcanzan.

### 2026-07-23 — Resultado funcional estructurado

**Decisión**: todas las etapas supervisadas usan `success`, `no_work`, `degraded` o
`failed`, con contadores y códigos de salida 0/0/2/1.

**Motivo**: un exit 0 del proceso y textos como “publicadas” producían falsos
positivos aun para 0/N o credenciales inválidas.

**Alternativas rechazadas**: seguir parseando stdout o convertir todos los fallos en
warnings.

**Consecuencias**: los scripts hijos deben emitir `LVR_STAGE_RESULT`; salir 0 sin
contrato se considera fallo de integración.

**Revisar nuevamente cuando**: se incorpore un protocolo de observabilidad externo que
preserve la misma semántica.

### 2026-07-23 — Cola durable para reescritura y cuarentena social ambigua

**Decisión**: la reescritura transfiere staging a una cola durable antes de vaciarlo.
En redes, un claim interrumpido después de una llamada externa pasa a dead-letter para
conciliación y no se reintenta automáticamente.

**Motivo**: la primera medida evita pérdida; la segunda evita duplicar una publicación
que pudo haber sido aceptada sin que el cliente recibiera el ID.

**Alternativas rechazadas**: vaciar staging antes de procesar; reintentar a ciegas toda
entrada `processing`.

**Consecuencias**: existe recuperación automática cuando el outcome es localmente
conocido y recuperación manual cuando es externamente ambiguo.

**Revisar nuevamente cuando**: CMS/Meta ofrezcan una clave de idempotencia o consulta
confiable por clave propia.

### 2026-07-23 — Política explícita de fallbacks

**Decisión**: configurar `block`, `allow_non_sensitive` o `allow_all`; por defecto se
permite fallback sólo en contenido no sensible. Policiales, judiciales, menores y
breaking requieren resultado enriquecido sin fallback.

**Motivo**: conservar continuidad sin publicar silenciosamente contenido degradado de
alto riesgo.

**Alternativas rechazadas**: fallback implícito siempre permitido; aprobación humana
obligatoria, porque no existe una decisión editorial que la autorice.

**Consecuencias**: todo fallback se marca y registra; un fallback bloqueado termina en
dead-letter.

**Revisar nuevamente cuando**: el equipo editorial cambie explícitamente la política.

### 2026-07-23 — Dry-run exclusivamente local y UI manual sólo loopback

**Decisión**: `cli.py run-once --dry-run` ejecuta el E2E simulado y nunca el pipeline
real. La UI manual rechaza binds externos y entradas de URL/path no seguras.

**Motivo**: un dry-run no debe devolver éxito ficticio ni tocar cuentas, colas o
archivos reales.

**Alternativas rechazadas**: simular éxito dentro de los publicadores reales; exponer
la UI sin autenticación.

**Consecuencias**: para una prueba externa se necesita un entorno explícito y
credenciales de prueba. El acceso remoto a la UI no está soportado.

**Revisar nuevamente cuando**: se diseñe autenticación y despliegue seguro de esa
interfaz.

### 2026-07-26 — CI Windows-first sin despliegue automático

**Decisión**: ejecutar instalación, `pip check`, suite con deprecaciones como error,
`compileall`, `doctor core`, E2E dry-run y `git diff --check` en `windows-latest`.

**Motivo**: el host y los contratos de proceso son Windows-first.

**Alternativas rechazadas**: CI sólo Linux; usar secretos productivos; desplegar desde
el workflow.

**Consecuencias**: el mismo conjunto de comandos se reproduce localmente. La
protección de `main` debe exigir el check después de publicar el workflow.

### 2026-07-26 — Preflight externo no destructivo

**Decisión**: fuentes, OpenAI, CMS y Meta se verifican sin publicar. R2 usa únicamente
un objeto UUID bajo `healthchecks/` y exige cleanup confirmado.

**Motivo**: un mock no verifica autenticación, permisos, cuota, DNS ni HTML vivo.

**Alternativas rechazadas**: crear una noticia CMS en el preflight general; simular
salud cuando falta endpoint o credencial.

**Consecuencias**: lo no verificable es `blocked` con exit 3. Un cleanup R2 incierto
no puede ser `success`.

### 2026-07-26 — Canary explícito y outcomes ambiguos

**Decisión**: el canary requiere `CANARY_ENABLED=true` y confirmación por argumento,
queda fuera de colas y reserva idempotencia antes de llamar al tercero.

**Motivo**: validar escritura real con máximo impacto de una publicación por canal.

**Alternativas rechazadas**: consumir la cola general; reintentar timeouts a ciegas;
usar contenido sensible o breaking.

**Consecuencias**: una respuesta ambigua queda registrada y requiere conciliación.
El cleanup puede ser manual si no existe endpoint seguro.

### 2026-07-26 — Alertas por outbox y adaptador opcional

**Decisión**: separar detección, dedupe, persistencia y entrega. La fuente durable es
`alert_outbox.json`; el webhook es opcional y está apagado por defecto.

**Motivo**: la falta o caída del proveedor de avisos no debe bloquear el pipeline.

**Alternativas rechazadas**: dashboard nuevo; acoplar detección a un proveedor; enviar
secretos o URLs internas.

**Consecuencias**: un watchdog externo sigue siendo necesario para detectar la muerte
del proceso completo.

### 2026-07-26 — Arranque progresivo y kill switches autoritativos

**Decisión**: iniciar en `observe` y avanzar manualmente por `web_only`, un modo social
parcial y `all`. El modo nunca sobrepasa los switches de web, Facebook o Instagram.

**Motivo**: reducir radio de impacto y evitar que la presencia de una credencial
habilite publicaciones.

**Alternativas rechazadas**: encender todos los canales al iniciar; escalar modos
automáticamente; aumentar límites en el primer despliegue.

**Consecuencias**: las contradicciones fallan en `doctor`; el límite inicial es una
publicación por canal y ciclo.

### 2026-07-26 — Conciliación conservadora de Facebook

**Decisión**: reportar por identidad estable y evidencia; aplicar sólo decisiones
ligadas al `report_id` actual.

**Motivo**: el backlog histórico puede contener publicaciones realizadas, expiradas o
sin URL web y no debe reencolarse en masa.

**Alternativas rechazadas**: similitud de título como evidencia; vaciar la cola;
reintentar ambiguos; marcar publicado sin ID.

**Consecuencias**: los elementos no decididos permanecen intactos y trazables.

### 2026-07-26 — Condición para declarar 24/7

**Decisión**: no declarar 24/7 hasta completar gates A–I, merge aprobado, tag posterior
al merge y evidencia externa por canal.

**Motivo**: código verde y contratos mockeados no prueban el host ni los terceros.

**Consecuencias**: el tag propuesto `v1.0.0-reliability-baseline` no se crea durante
esta preparación; cualquier integración `blocked` impide habilitar su canal.

### 2026-07-26 — yt-dlp como única herramienta de descarga de video fuente

**Decisión**: usar `yt-dlp` (declarado en `requirements.txt`) como único mecanismo de
descarga de video fuente para el pipeline manual de reels, para Instagram, YouTube,
TikTok, X/Twitter, Facebook, Vimeo y cualquier otro sitio soportado por su extractor
genérico, en vez de agregar herramientas específicas por plataforma.

**Motivo**: investigación de esta sesión (julio 2026) confirmó que yt-dlp es la
herramienta open-source más activamente mantenida del ecosistema (releases casi
semanales, reacciona en horas/días cuando una plataforma rompe su reproductor) y ya
cubre las 4 redes pedidas con una sola herramienta. Se verificó en vivo contra un link
real de Instagram (`instagram.com/p/Daj2ZQFsRik/`) sin necesidad de cookies.

**Alternativas rechazadas**: `instaloader`/`gallery-dl` específicos de Instagram — sólo
aportarían valor para scraping masivo de perfiles/hashtags, fuera de alcance (acá se
ingesta un link individual por vez, pegado manualmente por un operador).

**Consecuencias**: sigue siendo scraping no oficial de cada plataforma (ninguna ofrece
API oficial para descargar contenido de terceros), sujeto a romperse sin aviso cuando
una plataforma cambia su reproductor; requiere `pip install -U yt-dlp` periódico. Se
agregó `error_type` estructurado (`OperationResult`) para distinguir "necesita
actualizarse" de "necesita cookies" de "error transitorio de red", en vez de un
fallback silencioso a imagen.

**Revisar nuevamente cuando**: yt-dlp deje de recibir mantenimiento activo, o el
volumen de uso justifique tercerizar en un proveedor SaaS (Apify, ScrapeCreators)
para no mantener la actualización del extractor in-house.

### 2026-07-26 — Riesgo legal aceptado: sin gate de derechos sobre video de terceros

**Decisión**: el pipeline sigue descargando y re-marcando con el layout LVR cualquier
video fuente (propio o de terceros) sin exigir que el operador confirme titularidad o
licencia antes de procesarlo. No se agrega ningún gate ni validación de derechos.

**Motivo**: decisión explícita del operador del sistema (2026-07-26), priorizando
simplicidad operativa sobre la mitigación de riesgo legal identificada en la
investigación de esta sesión.

**Alternativas rechazadas**: exigir marcar "contenido propio"/"con permiso" antes de
descargar contenido ajeno, usando embed oficial (oEmbed) con atribución como default
para todo lo no confirmado — es el estándar de la industria y la opción de menor
riesgo, pero el operador prefirió no agregar esa fricción por ahora.

**Consecuencias**: descargar y re-publicar contenido de terceros sin permiso expone a
riesgo real de reclamo por infracción de copyright — hay casos recientes (enero 2025)
de medios de noticias demandados específicamente por esto. El riesgo queda aceptado
conscientemente, no por desconocimiento.

**Revisar nuevamente cuando**: se reciba un reclamo real, o el volumen/perfil público
del medio aumente el riesgo percibido lo suficiente como para justificar el gate.

### 2026-07-27 — Corte durable por fecha, sin vaciar colas

**Decisión**: archivar todos los payloads anteriores al 27/07/2026 y conservar
eventos, estados terminales y backups; bloquear nuevas ingestas anteriores mediante
`ARTICLE_NOT_BEFORE_DATE`.

**Motivo**: el operador solicitó publicar sólo noticias de hoy en adelante y el
backlog histórico tenía riesgo de publicación tardía o duplicada.

**Alternativas rechazadas**: vaciar JSON; editar estados manualmente; marcar todo como
publicado; eliminar el historial.

**Consecuencias**: `queue_cutover_archive.json` pasa a ser evidencia durable y debe
entrar en la política de backup/retención.

### 2026-07-27 — Arranque autorizado con perfil externo al `.env`

**Decisión**: no modificar ni imprimir el `.env` histórico. El arranque usa
`scripts/start_24x7_production.ps1`, fija el modo y los kill switches explícitamente,
mantiene canary apagado y exige `doctor supervisor` verde.

**Motivo**: el `.env` conserva Web activa pero no declara un deployment mode; el
default seguro `observe` detecta correctamente esa contradicción.

**Alternativas rechazadas**: relajar `doctor`; convertir contradicciones en warnings;
sobrescribir secretos/configuración histórica.

**Consecuencias**: el script es la fuente operativa del perfil de este host. El
heartbeat registra fingerprint, fecha, operador y backup sin secretos.

### 2026-07-27 — Watchdog local idempotente

**Decisión**: Task Scheduler ejecuta cada cinco minutos los scripts de supervisor y
UI manual. La UI sólo acepta loopback y rechaza un servicio desconocido en el puerto.

**Motivo**: un proceso detached no cubre crashes ni cierres accidentales.

**Alternativas rechazadas**: plataforma de monitoreo nueva; exponer la UI; iniciar
instancias sin comprobar PID/puerto.

**Consecuencias**: la recuperación esperada es menor a cinco minutos mientras el host
y Task Scheduler estén activos. Sigue pendiente un watchdog externo y un reboot real.

### 2026-07-27 — Bloqueo CMS read-only no se falsea

**Decisión**: conservar `preflight_cms=blocked` mientras no exista un endpoint GET
autenticado con versión/capacidades.

**Motivo**: una publicación real valida escritura, pero no reemplaza un chequeo seguro
para cada arranque.

**Consecuencias**: el servicio fue activado por autorización explícita. El límite
inicial de uno por ciclo fue reemplazado luego por la decisión documentada “Web sin
cupo y Meta con ocho por ciclo”; no se declara release 24/7 listo ni se crea el tag.

### 2026-07-27 — Línea de base por orden durable, no por fecha editorial

**Decisión**: conservar las 20 noticias únicas más recientes según los timestamps
durables de Web/Meta. Archivar el resto con payload y evento; no marcarlo como
publicado sin evidencia externa.

**Motivo**: algunas fuentes omiten o degradan la fecha editorial. El timestamp de cola
se genera dentro del sistema, permite un orden reproducible y no depende del HTML.

**Consecuencias**: `ARTICLE_NOT_BEFORE_DATE` queda apagado en el perfil operativo. Un
item sin timestamp durable bloquea el corte completo. La selección inicial dejó
20/20 en Web y 20/20 en Meta.

### 2026-07-27 — Sexto intento editorial seguro y medible

**Decisión**: cada revisión recibe el intento anterior y todos los warnings. Si el
sexto intento sólo conserva problemas de calidad/similitud, se publica el último
resultado como `degraded`; warnings factuales, judiciales o HTML continúan bloqueando.

**Motivo**: el flujo anterior descartaba mejoras reales y volvía al texto original.
Además, feedback genérico sin el intento previo podía repetir la misma respuesta.

**Consecuencias**: queda `revision_history`, se detecta `revision_no_material_change`
y cambiar sólo el score no cuenta. La política editorial sensible no se relaja ante
datos inventados o afirmaciones inseguras.

### 2026-07-27 — Mensaje y preview verificable de Facebook

**Decisión**: Facebook usa título + caption exacto de Instagram + URL Web. Antes de
Graph, un prewarm SSRF-safe debe validar la página y descargar su `og:image`.

**Motivo**: pasar sólo el campo `link` no demuestra que Meta encontrará una imagen
pública en ese momento.

**Consecuencias**: un preview no verificable difiere la publicación sin outcome
ambiguo. El mismo constructor de caption evita divergencias entre plataformas.

### 2026-07-27 — Web sin cupo y Meta con ocho por ciclo

**Decisión**: el supervisor inyecta Web ilimitada y 8 publicaciones por ciclo para
Facebook y 8 para Instagram.

**Motivo**: el CMS administrado por el operador no aplica rate limit y el cupo anterior
de uno generó crecimiento comprobado de backlog. Meta conserva un límite explícito.

**Consecuencias**: los kill switches y backoffs continúan siendo autoritativos. Un
rate limit corta y conserva el resto pendiente; el límite no implica éxito forzado.

### 2026-07-30 — Router editorial premium: automatic/candidate/suppressed (Fase 1)

**Decisión**: incorporar `utils/editorial_router.py`, un router determinístico y sin
llamadas nuevas a IA que clasifica cada noticia reescrita en `automatic`, `candidate`
o `suppressed` por canal (`route_by_channel.web/facebook/instagram`). Sólo restringe
la selección automática de Instagram, y sólo cuando `EDITORIAL_ROUTER_ENABLED=true`
(por defecto `false`); Web y Facebook conservan exactamente su comportamiento actual.
El cómputo y la persistencia de metadata de ruteo (`data/topic_publication_state.json`,
`data/editorial_candidates.json`, `data/editorial_routing_events.json`) corren siempre
dentro de `openIA/rewrite_news.py::rewrite_noticia`, de forma aditiva, para que la
biblioteca de la Fase 2 tenga datos reales desde el primer día aunque el gate de
Instagram siga apagado.

Regla de tema: dentro de una ventana móvil de 12 horas por `topic_key`, la primera y
segunda publicación de Instagram son automáticas; la tercera y siguientes son
candidatas, salvo `breaking` (reutiliza `utils.editorial_priority.item_is_breaking`,
ya usado para "Último Momento") o `material_update` (detectado por palabras clave
determinísticas, y sólo relevante si ya hubo una publicación previa del tema). Antes
de aplicar esa regla, existe un gate independiente: una noticia sin vínculo riojano
comprobado (`hashtag_localidad`, categoría `interior`, o coincidencia con una lista
fija de localidades/"La Rioja") va directo a candidata para Instagram, incluso como
primera publicación del tema — este gate **no** tiene excepción por `breaking`, a
diferencia del cap de 12h, siguiendo el texto literal de la especificación aprobada.

**Motivo**: separar auditablemente "publicación automática" de "oportunidad editorial
premium" sin costo de IA adicional ni riesgo de alucinar un vínculo riojano
inexistente. La reutilización de `item_is_breaking` para el `breaking` del router es
intencional (consistencia con la cola social existente), aunque su lista de keywords
es amplia — en la práctica, buena parte de policiales/interior/sociedad ya califica
como "Último Momento" y por lo tanto puede superar el cap del tema; se acepta como
comportamiento conocido, no como bug.

**Alternativas rechazadas**: embeddings o clustering externo para `topic_key`
(prohibido explícitamente: costo y latencia); una segunda llamada a OpenAI para
detectar vínculo riojano o actualización material (prohibido: costo, y riesgo de
alucinación); aplicar el mismo gate a Web/Facebook en esta fase (no hay evidencia de
una política más restrictiva ya vigente ahí, y la instrucción explícita es limitar el
cambio a Instagram).

**Consecuencias**: el `topic_key` es un fingerprint determinístico (entidades
capitalizadas que no son inicio de oración + localidad + categoría + fecha) con una
limitación conocida: dos títulos sobre el mismo hecho que no comparten ninguna entidad
capitalizada pueden recibir `topic_key` distintos y no agruparse (ver
`docs/KNOWN_ISSUES.md`). Un fallo del router durante la reescritura nunca reintenta la
llamada a OpenAI (se captura y loguea; la noticia sigue su curso sin metadata de
ruteo, y `meta/run_ig.py` trata la ausencia de metadata como `automatic` para no
bloquear nada por accidente).

**Revisar nuevamente cuando**: se mida en producción cuánto backlog genera candidatas
de Instagram, o el equipo editorial pida ajustar el umbral de dos publicaciones/12h.

### 2026-07-30 — Override manual completo: automatic↔candidate, incluida la publicada

**Decisión**: completar las cuatro transiciones manuales de `docs/PRODUCT.md` (rule
16) en `utils/editorial_router.py`:

- `demote_automatic_to_candidate(identity, reason, operator)` — caso A: una noticia
  automática **todavía no publicada** en Instagram se saca de la selección
  automática (se excluye de `noticias_sociales_pendientes.json` con
  `instagram_state="excluded"`, se actualiza `route_by_channel.instagram="candidate"`
  en `noticias_meta.json`) y se conserva en `data/editorial_candidates.json` con
  `origin="operator_demotion"`. Se niega si ya hay evidencia de publicación
  (usar el caso B) o si hay un claim en curso (`instagram_state="processing"`).
- `add_published_to_candidates(identity, reason, operator)` — caso B: una noticia
  **ya publicada** se agrega a candidatas (`origin="published_reuse"`) para
  reutilizarla en un carrusel premium, sin tocar `ig_posted.json` ni
  `route_by_channel` — el histórico de publicación queda exactamente igual.
- `update_candidate_status(candidate_id, "automatic"|"candidate"|"discarded", ...)` —
  caso C: candidate↔automatic (sincroniza `route_by_channel.instagram` en la noticia
  real si todavía no fue publicada) y candidate↔discarded. Renombrado desde
  `"promoted"` a `"automatic"` para ser simétrico con `route_by_channel`.

Todas las mutaciones usan `update_json`/`update_json_files` (atómicas, con lock) y
son idempotentes: repetir la misma llamada no duplica candidata ni evento, y
devuelve `changed: False`. Cada transición registra un evento en
`data/editorial_routing_events.json` con `previous_route`, `new_route`,
`changed_at_ts`, `changed_by` y `reason` explícitos.

**Motivo**: era un criterio obligatorio de la Fase 1 (rule 16) que había quedado
parcialmente implementado (sólo candidate↔"promoted"/discarded, sin tocar la
noticia real ni cubrir el caso de una noticia ya automática/publicada).

**Alternativas rechazadas**: inferir "ya publicada" desde `route_by_channel` en vez
de evidencia externa real (`ig_posted.json`/`instagram_state=="completed"`) —
`route_by_channel` es una decisión de ruteo, no evidencia de publicación, y usarla
como tal podría demover silenciosamente algo que ya se publicó.

**Consecuencias**: `meta/run_ig.py` ve el nuevo `route_by_channel.instagram` en el
siguiente ciclo de bootstrap (lee `noticias_meta.json` de nuevo cada vez). Una
noticia demovida mientras ya estaba en `noticias_sociales_pendientes.json` con
`instagram_state="pending"` queda `excluded` inmediatamente — no espera al próximo
bootstrap para dejar de ser seleccionable.

**Revisar nuevamente cuando**: se agregue una UI de búsqueda/browse de noticias
automáticas (hoy el operador debe conocer la `identity` — `meta_queue_key`/
`dedup_key`/`canonical_url` — para operar sobre una noticia puntual desde la pestaña
Candidatas; no hay todavía una lista navegable de "automáticas" en la UI).

### 2026-07-30 — Biblioteca multimedia de diez días como agregación, no como copia (Fase 2)

**Decisión**: `utils/media_library.py` no duplica el estado existente. Combina en
memoria, en cada búsqueda: candidatas (`utils.editorial_router.list_candidates`),
noticias de `noticias_meta.json` con evidencia real de publicación (cruzando
`ig_posted.json`/`fb_posted.json`/`noticias_web_publicadas.json` por `dedup_key`),
publicaciones premium existentes (`utils.manual_post_queue`) y un registro propio de
assets de imagen (`data/media_library.json` + `output/media_library/{masters,thumbs}/`)
para contenido subido manualmente o reutilizado. Los assets se deduplican por hash
SHA-256 del contenido (nunca por nombre de archivo).

**Motivo**: evitar una segunda fuente de verdad para noticias/publicaciones que ya
existen en otros JSON; el único estado nuevo es el de imágenes optimizadas, que no
tenía dónde vivir.

**Alternativas rechazadas**: copiar cada noticia a `media_library.json` al momento de
rutear (duplicaría datos y crearía desincronización); usar una base de datos para la
búsqueda (sin evidencia de que JSON + filtrado en memoria sea insuficiente a este
volumen).

**Consecuencias**: la ventana visual de diez días se aplica sobre `created_at_ts` de
cada fila agregada (fecha editorial o `queued_at`/`routed_at_ts` según el origen), no
sobre un timestamp único. El cleanup de assets (`cleanup_expired_assets`) nunca borra
la entrada de metadata completa — sólo los archivos físicos (`files_purged=true`) — y
se niega a correr si el llamador indica una publicación activa (`active_publication=True`,
a cablear desde el orquestador de la Fase 3). Un asset referenciado por un borrador
sobrevive más allá de los diez días.

**Revisar nuevamente cuando**: el volumen de `noticias_meta.json` o `media_library.json`
haga que la agregación en memoria sea lenta en cada búsqueda.

### 2026-07-30 — Estudio de publicaciones premium: social-only y de flujo propio (Fase 3)

**Decisión**: las publicaciones premium (`utils/premium_contract.py`,
`utils/premium_post_queue.py`, `utils/premium_publisher.py`) nunca crean artículo web,
nunca llaman al publisher del CMS y nunca dependen de una publicación web exitosa.
Instagram siempre publica como carrusel (2-10 slides, contenedores hijos con
`is_carousel_item=true` + contenedor padre `media_type=CAROUSEL`, función nueva
`post_premium_carousel_to_instagram` en `meta/ig_client.py` — no se reutiliza el
camino de imagen individual existente). Facebook usa un camino directo nuevo
(`post_premium_direct_media_to_facebook` en `meta/fb_client.py`): una foto vía
`/{page}/photos` o varias fotos subidas como `published=false` seguidas de un único
post en `/{page}/feed` con `attached_media`, sin `link` en ningún caso. Ese camino se
activa únicamente si el paquete declara explícitamente
`{"publish_mode": "direct_media", "workflow": "manual_premium"}` — nunca se infiere
por ausencia de URL.

**Motivo**: mantener Reels, publicaciones premium y el lote automático como flujos
internos separados, sin tocar el contrato ni el comportamiento de las publicaciones
automáticas existentes (que sí requieren `web_url` y sí agregan link).

**Alternativas rechazadas**: reutilizar `post_to_instagram_detailed`/
`post_to_facebook_detailed` agregando parámetros condicionales (aumentaba el riesgo de
que un bug en premium afectara el flujo automático real); inferir `direct_media` por
ausencia de `web_url` (contradice la instrucción explícita del producto — un bug de
scraping que dejara `web_url` vacío habría activado sin querer el camino sin link).

**Consecuencias**: dedup y estado de publicación quedan en registros propios
(`data/premium_ig_posted.json`, `data/premium_fb_posted.json`, `data/premium_packages.json`),
pero el **backoff de rate limit se comparte** con el flujo automático
(`ig_rate_limit.json`, y el `page_backoff` dentro de `fb_posted.json`) porque es la
misma cuenta/página real de Meta — nunca se inventa un backoff independiente que
permita saltarse un bloqueo real del proveedor. Un canal exitoso y otro fallido deja
el paquete `degraded`, conserva el ID del canal exitoso y sólo permite reintentar el
canal fallido (`retry_channel`); un resultado ambiguo (`network_error` con outcome
desconocido) queda marcado `requires_reconciliation` y no se reintenta sin
confirmación explícita (`force=True`). Los slides tipo `video` están en el esquema
para el futuro pero `publish_package` los bloquea en esta versión (sólo carruseles de
imágenes). El renderer (`utils/premium_renderer.py`) es Pillow interino; la Fase 4 lo
reemplaza con Remotion sin cambiar su firma pública, así que preview y publicación
siguen usando exactamente la misma función.

**Revisar nuevamente cuando**: se implemente el tipo de slide `video` end-to-end, o el
volumen de publicaciones premium justifique separar también el backoff del automático.

### 2026-07-30 — Remotion como sistema visual compartido, Pillow como fallback (Fase 4)

**Decisión**: agregar tres composiciones still de Remotion (`PremiumSlide`,
`AutomaticInstagramCard`, `FacebookOgCard`) y centralizar la paleta de marca en
`remotion/src/constants.ts` (`ROJO`, `BORDO`, `AZUL`, `NEGRO`, `WHITE` — **sin
dorado**; se reemplazó `GOLD` por `AZUL` en el handle `@lavozriojana` de `Main.tsx`,
el único uso real de dorado como color de marca encontrado). `utils/premium_renderer
.py::render_package_with_engine` es el único punto de entrada real para
preview/publicación: respeta `STATIC_RENDER_ENGINE` (`auto` intenta Remotion y cae a
Pillow; `remotion` exige Remotion y reporta fallo si no está disponible; `pillow`
fuerza el motor anterior sin cambios). `layout/image_generator.py` y
`utils/premium_renderer.py`'s funciones Pillow originales (`render_slide`,
`render_package`, `render_package_bytes`) **no se eliminan** — siguen siendo el
fallback garantizado y lo que usan los tests puramente unitarios.

Palabras clave destacadas: `remotion/src/shared/HighlightedTitle.tsx` implementa el
contrato `{title, highlight_terms}` (coincidencia de palabra completa,
case-insensitive, preserva tildes/mayúsculas) y lo comparten `Main` (Reels,
`highlightTerms` opcional con default `[]` — compatible con props anteriores),
`PremiumSlide`, `AutomaticInstagramCard` y `FacebookOgCard`. No se agregó una
segunda llamada de OpenAI: para contenido automático, `highlight_terms` se
extendería en la misma llamada de reescritura existente en una iteración futura (no
implementado en esta entrega — ver `docs/BACKLOG.md`); para contenido premium, el
operador los edita directamente en el Estudio Premium (Fase 3).

**Motivo**: reutilizar una sola paleta e identidad visual entre Reels, piezas
automáticas y premium, con Pillow como red de seguridad mientras el rendimiento de
Remotion (medido, ver `docs/METRICS.md`) no sea aceptable para el flujo automático de
alto volumen.

**Alternativas rechazadas**: eliminar `layout/image_generator.py` (instrucción
explícita de conservarlo); usar Remotion también para el flujo automático de alto
volumen sin medir antes su costo real (el benchmark mostró ~19s/paquete contra
~0.03s de Pillow — ver Known Issue #69); calcular `highlight_terms` con una llamada
de IA separada (prohibido explícitamente por costo).

**Consecuencias**: cada render Remotion actual re-bundlea desde cero (Known Issue
#69); el path Remotion no detecta overflow de título todavía (Known Issue #70). Un
fallback de `auto` a Pillow queda siempre registrado en `logs/premium_renderer.log` y
en el resultado estructurado (`engine_used`/`render_engine`), nunca en silencio.

**Revisar nuevamente cuando**: se agregue un servidor de render persistente de
Remotion, o se decida extender `highlight_terms` al flujo automático de reescritura.

### 2026-07-30 — Corrección: política de renderers separada por workflow

**Decisión**: la entrada anterior ("Remotion como sistema visual compartido...")
describía un único `STATIC_RENDER_ENGINE=auto` como default seguro para todo. Es
incorrecto presentarlo así: el benchmark midió Remotion ~560x más lento que Pillow
por render (19,1s vs 0,034s promedio), y un host con Node/Remotion instalado con
`STATIC_RENDER_ENGINE=auto` sin más contexto haría que **cualquier** workflow que
llegara a consultarlo intentara Remotion primero — un riesgo real si ese modo se
reutiliza para el flujo automático de alto volumen sin quererlo explícitamente. Se
reemplaza por tres variables independientes, cada una con su propio default y las
tres soportando `auto|remotion|pillow`:

```text
AUTOMATIC_STATIC_RENDER_ENGINE=pillow   (default; automático de Instagram)
PREMIUM_STATIC_RENDER_ENGINE=remotion   (default; Estudio Premium manual)
OG_STATIC_RENDER_ENGINE=pillow          (default; OG de Facebook/web)
```

`utils/remotion_renderer.py::resolve_engine(workflow)` reemplaza a la firma anterior
sin argumentos. Precedencia: 1) variable específica del workflow si está definida
explícitamente; 2) `STATIC_RENDER_ENGINE` (legacy) sólo si está definida
explícitamente; 3) default seguro del workflow. `.env.example` deja las cuatro
variables **comentadas**, precisamente para que copiar el archivo
(`Copy-Item .env.example .env`, el paso de instalación estándar) nunca active el
legacy override por accidente.

**Motivo**: el flujo premium es manual y de bajo volumen (2-10 slides, unas pocas
veces al día) — ahí Remotion por defecto es aceptable y deseable por calidad visual.
El flujo automático de Instagram es de alto volumen (hasta 8 publicaciones/ciclo) y
no está wireado a Remotion en esta entrega (`meta/ig_client.py::_prepare_image` sigue
usando Pillow directo, sin consultar `resolve_engine` todavía) — pero la variable de
configuración ya existe con el default correcto para cuando esa integración se haga.
Lo mismo aplica al OG de Facebook/web.

**Alternativas rechazadas**: mantener una sola variable global (el problema original:
no permite que premium use Remotion por defecto sin arriesgar que automático/OG
también lo hagan si alguien la enciende pensando en premium); hacer que `remotion`
sea silenciosamente equivalente a `auto` para reducir sorpresas (contradice
"remotion: usar Remotion y reportar fallo si no está disponible", que el operador de
premium sí quiere: prefiere un fallo visible a una degradación de calidad silenciosa).

**Consecuencias**: `render_package_with_engine(package, workflow="premium")` (default)
es la única función con wiring real a Remotion en esta entrega. `resolve_engine`
soporta `"automatic"` y `"og"` como workflows válidos y totalmente probados
(incluida la precedencia y el fallback), pero **no existe todavía** el llamador real
en `meta/ig_client.py`/`layout/image_generator.py` que los use — es deliberado, para
no introducir riesgo en el flujo automático de publicación real sin una decisión
aparte. Cada resolución de motor queda en el log rotativo de
`remotion_renderer.log` con `workflow`, `engine_requested`, `engine_used` y
`fallback_reason`.

**Revisar nuevamente cuando**: se decida wireear Remotion al flujo automático o al
OG de verdad (requiere su propia decisión y benchmark, dado el costo medido).

### 2026-07-30 — Generación asistida del paquete premium sin investigación externa

**Decisión**: el Estudio Premium puede transformar con OpenAI el texto completo que
pega el operador en el mismo JSON que acepta el importador manual. La llamada vive en
`openIA/premium_package_generator.py`, exige no inventar datos, personas, armas,
cifras ni hechos ajenos al original, y no hace búsquedas ni recibe URLs como fuente de
investigación. El endpoint `/api/premium/generate` pasa siempre la respuesta por
`utils.premium_importer.import_chatgpt_package` antes de guardar el borrador. Si
OpenAI o el JSON fallan, la acción manual muestra un error y no fabrica una plantilla
degradada ni un fallback silencioso.

**Motivo**: el operador ya aporta la noticia actualizada y necesita reducir el trabajo
mecánico de dividirla en título, caption y slides. Estructurar esa entrada no viola la
restricción vigente contra investigar noticias con IA: la fuente factual es el texto
pegado por el operador y el modelo sólo organiza ese material.

**Alternativas rechazadas**: generar una plantilla mecánica sin IA (el operador eligió
explícitamente OpenAI); permitir que el modelo complete contexto desde conocimiento
propio o búsquedas (podría inventar o mezclar hechos); construir el paquete directo
en el endpoint (duplicaría el contrato del importador); devolver un fallback
silencioso ante un error del proveedor (ocultaría al operador que la estructura no
fue generada por el modelo solicitado).

**Consecuencias**: el import JSON manual se conserva como camino secundario. La
generación usa las credenciales, timeout y reintentos OpenAI ya configurados, pero no
publica nada: crea un borrador que todavía debe revisarse, recibir imágenes, guardarse
y pasar por preview/publicación. Los links de imagen son un flujo aparte, con
validación SSRF-safe, límite de 20 MB e ingesta por contenido; las subidas propias
también terminan en la misma biblioteca deduplicada.

**Revisar nuevamente cuando**: se quiera incorporar investigación, fuentes externas o
verificación factual automática; cualquiera de esos cambios requiere una decisión
editorial y de seguridad nueva.
