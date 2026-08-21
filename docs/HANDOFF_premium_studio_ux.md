# Handoff: rediseño de Estudio Premium (branch `feature/premium-studio-ux`)

Contexto para retomar este trabajo en otra sesión/herramienta (Codex u otra).
Rama activa: `feature/premium-studio-ux`, creada desde `main` en `4b8a1c7`
(el merge del PR #2 ya está en producción y funcionando — no tocar `main`
directamente, todo este trabajo es nuevo y va en PR aparte).

## Estado de ejecución al cierre

El plan de este documento quedó **implementado de punta a punta** y está en el
[PR draft #3](https://github.com/NahimMora/news-auto-publisher-lavozriojana/pull/3),
abierto contra `main`; no fue mergeado ni publicado en cuentas reales.

Commits lógicos:

- `0712834` — generador de paquetes premium desde texto + tests;
- `3b7f470` — miniaturas HTTP confinadas + tests de biblioteca;
- `3cfd6f9` — endpoints seguros, rediseño en cuatro pasos y tests HTTP/E2E;
- `ad8b753` — documentación completa del comportamiento y QA.

Validación: 350 tests ejecutados OK (1 skip de clase que agrupa cuatro renders
Remotion live), 31 tests focalizados OK, 17/17 E2E local dry-run,
`doctor core/all` 8/8 con overrides seguros, `compileall`, sintaxis JS,
`git diff --check` y CI `reliability-windows` verdes. El detalle y las excepciones
del host están en `docs/METRICS.md`.

Las secciones “Ya hecho” y “Falta hacer” de abajo conservan el plan original como
trazabilidad; todos sus puntos quedaron resueltos en el PR.

## Pedido original del usuario (verbatim, traducido a tareas)

> "quiero modificarlo: quiero mas claridad, quiero poner yo un texto de la
> noticia actualizada que quiero, luego empezar, que se haga sola la
> estructura del json, profesionalmente y que luego en asignar imagen que
> pueda poner un link, seleccionar de mi galeria o buscar en la biblioteca
> pero que en la biblioteca salga cual es la imagen"

Es decir, en Estudio Premium (tab de `video_reel_manager.py`, UI manual en
`http://127.0.0.1:8765/`):
1. Más claridad de flujo (pasos numerados, igual que otras tabs).
2. Pegar el texto de la noticia y que la IA arme el JSON del paquete
   automáticamente (el usuario eligió explícitamente **"Sí, con OpenAI
   (recomendado)"** frente a la alternativa de plantilla mecánica sin IA).
3. Al asignar imagen a cada slide, tres formas: pegar un link, subir desde
   "mi galería" (subida de archivo propio), o buscar en la biblioteca — y en
   los resultados de biblioteca **tiene que verse la miniatura**, cosa que
   hoy no pasa (`searchPremiumLibrary()` es sólo texto).

Restricciones que siguen vigentes en todo momento:
- No modificar `main` / no deployar nada de esto a producción sin que el
  usuario lo pida explícitamente.
- `.env`: nunca leerlo completo ni imprimirlo; sólo grep puntual de nombres
  de variables o append con ruta absoluta, nunca overwrite.
- "No inventar datos": cualquier generación por IA debe basarse sólo en el
  texto que pega el operador, nunca investigar/completar información nueva.
- No hacer merge de PRs vía git directo si `gh pr merge` es bloqueado por el
  clasificador de auto-mode — avisar al usuario y que lo haga desde GitHub UI.

## Ya hecho

- **`openIA/premium_package_generator.py`** (archivo nuevo, completo, no
  commiteado todavía — está *untracked* en el working tree). Sigue las
  convenciones de `openIA/caption_generator.py`:
  - `generate_premium_package_json(raw_text: str) -> str`: llama a OpenAI en
    modo JSON (`response_format={"type": "json_object"}`), usa
    `OPENAI_API_KEY`/`OPENAI_MODEL`/`OPENAI_RETRY_COUNT`/`OPENAI_RETRY_SLEEP`/
    `OPENAI_TIMEOUT` (mismas env vars que el resto del pipeline).
  - A diferencia de `caption_generator.py`, **no** tiene fallback silencioso:
    lanza `PremiumGenerationError` si falla tras los reintentos, porque es
    una acción manual/bloqueante del operador (debe ver el error, no recibir
    un paquete degradado sin saberlo).
  - El prompt de sistema exige no inventar datos, fija las 10 categorías
    válidas (`policiales, interior, sociedad, economia, salud, educacion,
    deportes, cultura, espectaculos, politica`), los 3 templates
    (`lvr_cronica, lvr_datos, lvr_visual`), pide 3-5 slides con
    `cover` primero y `closing` al final, y pide `asset_hint` corto por
    slide para poder sugerir imágenes de biblioteca.
  - La salida tiene EXACTAMENTE la forma del contrato de importación
    ChatGPT que ya consume `utils/premium_importer.py::import_chatgpt_package`
    (`title, caption, section, suggested_template, slides[], sources,
    unknowns`), o sea que el endpoint nuevo debe reusar
    `import_chatgpt_package` para validar — **no duplicar** esa lógica.

## Falta hacer (en orden sugerido)

### 1. Endpoint `/api/premium/generate` en `video_reel_manager.py`

Insertar junto a los demás handlers de Estudio Premium, justo antes de
`/api/premium/import` (línea ~2178 en la versión actual del archivo,
método `do_POST`, dentro del `try` que parsea `payload`):

```python
if path == "/api/premium/generate":
    from openIA.premium_package_generator import PremiumGenerationError, generate_premium_package_json
    from utils.premium_importer import import_chatgpt_package
    from utils.premium_post_queue import save_package

    raw_text = str(payload.get("raw_text") or "")
    if not raw_text.strip():
        self._json(400, {"error": "raw_text requerido"})
        return
    try:
        generated_json = generate_premium_package_json(raw_text)
    except PremiumGenerationError as exc:
        self._json(422, {"error": str(exc)})
        return
    package, errors, warnings = import_chatgpt_package(generated_json)
    if package is not None:
        package = save_package(package)
    self._json(200, {"package": package, "errors": errors, "warnings": warnings, "generated_json": generated_json})
    return
```

Notar que devuelve también `generated_json` (el texto crudo) para que la UI
pueda, si quiere, mostrarlo/permitir edición manual antes de importar —
mismo patrón que ya usa `/api/premium/import`.

### 2. JS: nuevo flujo "Paso 1: pegar texto → generar"

En el bloque HTML de Estudio Premium (~línea 500-555) y su JS (~línea 1150
en adelante, junto a `importPremiumPackage()`):
- Agregar un textarea nuevo (p.ej. `premium_raw_article_text`) con label
  "Pegá acá el texto actualizado de la noticia" y un botón "Generar
  estructura con IA" que llame a una nueva función `generatePremiumPackage()`
  análoga a `importPremiumPackage()` pero contra `/api/premium/generate`.
- Mantener el textarea/botón de import manual existente (`premium_import_text`
  + `importPremiumPackage()`) como opción secundaria ("¿ya tenés el JSON? pegalo
  acá"), no reemplazarlo — cubre el caso de que el operador ya use ChatGPT por
  su cuenta.
- Reusar `renderPremiumEditor()`/`renderPremiumSlides()` ya existentes para
  mostrar el resultado — el shape de respuesta es idéntico al de
  `/api/premium/import`.

### 3. Asignación de imagen por link (Task #13)

Necesita: endpoint nuevo, p.ej. `POST /api/premium/asset-from-url`, que:
- reciba `{url, slide_index o similar}`,
- valide la URL con `utils/safe_http.py` (revisar esa utilidad — ya existe
  en el repo, usarla para evitar SSRF/descargas arbitrarias; seguir el
  patrón que ya usa el resto del pipeline para descargar imágenes de
  fuentes externas),
- descargue los bytes y los pase a
  `utils.media_library.ingest_image_bytes(data, filename=..., origin="premium_link", source_url=url)`,
- devuelva el `asset_id`/`resource_id`/`thumbnail` igual que hace
  `_suggest_assets()` en `premium_importer.py` (líneas 40-59), para que el
  frontend pueda asignarlo al slide igual que una sugerencia de biblioteca.

JS: en el bloque de asignación de imagen por slide, agregar un input de URL
+ botón "Usar este link" que llame este endpoint y actualice
`slide.assigned_asset` (revisar cómo se llama el campo real en
`renderPremiumSlides()` antes de nombrarlo distinto).

### 4. Subida de imagen propia / "mi galería" (Task #14)

Ya existe `/api/upload` (línea ~1970) que guarda un archivo subido a mano y
lo sirve desde `/api/uploads/{filename}` (usado hoy para publicaciones
personalizadas, ver `setupDropzone()` en el JS y el flujo de
`/api/custom/*`). Falta:
- Un endpoint que tome el archivo YA subido (por nombre/ruta que devuelve
  `/api/upload`) y lo "promueva" a asset de biblioteca, reusando
  `ingest_image_bytes(..., origin="premium_upload")` — igual que el punto 3
  pero leyendo bytes desde el archivo subido en vez de descargar una URL.
- En la UI de Estudio Premium, agregar por slide un dropzone/file-input
  igual al que ya existe (mismo JS `setupDropzone()` si es reutilizable, o
  una copia mínima) que suba y después llame este endpoint de promoción.

### 5. Miniaturas visibles en biblioteca (Task #15) — bug real, no sólo UX

`utils/media_library.py::_asset_row()` (línea 402-412) día de hoy devuelve:
```python
"thumbnail": None if asset.get("files_purged") else asset.get("thumb_path"),
```
`thumb_path` es una **ruta de filesystem absoluta**, no servible por HTTP
— por eso `searchPremiumLibrary()` no puede mostrar imagen. Hace falta:
- Un endpoint `GET /api/media-library/thumb/{asset_id}` que resuelva el
  `asset_id` → `thumb_path` real (revisar cómo se guarda/busca el asset por
  id en `media_library.py`, hay funciones de lookup ya usadas por otros
  paths) y sirva el JPEG con `self._send(200, data, "image/jpeg")` (mismo
  patrón que `/api/custom/preview/{id}.jpg`, línea 1843-1854, y
  `/api/uploads/`, línea 1869+). Validar `asset_id` con `_safe_object_id()`
  antes de tocar el filesystem, igual que en todos los demás handlers que
  reciben ids en la URL.
- Cambiar `_asset_row()` para que devuelva una URL relativa
  (`f"/api/media-library/thumb/{asset_id}"`) en vez de la ruta absoluta,
  sólo cuando el asset no está purgado.
- JS: `searchPremiumLibrary()` (línea ~1376) hoy arma resultados sólo de
  texto — agregar un `<img src="...">` por resultado usando el campo
  `thumbnail` ya devuelto por `/api/media-library` (la ruta GET existente,
  línea 1783-1799, usa la misma `_asset_row()` así que se arregla para
  todos los consumidores a la vez, no sólo Estudio Premium).

### 6. Rediseño de claridad del flujo (Task #16)

Reestructurar el bloque HTML de Estudio Premium en pasos numerados
reusando las clases CSS que ya existen en otras tabs del mismo archivo:
`.step-badge`, `.block-title`, `.pipe-block`, `.field`, `.actions`,
`.status`. Orden sugerido de pasos:
1. Pegar texto de la noticia → Generar con IA (o pegar JSON manual).
2. Revisar/editar slides (editor ya existente: `renderPremiumSlides()`,
   `addPremiumSlide()`, `moveSlide()`, `duplicateSlideUI()`,
   `removeSlideUI()`).
3. Asignar imagen por slide (biblioteca con miniatura / link / subida
   propia — los tres del punto 3-4-5 arriba).
4. Guardar borrador / Previsualizar / Publicar (`savePremiumDraft()`,
   `previewPremium()`, `publishPremium()`, ya existentes, no tocar su
   lógica, sólo reordenar visualmente).

No romper `pollPremiumJob()` ni `loadPremiumDraftList()` — son transversales
a los pasos.

### 7. Tests y validación (Task #17)

- `tests/test_premium_package_generator.py` (nuevo): mockear
  `openai.OpenAI` (mismo patrón que tests existentes de
  `caption_generator`/`rewrite_news` si los hay — buscar con
  `grep -r "OpenAI" tests/` para copiar el mock exacto), casos: éxito,
  reintentos con fallo final → `PremiumGenerationError`, `raw_text` vacío,
  `OPENAI_API_KEY` no configurada.
- Tests para el endpoint `/api/premium/generate` (si hay tests de
  `video_reel_manager.py` — revisar si existen; si no, puede quedar fuera
  de alcance y cubrir sólo el módulo de generación + los módulos de
  `media_library`/`safe_http` que se toquen).
- Tests para ingestión por URL y por upload (`ingest_image_bytes` ya tiene
  tests en `tests/test_media_library.py` — agregar casos ahí si el código
  nuevo vive como función en `media_library.py`, o test aparte si vive en
  `video_reel_manager.py`).
- Test para el endpoint de thumbnail (`GET` válido, `asset_id` inválido →
  400, asset purgado → 404 o `thumbnail: null` según se decida).
- Smoke test manual: levantar `video_reel_manager.py` local (puerto
  distinto de 8765 para no pisar producción, p.ej. `--port 8766`), probar
  el flujo completo a mano.
- Actualizar `docs/METRICS.md` con el conteo de tests nuevo (seguir el
  mismo formato de auditoría exacta que ya se usó para la fase anterior:
  baseline, total, neto, por archivo, comandos exactos usados).
- Actualizar `docs/DECISIONS.md` con una entrada nueva explicando por qué
  la generación por IA en Estudio Premium no viola la regla de "no
  investigar noticias con IA" (el texto de entrada ya lo trae el operador,
  no hay research).

## Commits / PR

Seguir el mismo criterio que la fase anterior: commits lógicos pequeños,
no un commit monolítico (por ejemplo: 1 commit por generador+endpoint,
1 por imágenes-por-link, 1 por upload-a-galería, 1 por miniaturas/bugfix
de `_asset_row`, 1 por rediseño UI, 1 por tests+docs). Abrir PR como
**draft** contra `main`, no mergear sin autorización explícita del usuario
(el merge de PRs vía `gh pr merge` puede ser bloqueado por el clasificador
de auto-mode — si pasa, avisar y pedir que lo haga desde GitHub UI, no
buscar un workaround por git).

## Archivos clave para releer al retomar

- `video_reel_manager.py` — UI + handlers HTTP (archivo grande, leer por
  secciones: HTML/CSS ~1-700, JS ~700-1500, handlers GET ~1750-1870,
  handlers POST ~2100-2250 aprox., éstas son líneas aproximadas de esta
  sesión, pueden haber cambiado).
- `utils/premium_importer.py` — contrato de importación, `_suggest_assets()`.
- `utils/premium_contract.py` — `SLIDE_TYPES`, límites de slides, templates.
- `utils/media_library.py` — `ingest_image_bytes()`, `search_library()`,
  `_asset_row()` (línea 402), lookup de asset por id.
- `utils/safe_http.py` — revisar antes de escribir el ingest-por-URL.
- `openIA/caption_generator.py` — patrón de referencia ya usado para
  escribir `premium_package_generator.py`.
- `openIA/premium_package_generator.py` — ya escrito, punto de partida.
