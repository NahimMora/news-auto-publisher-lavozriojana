---
name: lvr-video-qa
description: QA visual y técnico del Noticiero de la Noche (Reel de las 21 de La Voz Riojana). Usar antes de dar por bueno cualquier cambio en utils/newscast_v5.py, utils/newscast_v3.py, remotion/src/v2/newscast5/ o el guion, y al revisar una edición renderizada. Ciclo render → inspección → defectos → corrección → nuevo render, sin TTS, sin visión paga y sin publicar.
---

# QA del Noticiero (render real, nunca sólo tests)

Un MP4 que renderiza sin errores puede ser visualmente malo. Esta skill es el
procedimiento para mirarlo como lo mira alguien en el teléfono.

## Reglas

- **Nunca publicar** para probar: `meta/run_nightly_newscast.py --dry-run` o un
  driver con `providers` de fixture. No ejecutar el script de la tarea.
- **Nunca llamar al TTS ni a la visión** en QA: reutilizar WAVs de la caché
  (`remotion/public/tmp/newscast_cache/voz4_*.wav`, clave = sha1 de modelo|voz|
  tempo|ppm|dirección|texto, ver `newscast_v3.cached_tts`) y los controles
  visuales guardados (`visual_plan.json` → `assets[].check`).
- Aislar estado: `LVR_DATA_DIR`, `LVR_LOGS_DIR`, `LVR_OUTPUT_DIR`, `LVR_FOTOS_DIR`
  en una carpeta temporal; `GEMINI_API_KEY=""` en el proceso del driver.
- `build_edition_v5(..., providers={"tts", "align", "vision", "no_library": True,
  "cache_dir": <tmp>, "keep_work": True})` corre el código de producción con
  material congelado. `keep_work` deja `props.json` para re-renderizar tramos.
- Para editar archivos con acentos o `\b`, escribir el parche con la herramienta
  de archivos, no con heredocs de bash (cambian la codificación y los escapes).

## Pasos

1. `cd remotion && npx tsc --noEmit && npx eslint src/v2/newscast5`
2. `venv\Scripts\python.exe -m unittest tests.test_newscast_v5 tests.test_newscast_v4 tests.test_newscast_v3 tests.test_nightly_newscast`
3. Render (driver de fixture o `--dry-run`). Para comparar sólo la apertura:
   `npx remotion render src/index.ts NightlyNewscastV5 out.mp4 --frames=0-119 --props=<props.json>`.
4. `venv\Scripts\python.exe scripts\newscast_inspect.py <mp4> --out <carpeta>`
5. Mirar, en este orden: `apertura.jpg` (0–3 s a 360 px), `movil_ui.jpg`
   (interfaz de Reels simulada encima), `fronteras.jpg` (antes/corte/después de
   cada toma) y `hoja_1fps.jpg`. Ampliar a 540 px los cuadros dudosos con
   `ffmpeg -ss <t> -i <mp4> -frames:v 1 -vf scale=540:-2`.
6. Leer `inspeccion.json`: `static_spans`, `silences`, `lufs`, `true_peak_dbfs`,
   `black`, `freezes`, `stories[].seconds/shots`; y `visual_plan.json` →
   `voice` (ppm), `validation`, `diagnostics`.
7. Anotar cada defecto con su segundo, corregir la causa (no el síntoma) y
   volver al paso 3. No se aprueba con defectos visibles abiertos.

## Checklist de aprobación

Apertura
- [ ] Frame 0: foto del hecho + marca + titular entrando; titular completo ≤ 0,3 s.
- [ ] La voz dice el hecho desde el frame ~2; nada genérico ("Estas son…").
- [ ] Se entiende que es La Rioja sin audio (barra de marca o mapa).

Composición (a 360×640)
- [ ] Nada esencial en y < 200, y > 1500 ni x > 930.
- [ ] Titular grande y subtítulos nunca en la misma franja; regleta arriba.
- [ ] Ningún solapamiento: dato vs titular, dato vs mapa, rótulo del mapa vs
      contorno, CTA del cierre vs frases, foto del mapa vs subtítulo.
- [ ] Un solo rojo protagonista por cuadro (palabra clave, dato o pin).
- [ ] Fotos sin bordes vacíos (la franja `band` cubre de borde a borde).

Movimiento y ritmo
- [ ] `static_spans` vacío; historias ≥ 5 s con ≥ 2 tomas.
- [ ] Transiciones sin salto en el corte (la toma entrante coincide con su frame 0).
- [ ] Mapa sólo para localidades del nomenclador; nunca "barrio X" ni calles.

Periodismo
- [ ] Títulos fieles a la situación procesal (demorado ≠ detenido).
- [ ] Ningún hecho de otro día contado como de hoy.
- [ ] Sin edades como dato ni destacadas; sin rostros en temas sensibles.
- [ ] Sin nombres de fuentes en pantalla ni en el caption.

Audio y entregables
- [ ] LUFS −14 ± 1, pico ≤ −1,5 dBFS, sin silencios largos.
- [ ] Ritmo de voz 155–170 ppm (`visual_plan.json` → `voice`); factor ≤ 1,08.
- [ ] `portada.jpg`: titular dentro del 1:1 central, marca dentro del 3:4.
- [ ] `texto.txt` < 2200 caracteres, 4 hashtags, sin emojis ni fuentes.

## Trampas conocidas

- El preflight de Tailwind (`remotion/src/index.css`) pone `max-width: 100%` a
  `img`/`video`: en encuadres más anchos que el contenedor hay que pasar
  `maxWidth: "none"` o la foto se recorta.
- El noticiero se renderiza con `npx remotion render` (bundle propio); el
  render server persistente del supervisor no participa.
- `whisper.cpp` da tiempos por palabra con ±50–100 ms: cortes de audio sólo en
  silencios medidos en el WAV, nunca en el tiempo de una palabra.
