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
