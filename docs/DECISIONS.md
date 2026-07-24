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
