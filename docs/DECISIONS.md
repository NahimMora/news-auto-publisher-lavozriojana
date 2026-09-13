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
bootstrap para dejar de ser seleccionable. La pestaña `Candidatas` representa estas
mismas transiciones sin crear estados nuevos: lista sólo `status="candidate"`,
diferencia la publicación reutilizada de la candidata todavía promovible y mantiene
el formulario por identidad como operación secundaria.

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

Desde el incidente reproducido el 2026-07-31, Instagram no considera suficiente que
`POST /media` devuelva un ID: el flujo Premium consulta `status_code,status` y exige
`FINISHED` para cada hijo antes de crear el padre, y para el padre antes de llamar a
`media_publish`. Los límites de espera son exclusivos de este workflow
(`PREMIUM_IG_CONTAINER_PROCESSING_TIMEOUT_SECONDS` y
`PREMIUM_IG_CONTAINER_PROCESSING_POLL_SECONDS`). Un timeout ocurre antes de publicar,
queda como `not_published` reintentable y nunca habilita un reintento de Facebook.
Además, el resultado por canal persiste sólo diagnóstico seguro de Meta (HTTP,
código/subcódigo, tipo y etapa), no el cuerpo o mensaje externo arbitrario.

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

### 2026-07-31 — Contrato editorial verificable para la generación Premium

**Decisión**: hacer verificables las pautas de redacción del JSON generado por IA,
sin endurecer el contrato general de los borradores manuales. El prompt y el gate de
`openIA/premium_package_generator.py` exigen títulos de 60 a 80 caracteres,
informativos, naturales y prudentes en hechos policiales o judiciales; 3 o 4 slides
sustantivos que permiten entender qué pasó, dónde, por qué importa y qué sigue; y
captions con apertura periodística local, emojis pertinentes, fuente sólo si consta
en la entrada y de 3 a 6 hashtags relevantes, siempre con `#LaRioja`. La generación
automática no usa slides de cierre porque cada lugar del carrusel debe aportar hechos.

**Motivo**: una pauta escrita solamente en el prompt no garantiza consistencia. El
operador necesita que el resultado tenga cuerpo y funcione en redes, pero también que
las 3 o 4 placas sean autosuficientes y mantengan atribuciones, incertidumbre judicial
y vínculo riojano sin caer en clickbait ni morbo.

**Consecuencias**: cada respuesta se valida antes de aceptarse. Ante un título corto,
slides demasiado delgados, caption sin emojis/hashtags u otra infracción medible, el
siguiente intento conserva el texto original, recibe el JSON erróneo como respuesta
anterior del asistente y los errores como feedback separado. La corrección debe usar
exclusivamente el texto original. Si se agotan los intentos y existe al menos un JSON
parseable, el endpoint importa el último y muestra los incumplimientos como avisos para
revisión manual; no fabrica ni modifica esa respuesta. Si nunca hubo JSON parseable,
el fallo sigue siendo visible y bloqueante. Los borradores importados o editados
manualmente conservan el contrato compatible existente.

**Revisar nuevamente cuando**: cambie la estrategia editorial de redes, se quiera
validar automáticamente nombres propios o se incorporen fuentes verificadas externas.

### 2026-07-31 — Tipos únicos y escala móvil del carrusel Premium

**Decisión**: cada carrusel Premium puede usar una sola vez cada tipo de slide. La
restricción vive en el selector de la UI, los helpers de edición, la validación del
contrato y el gate de generación por IA. `duplicate_slide` queda rechazado porque su
resultado violaría necesariamente la regla. Los imports con repeticiones se conservan
como borrador inválido para permitir recuperar y reasignar el contenido, pero
`publish_package` no los publica.

Se incorpora el tipo aditivo `impact`, textual y sin imagen, para separar antecedentes
(`context`) de impacto local, aplicación práctica o próximos pasos. En la generación
automática únicamente, un segundo `context` se normaliza a `impact` preservando todo
su contenido y vaciando sólo `asset_hint`; otras repeticiones siguen siendo errores.
Los imports manuales no se corrigen de forma implícita. La extensión es compatible con
paquetes existentes y no requiere migración del `schema_version` 1.

La legibilidad móvil se mejora con una escala exclusiva de `PremiumSlide`: titulares
aproximadamente 6% mayores y cuerpos/módulos entre 10% y 14% mayores, incluyendo
puntos clave, citas, cifras, chips y firma. La cabecera y el footer Premium reservan
además más alto real y escalan 18% el logo, la sección, la señal de deslizamiento y
la numeración; la tarjeta modular de contexto usa 82% del ancho útil. `StillLayout`
y `HeadlineBlock` aceptan escalas opcionales con default 1;
`AutomaticInstagramCard` no las activa y conserva su salida actual.

**Motivo**: dos placas `context` (o de cualquier otro tipo) producen un carrusel
repetitivo y dificultan asignar una función narrativa clara a cada pantalla. A la vez,
los pisos tipográficos anteriores perdían presencia al reducir la pieza 1080x1350 al
ancho habitual de un teléfono.

**Consecuencias**: un borrador viejo o un import manual con tipos duplicados exige
corrección antes de publicar. La salida automática ya no queda en estado fallido por
dos `context`: conserva uno como contexto y presenta el otro como impacto local. No
hay migración ni pérdida automática de contenido. La ampliación visual no altera el
renderer automático, las colas, el CMS ni los contratos de Meta.

**Revisar nuevamente cuando**: se agregue un tipo nuevo, vuelva una acción de
duplicación con conversión explícita a otro tipo o cambie el formato del lienzo.

### 2026-07-31 — Editorial Cinemática Riojana: sistema visual compartido + servidor de render persistente

**Decisión**: rediseñar el sistema visual de las dos piezas estáticas (carrusel premium y
card automática de Instagram) bajo una dirección de arte única, "Editorial Cinemática
Riojana", con tokens compartidos (`remotion/src/shared/designSystem.ts`): tres modos de
composición (`cronica`/`editorial`/`datos`, derivados de `template` en premium y de
`seccion` en automático), tipografía Archivo + Source Serif 4 (variables, SIL OFL,
cargadas localmente sin red — `remotion/src/shared/fonts.ts`), gradientes por capas
(scrim + wash de marca + luz radial + viñeta), textura de grano vía filtro SVG
(`Grain.tsx`), y auto-fit de texto medido con Canvas 2D real (`fitText.ts`) que cierra
`docs/KNOWN_ISSUES.md` #70 (el path Remotion no detectaba overflow de título).

Para conectar Remotion de verdad al flujo automático (antes sólo Pillow, ver la entrada
2026-07-30 "Corrección: política de renderers separada por workflow") sin pagar el costo
medido de ~19s/paquete (Known Issue #69), se agregó un servidor de render persistente
(`remotion/render_server.mjs`): bundlea el proyecto **una sola vez** por proceso con
`@remotion/bundler` y abre un browser Chromium reusado entre renders vía
`@remotion/renderer`, expuesto por HTTP en `127.0.0.1` (sólo loopback, sin auth — mismo
criterio que la UI manual del proyecto). `utils/remotion_renderer.py::render_still()`
mantiene firma y contrato de retorno idénticos: intenta el servidor primero
(`ensure_render_server()`, lo levanta bajo demanda si no está corriendo) y cae al
`subprocess` de `npx remotion still` si el servidor no puede levantar por cualquier
motivo — ningún caller (tests incluidos) tuvo que cambiar.

Benchmark real (`scripts/benchmark_static_render.py`, mismos 10 fixtures que el
benchmark original, medido 2026-07-31): **19.119s → 2.881s promedio por paquete**
(≈6.6x más rápido; ≈1.0-1.25s por slide individual, primer render de la corrida incluido
con el costo de bundle+browser en frío). Ver `docs/METRICS.md` para la tabla completa.

Con esa mejora de performance, `layout/image_generator.py` gana una función aditiva
nueva, `generate_instagram_with_engine(article, preloaded_img=None)`, que resuelve
`resolve_engine("automatic")` e intenta Remotion antes de caer a `generate_post`
(Pillow, sin tocar esa función) — mismo patrón que
`utils.premium_renderer.render_package_with_engine`. Se actualizaron los call sites
reales (`meta/ig_client.py::_prepare_image`, `pipeline/custom_post.py::render_preview_image`,
`preview_pipeline.py`) para usarla. El default de `AUTOMATIC_STATIC_RENDER_ENGINE` pasa
de `pillow` a **`auto`** (intenta Remotion, cae a Pillow sin bloquear una publicación
real si el servidor tiene un problema puntual) — deliberadamente no `remotion` estricto,
que haría fallar la publicación completa ante cualquier hiccup de Node en el host 24/7.
`OG_STATIC_RENDER_ENGINE` (Facebook/web) no se tocó — fuera de alcance de este rediseño,
igual que `FacebookOgCard.tsx` (se aisló en `remotion/src/shared/LegacyStillLayout.tsx`
para que no dependiera del contrato nuevo de `StillLayout.tsx`, pensado sólo para
`PremiumSlide`/`AutomaticInstagramCard`).

Cards automáticas sin foto ya no caen a un fondo negro liso: usan un fondo de marca con
textura y gradiente (fallback profesional). El recorte también varía según orientación
de la imagen (`assetOrientation`, prop opcional en ambos schemas — Python ya tenía el
width/height barato disponible vía `media_library.py`/PIL, no hace falta reabrir el
archivo). El fallback Pillow de emergencia (`layout/image_generator.py::_font`) también
prioriza el `.ttf` de Archivo (con `set_variation_by_axes` para el peso, si el build de
FreeType lo soporta) antes de Arial — cambio mínimo, no se rediseñó el resto del layout
Pillow por instrucción explícita del pedido original.

**Motivo**: el operador pidió explícitamente subir la calidad de edición, componentes y
distribución de ambas piezas usando Remotion — no sólo el carrusel premium, también las
cards automáticas scrapeadas, que hasta esta entrega no tenían wiring real
(`AutomaticInstagramCard.tsx` existía sólo para tests). Eso exigía resolver primero el
cuello de botella de re-bundling, documentado como riesgo residual en el propio Known
Issue #69 ("si se decide usar Remotion para el flujo automático de alto volumen, hace
falta un servidor de render persistente").

**Alternativas rechazadas**: fijar `AUTOMATIC_STATIC_RENDER_ENGINE=remotion` estricto en
vez de `auto` (se rechaza: un fallo puntual de Node bloquearía publicaciones reales de
Instagram sin necesidad, cuando Pillow sigue siendo un fallback perfectamente
funcional); rediseñar también `layout/image_generator.py` (Pillow) a fondo para que
compita visualmente con Remotion (se rechaza: el brief pide explícitamente mantenerlo
como fallback de emergencia simple, no una segunda implementación completa del sistema
de diseño); tocar `FacebookOgCard.tsx`/workflow `og` en esta entrega (fuera del alcance
explícito pedido); usar `@remotion/fonts` para cargar las tipografías locales (se
rechaza: la documentación oficial no confirma soporte de rango de peso variable
`font-weight: 100 900` sobre un único archivo de fuente variable, que es justamente lo
que permite pedir 400/700/900 desde el mismo `.ttf` de Archivo — se usa la API
`FontFace` nativa del navegador en su lugar, con `delayRender`/`continueRender`
integrado a un hook de React (`useFontsReady`) para forzar un re-render real después de
que la fuente cargue, no sólo bloquear la captura — un bug real detectado en pruebas
manuales mostró que medir con Canvas 2D *antes* de que la fuente terminara de cargar
producía wraps de texto incorrectos con la métrica de la fuente de fallback).

**Consecuencias**: `remotion/render_server.mjs` es un proceso Node adicional que puede
quedar corriendo en el host (se apaga solo por inactividad, default 20 minutos —
`RENDER_SERVER_IDLE_MS`) — no es un servicio nuevo que haya que registrar en el
supervisor ni en las tareas programadas, se levanta bajo demanda la primera vez que se
necesita. `.render-cache/` (bundle) y `.render-server.json` (metadata del proceso) son
artefactos locales, gitignorados, nunca se commitean. En Windows, `SIGTERM`/`SIGINT` no
garantizan que el proceso corra su handler de apagado prolijo (limitación conocida del
sistema operativo, no de esta implementación) — el archivo de metadata puede quedar
obsoleto tras un `taskkill` externo, por eso `ensure_render_server()` siempre valida
con un healthcheck HTTP real antes de confiar en él, nunca sólo en el archivo. El
resaltado de términos en las composiciones nuevas (`FittedTitle.tsx`) resalta la
**palabra completa** (con puntuación pegada, p.ej. "end-to-end:") si el término aparece
en cualquier parte de ella, no sólo la subcadena exacta — necesario para que el mismo
tokenizado por espacios sirva tanto para el wrap como para el resaltado sin desincronizarse
(bug real encontrado y corregido durante esta entrega: un término que hacía match en
medio de una palabra con puntuación pegada generaba un token de más y desplazaba el
resto de las palabras a la línea equivocada). Un título con una palabra sin espacios más
ancha que el lienzo (identificador técnico, URL) se corta a nivel de carácter
(`breakLongWord` en `fitText.ts`) para garantizar que nunca se desborde — en ese caso
puntual se pierde el color de resaltado como degradación segura, no la legibilidad.

**Revisar nuevamente cuando**: se acumule evidencia real de producción sobre el
comportamiento de `auto` para el flujo automático (tasa de fallback a Pillow, tiempos
reales bajo carga de 8/ciclo) que justifique subir a `remotion` estricto o bajar de
nuevo a `pillow`; se decida extender el sistema visual nuevo a `FacebookOgCard.tsx` o a
los Reels (`Main.tsx`/`Outro.tsx`); o se agregue algún mecanismo de invalidación
automática del bundle cacheado si el código de `remotion/src/` cambia mientras el
servidor sigue corriendo (hoy requiere reiniciar el proceso manualmente, documentado en
`remotion/README.md`).

### 2026-07-31 — Las piezas de una sola imagen adoptan la escala premium

**Decisión**: se revierte la exclusividad decidida en "Tipos únicos y escala móvil del
carrusel Premium" (más arriba, mismo día). `AutomaticInstagramCard.tsx` — que renderiza
tanto las publicaciones automáticas del scraper (`meta/ig_client.py`,
`preview_pipeline.py`) como las publicaciones personalizadas manuales
(`pipeline/custom_post.py`, mismo componente, ver comentario "reusando el mismo
pipeline del autopublicador" en ese archivo) — ahora importa y usa exactamente las
mismas constantes que `PremiumSlide.tsx`: `PREMIUM_MASTHEAD_H` (108), `PREMIUM_FOOTER_H`
(96), `PREMIUM_CHROME_SCALE` (1.18) y `PREMIUM_HEADLINE_SCALE` (1.06, vía un wrapper
`AutoHeadlineBlock` local). Estas constantes pasan a exportarse desde `PremiumSlide.tsx`
en vez de vivir sólo ahí. La pieza sigue sin `showSwipeCue`/`total`: es una sola imagen,
no un carrusel, así que nunca hubo ni hay señal de deslizamiento ni numeración.

**Motivo**: pedido explícito — las publicaciones (manuales) y autopublicaciones de una
sola imagen deben verse con el mismo peso editorial que una placa del carrusel premium,
no con el masthead/footer/tipografía más chicos heredados de la v1.

**Consecuencias**: `CONTENT_H`, `PHOTO_H`→`panelTop` y todo el resto de la geometría de
`AutomaticInstagramCard.tsx` se recalculan automáticamente contra el masthead/footer más
altos (mismo patrón que ya usa `CoverSlide` en `PremiumSlide.tsx`). No cambia
`FacebookOgCard.tsx` (sigue en `LegacyStillLayout`, workflow `og`, fuera de alcance) ni
ningún contrato de datos/props públicos de `AutomaticInstagramCardSchema`. El test
`tests/test_remotion_visual.py::PremiumSlideSchemaTests` se actualizó para verificar la
paridad en vez de la exclusividad anterior.

**Revisar nuevamente cuando**: se quiera volver a diferenciar visualmente la pieza
automática/manual de la premium, o se decida extender esta misma escala a
`FacebookOgCard.tsx`.

### 2026-07-31 — FacebookOgCard adopta el sistema visual nuevo y se wirea a Remotion

**Decisión**: se revierte también el "fuera de alcance" repetido de `FacebookOgCard.tsx`
(tarjeta Open Graph que Facebook/WhatsApp/etc. muestran al compartir el link del
artículo web, generada por
`pipeline/node_webapp/media.py::generate_og_image`). `FacebookOgCard.tsx` deja de usar
`shared/LegacyStillLayout.tsx` (Arial, `AZUL`/`WHITE` fijos, `HighlightedTitle` con wrap
del navegador) y pasa al mismo sistema de `AutomaticInstagramCard.tsx`/`PremiumSlide.tsx`:
`StillLayout` con `EditorialMasthead`, `HeroMedia` (full_bleed) y `HeadlineBlock`
(auto-fit real), modo por sección (`modeFromSection`). El lienzo (1200x630) es mucho más
bajo que el de las otras dos piezas (1080x1350), así que usa constantes propias
`OG_MASTHEAD_H`/`OG_FOOTER_H`/`OG_CHROME_SCALE` (76/64/0.82) en vez de las `PREMIUM_*` —
reusar esas literalmente habría dejado casi sin aire la foto y el panel. El titular se
acota a 2 líneas (con imagen) o 3 (sin imagen, panel más alto disponible), sin activar
`fontScale`. Sigue sin `showSwipeCue`/`total`.

Además, `resolve_engine("og")` pasa de default `"pillow"` a `"auto"` (mismo criterio que
`"automatic"` en la entrada anterior de este mismo día): se agregan
`layout/image_generator.py::_generate_facebook_remotion`/`generate_facebook_with_engine`
(mismo patrón que sus pares de Instagram) y `generate_og_image` los usa en vez de llamar
`generate_post` directo. `preview_pipeline.py` también se actualizó para generar el FB de
preview con el motor real, igual que ya hacía con el IG.

**Motivo**: pedido explícito de aplicar el mismo rediseño a la pieza de Facebook/OG.
Dejar sólo la composición Remotion redibujada sin wirearla habría sido un cambio
invisible: la imagen OG real seguía saliendo de `generate_post` (Pillow, diseño viejo).

**Consecuencias**: la tarjeta OG de cada artículo publicado en la web pasa a Remotion
cuando está disponible, con la misma red de seguridad que "automatic" — si el servidor
de render tiene un problema puntual, cae a Pillow en silencio (logueado) y la
publicación web nunca se bloquea por esto. No cambia el contrato de
`FacebookOgCardSchema` ni el de `generate_og_image`/`upload_og_image`. Facebook/Instagram
en sí no reciben esta imagen directo (`post_to_facebook_detailed` comparte un link y usa
el OG de la página web, ver comentario en `pipeline/custom_post.py`), así que el cambio
sólo se ve al visitar o compartir la URL pública del artículo, no en un botón de vista
previa dentro de la UI de `video_reel_manager.py`.

**Revisar nuevamente cuando**: se acumule evidencia real de volumen/latencia del
workflow `og` bajo Remotion (hoy es 1 render por artículo publicado, no un flujo de alto
volumen); o se quiera compartir constantes de masthead/footer entre los tres lienzos en
vez de mantener `OG_*` separadas de `PREMIUM_*`.

### 2026-07-31 — Ajuste fino de AutomaticInstagramCard: ancho/posición del título, chip de lugar, bajada y footer social

**Decisión**: feedback puntual sobre la card de una sola imagen ya rediseñada
(`AutomaticInstagramCard.tsx`), verificado con renders reales y en vivo contra la UI de
`http://127.0.0.1:8765/`:

1. **Ancho/alineación del título**: el modo Editorial (`mode.grid === "column"`, la
   mayoría de las secciones) reducía el título a 80% del ancho y lo alineaba a la
   derecha — sin motivo real, ya que `CoverSlide` en `PremiumSlide.tsx` (la referencia
   de este rediseño) siempre usa el ancho completo y alineación a la izquierda, en
   cualquier modo. `FullBleedBody`/`NoImageBody` ahora hacen lo mismo.
2. **Posición del título**: `maxHeight` restaba un valor fijo (`panelH - 60`) menor que
   el padding real del panel (`pad`, 64 o 80 según el modo). Con títulos largos, el
   bloque de texto podía desbordar el margen superior del panel y quedar pegado contra
   el borde de la foto ("el título está muy arriba"). Ahora resta el padding real de
   ambos lados (`panelH - pad * 2`), y el modo Editorial además centra verticalmente
   (mismo criterio que `CoverSlide`) en vez de anclar arriba.
3. **Localidad y bajada completadas por IA**: nueva función
   `openIA/caption_generator.py::generate_locality_and_deck` (esquema/prompt propio,
   no toca `generate_caption`) — `locality` (chip de lugar, p.ej. "Chilecito") vacío si
   el texto no nombra una localidad riojana concreta, y `deck` (bajada corta ANTES del
   título, nunca repite el título) igual de vacío si no hay contexto claro. Fallback
   silencioso si OpenAI no está disponible o falla: ambos quedan vacíos, la imagen se
   genera igual sin chip ni bajada — nunca bloquea una publicación. Se llama desde
   `openIA/rewrite_news.py::rewrite_noticia` (automático, junto a `generate_caption`) y
   desde `pipeline/custom_post.py::build_custom_noticia` (manual, nuevo). Ambos campos
   viajan por `AutomaticInstagramCardSchema` (`locality`/`deck`, default `""`) y se
   renderizan con `ContextChip`/`HeadlineBlock.deck` — mismos componentes que ya usa
   `CoverSlide`.
4. **Footer con firma social**: `StillLayout` gana un prop opcional
   `showSocialFooter` que, cuando está activo, reemplaza el crédito de fuente por
   íconos FB/IG + `lavozriojana.com` (`shared/editorial/SocialFooter.tsx`, reusa
   `SocialMark` — extraído de `BrandSignature.tsx` para no duplicar el ícono
   enmascarado). `AutomaticInstagramCard`/`FacebookOgCard` lo activan;
   `PremiumSlide` nunca lo activa (su footer sigue siendo crédito + deslizamiento +
   numeración).

**Motivo**: feedback directo sobre el resultado ya en producción — el ancho/posición
del título eran regresiones respecto de la referencia real de Premium (no un cambio de
diseño nuevo), y localidad/bajada/footer social son piezas que sí tiene el sistema
Premium (chip de `CoverSlide`, marca de `BrandSignature`) y que la card automática
todavía no había adoptado.

**Consecuencias**: `pipeline/custom_post.py::build_custom_noticia` ahora hace una
llamada a OpenAI adicional (además de la que ya hacía `openIA/rewrite_news.py` para el
flujo automático); dado que "Vista previa" y "Publicar" llaman a
`build_custom_noticia` por separado, un mismo posteo manual puede disparar la llamada
dos veces — aceptado por simplicidad (mismo orden de magnitud que ya acepta el Estudio
Premium al generar contenido con IA de forma interactiva). `FacebookOgCard` no recibe
`locality`/`deck` (fuera de este pedido); sólo gana el footer social. No cambia
ningún contrato público existente: `locality`/`deck` tienen default `""` y son
compatibles hacia atrás con cualquier caller que no los envíe.

**Revisar nuevamente cuando**: el volumen de publicaciones manuales justifique cachear
`generate_locality_and_deck` entre preview y publish en vez de llamarlo dos veces; o se
decida extender `locality`/`deck` a `FacebookOgCard.tsx`.

### 2026-08-01 — Corrige título superpuesto al footer y sube el chrome de FacebookOgCard

**Decisión**: feedback directo, verificado con renders reales:

1. **Título superpuesto al footer**: `FacebookOgCard.tsx` reusaba el padding de marca
   (`mode.pad`, 64/80px, pensado para el lienzo 1080x1350 de Premium/Automatic) y un
   `maxHeight` fijo (`panelH - 36`) muy por encima del alto real disponible en su
   panel — mucho más bajo al ser un lienzo 1200x630. El título podía necesitar hasta
   ~140px cuando el panel con padding real sólo tenía ~15-45px, desbordando la foto
   arriba y el footer abajo. Corrección: escala tipográfica propia
   (`OG_HEADLINE_SCALE = 0.62` sobre `TYPE.titleBody`, en vez de heredar la de
   Premium/Automatic, que no entra en un panel tan bajo), padding comprimido al 75%
   de `mode.pad`, `maxHeight` recalculado contra ese padding real, y `overflow:
   hidden` como red de seguridad final. También afectaba a `AutomaticInstagramCard`
   en un caso más acotado: cuando había chip de localidad, su alto + el `gap` no se
   restaban del presupuesto del título (`CHIP_H` + `chipReserve`, ahora sí), y el modo
   Editorial centraba el título en un contenedor sin padding vertical real (ahora
   tiene, y su `maxHeight` lo descuenta). `maxLines` de `FullBleedBody` baja de 4 a 3
   como margen adicional.
2. **Chrome de FacebookOgCard "que se vea como las de Estudio Premium"**: subir
   `OG_CHROME_SCALE` de 0.82 a 1.05 y `OG_MASTHEAD_H`/`OG_FOOTER_H` de 76/64 a 92/78 —
   el logo, la sección y el footer social se ven notoriamente más grandes y en línea
   con el resto del sistema, sin llegar a los valores de Premium (108/96/1.18), que en
   un lienzo de 630px de alto dejarían casi sin panel disponible.
3. **Componentes del footer social un poco más grandes**: `SocialFooter.tsx` sube sus
   tamaños base (íconos 24→28px, texto 22→25px, gap 12→14px) — afecta tanto a
   `AutomaticInstagramCard` como a `FacebookOgCard` (ambos usan el mismo componente).

**Motivo**: el desborde era un bug real de geometría (no una preferencia de diseño) —
el panel de OG simplemente no tenía el alto que el cálculo de `maxHeight` asumía. El
chrome más grande es un pedido explícito de que la pieza de Facebook/OG se sienta
igual de sólida que el resto del sistema "Editorial Cinemática Riojana".

**Consecuencias**: títulos muy largos en modo Editorial + chip de localidad pueden
truncarse a 3 líneas con elipsis antes de lo que truncaban antes (a 4) — degradación
aceptada frente a la alternativa (desborde visible). `FacebookOgCard` nunca alcanza el
tamaño de fuente de `TYPE.titleBody` sin escalar (`OG_HEADLINE_SCALE` siempre reduce);
esto es intencional, el lienzo de 630px de alto no lo soporta. No cambia ningún
contrato de props: `FacebookOgCardSchema`/`AutomaticInstagramCardSchema` no ganan
campos nuevos en esta entrada.

**Revisar nuevamente cuando**: se rediseñe el lienzo de OG (p.ej. cuadrado en vez de
1.91:1) de forma que sobre alto real para el panel sin comprimir tanto el padding ni
la tipografía.

### 2026-08-02 — Publicaciones conserva el título y deriva un único destaque verificable

**Decisión**: la pestaña `Publicaciones` acepta títulos de 8 a 120 caracteres tanto
en HTML como en `pipeline/custom_post.py`. Para el origen `manual_custom_post`, el
prop explícito `publicationStyle=manual_publication` hace que `AutomaticInstagramCard`
mida el título con Canvas/fuente real y calcule un panel degradado de 260–554 px según
líneas, localidad y bajada. El margen vertical es proporcional (7,5%, acotado a
36–48 px por lado), admite hasta cinco líneas y puede bajar a 32 px; no se recorta el
contenido en la web ni se reemplaza el final por `...` dentro de ese contrato. La
sección fuerza la misma bandera/recuadro del masthead Premium: rojo
Crónica y el token exclusivo `SECTION_BLUE_DARK=#0B2F4F` para Editorial. El azul más
luminoso de `mode.accent` queda reservado al destaque dentro del título. El default
`automatic` conserva la geometría, cantidad de líneas y masthead previos.

La llamada existente `generate_locality_and_deck`, invocada con
`include_highlight=True` sólo desde Publicaciones, agrega `highlight_phrase`: una sola
frase relevante de 2 a 4 palabras contiguas copiadas literalmente del título. Las
reglas priorizan el núcleo informativo (acción + objeto, sujeto + decisión o resultado)
y la primera mitad; rechazan bordes funcionales, lugar/fecha aislados y cierres
genéricos. Una frase ubicada en el último 35% sólo pasa si contiene una acción o
resultado concreto. El backend valida la secuencia y las reglas; una propuesta ajena
se descarta. Si falta OpenAI o falla, el selector determinístico aplica la misma
política sin inventar datos, armas, personas ni hechos. El valor viaja como
`highlight_terms` y `FittedTitle` lo colorea con el acento de la card.

**Motivo**: el límite anterior de 240 caracteres era incompatible con un panel de
tres líneas y producía elipsis o riesgo de superposición. La card manual tampoco
alimentaba el contrato de highlights que Remotion ya soportaba, y el tratamiento de
sección variaba entre modos pese a la referencia visual del Estudio Premium.

**Alternativas rechazadas**: truncar silenciosamente el título antes de renderizar
(pierde información editorial); dejar 240 caracteres y reducir la fuente sin piso
(degrada legibilidad); hacer otra llamada a OpenAI sólo para el highlight (costo y
latencia innecesarios); aceptar una paráfrasis del modelo (podría introducir palabras
no escritas por el operador).

**Consecuencias**: los borradores manuales viejos con más de 120 caracteres deben
editarse antes de previsualizar o publicar; nunca se truncan automáticamente. Preview
y publicación siguen usando el mismo renderer real. El flujo automático no recibe
`highlight_terms` ni modifica su prompt o su composición por esta decisión. No cambia
el contrato JSON durable ni los publicadores de CMS/Meta.

**Revisar nuevamente cuando**: títulos reales dentro de 120 caracteres obliguen a
bajar de 32 px o cuando el equipo editorial prefiera que el operador elija manualmente
la frase destacada.

### 2026-08-02 — Publicaciones manuales renderiza a 2× y conserva crominancia 4:4:4

**Decisión**: `utils.remotion_renderer.render_still` acepta una escala explícita,
validada entre 0.1 y 4, y la transmite por igual al servidor persistente y a
`npx remotion still`. `layout.image_generator` pide escala 2 sólo cuando el origen es
`manual_custom_post`: la composición conserva su sistema lógico 1080×1350 y produce
un archivo 2160×2700. Ese PNG se convierte a JPEG calidad 95, `subsampling=0` (4:4:4)
y `optimize=True`. El fallback Pillow manual genera directamente con las mismas
dimensiones y opciones JPEG. El workflow automático sigue en escala 1 y JPEG calidad
90.

**Motivo**: la card estaba diseñada para el tamaño de feed, pero la UI permite verla
y ampliarla en un monitor. A 1080 px de ancho, el zoom hacía visible tanto la grilla
de píxeles como el submuestreo de color alrededor de texto azul/rojo. Duplicar la
densidad mejora esos bordes sin tocar medidas, auto-fit, footer ni proporción 4:5.

**Alternativas rechazadas**: escalar el JPEG 1080 después del render (interpola
píxeles pero no agrega detalle); usar PNG como artefacto social (archivo mucho mayor
y cambio de contrato); aplicar 2× al lote automático completo (duplica costo de
render y transferencia en el flujo de mayor volumen sin un pedido operativo).

**Consecuencias**: preview y publicación manual generan archivos más grandes y el
render consume más memoria/tiempo. La imagen original no gana detalle si ya llega en
baja resolución, pero texto, vectores, gradientes y composición sí se rasterizan a
2160×2700 reales. Un servidor persistente anterior que ignore `scale` no se acepta
para un pedido 2×: la ausencia del header de confirmación activa el CLI de respaldo.

**Revisar nuevamente cuando**: el tamaño de los JPEG manuales afecte tiempos de
subida, Meta imponga un límite más estricto o se quiera exponer una opción editorial
de resolución en vez del valor fijo 2×.

### 2026-08-02 — El automático adopta el paquete visual de Publicaciones detrás de un flag

**Decisión**: `AUTOMATIC_MANUAL_VISUAL_STYLE_ENABLED` controla únicamente la paridad
visual del workflow automático y tiene default seguro `false`. Cuando vale `true`, la
card automática de Instagram usa `publicationStyle=manual_publication`: panel
adaptativo sin elipsis dentro del contrato de 120 caracteres, sección en recuadro,
destaque relevante y salida JPEG 2160×2700, calidad 95 y crominancia 4:4:4. El
fallback Pillow conserva la misma resolución y codificación. La tarjeta OG recibe el
mismo estilo de sección y destaque dentro de su proporción propia 1200×630; no se la
deforma para copiar la geometría 4:5 de Instagram.

Las noticias nuevas obtienen `highlight_terms` en la llamada ya existente de
`generate_locality_and_deck`, sin sumar otro request a OpenAI. El prompt y el
validador exigen una frase contigua de 2 a 4 palabras tomada literalmente del título,
sin inventar datos, armas, personas ni hechos. Las entradas antiguas de las colas que
no tienen ese campo usan al renderizar el mismo selector local determinístico. El
campo se incorpora de forma opcional a la metadata; no exige migración ni modifica la
forma de los estados durables.

**Motivo**: el operador pidió que lo generado por autopublicación sea visualmente
igual a lo creado desde `Publicaciones`, incluidos legibilidad al ampliar, recuadro de
sección y palabra o frase relevante con el color de la card.

**Alternativas rechazadas**: cambiar el automático sin interruptor (riesgo operativo
en el workflow de volumen); hacer una segunda llamada de IA sólo para el destaque
(costo y latencia sin beneficio); dejar las entradas ya encoladas sin destaque
(resultado inconsistente); escalar el JPEG después de renderizar (no agrega detalle
real en tipografía ni vectores).

**Consecuencias**: con el flag activo aumentan el tiempo de render, el uso de memoria
y el tamaño de los archivos automáticos. El rollback visual es inmediato poniendo el
flag en `false`, sin tocar colas. Este host lo activa por pedido explícito, pero la
tarea productiva permanece detenida durante el QA y no se ejecuta ningún publicador.
Los flujos Premium y Reels conservan sus colas, contadores y renderers separados.

**Revisar nuevamente cuando**: el costo de 2× afecte el ciclo automático, Meta cambie
sus límites de imagen o se necesite seleccionar el destaque manualmente en lugar de
derivarlo con reglas verificables.

### 2026-08-02 — Reactivar 24/7 desde una línea de base fresca de 20 noticias

**Decisión**: ante la autorización explícita del operador, refrescar primero las
fuentes con los tres publicadores forzados a `off`, crear backup y aplicar
`queue-cutover --keep-latest 20` sólo con `unknown_order=0`. Después, validar el
perfil productivo mediante `scripts/start_24x7_production.ps1 -ValidateOnly`, habilitar
la tarea `LaVozRiojana-24x7` y arrancar en modo `all`. El canary permanece apagado.

**Motivo**: las primeras 20 entradas durables eran del 30/07 y no representaban las
últimas noticias disponibles. La ingesta previa evitó arrancar con ese lote antiguo;
el segundo corte dejó 20 identidades del 01/08, las más recientes expuestas por las
fuentes al momento de la activación.

**Condición conocida**: `preflight_cms` sigue `blocked` por falta de un endpoint GET
autenticado de capacidades. No se convierte en éxito. Se conserva la excepción
operativa del 27/07 —publicación CMS con evidencia de ID/URL, kill switch y rollback—
porque el operador volvió a autorizar explícitamente la activación. Fuentes, OpenAI,
R2, Facebook, Instagram y filesystem sí pasaron sus preflights.

**Consecuencias**: el primer ciclo publicó 17 notas Web, 5 Facebook y 2 Instagram;
tres Web eran duplicados y cinco publicaciones Web quedaron degradadas por el sexto
intento seguro, sin warnings factuales, judiciales ni de HTML. No hubo fallos externos
ni resultados ambiguos. La tarea programada queda habilitada de forma permanente y
el supervisor procesa ciclos horarios con watchdog cada cinco minutos. Los pendientes
sociales se conservan para ciclos siguientes y no se reintentan por fuera de la cola.

**Revisar nuevamente cuando**: el CMS incorpore `WEBAPP_PREFLIGHT_PATH`, el heartbeat
quede stale, aparezca un outcome ambiguo o cambien los límites de Meta.

### 2026-08-02 — EditorialReel extiende el sistema visual al video detrás de un flag manual

**Decisión**: agregar `EditorialReel` como composición Remotion aditiva 1080×1920 y
mantener `Main` sin cambios como rollback. La composición nueva reutiliza el esquema
de props existente (`titulo`, `seccion`, asset, variante, duración y
`highlightTerms`), suma 90 frames de cierre dentro del mismo render y adopta Archivo,
Source Serif 4, modos Crónica/Editorial y los tokens de color de las publicaciones.
El movimiento se construye exclusivamente desde el frame: reveal del medio,
Ken Burns/parallax, entrada del masthead y badge, título escalonado, sweep de luz,
textura, progreso, compactación y outro de marca.

El caller elige la composición únicamente cuando
`REEL_CINEMATIC_VISUAL_STYLE_ENABLED=true`. El default de código y `.env.example` es
`false`; este host lo activa por pedido explícito para la UI manual. Si el título no
trae `highlight_terms`, se usa `select_highlight_phrase`, el mismo selector verificable
de Publicaciones: copia una frase literal y no suma una llamada a OpenAI. Si Remotion
falla, el camino ffmpeg y el outro legacy siguen disponibles.

**Motivo**: Reels había quedado fuera de la dirección de arte "Editorial Cinemática
Riojana": todavía usaba Arial, menos capas de movimiento y un cierre independiente,
mientras las piezas estáticas ya compartían una identidad mucho más sólida. El pedido
explícito fue hacer la generación de videos más pulida, animada y profesional tomando
como base esos estilos.

**Alternativas rechazadas**: reemplazar `Main` en forma irreversible (elimina el
rollback y cambia comportamiento al desplegar); activar el cambio dentro del lote
automático o las colas Premium (son workflows separados); usar animaciones CSS
temporales (no son deterministas en render); sumar una llamada de IA sólo para elegir
el destaque; reusar el MP4 de outro cacheado, que mantendría el lenguaje visual viejo.

**Consecuencias**: un render cinemático dura tres segundos más que el contenido, igual
que el flujo anterior que concatenaba el outro, pero ahora la transición visual es
continua. La respuesta informa `visual_style=editorial_cinematic_v2`. El cambio no
publica, no consume cupos externos y no altera CMS, Meta, autopublicadores ni sus
colas. El costo de render es mayor que el layout legacy por las capas y efectos;
queda acotado al flujo manual y conserva fallback.

**Revisar nuevamente cuando**: haya métricas de tiempo/tamaño con videos fuente largos,
se quiera habilitar esta estética en otro workflow o haga falta exponer variantes de
movimiento elegibles por el operador.

### 2026-08-02 — El chrome del Reel usa reservas grandes de lectura móvil

**Decisión**: ampliar en `EditorialReel` la cabecera, la bandera de sección y el footer
como bloques completos, no sólo sus fuentes. La cabecera queda en 164 px con logo de
74 px; la sección en 78 px con etiqueta de 31 px; y el footer en 104 px con texto de
33 px e íconos de 38 px. El medio empieza en y=150, el panel termina en y=1784 y el
presupuesto del titular descuenta la nueva altura de sección.

**Motivo**: al reducir 1080×1920 al tamaño habitual de un teléfono, la escala anterior
perdía jerarquía y no permitía identificar claramente marca, sección ni firma social.

**Alternativas rechazadas**: escalar sólo texto e íconos (produce colisiones dentro de
franjas chicas); agrandar el chrome sin recalcular medio/panel (invade el titular);
cambiar la resolución del Reel (no corrige la proporción visual y altera el contrato).

**Consecuencias**: el medio cede 38 px superiores y 20 px inferiores, mientras el panel
inicial gana altura al comenzar antes. Títulos largos conservan auto-fit y safe area.
El cambio sólo afecta `EditorialReel`; `Main`, cards estáticas y publicadores no cambian.

**Revisar nuevamente cuando**: cambie el lienzo 9:16, el logo o el tamaño de reproducción
objetivo en la UI.

### 2026-08-02 — La fase compacta recompone sección y titular como un solo grupo

**Decisión**: usar dos layouts tipográficos: el grande de hasta 88 px y uno compacto
de hasta 72 px que vuelve a envolver el texto sobre 800 px seguros. Ambos cruzan su
opacidad mediante `compactProgress`; no hay animaciones CSS. El alto real del layout
compacto determina la posición final del panel completo. La sección conserva su
posición relativa a 18 px estructurales del titular y el bloque termina con safe area
antes del footer. Los renglones de `fitText` no pueden partirse otra vez dentro de los
spans de color.

**Motivo**: escalar con origen superior conservaba un vacío negro bajo el titular. El
primer ajuste trasladó sólo el texto y movió ese vacío al espacio entre sección y
título. Mover el panel corrigió el eje vertical, pero la escala uniforme todavía
encogía el ancho y desaprovechaba espacio donde podían entrar más palabras. La unidad
visual correcta es el panel completo con una composición tipográfica propia.

**Alternativas rechazadas**: rellenar la franja con otra capa (oculta el error de
layout); trasladar sólo el titular (separa la sección); mantener escala uniforme
(reduce también el ancho); cambiar los renglones en caliente en un único nodo (salta
durante el wrap); posicionar por cantidad de caracteres (no respeta métricas reales).

**Consecuencias**: sección, títulos cortos o largos y footer mantienen una composición
compacta equilibrada sin alterar la entrada escalonada ni la duración. Es un cambio
exclusivo de `EditorialReel`; no publica ni modifica colas o workflows automáticos.

**Revisar nuevamente cuando**: cambie la tipografía, el máximo de renglones, el ancho
seguro o la geometría del panel/footer.

### 2026-08-03 — La promoción manual a automática prevalece sobre filtros previos de Instagram

**Decisión**: una transición explícita `candidate→automatic` hecha por el operador es
autoritativa para la selección editorial de Instagram. `run_ig` cruza las identidades
de `noticias_meta.json` con `manual_override_history` en
`editorial_candidates.json`; si la noticia conserva ruta `automatic`, puede superar
`IG_ALLOWED_CATEGORIES`, la condición `breaking` y, sólo para Instagram, la espera de
URL Web. El cliente de Instagram no usa esa URL en el payload; sí conserva el gate de
imagen pública. No se agrega un campo ni una migración: se reutiliza evidencia durable
que ya existe. `published_reuse` no participa
porque esa candidata representa una publicación confirmada que sólo se reutiliza en
Premium.

**Motivo**: el operador confirmó que “Enviar a automática” significa publicar esa
noticia, no sólo cambiar una etiqueta interna. Antes, la UI ocultaba la candidata pero
el bootstrap podía omitirla por categoría, creando una falsa expectativa y dejando la
decisión sin efecto.

**Alternativas rechazadas**: tratar cualquier `route_by_channel.instagram=automatic`
como override (ampliaría silenciosamente todas las decisiones automáticas del router);
agregar un segundo marcador al JSON y migrar el estado (duplica la evidencia existente);
revivir `processing` o `dead_letter` (podría duplicar una publicación con outcome
ambiguo).

**Consecuencias**: las promociones existentes y futuras entran a la cola de Instagram
en el próximo ciclo, incluso si la publicación Web quedó pendiente o ausente. La
cola Meta activa tampoco es la única fuente: si el ítem rotó antes del bootstrap, se
recupera el payload que ya conserva `editorial_candidates.json`, con la identidad
original y sin migrar el formato. La
excepción no se extiende a Facebook ni al ruteo automático normal. Se conserva
validación de imagen, deduplicación, `completed`, claims, backoff, rate limit, kill
switch y dead-letter. El bootstrap expone `included_by_manual_override` y
`manual_override_without_web_url`, además de `restored_from_candidate_store`; la UI
confirma el efecto externo antes de guardar.

**Revisar nuevamente cuando**: se agreguen destinos manuales distintos de Instagram o
se quiera que el operador pueda revivir explícitamente un dead-letter después de una
conciliación externa.

### 2026-08-05 — Fuente paparazzi.com.ar: cupo reservado 8+2 en Instagram y carrusel imagen+video

**Decisión**: se agrega paparazzi.com.ar (farándula/espectáculos) como fuente de
scraping (`scraping/base_paparazzi.py`, `main_paparazzi.py`), apagada por defecto
(`SCRAPER_PAPARAZZI_ENABLED=0`). A diferencia de las demás fuentes, sus notas de
Instagram no compiten por `IG_MAX_PER_RUN` (8): `meta/run_ig.py` selecciona dos pools
independientes vía `utils.social_queue.get_pending(..., source_prefix=/exclude_source_prefix=)`
— hasta 8 generales (excluyendo paparazzi) + hasta `IG_PAPARAZZI_MAX_PER_RUN` (2) de
paparazzi — y los concatena. `_allowed_for_instagram` deja pasar cualquier ítem de esa
fuente sin depender de `IG_ALLOWED_CATEGORIES` (su categoría, `espectaculos`, no está en
la lista general por defecto).

Cuando la nota tiene video (la mayoría — el sitio embebe JWPlayer;
`scraping/base_paparazzi.py` resuelve el `media_id` contra el endpoint público
`cdn.jwplayer.com/v2/media/{id}` para obtener una URL mp4 directa y la duración real,
sin headless browser), se publica un carrusel — portada (mismo generador que el resto
del automático, `layout/image_generator.py`) + 1 o 2 slides de video editados con la
misma marca (`utils.video_renderer.render_paparazzi_clips`, nuevo, 1080×1350 igual
aspect-ratio que la portada). Usa como máximo `PAPARAZZI_CAROUSEL_VIDEO_TOTAL_MAX_SECONDS`
(120s) reales del video fuente — las notas fuente son entrevistas de varios minutos,
nunca aptas para publicar completas — y si eso supera
`PAPARAZZI_CAROUSEL_VIDEO_PART_MAX_SECONDS` (60s, límite de Instagram por hijo de video
en un carrusel), lo divide en 2 partes consecutivas de a lo sumo 60s cada una (carrusel
de 3 slides: portada + parte 1 + parte 2). Sin video utilizable, cae al post estándar de
imagen sola — nunca fuerza un carrusel de una sola imagen.
`meta/ig_client.post_paparazzi_carousel_to_instagram` es la función nueva; reutiliza el
mismo `ig_posted.json`/dedup que el flujo automático normal (a diferencia del carrusel
Premium, que es social-only con estado propio), porque estos ítems sí pasan por la cola
social estándar.

**Corrección post-activación (mismo día)**: al activar en producción, el primer ciclo
real mostró que ninguna nota de paparazzi llegaba a Instagram pese al cupo 8+2 — el
gate del router editorial (`EDITORIAL_ROUTER_ENABLED=true`, `_routed_for_instagram` en
`meta/run_ig.py`) es *independiente* del gate de categoría y bloqueaba todo por no
tener vínculo riojano (`gate:no_riojan_link`), algo que farándula nacional nunca va a
tener por diseño. `_routed_for_instagram` ahora bypassa "candidate" específicamente
para la fuente paparazzi (su propio cupo 8+2 + carrusel ES su política editorial, no
necesita también aprobar la del router), pero sigue respetando "suppressed"
(duplicado técnico real — protección que no depende de localidad).

**Corrección #2 (mismo día)**: Facebook no tenía ninguna lógica específica para
paparazzi — `meta/run_fb.py` llamaba `post_to_facebook_detailed` para todo, que sube
video nativo cuando hay `video_url` sin distinguir la fuente. Como el scraper deja el
`video_url` crudo del sitio (la entrevista completa, sin recortar ni marca — ver
`scraping/base_paparazzi.py`), varias notas salieron a Facebook con el video original
sin editar. Nueva función `meta/fb_client.py::post_paparazzi_video_to_facebook`
(dispatchada desde `meta/run_fb.py` igual que en Instagram): sube un único clip
editado vía `utils.video_renderer.render_paparazzi_clips(noticia, split=False)` —
Facebook no tiene el límite de 60s por hijo que sí tiene el carrusel de Instagram, así
que no hace falta dividir en partes; usa el mismo tope de
`PAPARAZZI_CAROUSEL_VIDEO_TOTAL_MAX_SECONDS` (120s) y el mismo branding que la
portada. Sin video utilizable, cae al post estándar (link/imagen), igual que del lado
de Instagram. `render_paparazzi_clips` ganó el parámetro `split` (default `True`) para
que Instagram y Facebook reutilicen exactamente la misma lógica de descarga/recorte/marca
sin duplicar código.

Se validó contra la Graph API real antes de construir el pipeline (spike de un solo
uso, no versionado): un carrusel con hijo `image_url` + hijo `video_url`+`media_type:
"VIDEO"` (ambos `is_carousel_item: "true"`) fue aceptado y publicado con éxito, mismo
aspect-ratio 4:5 en ambos hijos.

**Motivo**: el operador pidió sumar farándula sin diluir el cupo curado de Instagram
que ya tienen las categorías locales (`interior`, `sociedad`, `politica` + breaking), y
pidió específicamente que el video acompañe a la imagen "con el mismo estilo" en vez de
sólo texto.

**Alternativas rechazadas**: subir `IG_MAX_PER_RUN` a 10 y agregar `espectaculos` a
`IG_ALLOWED_CATEGORIES` (dejaría que ambos pools compitan por el mismo cupo sin
garantizar el reparto 8+2); reusar el carrusel Premium tal cual (es social-only, con su
propio estado y sin conexión a la cola/dedup automática que necesitan estas notas
scrapeadas); publicar el video completo de la entrevista sin recortar (excede el límite
de duración de Instagram para hijos de carrusel).

**Consecuencias**: `utils.editorial_priority.item_source()` y los parámetros
`source_prefix`/`exclude_source_prefix` de `get_pending` quedan disponibles como
mecanismo genérico de cupo reservado por fuente — cualquier fuente futura con la misma
necesidad puede reusarlos sin tocar `split_priority_batch`. paparazzi.com.ar
rate-limitea (429) sin pausa entre requests; el scraper aplica su propio
`PAPARAZZI_REQUEST_DELAY_SECONDS` (2.5s), a diferencia de las demás fuentes.

**Revisar nuevamente cuando**: Meta cambie los límites de duración/aspect-ratio para
video en hijos de carrusel, o se quiera un cupo reservado por fuente para más de una
fuente a la vez (hoy el mecanismo soporta N fuentes vía prefijo, pero sólo paparazzi lo
usa).

### 2026-08-05 — Estadísticas de Instagram promueven candidatas de buen rendimiento

**Decisión**: nueva etapa `meta/ig_insights.py` (agregada a `CYCLE_STEPS` en
`run_24x7.py` y `CYCLE_SCRIPTS` en `cli.py`, tag de canal `instagram`), apagada por
`IG_STATS_ENABLED`. Cada ciclo trae `reach`/`total_interactions` de hasta
`IG_STATS_MAX_POSTS_PER_RUN` (30) publicaciones recientes de `ig_posted.json`
(usando el campo `seccion` que cada publicación ya guarda) y agrega una tasa de
interacción (`total_interactions / reach`) por categoría normalizada, persistida en
`data/ig_category_performance.json`. Sólo hace `GET`; nunca publica ni toca colas.

El router editorial (`utils/editorial_router.py::evaluate_routing`) gana un segundo
camino para pasar el gate de localidad: si la nota no tiene vínculo riojano
confirmado (`detect_riojan_link`) pero su categoría tiene rendimiento fuerte
(`utils.category_performance.is_strong_performing_category` — tasa de interacción de
la categoría ≥ tasa promedio de la cuenta × `IG_STATS_PROMOTION_THRESHOLD_RATIO`
(1.0), con al menos `IG_STATS_MIN_SAMPLE_SIZE` (5) publicaciones de muestra), pasa
igual que si tuviera vínculo riojano confirmado. Deliberadamente **no** bypassa nada
más: breaking, material_update y sobre todo `TOPIC_AUTOMATIC_CAP` (el tope por tema)
se evalúan exactamente igual después — el rendimiento histórico decide si una
categoría entera merece confianza, no si un tema puntual puede saturar el feed.
`evaluate_routing` sigue siendo pura (recibe `category_performance` ya cargado por el
llamador, `utils.category_performance.load_category_performance()`, que devuelve `{}`
— mismo efecto que sin datos — si `IG_STATS_PROMOTION_ENABLED` está apagado o el
archivo no existe todavía). `openIA/rewrite_news.py` lo carga una sola vez por
corrida, no por noticia.

**Motivo**: el operador reportó ver demasiadas candidatas pendientes de revisión
manual (181 al momento de esta decisión — Deportes 53, Política 38, Policiales 36,
etc.), producto de que `detect_riojan_link` es puramente determinístico
(hashtag/categoría "interior"/keyword de localidad) y no tiene forma de reconocer que
una categoría entera viene funcionando bien en Instagram aunque una nota puntual no
mencione una localidad riojana. Pidió explícitamente usar las estadísticas reales de
Instagram como señal para no exigir revisión manual en esos casos.

**Alternativas rechazadas**: ampliar `IG_ALLOWED_CATEGORIES` estáticamente según
rendimiento (se discutió pero se descartó — mezclar un gate estático con una señal que
cambia con el tiempo es más confuso que extender el router, que ya es el lugar
correcto para decisiones caso-por-caso); usar alcance (`reach`) solo en vez de tasa de
interacción (el operador pidió específicamente la tasa, que normaliza por alcance en
vez de premiar posts que simplemente llegaron a más cuentas sin generar reacción).

**Consecuencias**: con la cuenta todavía joven (pocas publicaciones, historial de
horas no de meses), la mayoría de las categorías no van a alcanzar
`IG_STATS_MIN_SAMPLE_SIZE` todavía — el efecto práctico crece a medida que
`ig_posted.json` acumula más publicaciones con estadísticas reales. `IG_STATS_ENABLED`
y `IG_STATS_PROMOTION_ENABLED` son flags independientes: se puede recolectar
estadísticas sin que cambien las decisiones de ruteo (útil para observar antes de
confiar), o apagar solo la promoción sin perder la recolección.

**Revisar nuevamente cuando**: haya suficiente historial (semanas, no días) para
evaluar si `IG_STATS_PROMOTION_THRESHOLD_RATIO=1.0` es el punto justo, o si conviene
diferenciar el umbral por categoría en vez de un único ratio global.

### 2026-08-05 — El clip de video paparazzi se marca con Remotion, no PIL/ffmpeg

**Decisión**: nueva composición Remotion `PaparazziClip` (1080×1350,
`remotion/src/PaparazziClip.tsx`, registrada en `Root.tsx`) reemplaza el overlay
PIL/ffmpeg simple (barra de color + logo) que marcaba el clip del carrusel paparazzi
hasta ahora. La composición reusa exactamente el mismo chrome de marca que
`AutomaticInstagramCard` (la portada del mismo carrusel): `StillLayout` +
`EditorialMasthead` (logo, "La Voz Riojana", sección con color de `mode.accent`) +
`SocialFooter` (íconos FB/IG + `lavozriojana.com`), sin título propio (el titular ya
vive en la portada). El video fuente se compone con el mismo truco que
`EditorialReel` para material que no es nativamente 4:5 (entrevistas sueles ser
16:9): fondo blureado a pantalla completa (`@remotion/media` `&lt;Video&gt;` con
`objectFit="cover"` + `blur(50px)`) + copia nítida encima en `objectFit="contain"`,
sin recorte feo.

Del lado Python, `utils.video_renderer.render_paparazzi_clips` ahora recorta el
segmento con ffmpeg puro (`_ffmpeg_trim_clip`, sin marca) y se lo pasa a
`_render_remotion_paparazzi_clip` (mismo patrón que `_render_remotion_main`: copia el
asset a `remotion/public/tmp/`, escribe props a JSON, `npx remotion render
PaparazziClip ... --props=...`). Si Remotion/Node no está disponible o el render
falla, cae al overlay PIL/ffmpeg anterior (`_paparazzi_overlay` +
`_ffmpeg_compose_paparazzi_clip`, ahora operando sobre el clip ya recortado en vez de
recortar+marcar en un solo paso) — mismo patrón de fallback que `render_video()` con
`Main`/`EditorialReel`. No hay flag nuevo: la disponibilidad de Remotion es el gate,
igual que en el resto del sistema.

**Motivo**: el operador pidió explícitamente que la edición de video use el mismo
sistema Remotion/"Editorial Cinemática Riojana" que ya se ve en la UI manual de Reels
(127.0.0.1:8765) en vez del overlay simple — el video del carrusel quedaba visualmente
desprolijo al lado de una portada ya renderizada con el sistema de diseño completo.

**Hallazgo durante la investigación**: el sistema de diseño Remotion
(`designSystem.ts::SECTION_MODE`) mapea `espectaculos` al modo `"editorial"` (acento
azul), mientras que `layout/image_generator.py::SECTION_COLORS` lo mapea a rojo. El
overlay PIL de fallback sigue usando el rojo de `layout/image_generator.py` (no se
tocó, es sólo el camino degradado) — si se quiere reconciliar, hay que decidir cuál de
los dos sistemas es la fuente de verdad para esa categoría.

**Alternativas rechazadas**: reescribir `_paparazzi_overlay` en PIL para que se vea
más parecido a mano (no logra paridad real con el sistema de diseño — tipografía,
gradientes y el truco de blur-backdrop para video no-4:5 son mucho más simples de
mantener en React/Remotion, que ya es la fuente de verdad visual del resto del
sistema); renderizar el video completo con `EditorialReel` y recortarlo a 4:5 después
(esa composición es 9:16 con outro/título pensados para Reels independientes, no para
un slide de carrusel — recortar post-render pierde el control fino del encuadre).

**Consecuencias**: cada segmento ahora pasa por un recorte ffmpeg previo (sin marca)
antes del render Remotion — un paso más que antes, pero necesario porque
`&lt;Video&gt;` de Remotion reproduce el archivo completo tal cual (no hay trim por
props en esta composición); es más simple recortar antes que sumar lógica de offset
de frames a la composición. Los renders Remotion de video (a diferencia de los
stills) siempre son un subprocess fresco (`npx remotion render`), sin servidor
persistente — mismo costo por render que ya tenían `Main`/`EditorialReel`.

**Revisar nuevamente cuando**: se quiera evitar el recorte ffmpeg previo agregando
soporte de `startFrom`/duración por props directamente en `PaparazziClip`, o se
decida reconciliar el color de "espectaculos" entre `designSystem.ts` y
`layout/image_generator.py`.

### 2026-08-10 — Reel independiente de paparazzi (video solo), motor 127.0.0.1:8765

**Decisión**: cuando una nota de paparazzi.com.ar con video fuente ya se publicó con
éxito como carrusel/video estándar (`meta.ig_client.post_paparazzi_carousel_to_instagram`,
que dispara internamente el video nativo de Facebook también — ver decisión
2026-08-05), `meta/run_ig.py` dispara además, best-effort,
`utils.paparazzi_reels.publish_paparazzi_reel(noticia)`: renderiza un Reel con el
mismo motor que la UI manual (`utils.video_renderer.render_video` — Remotion
`EditorialReel`/`Main` con título superpuesto, distinto del clip de marca simple sin
título que usa el carrusel, `PaparazziClip`) a partir del mismo `video_url` crudo del
scraper, lo sube a R2 y lo publica como **segunda publicación independiente** en
Instagram (`media_type: REELS`) y Facebook (`/videos`).

Nuevas funciones "tontas" sin dedup propio —
`meta.ig_client.post_reel_video_to_instagram` y
`meta.fb_client.post_reel_video_to_facebook`, ambas toman un `item` con `video_url` ya
hosteado en R2 y publican sin chequear duplicados. La idempotencia vive enteramente en
`utils/paparazzi_reels.py`, con estado propio (`data/paparazzi_reels_posted.json`,
dedup_key `reel:{hash}` derivado de la misma identidad que el carrusel) — a propósito
separado de `ig_posted.json`/`fb_posted.json`: si reusara ese estado, el chequeo de
"publicación similar previa" (`_posted_duplicate_reason`, mismo `canonical_url`/`url`
que el carrusel ya publicado) bloquearía el Reel pensando que es un duplicado técnico,
cuando en realidad es una segunda publicación intencional en otro formato. Mismo
patrón que el carrusel premium (`premium_ig_posted.json`) para el mismo problema.

Apagado por defecto (`PAPARAZZI_REEL_ENABLED=false`) — no cambia el comportamiento
actual hasta activación explícita, siguiendo el mismo patrón que el resto de los kill
switches del proyecto. Con el flag encendido, cada plataforma respeta además su propio
switch (`IG_PUBLISH_ENABLED`/`FB_PUBLISH_ENABLED`): si sólo una está prendida, el Reel
se publica sólo ahí, nunca bypassa el switch de la otra. Si el video fuente no se
puede descargar al momento de renderizar (`render_info["source_used"] != "video"` —
cayó a Ken Burns/overlay), no se publica nada: este flujo es explícitamente "el video
solo", no un Reel de imagen.

**Motivo**: el operador pidió que las notas de paparazzi que ya salen con video en el
carrusel/nativo también salgan como Reel independiente (mejor alcance orgánico que un
hijo de carrusel), usando el mismo generador con título superpuesto que ya usa a mano
en la UI de Reels (127.0.0.1:8765) en vez del branding sin título del clip de
carrusel.

**Alternativas rechazadas**: reusar `ig_posted.json`/`fb_posted.json` con un
`dedup_key` distinto (el `dedup_key` exacto sí es único, pero
`_posted_duplicate_reason`/`_is_posted` de esos estados igual comparan por
`canonical_url`/`url` contra registros ya existentes, bloqueando el Reel); armar un
nuevo stage/script (`meta/run_paparazzi_reels.py`) con su propio canal en
`run_24x7.py`/`cli.py`/`utils/deployment.py` (más superficie para una función que
sólo aplica a un subconjunto de una sola fuente ya gateada por su propio flag; el
punto natural para generar el Reel es el mismo lugar donde ya se conoce el `noticia`
completo recién publicado, sin tener que releer ningún estado); recortar el video
fuente antes de pasarlo a `render_video` (innecesario — `render_video` ya limita a
90s reales del inicio del video, igual que si un operador pegara la misma URL larga en
la UI manual).

**Consecuencias**: una nota de paparazzi con video puede terminar publicada hasta 3
veces (carrusel IG, video nativo FB, Reel IG+FB) — intencional, no es un bug de dedup.
El renderizado ocurre síncronamente dentro del loop de `run_ig.py` (mismo patrón que
ya tenía el recorte del carrusel), agregando latencia por nota paparazzi cuando el
flag está activo. Cualquier fallo del Reel (render, R2, Graph API) se loguea pero
nunca afecta el resultado/contadores de la etapa `instagram` ni la publicación ya
confirmada del carrusel.

**Revisar nuevamente cuando**: se quiera medir el Reel independiente con estadísticas
propias (hoy `meta/ig_insights.py` sólo lee de `ig_posted.json`, no de
`paparazzi_reels_posted.json`), o se decida que el recorte de duración deba usar una
ventana distinta a "los primeros 90s" (por ejemplo, el mismo criterio de
`render_paparazzi_clips`).

### 2026-08-15 — Fuente infobae.com/sociedad/policiales/ y lote único de publicación (3 baldes) para Web/Facebook/Instagram

**Decisión**: se agrega infobae.com/sociedad/policiales/ (`scraping/base_infobae.py`,
`main_infobae_policiales.py`, apagada por defecto hasta probarse, luego habilitada) como
segunda fuente de policiales nacional/video, junto a paparazzi.com.ar. A diferencia de
TN.com.ar (evaluado y descartado: su player vodgc/Genoa resuelve el video con JS
ofuscado, sin endpoint público), Infobae embebe JWPlayer estándar — el JSON-LD
`VideoObject.contentUrl` de la nota ya trae la URL mp4 directa
(`cdn.jwplayer.com/videos/{id}.mp4`), sin resolver nada contra una API ni headless
browser. Política propia de la fuente: sólo se guarda una nota si tiene video o vínculo
riojano (`utils.editorial_router.detect_riojan_link`, reutilizado tal cual) — el resto
se descarta en el scraping mismo, antes de gastar reescritura, vía un nuevo parámetro
`extra_discard` en `scraping/runner.py::run_section` (opcional, `None` por defecto —
aditivo, no cambia el comportamiento de ninguna otra fuente).

Al mismo tiempo se reemplazó por completo el criterio de qué se publica en cada canal.
Antes: Web publicaba casi todo (sólo tope de Deportes=1/corrida), Facebook publicaba
literalmente todo lo que tuviera `web_url` (sin ningún filtro), e Instagram era el único
canal con curación real — un gate de categoría (`IG_ALLOWED_CATEGORIES`) más el router
editorial (`detect_riojan_link`, candidate/automatic), y paparazzi tenía además un cupo
reservado propio (`IG_PAPARAZZI_MAX_PER_RUN=2`) que bypassaba ese gate por completo. El
resultado observable: Instagram se llenaba de espectáculo (paparazzi, vía reservado sin
gate) mientras notas locales/policiales de La Rioja genuinas quedaban en `"candidate"`
sin publicarse — el gate de vínculo riojano exige mencionar literalmente una de ~20
localidades en el texto, algo que un medio riojano no siempre repite porque el contexto
ya es local.

Se reemplaza todo eso por un único cálculo de lote (`utils/publish_selection.py`,
`select_publish_batch.py` — nueva etapa en `run_all.py`, después de
`openIA/rewrite_news.py`) que decide qué se publica una sola vez por ciclo y lo marca
(`selected_for_publish`, `publish_batch_id`, `publish_bucket`) en ambas colas de salida
de la reescritura (`noticias_meta.json` y `noticias_web_pending.json`, correlacionadas
por `canonical_url`/`url`) — Web, Facebook e Instagram terminan publicando exactamente
el mismo lote, en vez de cada uno decidir por su cuenta. Tres baldes por corrida:
- **Local** (`PUBLISH_LOCAL_MAX_PER_RUN=6`): cualquier fuente que no sea paparazzi ni
  infobae, en el orden de prioridad editorial ya existente
  (`utils.editorial_priority.priority_interleave`, que ya prioriza
  policiales/interior por delante de política/sociedad/deportes) — sin código nuevo
  para el orden. Al excluir paparazzi/infobae por fuente (no por categoría ni por
  texto), el gate de vínculo riojano deja de ser necesario para este balde: todo lo
  que entra ya es de un medio riojano por construcción.
- **Paparazzi** (`PUBLISH_PAPARAZZI_MAX_PER_RUN=2`): video primero, después por el
  score de relevancia que ya calculaba la reescritura (`paparazzi_relevance_score`) —
  sin llamadas de IA nuevas.
- **Infobae** (`PUBLISH_INFOBAE_MAX_PER_RUN=2`): video primero, después por intensidad
  de `BREAKING_KEYWORDS` en el título (proxy gratuito de "fuerte/polémica", sin IA) —
  se evaluó agregar un score con IA como el de paparazzi y se descartó para no sumar
  llamadas por nota.

`meta/run_ig.py` y `meta/run_fb.py` ahora sólo encolan lo marcado `selected_for_publish`
(más `web_url` verificado); `pipeline/node_webapp/publisher.py::publish_pending` hace lo
mismo en vez de `split_priority_batch` con cap de Deportes. Se retiraron por completo
(código y variables): `IG_ALLOWED_CATEGORIES`, `_allowed_for_instagram`,
`_routed_for_instagram`, `IG_PAPARAZZI_MAX_PER_RUN`, `EDITORIAL_ROUTER_ENABLED` (el
router seguía corriendo igual sin el flag — sólo controlaba si `run_ig.py` lo
consultaba), `WEB_PUBLISH_MAX_PER_RUN`/`WEB_MAX_DEPORTES_PER_RUN`/`MAX_DEPORTES_PER_RUN`/
`SOCIAL_MAX_DEPORTES_PER_RUN` y `utils.paparazzi_relevance.passes_relevance_gate` (el
score en sí, `score_relevance`, se conserva — ahora alimenta el orden del balde en vez
de un gate booleano). Lo único del router que sigue gateando Instagram es
`route_by_channel.instagram == "suppressed"` (duplicado técnico real), igual que antes
sólo aplicaba a paparazzi — ahora aplica parejo a cualquier fuente.

**Corrección post-activación (mismo día)**: al reescribir `_matches_manual_automatic`
para depender sólo de `not suppressed` (en vez de exigir además
`route_by_channel.instagram == "automatic"`), un backlog de 50 candidatas que un
operador había promovido manualmente vía UI en días previos — nunca publicadas porque
el gate viejo las mantenía bloqueadas pese a la promoción — entraron todas de una sola
corrida de `run_ig.py`. Varias con video de paparazzi (minutos de procesamiento cada
una) hicieron que la etapa superara el timeout de 1200s dos ciclos seguidos
(`error_type: timeout`, `exit_code: 1`, cero publicadas). Se agregó
`IG_MANUAL_OVERRIDE_MAX_PER_RUN` (default 3): tope combinado entre los dos caminos de
restauración manual de `_bootstrap_queue` (encontradas en `noticias_meta.json` +
recuperadas desde `editorial_candidates.json`), pacea el drenaje del backlog a través
de varias corridas en vez de intentarlo todo junto. Lo no procesado por falta de cupo
no se pierde — sigue en `editorial_candidates.json`, elegible en la próxima corrida.

**Corrección post-activación #2 (mismo día) — la causa real de por qué casi nada
llegaba a Facebook/Instagram**: con el lote nuevo corriendo, `noticias_meta.json`
mostraba **0 de 952 notas con `web_url`** — incluidas las 8 recién seleccionadas por el
lote. El gate que exige `web_url` antes de publicar en redes es intencional (ver
KNOWN_ISSUES #52), pero no debería fallar para casi todo. Dos bugs distintos, ambos
preexistentes a este cambio:

1. `openIA/rewrite_news.py::normalize_meta_queue()` reconstruye **cada ítem** de
   `noticias_meta.json` vía `build_meta_item()` en **cada corrida** del pipeline (no
   sólo la primera vez — corre sin condición alguna dentro de
   `run_rewrite_pipeline()`), y `build_meta_item()` sólo conserva los campos listados
   en `META_FIELDS`. `web_url` (escrito por
   `pipeline.node_webapp.publisher.sync_meta_web_link` justo después de publicar en
   Web) nunca estuvo en esa lista — se borraba en silencio en el ciclo siguiente. Esto
   también amenazaba los campos nuevos de esta misma decisión
   (`selected_for_publish`/`publish_batch_id`/`publish_batch_at`/`publish_bucket`).
   Corrección: se agregaron `web_url`, `noticia_url`, `web_published_at`, `web_slug`,
   `web_post_id` y los 4 campos del lote a `META_FIELDS`. Test de regresión:
   `tests.test_node_webapp_publisher::test_normalize_meta_queue_preserves_fields_written_after_the_fact`.
2. `utils/publish_selection.py::compute_next_batch()` armaba el pool de candidatas
   sólo desde `noticias_meta.json` (952 ítems, un histórico que crece y se poda por su
   propio TTL) sin verificar que el ítem siguiera vivo en `noticias_web_pending.json`
   (29 ítems — se vacía al publicar y se poda por su propio TTL, independiente del de
   meta). Resultado: el lote podía seleccionar notas cuya entrada en la cola web ya
   había expirado semanas atrás, que nunca iban a conseguir `web_url` sin importar
   cuántas veces se recalculara el lote — de las primeras 8 seleccionadas, 7 eran así.
   Corrección: el pool ahora filtra a ítems que ya tienen `web_url` (publicados antes)
   O siguen presentes en `noticias_web_pending.json` (van a publicarse este ciclo o uno
   próximo). Test de regresión:
   `tests.test_publish_selection::test_excludes_meta_items_whose_web_queue_entry_already_expired`.

Reparación de datos (una vez, sobre producción): se restauraron desde backup las 29
entradas de `noticias_meta.json` correspondientes a notas que seguían vivas en
`noticias_web_pending.json` y que un cleanup manual previo había borrado por error (por
tener el mismo síntoma — sin `web_url` — que el backlog genuinamente muerto); se
recuperó `web_url` desde `noticias_web_publicadas.json` para una nota que sí se había
publicado antes; se eliminaron 7 notas sin salida posible (ni `web_url` ni presencia en
la cola web). Validado end-to-end contra producción real tras el fix: Web publicó 7/7,
Facebook 7/7 (incluye video paparazzi editado), Instagram 8/8 (incluye carrusel + reel
de una nota que vino del lote nuevo, no de un override manual) — la cadena
scraping→reescritura→lote→Web→sync→Facebook/Instagram quedó confirmada funcionando de
punta a punta, no sólo en tests.

**Motivo**: el operador pidió sumar policiales/video nacional sin caer en ninguno de los
dos extremos — ni "se publica todo en todos lados" (Web/Facebook de antes) ni "casi
nada local llega a Instagram" (el gate de vínculo riojano de antes) — y que el criterio
de selección sea el mismo en los 3 canales, coherente con un medio local que también
publica espectáculo y policiales/video nacional pero de forma acotada, no dominante.

**Alternativas rechazadas**: TN.com.ar como fuente de policiales/video nacional (video
sin resolver, ver arriba); mantener el gate de vínculo riojano por texto y sólo ampliar
la lista de localidades (no ataca la causa real — un medio riojano no necesita nombrar
la provincia en cada nota); cupo reservado propio para infobae igual que paparazzi
(hubiera mantenido dos mecanismos de selección distintos en vez de uno solo aplicado
parejo).

**Consecuencias**: Web y Facebook dejan de ser un espejo 1:1 de todo lo scrapeado — sólo
publican el lote curado. Cualquier fuente nueva que se agregue en el futuro entra
automáticamente en el balde "local" (no necesita código nuevo) salvo que se le quiera
dar su propio balde nacional, como paparazzi/infobae.

**Revisar nuevamente cuando**: se quiera que el lote sea literalmente idéntico
ítem-por-ítem entre los 3 canales en vez de "mismo criterio, misma marca, cada canal
publica a su propio ritmo" (hoy Web/Facebook/Instagram pueden desfasarse si alguno
falla o queda pendiente); se agregue una tercera fuente nacional (definir si comparte
cupo con paparazzi/infobae o necesita balde propio); o el backlog de candidatas
manuales (`IG_MANUAL_OVERRIDE_MAX_PER_RUN`) se drene por completo y el tope pueda
subirse sin riesgo de timeout.

### 2026-08-15 — El balde local no completa con Deportes/Espectáculos; el cupo libre pasa a paparazzi/infobae

**Decisión**: el operador reportó que se estaba publicando mucho Deportes. Causa:
`utils.publish_selection.select_batch` llenaba el balde local (`PUBLISH_LOCAL_MAX_PER_RUN=6`)
recorriendo todo el orden de prioridad editorial cuando no había 6 candidatas de
policiales/interior — bajando hasta política, sociedad, y finalmente deportes, la
categoría de menor prioridad. Se agrega `PUBLISH_LOCAL_EXCLUDED_CATEGORIES` (default
`deportes,espectaculos`): estas categorías quedan afuera del balde local por completo,
nunca completan aunque no haya nada más disponible esa corrida. La capacidad que el
local deja sin usar (`shortfall = PUBLISH_LOCAL_MAX_PER_RUN - len(local_selected)`) se
reparte entre paparazzi e infobae — mitad y mitad, redondeando a favor de paparazzi —
en vez de perderse; si uno de los dos no tiene candidatas suficientes para usar su
extra, el remanente pasa al otro (`select_batch`, ver docstring).

**Motivo**: Deportes es la categoría de menor prioridad editorial por diseño
(`DEFAULT_CATEGORY_PRIORITY["deportes"] = 9`, la más alta) — llegaba a publicarse sólo
porque completaba el cupo, no porque compitiera bien. El operador prefiere que ese
espacio lo ocupe contenido ya curado (paparazzi con score de relevancia, infobae con
video/intensidad) antes que relleno deportivo de bajo impacto. `espectaculos` se excluye
también porque paparazzi ya cubre esa categoría a nivel nacional con su propio criterio
de selección — no hace falta que el balde local la duplique con contenido local de menor
alcance.

**Alternativas rechazadas**: bajar `PUBLISH_LOCAL_MAX_PER_RUN` (reduciría también
policiales/interior genuino, no sólo el relleno); excluir deportes/espectaculos del todo
el sistema en vez de sólo del balde local (deportes/espectaculos locales fuertes
igual pueden competir si alguna vez se les da un balde propio — acá sólo se les quita
el rol de "relleno automático").

**Consecuencias**: en una corrida sin suficiente policiales/interior/política/sociedad
local, paparazzi e infobae pueden superar su cupo nominal (hasta duplicarlo) esa
corrida puntual — es intencional, no un bug de cupo.

**Revisar nuevamente cuando**: se quiera un balde propio para deportes/espectaculos
local en vez de excluirlos sin más; o `PUBLISH_LOCAL_EXCLUDED_CATEGORIES` necesite
categorías adicionales según cómo evolucione el volumen por fuente.

---

### 2026-08-21 — El servicio corre exclusivamente en una PC de producción dedicada

**Decisión**: `AutoPublicador_LaVozRiojana` sólo se ejecuta 24/7 (supervisor + UI
manual + tareas programadas) en una PC de producción dedicada
(`PC@192.168.1.150`, `C:\LVR`), accedida por SSH con clave. Cualquier otra copia del
repo, incluida la máquina de desarrollo (`pc10`), es exclusivamente para escribir
código, correr tests y validar renders — nunca para correr el servicio real, ni
siquiera temporalmente. El flujo de cambios es: desarrollar/probar en dev → commit →
push → PR con CI (`reliability-windows`) verde → merge a `main` → `git pull` +
reinicio del backend por SSH en la PC de producción.

**Motivo**: la máquina de desarrollo conservaba tareas programadas
(`LaVozRiojana-24x7`, `LaVozRiojana-ManualUI`) del arranque productivo original del
2026-07-27. Al migrar el servicio a la PC dedicada se detuvieron los procesos en dev
pero no se borraron esas tareas, que lo relanzaron solas cada 5 minutos con
credenciales productivas reales — dos instancias vivas, con las mismas credenciales
de Facebook/Instagram/OpenAI/R2/CMS, sin compartir estado de deduplicación entre sí.
Ver el incidente completo en `docs/KNOWN_ISSUES.md` #84.

**Alternativas rechazadas**:
- Dejar ambas máquinas capaces de correr el servicio y confiar en que el operador
  recuerde apagar una antes de encender la otra: rechazada porque ya falló una vez
  de esta forma exacta, y el costo de un error (publicación duplicada en redes con
  cuentas reales) es alto y visible públicamente.
- Compartir un único `.env`/`data/` entre ambas máquinas (por ejemplo, por una
  carpeta de red): rechazada porque el bloqueo de archivos (`FileLock`) protege
  contra corrupción de un JSON individual, pero no fue diseñado ni probado para dos
  supervisores completos compitiendo por las mismas colas desde dos hosts.

**Consecuencias**: todo cambio de código tarda un paso más en llegar a producción
(push + PR + merge + pull + restart por SSH, en vez de simplemente reiniciar en el
lugar donde se editó). A cambio, dev puede tener `.env` de pruebas, credenciales
apagadas o `PIPELINE_DEPLOYMENT_MODE=observe` sin ningún riesgo de que eso se
confunda con producción real. El procedimiento de despliegue queda documentado en
`docs/RUNBOOK.md` ("Entorno: desarrollo vs. producción").

**Revisar nuevamente cuando**: se decida automatizar el despliegue (CI/CD real hacia
la PC de producción) en vez de `git pull` manual por SSH; o se agregue una segunda
PC de producción, caso que `Ops\docs\ARCHITECTURE.md` (proyecto hermano HolaSalta)
ya advierte que requiere asignar capacidades/recursos explícitos, no asumir un
segundo agente con todo habilitado por default.

---

### 2026-09-10 — SQLite derivado para el Archive Context Engine (no reemplaza JSON)

**Decisión**: crear `data/derived/editorial_context.sqlite3` (índice FTS5 con
fallback `LIKE`, probado en runtime) como índice **derivado, reconstruible y no
autoritativo** para el Archive Context Engine y Story Engine
(`docs/EDITORIAL_CONTEXT.md`). Las colas JSON siguen siendo el estado autoritativo.

**Motivo**: la decisión previa de 2026-07-23 rechazó migrar a SQLite como
*reemplazo* de JSON por falta de evidencia de volumen — esa razón sigue vigente y no
se contradice acá. Lo que se necesita ahora es un índice de búsqueda full-text sobre
miles de notas históricas para el retrieval en dos pasos (Parte 7 del plan de
contexto editorial), algo que recorrer JSON completo no puede resolver a un costo
razonable, y que además puede borrarse y reconstruirse sin ningún riesgo (`cli.py
archive-index rebuild`), a diferencia de las colas productivas.

**Alternativas rechazadas**: reemplazar las colas JSON por SQLite (fuera de alcance
y contradiría la decisión anterior); mantener sólo búsqueda en memoria sobre JSON
completo por ciclo (no escala con miles de notas ni sobrevive reinicios sin
recalcular todo).

**Consecuencias**: nueva dependencia de runtime (sqlite3, ya en la stdlib, sin
paquete nuevo) y un archivo binario nuevo en `data/derived/` (gitignored). Si el
build de `sqlite3` del host no soporta FTS5, se usa automáticamente un fallback
`LIKE` más lento pero funcional — confirmado disponible en Python 3.10.0 (mismo
build que producción) al momento de esta decisión.

**Revisar nuevamente cuando**: el volumen de `archive_articles` crezca lo
suficiente como para que el fallback `LIKE` (si algún host no soporta FTS5) se
vuelva lento; o se quiera exponer un buscador de noticias público
(`ArchiveSearchProvider` ya está diseñado para eso, Parte 48).

---

### 2026-09-10 — Backfill del archivo propio vía API del CMS, no sitemap

**Decisión**: usar `GET /api/public/posts` (endpoint de lectura ya existente del
CMS propio) como fuente principal de backfill histórico
(`editorial_context/archive_backfill.py`), en vez de sitemap + JSON-LD por
artículo como sugiere el orden de preferencia genérico de la Parte 6 del plan.

**Motivo**: `noticias_web_publicadas.json` resultó ser sólo una ventana rodante de
7 días (podada en cada lectura por `publisher.py::_load_published_history`), no un
histórico completo — el plan ya anticipaba que podía hacer falta backfill. El
endpoint público del CMS ya devuelve exactamente los campos necesarios
(slug/título/excerpt/categoría/fecha/tags) paginado, en una sola llamada por
página; sitemap + JSON-LD hubiera requerido primero descubrir todas las URLs y
después un fetch HTML por artículo — más requests, más lento, mismo resultado.

**Alternativas rechazadas**: sitemap + JSON-LD por artículo (más caro, más lento,
sin ventaja de datos); scraping del HTML público de cada nota (innecesario
existiendo un endpoint JSON propio).

**Consecuencias**: el backfill depende de que `GET /api/public/posts` no cambie de
forma sin aviso — los nombres de campo se tomaron de la auditoría del repo
`LaVozRiojana`, no de una respuesta real verificada; queda como riesgo abierto
documentado (`docs/EDITORIAL_CONTEXT_PROGRESS.md`).

**Revisar nuevamente cuando**: se confirme el formato exacto de
`GET /api/public/posts` contra una respuesta real; o el CMS cambie ese contrato.

---

### 2026-09-10 — `metadata` JSON existente para "En contexto", columna nueva sólo para `storyKey`

**Decisión**: en el CMS (`Post`), agregar únicamente una columna nueva real
(`storyKey String? @db.VarChar(160)`, indexada) para el timeline; el antecedente
"En contexto" (cuando no hay timeline) se guarda dentro del campo `metadata Json?`
que ya existía (`metadata.archiveContext`), sin modelo ni migración adicional.

**Motivo**: `storyKey` necesita un índice real porque se consulta con `WHERE
storyKey = ? ORDER BY publishedAt` sobre potencialmente miles de posts — un campo
JSON no indexable no serviría ahí. El antecedente de "En contexto" es sólo para
mostrar 1-2 notas relacionadas en la UI, no se consulta por ese campo desde SQL, así
que reusar `metadata` (ya presente, ya nullable, ya sin impacto en notas viejas) es
la solución más simple que cumple la Parte 41 ("preferir la solución más simple").

**Alternativas rechazadas**: tabla `Story` completa + tabla `PostRelation` (Parte
41 lo permite, pero es arquitectura de más para lo que hace falta hoy — no hay
necesidad de metadata de historia más allá de agrupar por `storyKey`); una segunda
columna JSON dedicada a `archiveContext` (redundante con `metadata`, que ya cumple
la misma función sin nueva migración).

**Consecuencias**: `metadata.archiveContext` es JSON libre sin validación de schema
en el lado de lectura — `components/news/ArchiveContextNote.tsx` lo parsea de forma
defensiva (`parseArchiveContext`), tolerando forma inesperada sin romper el render.

**Revisar nuevamente cuando**: se necesite consultar por contenido de
`archiveContext` desde SQL (ej. reportes), momento en que sí justificaría una tabla
propia.

---

### 2026-09-10 — HTML_INDEX por sección en vez de sitemap para `argentina.gob.ar`

**Decisión**: para las 10 fuentes nacionales bajo `www.argentina.gob.ar`
(Gendarmería, PFA, Vialidad Nacional, Salud Nación, Educación Nación, ARCA, SENASA,
Energía Nación, Prefectura, Seguridad Nación), usar HTML_INDEX por sección en vez
de sitemap, pese a que el orden de preferencia genérico de la Parte 21 pone sitemap
por encima de HTML index.

**Motivo**: se confirmó con un fetch real que `sitemap.xml` de ese dominio es un
índice genérico de **todo el portal** (miles de URLs de trámites, ministerios y
contenido histórico desde 2017 mezclados), sin forma barata de filtrar sólo la
sección de noticias de un organismo. El índice HTML por sección
(`/gendarmeria/noticias`, etc.) da exactamente lo que hace falta con un solo
request por sección.

**Alternativas rechazadas**: descargar y filtrar el sitemap completo del portal
(mucho más pesado y lento por sección que un solo HTML index, sin ninguna ventaja
de datos).

**Consecuencias**: el adapter genérico `sources/strategies/html_index.py` es una
heurística (anchors con texto largo, mismo host, path con ≥2 segmentos, fecha
opcional del contenedor cercano) — no un scraper a medida por sitio, así que puede
devolver `published_at` vacío para algunos ítems o requerir ajuste si el sitio
cambia de plantilla. Se acepta ese costo de precisión a cambio de mantenibilidad
(Parte 21: preferir lo simple/mantenible).

**Revisar nuevamente cuando**: `source_metrics` muestre `parse_failures` altos o
`items_new` en cero sostenido para alguna de estas fuentes.

---

### 2026-09-10 — Corrección: no mandar `authorName` fijo por categoría

**Decisión**: eliminar `pipeline/node_webapp/publisher.py::_CATEGORY_AUTHORS`
(mapeaba categoría → `"Redacción Política"`, `"Redacción Deportes"`, etc.) y dejar
de mandar `authorName` en el payload cuando no hay autor explícito, para que el CMS
resuelva su propia política editorial actual (Fernando Nahim Mora,
`lib/post-mutations.ts::resolveAuthor`).

**Motivo**: hallazgo de la auditoría inicial de esta etapa —
`_CATEGORY_AUTHORS` contradecía directamente la Parte 61 del plan de contexto
editorial, que pide explícitamente mantener la política real del CMS y no
reintroducir bylines tipo "Redacción X". El CMS ya tenía el fallback correcto
implementado (commit previo "Consolidar autoría: Fernando Nahim Mora firma real de
todas las notas" en el repo `LaVozRiojana`); el autopublicador lo estaba
sobrescribiendo en cada publicación sin que nadie lo pidiera así.

**Alternativas rechazadas**: mandar `authorName: "Fernando Nahim Mora"` explícito
desde el autopublicador (duplicaría la política editorial en dos repos; si el CMS
cambia de responsable editorial en el futuro, el autopublicador quedaría
desactualizado sin que nadie lo note).

**Consecuencias**: las notas publicadas a partir de este cambio muestran el autor
real (Fernando Nahim Mora) en vez de un nombre de sección genérico. No afecta notas
ya publicadas (no se hizo backfill de autoría histórica, fuera de alcance de esta
etapa).

**Revisar nuevamente cuando**: el CMS cambie su política de autoría por defecto —
en ese caso, esta ausencia deliberada de `authorName` seguiría siendo correcta (el
autopublicador seguiría delegando en el CMS), no haría falta tocar nada acá.

---

### 2026-09-10 — Fuentes sin estrategia confirmada quedan deshabilitadas, nunca adivinadas

**Decisión**: `policia_larioja`, `salud_larioja`, `secretaria_justicia_larioja`,
`anses`, `indec`, `smn_alerts` y `boletin_oficial_larioja` quedan sembradas en
`config/official_sources.json` con `enabled=false` y una razón documentada en
`notes`, en vez de forzar una estrategia sin evidencia real de que funciona.

**Motivo**: un relevamiento técnico real (fetch en vivo, no inferencia) mostró que
estas fuentes no tienen un mecanismo de descubrimiento confirmado hoy: sin
alternativa a Facebook, sitio caído, HTML sin listado real, contenido cargado por
JS sin endpoint visible, o dominio sin provenance oficial confirmada. Inventar una
estrategia sin confirmarla arriesgaría publicar con datos de un parser roto o de
una fuente ilegítima. Ver `docs/OFFICIAL_SOURCES.md` para el detalle por fuente.

**Alternativas rechazadas**: implementar un adapter "mejor esfuerzo" para cada una
igual (rechazado explícitamente por el plan: "no inventar, comprobar"; y por el
criterio de decisión general de este proyecto de preferir no perder/corromper datos
antes que sofisticación).

**Consecuencias**: quedan sin cobertura automática algunas fuentes de prioridad
HIGH/CRITICAL del plan (notablemente ANSES e INDEC, relevantes para economía). El
`SourceSelector` simplemente no las selecciona mientras estén deshabilitadas.

**Revisar nuevamente cuando**: alguien confirme manualmente (o con un fetch real
con headers de navegador, no sólo el usado en este relevamiento) un mecanismo
estable para alguna de estas fuentes.
