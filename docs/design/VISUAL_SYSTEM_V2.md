# La Voz Riojana — Visual System V2

Estado: **prototipo en evaluación. NO activo en producción.** Rama
`feature/visual-system-v2`. Producción sigue en V1 y el default del selector es
`v1`. La activación requiere aprobación explícita del responsable editorial.

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

## 3. Reel V2 (`EditorialReelV2`, 1080×1920, 30 fps)

Estados:

- **A · Hook (0–1,7 s).** El video arranca en el frame 0 con su audio. Uno de tres
  hooks:
  - `kinetic_breaking` — policiales o `breaking=true`: barrido de acento de 0,4 s,
    titular en mayúsculas condensadas palabra por palabra (resorte), etiqueta de
    sección en caja, caja de destaque al final.
  - `cinematic_editorial` — general: el video se abre como obturador desde una regla
    horizontal (0,3 s), cámara virtual 1,10→1,0, titular en tipografía partida
    (cada línea se arma desde dos mitades).
  - `visual_statement` — si el titular contiene una cifra verificable (`%`, `$`,
    miles con punto, "millones"): la cifra en 160–330 px sobre caja de acento y el
    titular completo debajo. **La cifra se extrae literalmente del titular**; si no
    hay, el hook no se usa.
  Selección determinística (`v2/text.ts::chooseHook`): `hookStyle` explícito →
  breaking/policiales → cifra → editorial. Nunca aleatoria.
- **B · Reorganización (~0,7 s).** El titular grande sale por máscara hacia arriba,
  el oscurecimiento se retira, la cámara se detiene y entra el titular compacto.
- **C · Video protagonista.** Firma superior compacta (sello + wordmark + sección) y
  regla de progreso de 3 px. Titular compacto:
  - videos horizontales/cuadrados → **doble plano**: video entero arriba, titular
    debajo, nunca encima del video;
  - videos verticales → bloque sólido compacto en la zona segura inferior que se
    retira tras ≥ 4 s (35 % de la duración) y **vuelve en los últimos 4 s** de
    videos ≥ 25 s.
- **D · Cierre (1,8 s, antes 3 s).** Campo de color de sección sube por máscara,
  sello circular, wordmark, regla y "Seguinos en @lavozriojana". Se agrega
  después del video: no recorta contenido.

Fuente nunca recortada: horizontales y cuadrados se escalan enteros; verticales
usan `cover` sólo si difieren < 4 % de 9:16 (p. ej. 540×960 exacto). El fondo es
el mismo material desenfocado, pintado a ¼ de resolución (el desenfoque cuesta
16× menos que en V1).

Zonas seguras: todo el texto propio queda entre y=210 y y=1540 y x≤952 (la UI de
Instagram/Facebook cubre ~380 px abajo y la columna de botones a la derecha). V1
ubicaba el footer en y≈1784, debajo de esa UI.

## 4. Post Instagram V2 (`AutomaticInstagramCardV2`, 1080×1350, render 2×)

Composición elegida por reglas (`resolveCardLayout`):

| Layout | Cuándo | Idea |
|---|---|---|
| `papel` | foto horizontal/cuadrada, sección de tono papel | página editorial clara: foto con margen, regla de acento, titular en tinta, bajada serif |
| `tinta` | foto horizontal/cuadrada, policiales/deportes/espectáculos/breaking | misma retícula sobre tinta, foto a sangre |
| `cintas` | foto vertical (ancho/alto ≤ 0,87) | foto a sangre, titular en cintas sólidas por línea |
| `poster` | sin foto | campo de color de sección, titular protagonista |

Longitud variable: la foto crece mientras el titular conserve ≥ 76 px; luego se
acepta el mínimo (52 px); si aun así no entra, se omite la bajada antes que
achicar el titular; último recurso 40 px / 6 líneas. Recorte máximo de la foto:
~25 % sobre su proporción natural.

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

## 8. Activación futura (NO ejecutada)

Cuando se apruebe V2:

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
