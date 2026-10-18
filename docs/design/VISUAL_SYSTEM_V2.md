# La Voz Riojana — Visual System V2

Estado: **activo en producción desde el 2026-10-17** (aprobado por el responsable
editorial). `VISUAL_STYLE_VERSION=v2` en `scripts/start_24x7_production.ps1` y en
el `.env` del host; el default del código sigue siendo `v1`. Rollback:
`VISUAL_STYLE_VERSION=v1`, reiniciar supervisor y UI manual y borrar
`remotion/.render-cache` (ver sección 8).

## 1. Concepto: "Regla y tinta"

V2 evoluciona la identidad de La Voz Riojana sin cambiar marca, logo ni colores
corporativos. El lenguaje se apoya en cuatro recursos, iguales en Reels, posts y
Open Graph:

1. **Archivo condensada** (eje `wdth` real de la fuente variable que ya usa V1):
   titulares más grandes en el mismo espacio, carácter de portada de diario.
2. **Source Serif 4 itálica** para bajadas y firma ("Seguinos en…"): contraste
   editorial con la sans.
3. **La regla de acento** (rojo `#B30000` / azul `#2F6FB0` según sección): es el
   hilo conductor. Corta foto y texto en los posts, es costura en OG, viaja entre
   el titular grande y el compacto en el Reel y es la barra de progreso.
4. **Destacado por caja** (en vez de texto coloreado): blanco sobre el color de
   sección, contraste ≥ 4,5:1 en cualquier fondo.

Dos tonos según la sección: **papel** (`#F2EEE6`, referencia al diario impreso)
para política, interior, sociedad, economía, salud, educación, cultura; **tinta**
(`#0A0D12`) / campo de color para policiales, deportes, espectáculos y noticias
`breaking`. Así las noticias no se ven todas iguales y la sección se reconoce
antes de leer.

Se evitó a propósito: degradados como recurso por defecto (V2 usa planos
sólidos), sombras, bordes redondeados, tarjetas flotantes, intro con logo, y
efectos de sonido.

## 2. Mapa de archivos

| | V1 (sin cambios) | V2 (nuevo) |
|---|---|---|
| Reel | `remotion/src/EditorialReel.tsx`, `Main.tsx`, `Outro.tsx` | `remotion/src/v2/EditorialReelV2.tsx` |
| Post IG | `remotion/src/AutomaticInstagramCard.tsx`, `layout/image_generator.py` (Pillow) | `remotion/src/v2/AutomaticInstagramCardV2.tsx` |
| Open Graph | `remotion/src/FacebookOgCard.tsx` | `remotion/src/v2/FacebookOgCardV2.tsx` |
| Tokens | `remotion/src/shared/designSystem.ts`, `constants.ts` | `remotion/src/v2/tokens.ts` (sólo lee colores de `constants.ts`) |
| Fuentes | `remotion/src/shared/fonts.ts` | `remotion/src/v2/fonts.ts` (familias `LVR Archivo`/`LVR Serif`, mismos archivos) |
| Medición | `remotion/src/shared/fitText.ts` | `remotion/src/v2/fit.ts` (con ancho y tracking) |
| Motion | — | `remotion/src/v2/motion.ts`, `remotion/src/v2/components.tsx` |
| Reglas de texto/hook | — | `remotion/src/v2/text.ts` |
| Registro | `remotion/src/Root.tsx` | `remotion/src/v2/register.tsx` (Root sólo agrega `<V2Compositions />`) |
| Selector | `utils/visual_style.py` (flags V1, intactos) | `utils/visual_version.py` |
| Adaptador de datos | — | `utils/visual_v2_props.py` |
| QA | — | `scripts/visual_v2_gallery.py`, `remotion/scripts/render_compare.mjs`, `tests/fixtures/visual_v2/cases.json`, `tests/test_visual_version.py` |

El único archivo V1 modificado es `Root.tsx` (+3 líneas para registrar las
composiciones nuevas). Ningún call site productivo (`video_renderer.py`,
`image_generator.py`, `media.py`, `meta/*`) fue tocado en esta fase.

## 3. Reel V2 (`EditorialReelV2`, 1080×1920, 30 fps) — revisión 2026-10-18

La primera versión (hook que mostraba el titular grande, lo borraba y lo volvía
a mostrar compacto; tipografía partida) se descartó por pedido editorial: el
titular entraba dos veces, la animación partida se veía rota en los primeros
cuadros y el fondo desenfocado quedaba vacío. La composición actual es estable
desde el cuadro 0:

- **Encabezado** (y=330): sello + wordmark a la izquierda, pestaña de sección
  (+ localidad) en el color de la sección a la derecha; regla con barra de
  progreso debajo.
- **Titular**: entra UNA vez (línea por línea por máscara, ~0,4 s) y queda fijo
  todo el video; caja de destaque al terminar. Se muestra con su caja original
  (`titulo_display`): ya no se pasa a minúsculas un titular en MAYÚSCULAS
  (rompía nombres propios). Si sobra aire, el titular crece hasta 104 px.
- **Video** horizontal/cuadrado a todo el ancho (nunca recortado), con regla de
  acento arriba y crédito verificable abajo ("Video: X / @usuario",
  "Video: Infobae", "Video: Paparazzi", derivado de la URL de origen).
- **Bajada**: primera oración del párrafo 📌 del caption del mismo Reel (texto
  ya publicado; si es muy larga se omite, nunca se corta con "…"), con barra
  de acento; "Nota completa en lavozriojana.com →" si hay lugar.
- **Fondo**: el mismo material desenfocado (a ¼ de resolución), velo de tinta,
  tinte de sección, trama de puntos y la sección como marca de agua debajo de
  la zona segura. Visible desde el primer cuadro.
- **Verticales**: video a pantalla completa (cover sólo si es ~9:16), titular
  compacto fijo arriba sobre un velo, crédito abajo.
- **Cierre** de 1,8 s sin cambios.

Zonas: todo el texto propio entre y=330 y y=1540 — entra en el recorte 4:5
del feed (y 285–1635) y en la zona segura de pantalla completa (x ≤ 940).

### Portada (`ReelCoverV2`, still 1080×1920)

La misma composición en su estado final, con un cuadro del video fuente
(≈1,5 s) como imagen y una insignia "▶ VIDEO". Lo esencial queda dentro del
4:5 del feed y del 3:4 de la grilla. `REEL_COVER_ENABLED=true` la genera en
`render_video` (`info["cover_path"]`); `utils/paparazzi_reels.py` la sube a R2
y la pasa como `cover_url` (Instagram la prioriza sobre `thumb_offset`). Con
`REEL_COVER_FACEBOOK_ENABLED=true`, después de publicar el Reel en Facebook se
aplica como miniatura (`POST /{video-id}/thumbnails`, best-effort: un fallo
nunca cambia el resultado de la publicación). La UI manual sube
`{video_id}_cover.jpg` si existe. Si la portada falla, el Reel sale igual con
el cuadro por offset.

## 4. Post Instagram V2 (`AutomaticInstagramCardV2`, 1080×1350, render 2×) — revisión 2026-10-18

Formato "portada" con más elementos (la primera versión se veía como
plantilla y vacía):

| Variante | Cuándo | Idea |
|---|---|---|
| foto arriba (`papel`/`tinta`) | foto horizontal/cuadrada | foto a sangre que se funde con el fondo; el titular monta su borde; texto anclado abajo y la foto crece hasta alcanzarlo (recorte ≤ ~40 %) |
| foto completa (`cintas`) | foto vertical (ancho/alto ≤ 0,87) | foto a pantalla completa, texto sobre un velo inferior |
| póster | sin foto | campo de color de sección, trama, sección como marca de agua |

Elementos comunes: pestaña de marca (sello + LA VOZ RIOJANA) y pestaña de
sección (+ localidad) sobre la foto, franja de acento a la izquierda, bajada
con barra, trama de puntos y banda de pie en el color de la sección con
"Nota completa en lavozriojana.com →" y la fecha de publicación (hora
argentina, `dateLabel`). El titular manda: primero se reduce la bajada, nunca
se corta el titular.

## 5. Open Graph V2 (`FacebookOgCardV2`, 1200×630)

Diseñado para miniatura: columna de texto de 600 px a la izquierda con titular
condensado de hasta 66 px, costura de acento vertical y foto a alto completo a la
derecha. Sección de tono tinta → columna en el **color de la sección** (rojo
policiales, azul deportes, bordó espectáculos): identidad reconocible a 300 px de
ancho. Sin foto: campo de sección a todo el ancho.

## 6. Datos (compatibilidad)

Los props V2 son un superconjunto de los de V1. `utils/visual_v2_props.py`
reutiliza `select_highlight_phrase`, `restore_deck_casing` (vía
`_deck_for_render`) y los campos existentes (`locality`, `deck`, `breaking`,
`highlight_terms`). Mejora: un `highlight_terms` de la cola que no aparece
literalmente en el titular (frecuente: la cola guarda frases de otra versión del
título) se descarta y se usa el selector local; V1 lo envía igual y no resalta
nada. Ningún dato se inventa: si falta, el prop queda vacío y el layout se
adapta.

## 7. Selector de versión y política de cola

`utils/visual_version.py::resolve_visual_version(workflow, item)` →
`VisualVersionDecision(version, source, composition)`.

Variables (todas opcionales; sin ellas → `v1`):

- `VISUAL_STYLE_VERSION=v1|v2` — global para Reels, IG y OG.
- `REEL_VISUAL_STYLE_VERSION`, `INSTAGRAM_VISUAL_STYLE_VERSION`,
  `OG_VISUAL_STYLE_VERSION` — sólo para divergencias explícitas (se loguea warning).

Política de piezas en cola: la versión se fija en el primer render
(`item["visual_style_version"]`) y se respeta en reintentos; un rollback explícito
a `v1` gana siempre sobre una fijación `v2`. Las piezas ya publicadas nunca se
regeneran. `as_metadata()` devuelve lo necesario para reproducir el render
(versión, composición, origen de la decisión); junto con los props guardados
permite re-renderizar igual.

## 8. Activación (ejecutada el 2026-10-17)

Selector cableado en `utils/video_renderer.py::_render_remotion_main` (todos los
Reels: X, paparazzi/Infobae y UI manual pasan por `render_video`),
`layout/image_generator.py::_generate_instagram_remotion` y
`_generate_facebook_remotion`. La card V2 de IG siempre renderiza a 2× y se
guarda en JPEG 95 4:4:4. El Reel V2 incluye su cierre (no se concatena el outro
histórico) y `info` registra `visual_style_version`/`composition`. Pasos que se
siguieron:

1. Merge de la rama con el selector cableado en los tres call sites
   (`utils/video_renderer.py::_render_remotion_main`,
   `layout/image_generator.py::_generate_instagram_remotion` /
   `_generate_facebook_remotion`) — cambio pendiente, a revisar en PR propio,
   con default `v1` (comportamiento idéntico).
2. Desplegar con el supervisor detenido entre ciclos (ver memoria operativa:
   el 24/7 ejecuta el working copy).
3. `python -m unittest discover tests -v`, `cli.py doctor --scope core`,
   `cli.py run-once --dry-run`, galería contra datos actuales.
4. Definir `VISUAL_STYLE_VERSION=v2` en `.env` y reiniciar el render server
   (`remotion/.render-server.json`) para que bundlee las composiciones nuevas.
5. Verificar el primer Reel, post y OG en logs (`visual_version.log`) antes de
   dar por cerrado.

Rollback: `VISUAL_STYLE_VERSION=v1` (o borrar la variable) y reiniciar el render
server. V2 queda en el código.

Políticas que se conservan: Reels — si Remotion falla, no se publica (sin
plantilla clásica). Imágenes — la caída a Pillow existente se mantiene; al
cablear el selector, el resultado debe registrar `visual_style_version` y
`engine_used="pillow"` para que la degradación no sea silenciosa.

## 9. Problemas abiertos

- El selector no está cableado a los call sites productivos (decisión: fuera de
  alcance hasta la aprobación).
- `visual_statement` sólo reconoce cifras con unidad clara; frases/declaraciones
  ("dijo que…") no se extraen todavía: requeriría una señal del pipeline, nunca
  una invención.
- Las cintas del layout vertical tapan parte inferior de la foto (por diseño);
  con fotos donde el sujeto está abajo conviene `layout: "tinta"` explícito.
- Los clips de video de la galería son material local no vinculado a las notas
  usadas como titular (sólo para evaluar composición).

## 10. Rendimiento medido (galería 2026-10-17, misma máquina, mismos datos)

| Pieza | V1 | V2 |
|---|---|---|
| Reel imagen 10 s | 25,0 s / 34,6 s | 21,0 s / 22,5 s |
| Reel video horizontal 14 s | 34,7 s | 28,6 s |
| Reel video ultra ancho 12 s | 30,1 s | 24,2 s |
| Reel video vertical 28 s | 63,0 s | 54,9 s |
| Reel vertical angosto 10 s | 27,2 s | 30,2 s |
| Reel sin media 8 s | 18,3 s | 15,7 s |
| Post IG (2×) | ~1,0–1,7 s | ~1,0–1,7 s |
| OG | ~0,7–1,2 s | ~0,7–1,2 s |

V2 no agrega costo operativo: es más rápido en 6 de 7 Reels (fondo desenfocado a
¼ de resolución y cierre de 1,8 s en lugar de 3 s). Audio y duración del clip
fuente se conservan íntegros (verificado con ffprobe).
