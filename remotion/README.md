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
| `AutomaticInstagramCard` | still | 1080×1350 | Imagen de feed para publicaciones automáticas |
| `FacebookOgCard` | still | 1200×630 | Imagen OG para Facebook/web |

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
`FacebookOgCard`.

## Comandos

```console
npm i                              # instalar dependencias
npm run dev                        # Remotion Studio (preview interactivo)
npx remotion render Main out.mp4 --props=props.json
npx remotion still PremiumSlide out.png --props=props.json
npm run lint                       # eslint src && tsc --noEmit
```

## Invocación desde Python

- `utils/video_renderer.py` — reels (`Main`, `Outro`), vía `npx remotion render`.
- `utils/remotion_renderer.py` — piezas estáticas (`render_still`), vía
  `npx remotion still`. Copia el asset local a `public/tmp/<id>.<ext>` antes
  de renderizar (Remotion sólo puede leer archivos dentro de `public/`) y lo
  borra al terminar.
- `utils/premium_renderer.py::render_package_with_engine` es el punto de
  entrada real del Estudio Premium: llama a
  `utils/remotion_renderer.py::resolve_engine(workflow)` (`workflow="premium"`
  por defecto) y cae a Pillow si Remotion no está disponible en modo `auto`.
  La política de motor es **por workflow**, no global — ver
  `docs/DECISIONS.md` ("Corrección: política de renderers separada por
  workflow") y `docs/RUNBOOK.md`. Sólo `premium` tiene wiring real a Remotion
  en esta entrega; `automatic` y `og` existen como configuración lista para
  cuando se integren, con default `pillow`.

## Rendimiento conocido (medido, ver `docs/METRICS.md`)

Cada llamada a `npx remotion still`/`render` re-bundlea el proyecto desde
cero (no hay bundle cacheado ni servidor persistente). En el benchmark de
10 fixtures (`scripts/benchmark_static_render.py`) esto dio ~19s promedio
por paquete premium con Remotion vs ~0.03s con el fallback Pillow. Es
aceptable para publicación manual premium (2-10 slides, unas pocas veces al
día) pero **no** para reemplazar Pillow en el flujo automático de alto
volumen sin antes agregar un servidor de render persistente
(`@remotion/renderer` embebido o Remotion Studio en modo server).

## Licencia

Algunas entidades necesitan una licencia comercial de Remotion. Ver
[los términos](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md).
