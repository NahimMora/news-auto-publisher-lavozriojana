# Datos para la web (feed JSON en R2)

El pipeline publica en cada ciclo (cada hora) documentos JSON públicos para que
la web arme sus propios widgets. Etapa `meta/run_web_feed.py`, código
`utils/web_feed.py`, interruptor `WEB_FEED_ENABLED`.

- Base: `https://media.lavozriojana.com/feed/v1/` (`R2_PUBLIC_URL`).
- `Content-Type: application/json; charset=utf-8`, `Cache-Control: public, max-age=300`.
- Todos llevan `version` (hoy `1`) y `actualizado` (ISO 8601 con `-03:00`).
  Un cambio incompatible de forma pasa a `feed/v2/`; agregar campos no.
- Contrato acordado con la web: su validador es `lib/feed-types.ts` (zod) del
  repo `lavozriojana-news-app`. `web_feed.validate` aplica las mismas reglas
  antes de subir: un documento que no pasa no se sube y queda el anterior en R2.
- Sólo datos ya publicados o de fuentes oficiales; nada se completa ni se
  inventa. Un dato desconocido llega como `null` (nunca `0` ni `""`); una
  lista sin elementos, `[]`.
- Títulos en texto plano (sin HTML, markdown ni emojis) y en formato oración.
  El CMS los guarda en MAYÚSCULAS: `clean_title` los pasa tomando las
  mayúsculas de nombres propios y siglas del título original de la fuente y de
  la bajada, más una lista de departamentos, localidades y provincias.
- Instantes en ISO 8601 con `-03:00`; fechas de calendario `YYYY-MM-DD`.
- URLs de notas propias: `https://lavozriojana.com/noticias/<slug>`.
- Si la web lo lee desde el servidor (Next.js, ISR), no hace falta CORS. Para
  leerlo desde el navegador, configurar CORS del bucket para `lavozriojana.com`.

## `index.json`

```json
{"version": 1, "actualizado": "2026-10-23T11:20:00-03:00",
 "feeds": {"mas-visto": "https://media.lavozriojana.com/feed/v1/mas-visto.json", "servicios": "…", "actualizaciones": "…",
           "videos": "…", "historias": "…", "ultimo-momento": "…"}}
```

La web no lo lee; queda como índice.

## `mas-visto.json`

Ranking por **alcance en Instagram** de los posts de cada nota (el pipeline no
tiene las visitas de la web). Sólo notas publicadas en la web.

```json
{"metrica": "alcance en Instagram",
 "ventanas": {"24h": [ITEM, …], "7d": [ITEM, …]},
 "por_seccion_7d": {"policiales": [ITEM, …], "interior": […], …}}
```

`ITEM`:

```json
{"titulo": "Murió el joven que había volcado en la Ruta 75",
 "url": "https://lavozriojana.com/noticias/…",
 "seccion": "policiales",
 "publicada": "2026-10-23T07:34:00-03:00",
 "instagram": {"url": "https://www.instagram.com/p/…/", "alcance": 11701, "interacciones": 240}}
```

- Hasta 50 por ventana y 30 por sección. Las claves de `por_seccion_7d` son
  los slugs del CMS.
- `alcance` e `interacciones` vienen de Instagram Insights (reach e
  interacciones). Una nota sin alcance conocido no entra.
- `instagram.url` llega `null` si el enlace todavía no se pudo leer; se
  completa en el ciclo siguiente.

## `servicios.json`

Un bloque por fuente, cada uno con `fuente` y `actualizado`. Si una fuente
falla, se conserva el último dato bueno con su propia `actualizado`; un bloque
sólo falta si nunca hubo dato.

```json
{"clima": {"fuente": "Servicio Meteorológico Nacional", "estacion": "La Rioja", "observado": "2026-10-23T12:00:00-03:00",
           "temperatura": 23.8, "cielo": "cubierto", "humedad": 45, "viento": "Norte 13 km/h",
           "pronostico": [{"fecha": "2026-10-24", "dia": "sábado", "min": 14, "max": 27, "lluvia": "2,5 mm"}],
           "actualizado": "…"},
 "alerta": {"fuente": "Servicio Meteorológico Nacional", "estado": "activa",
            "tipo": "alerta", "nivel": "amarilla", "fenomeno": "viento", "zonas": ["Vinchina"],
            "vence": "2026-10-24T02:59:59-03:00", "descripcion": "El área será afectada por vientos…",
            "actualizado": "2026-10-23T20:59:42-03:00"},
 "dolar": {"fuente": "DolarApi.com", "brecha_blue_pct": 0.97,
           "cotizaciones": [{"casa": "oficial", "nombre": "Oficial", "compra": 1500.0, "venta": 1550.0, "actualizado": "…"}], "actualizado": "…"},
 "feriados": {"fuente": "argentina.gob.ar", "proximos": [{"fecha": "2026-11-23", "nombre": "Día de la Soberanía Nacional", "tipo": "trasladable"}], "actualizado": "…"},
 "pagos": {"fuente": "Hacienda La Rioja", "hoy": [PAGO], "proximos": [PAGO], "actualizado": "…"},
 "sismos": {"fuente": "INPRES", "ultimos_7_dias": [{"id": "20261023132557", "fecha": "2026-10-23T10:25:57-03:00", "magnitud": 2.7,
            "profundidad_km": 130, "lugar": "35 km al O de Cerro Bonete", "estado": "revisado"}], "actualizado": "…"},
 "cortes": {"fuente": "Notas de La Voz Riojana", "avisos": [{"servicio": "luz", "titulo": "…", "zona": "Alpasinche",
            "url": "https://lavozriojana.com/noticias/…", "publicado": "…"}], "actualizado": "…"}}
```

- **`clima`**
  - `observado`: la hora de la observación que informa el SMN.
  - `viento`: texto en km/h; "Calma" va sin número.
  - `lluvia`: **milímetros acumulados del día** según el pronóstico a 5 días,
    como texto ("2,5 mm"). No es probabilidad.
  - El pronóstico va desde hoy, y llega `[]` cuando el SMN publica el archivo
    vacío.
- **`alerta`**
  - `null` si no hay ninguna activa y vigente.
  - `actualizado`: la hora de emisión del SMN (campo `sent` del CAP), no la de
    la consulta.
  - `tipo`: `alerta` o `aviso a muy corto plazo`.
  - `nivel`: `amarilla`, `naranja` o `roja`.
  - `zonas`: departamentos de La Rioja.
- **`dolar`**
  - `casa`: `oficial`, `blue`, `bolsa` (MEP) y `contadoconliqui` (CCL), cada una
    con su hora de la fuente.
  - `brecha_blue_pct`: blue sobre oficial, en %.
- **`pagos`** (`PAGO`)
  - Forma: `{"fecha": "2026-10-15", "dia": "jueves", "concepto": "Quincena de octubre", "organismos": [{"banco": "Banco Rioja", "items": ["Salud", …]}], "url": "…hacienda…"}`.
  - `hoy` llega vacío si hoy no se paga.
  - `proximos` incluye el de hoy y hasta 6.
- **`sismos`**
  - Sismos con provincia La Rioja de los últimos 7 días, de cualquier magnitud.
  - `estado`: `automático`, `revisado` o `sentido`.
  - `lugar`: la localidad más cercana según el detalle de INPRES, que se lee
    una vez por sismo. Sin detalle, la provincia.
- **`cortes`**
  - Avisos de luz, agua y rutas de las últimas 72 h, tomados de notas propias.
  - `zona`: `null` si la nota no la dice.

## `actualizaciones.json`

Notas que actualizan otra del mismo hecho (`utils/same_event.py`), últimos 7
días. Sirve para poner un aviso en la nota vieja ("Actualización: …").

```json
{"items": [{"nota": {"titulo": "Avanza la investigación…", "url": "https://lavozriojana.com/noticias/avanza-…", "publicada": "…"},
            "actualiza": {"titulo": "Imputan por homicidio…", "url": "https://lavozriojana.com/noticias/imputan-…"},
            "novedad": "Imputaron a los cinco detenidos por el homicidio de Nancy Godoy"}]}
```

- `nota` es la ORIGINAL (más vieja) y `actualiza` la NUEVA.
- Una cadena A→B→C sale como A→B y B→C. Una nota nunca se actualiza a sí
  misma.
- Para la nota que se está mostrando, buscar su URL en `items[].nota.url`.

## `videos.json`

Reels publicados en Instagram (videos de X y notas con video): los 25 más
nuevos con enlace verificado, sin nada programado a futuro.

```json
{"items": [{"titulo": "Ataque a piedrazos contra una familia en Chamical", "publicado": "…", "origen": "nota",
            "instagram": {"url": "https://www.instagram.com/reel/…/", "miniatura": "https://scontent…",
                          "video": "https://instagram.fsla2-1.fna.fbcdn.net/…mp4?…&oe=…", "video_vence": "2026-10-25T10:30:00-03:00",
                          "tipo": "VIDEO"},
            "url_nota": "https://lavozriojana.com/noticias/…", "fuente_video": null}]}
```

- `origen`: `nota` (nota propia con video) o `x` (video de X; `fuente_video`
  es el post original).
- `url_nota`, `fuente_video` y `miniatura` llegan `null` si no hay dato.
- `instagram.miniatura` es el `thumbnail_url` de la Graph API: una URL firmada
  del CDN de Instagram que **vence en pocos días**, por eso se vuelve a pedir
  en cada corrida.
- `instagram.video` es el mp4 del Reel (`media_url` de la Graph API, de
  nuestra propia cuenta) en el CDN de Instagram, para un `<video>` nativo sin
  subir el archivo a R2. Admite pedidos por rango y CORS abierto.
  - `video_vence` es cuándo vence su firma (parámetro `oe`; hoy unas 32 h).
    Se renueva cada hora.
  - Llega `null` si no es video, si no hay firma legible o si vence en menos
    de 2 h. En ese caso, y también si el `<video>` falla, la web usa el
    reproductor de Instagram (`https://www.instagram.com/reel/<código>/embed/`).

## `historias.json`

Cronologías armadas **sólo** con actualizaciones verificadas del mismo hecho
(desde el 2026-10-23). El agrupamiento automático anterior quedó apagado porque
mezclaba hechos distintos (docs/KNOWN_ISSUES.md #101). Sólo salen historias con
al menos dos notas y movimiento en los últimos 30 días.

```json
{"origen": "actualizaciones verificadas del mismo hecho",
 "items": [{"storyKey": "event:3f2a…", "titulo": "Imputan por homicidio simple a los cinco detenidos…",
            "actualizado": "2026-10-23T16:01:04-03:00",
            "notas": [{"titulo": "Avanza la investigación…", "url": "https://lavozriojana.com/noticias/avanza-…", "publicada": "…", "novedad": ""},
                      {"titulo": "Imputan por homicidio…", "url": "https://lavozriojana.com/noticias/imputan-…", "publicada": "…",
                       "novedad": "Imputaron a los cinco detenidos por el homicidio de Nancy Godoy"}]}]}
```

- `notas` incluye todas las notas del hecho, en orden cronológico (la primera
  es la original).
- `titulo` de la historia es el de la nota más nueva. `novedad` llega vacía en
  la original.
- `storyKey` es la misma que trae cada post del CMS y siempre empieza con
  `event:`. Las cadenas anteriores al 2026-10-23 no tienen clave y no salen.
- En la página de una nota: si su post trae una `storyKey` que empieza con
  `event:`, mostrar la cronología de esa historia.

## `ultimo-momento.json`

```json
{"nota": {"titulo": "Detuvieron a dos ladrones tras robar a una docente…", "url": "https://lavozriojana.com/noticias/…",
          "seccion": "policiales", "activado": "2026-10-23T16:02:41-03:00", "vigente": true},
 "alerta": {…mismo bloque que servicios.alerta, sólo si está activa y vigente…}}
```

- **`nota`**
  - La marcada "Último momento" en el CMS (`isBreaking`); `null` si no hay.
  - La marca no vence sola en el CMS: `vigente` es `true` si se activó en las
    últimas 6 horas. La web además la oculta a las 12 h.
  - Mostrar la banda sólo con `vigente: true`.
- **`alerta`**: la alerta o el aviso del SMN vigente para La Rioja, o `null`.
- Se regenera cada hora con el resto. La web oculta alertas y urgentes si el
  archivo tiene más de 3 h.
