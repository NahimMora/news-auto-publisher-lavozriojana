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
