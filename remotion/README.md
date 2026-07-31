# Remotion — sistema visual de La Voz Riojana

Composiciones usadas por el pipeline Python (`utils/video_renderer.py`,
`utils/remotion_renderer.py`) para renderizar Reels y piezas estáticas.
Node/npm son dependencias de sistema; no se instalan con `pip`.

## Composiciones

| ID | Tipo | Resolución | Uso |
|---|---|---|---|
| `Main` | video | 1080×1920 | Reel automático/manual (`video_reel_manager.py`) |
| `Outro` | video | 1080×1920 | Cierre de marca, cacheado una vez |
| `PremiumSlide` | still | 1080×1350 | Slides del carrusel premium (`utils/premium_renderer.py`) |
| `AutomaticInstagramCard` | still | 1080×1350 | Card automática de Instagram (`layout/image_generator.py::generate_instagram_with_engine`) |
| `FacebookOgCard` | still | 1200×630 | Imagen OG para Facebook/web (workflow `og`, sin wiring real todavía) |

## Editorial Cinemática Riojana (sistema visual, `PremiumSlide`/`AutomaticInstagramCard`)

`PremiumSlide` y `AutomaticInstagramCard` comparten un sistema de diseño centralizado
en `src/shared/`:

- **`designSystem.ts`** — paleta, tres modos de composición (`cronica`/`editorial`/
  `datos`, derivados de `template` en premium y de `seccion` en automático vía
  `modeFromTemplate`/`modeFromSection`), escala tipográfica, spacing/safe areas y
  gradientes por capas (scrim + wash de marca + luz radial + viñeta).
- **`fonts.ts`** — carga local (sin red) de Archivo + Source Serif 4, ambas fuentes
  variables SIL OFL (`public/fonts/*.ttf`, ver `public/fonts/OFL-*.txt`), vía la API
  `FontFace` nativa con rango de peso `1 999` (permite pedir 400/700/900 desde un
  único archivo). El hook `useFontsReady()` bloquea la captura de Remotion
  (`delayRender`/`continueRender`) hasta que las fuentes están realmente registradas
  **y** el componente volvió a renderizar/pintar con ellas — medir con Canvas 2D antes
  de eso produce wraps incorrectos con la métrica de la fuente de fallback (bug real
  detectado y corregido durante el desarrollo).
- **`fitText.ts`** — auto-fit + wrap medido con Canvas 2D real (búsqueda binaria de
  tamaño de fuente, wrap por palabra completa, hard-break a nivel de carácter si una
  sola palabra sin espacios es más ancha que el lienzo). Usado por `FittedTitle.tsx`,
  que además resalta términos por **palabra completa** (no por subcadena exacta) para
  que la misma tokenización sirva tanto para el wrap como para el resaltado sin
  desincronizarse.
- **`Grain.tsx`**, **`SectionBadge.tsx`**, **`SlideCounter.tsx`** — textura sutil
  (filtro SVG `feTurbulence`) y componentes reutilizables de marca/numeración.
- **`StillLayout.tsx`** — fondo (foto ambiental con gradientes por capas, o base de
  marca con textura cuando no hay foto), barra de acento, footer con badge de sección +
  numeración, logo discreto. Exclusivo de `PremiumSlide`/`AutomaticInstagramCard`.
  `FacebookOgCard.tsx` sigue usando `LegacyStillLayout.tsx` (copia congelada del layout
  anterior) para quedar pixel-idéntico — está fuera del alcance de este rediseño.

`Main.tsx`/`Outro.tsx` (Reels) no se tocaron — siguen usando `HighlightedTitle.tsx`
(wrapping implícito del navegador) tal como estaban.

## Paleta oficial

`src/constants.ts` centraliza los tokens de marca: `ROJO`, `BORDO`, `AZUL`,
`NEGRO`, `WHITE`. **No hay dorado** — decisión de producto documentada en
`docs/DECISIONS.md` (2026-07-30, "Paleta oficial sin dorado"); el dorado
anterior (`GOLD`, usado en el handle `@lavozriojana` de `Main.tsx`) fue
reemplazado por `AZUL`.

## Palabras clave destacadas (highlight terms)

`src/shared/HighlightedTitle.tsx` resalta 1-3 términos dentro de un título
con coincidencia de palabra completa, preservando tildes y mayúsculas. Lo
usan `Main` (prop `highlightTerms`, opcional y compatible con props
anteriores — default `[]`), `PremiumSlide`, `AutomaticInstagramCard` y
`FacebookOgCard` (esta última vía `FittedTitle.tsx` en las dos primeras,
directamente en las últimas dos).

## Comandos

```console
npm i                              # instalar dependencias
npm run dev                        # Remotion Studio (preview interactivo)
npx remotion render Main out.mp4 --props=props.json
npx remotion still PremiumSlide out.png --props=props.json
npm run lint                       # eslint src && tsc --noEmit
node render_server.mjs --port=0    # levantar el servidor de render persistente a mano (debug)
```

## Invocación desde Python

- `utils/video_renderer.py` — reels (`Main`, `Outro`), vía `npx remotion render`.
- `utils/remotion_renderer.py` — piezas estáticas (`render_still`). Intenta primero el
  **servidor de render persistente** (`render_server.mjs`, ver abajo) y cae al
  `subprocess` de `npx remotion still` si no puede levantar — mismo contrato de
  retorno en ambos casos, ningún caller necesita saber cuál se usó.
- `utils/premium_renderer.py::render_package_with_engine` — punto de entrada real del
  Estudio Premium (`workflow="premium"` por defecto, `resolve_engine`).
- `layout/image_generator.py::generate_instagram_with_engine` — punto de entrada real
  de la card automática de Instagram (`workflow="automatic"`). Función aditiva: no
  modifica `generate_post`/`generate_instagram`/`generate_facebook` (Pillow), que
  siguen siendo el fallback si Remotion falla o no está disponible.
- La política de motor es **por workflow**, no global — ver `docs/DECISIONS.md` y
  `docs/RUNBOOK.md` para la tabla completa de variables/defaults.

## Servidor de render persistente

`render_server.mjs` resuelve el costo de re-bundling documentado en
`docs/KNOWN_ISSUES.md` #69: bundlea el proyecto **una sola vez por proceso**
(`@remotion/bundler`) y reusa un browser Chromium entre renders
(`@remotion/renderer`), expuesto por HTTP en `127.0.0.1` (sólo loopback, sin auth).

- Se levanta bajo demanda (la primera llamada a `render_still()` sin un servidor
  saludable lo lanza como proceso background) y se apaga solo por inactividad
  (default 20 min, `RENDER_SERVER_IDLE_MS`).
- `.render-cache/` (bundle) y `.render-server.json` (metadata del proceso: PID y
  puerto) son artefactos locales gitignorados — nunca se commitean.
- **Si el código de `src/` cambia con el servidor corriendo, hace falta reiniciarlo
  manualmente** para que sirva el bundle nuevo — no hay invalidación automática
  todavía (ver `docs/RUNBOOK.md` para el comando exacto en PowerShell).
- `REMOTION_RENDER_SERVER_DISABLED=true` fuerza el `subprocess` histórico.

## Rendimiento (medido, ver `docs/METRICS.md`)

Con el servidor persistente, el mismo benchmark de 10 fixtures
(`scripts/benchmark_static_render.py`) que antes daba ~19.1s promedio por
paquete premium ahora da **~2.4s promedio (~8.1x más rápido)**, ~0.03s con
Pillow. Viable para el flujo automático de alto volumen (hasta 8/ciclo) — de
ahí que `AUTOMATIC_STATIC_RENDER_ENGINE` haya pasado de `pillow` a `auto`
por defecto (intenta Remotion, cae a Pillow sin bloquear una publicación
real). Antes del servidor persistente, esto era **inviable** para ese
volumen (~560x más lento que Pillow, sin bundle cacheado).

## Licencia

Algunas entidades necesitan una licencia comercial de Remotion. Ver
[los términos](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md).
Las fuentes (Archivo, Source Serif 4) son SIL Open Font License — ver
`public/fonts/OFL-*.txt`.
