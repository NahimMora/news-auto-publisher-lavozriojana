# Sonidos del Noticiero de la Noche

Descargados de Pixabay el 2026-10-30 bajo la Pixabay Content License (uso
comercial permitido, sin atribución obligatoria). Procesados con ffmpeg
(recorte, fundidos y normalización de volumen). Para cambiar un sonido,
reemplazar el archivo manteniendo el nombre.

| Archivo | Uso | Fuente |
|---|---|---|
| siren.mp3 | Sirena de la apertura | https://pixabay.com/sound-effects/film-special-effects-police-siren-cinematic-hd-371856/ |
| impact.mp3 | Golpe del sello "21 H" | https://pixabay.com/sound-effects/film-special-effects-cinematic-impact-boom-05-352465/ |
| whoosh.mp3 | Cortina entre bloques | https://pixabay.com/sound-effects/film-special-effects-whoosh-cinematic-376875/ |
| sting.mp3 | Firma del cierre | https://pixabay.com/sound-effects/musical-breaking-news-intro-logo-2-314321/ |
| bed.mp3 | Música de fondo | https://pixabay.com/music/electronic-breaking-news-494566/ |

Recursos propios (sin licencia de terceros), generados por el código:

| Archivo | Uso | Origen |
|---|---|---|
| tick.mp3 | Acento de los datos (V4/V5) | sintetizado con ffmpeg (`newscast_v3.ensure_tick`) |
| ping.mp3 | Pin del mapa (V5) | sintetizado con ffmpeg (`newscast_v5.ensure_ping`) |
| grain.png | Grano fotográfico común (V5) | ruido gaussiano con semilla fija (PIL) |

El contorno de La Rioja (`remotion/src/v2/newscast5/laRioja.ts`) y el
nomenclador de localidades (`config/newscast_geo_la_rioja.json`) salen de los
datos abiertos del Servicio de Normalización de Datos Geográficos de Argentina
(datos.gob.ar, fuente IGN/BAHRA) con `scripts/build_newscast_geo.py`.
