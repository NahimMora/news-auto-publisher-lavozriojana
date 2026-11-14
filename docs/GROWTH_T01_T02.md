# Plan maestro de crecimiento — T01 y T02

Implementación de los dos primeros tickets del plan maestro
(`LVR_PLAN_MAESTRO_CRECIMIENTO_Y_AUTOMATIZACION_2026.md`, secciones 9, 20 y 25).
Todo queda **apagado por defecto**: desplegar este código no cambia ni una
imagen ni una medición hasta activar los flags.

## T01 — Metadata y medición

| Pieza | Qué hace | Flag |
|---|---|---|
| `utils/growth_measurement.py` | Inventario unificado de publicaciones de Instagram (`ig_posted`, `paparazzi_reels_posted`, `premium_ig_posted`, `social_formats_state`), una por `media_id`; formato confirmado o `unknown`; cohortes por edad real (`lt24h`, `24h`, `72h`, `7d`); reporte comparativo. | lectura siempre; escritura con `GROWTH_METRICS_ENABLED` |
| `utils/kpis.py::record_media_insights` | Fusiona el registro en vez de reemplazarlo (no pierde campos). Con el flag guarda `cohorts` por edad real; los campos de siempre no cambian de forma. | `GROWTH_METRICS_ENABLED` |
| `meta/ig_insights.py` | Con el flag, además de las 30 más recientes, mide hasta `GROWTH_COHORT_MAX_PER_RUN` (6) piezas que cruzaron 24 h / 72 h / 7 d, de todos los flujos. No entran al rendimiento por categoría del router ni cambian el resultado de la etapa. | `GROWTH_METRICS_ENABLED` |
| `layout/image_generator.py` + `meta/ig_client.py` | Con el flag, la card automática guarda `growth_render` (motor, composición, versión visual, reglas T02, ms) y el publicador lo copia a `ig_posted.json` (un campo más en la allowlist; payload y reintentos sin cambios). | `GROWTH_METRICS_ENABLED` |
| `cli.py kpis --growth [--days N] [--json]` | Reporte: cobertura por cohorte, formato, fuente, categoría, flujo; mediana/p75/total; extraordinarias (≥ 3× la mediana de su cohorte) frente a habituales; evolución entre cohortes. | — |

Reglas: ausente = `None`/`ND`, nunca 0. Formato `reel` sólo si Graph dice
`REELS` o el publicador creó un contenedor Reels; `image`/`video`/`carousel`
sólo si Graph lo confirma (`web_feed_state.json`); el resto `unknown`. Una
lectura a las 11 h es `lt24h`, nunca `72h`. No se atribuyen seguidores por
publicación. Sin base nueva, sin cola nueva, sin llamadas de IA.

Costo con el flag: como máximo 6 lecturas GET extra por ciclo de insights
(≈ 150 observaciones lógicas por día a 50 posts/día, como estima el plan).

## T02 — Reglas visuales

`utils/growth_image_rules.py` + prop `growth` en `FacebookOgCardV2` y
`AutomaticInstagramCardV2`. Sólo en la rama V2 de `image_generator`, que es la
misma para preview y publicación.

| Regla | OG 1200×630 | IG 1080×1350 |
|---|---|---|
| Destacado ≤ 3 palabras y ≤ 34 % del título, sin partir nombres propios ni cruzar puntuación | sí | sí |
| Sección editorial cuando llega la fuente (`Paparazzi` → `Espectáculos`) | sí | sí |
| Foto compuesta (2 paneles, grilla 2×2, barras laterales) → díptico, primera columna o foto sin barras | sí (hueco 600×630) | no (el hueco es ancho y ya entra) |
| Titular: mínimo 46 px (antes 40); si no entra, escala anterior; último recurso por alto, nunca cortado | sí | mínimo 64 px y 4 líneas; si no entra, plan anterior |
| Etiquetas legibles a 360 px | sección 26 px (antes 18), firma 28 px | pestaña 18–24 px, pie 28–30 px (sin fecha: Instagram ya la muestra), bajada 36 px |
| Foco vertical 35 % en fotos casi cuadradas o verticales | — | sí |

Detección de montajes: escalón nítido de 1 px que cruza ≥ 60 % del alto entre
el 20 % y el 80 % del ancho (`ImageChops`, sin numpy). En una muestra de 400
fotos reales de `output/web_media`, 83 de 373 horizontales (22 %) eran
montajes; las detecciones dudosas fueron 1–2 (gráficos de TV).

Flags: `GROWTH_IMAGE_RULES_ENABLED=false` y
`GROWTH_IMAGE_RULES_WORKFLOWS=instagram,og` (sólo cuenta si el primero está
activo). No usa `STATIC_RENDER_ENGINE` ni cambia el motor.

## QA

```powershell
python -m unittest tests.test_growth_measurement tests.test_growth_image_rules -v
python scripts/growth_visual_preview.py --out C:\LVR-QA\growth-t02\comparacion --media-dir C:\LVR\output\web_media --baseline-dir C:\LVR-QA\growth-t02\baseline
python cli.py kpis --growth --days 14
```

El script de previews aísla `LVR_*_DIR`, nunca carga `.env` y no publica.

## Activación (fase posterior, autorizada)

1. Merge y, como todo cambio de `remotion/src/`, matar el render server de
   `C:\LVR\remotion\.render-server.json` y borrar `.render-cache` (ver RUNBOOK).
2. Medición: `GROWTH_METRICS_ENABLED=true` en `scripts/start_24x7_production.ps1`
   y `.env`; reiniciar el supervisor entre ciclos. Revisar `cli.py kpis --growth`
   a los 3 y 7 días.
3. Imágenes: `GROWTH_IMAGE_RULES_ENABLED=true` (opcional
   `GROWTH_IMAGE_RULES_WORKFLOWS=og` para empezar sólo con el OG).

## Rollback

`GROWTH_METRICS_ENABLED=false` y/o `GROWTH_IMAGE_RULES_ENABLED=false`, reinicio
del supervisor y de la UI manual. Los campos agregados (`cohorts`,
`growth_render`) quedan y los lectores viejos los ignoran; no hay migración que
revertir. Las imágenes ya publicadas no se tocan.
