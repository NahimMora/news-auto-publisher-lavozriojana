# Datos para la web (feed JSON en R2)

El pipeline publica en cada ciclo (cada hora) documentos JSON públicos para que
la web arme sus propios widgets. Etapa `meta/run_web_feed.py`, código
`utils/web_feed.py`, interruptor `WEB_FEED_ENABLED`.

- Base: `https://media.lavozriojana.com/feed/v1/` (`R2_PUBLIC_URL`).
- `Content-Type: application/json; charset=utf-8`, `Cache-Control: public, max-age=300`.
- Todos llevan `version` (hoy `1`) y `actualizado` (ISO 8601, hora argentina).
  Un cambio incompatible de forma pasa a `feed/v2/`; agregar campos no.
- Sólo datos ya publicados o de fuentes oficiales; nada se completa ni se
  inventa. Un campo sin dato llega vacío (`""`, `[]` o `null`), nunca ausente
  dentro de un bloque presente.
- Si la web lo lee desde el servidor (Next.js, ISR), no hace falta CORS. Para
  leerlo desde el navegador, configurar CORS del bucket para `lavozriojana.com`.

## `index.json`

```json
{"version": 1, "actualizado": "2026-10-23T11:20:00-03:00",
 "feeds": {"mas-visto": "https://media.lavozriojana.com/feed/v1/mas-visto.json", "servicios": "…", "actualizaciones": "…", "videos": "…"}}
```

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

Hasta 10 por ventana y 5 por sección. `instagram.url` puede llegar vacío si el
enlace todavía no se pudo leer (se completa en el ciclo siguiente). `titulo` es
el de redes; para el título del sitio, usar la `url`.

## `servicios.json`

Un bloque por fuente. Si una fuente falla, se conserva el último dato bueno con
su propia `actualizado`; un bloque sólo falta si nunca hubo dato.

```json
{"clima": {"fuente": "Servicio Meteorológico Nacional", "estacion": "La Rioja", "observado": "23-octubre-2026 12:00",
           "temperatura": 23.8, "cielo": "Cubierto", "humedad": 45, "viento": "Norte 13 km/h",
           "pronostico": [{"fecha": "2026-10-23", "dia": "Hoy", "min": 14, "max": 27, "lluvia": 10}],
           "actualizado": "…"},
 "alerta": {"fuente": "Servicio Meteorológico Nacional", "estado": "activa",
            "tipo": "alerta", "nivel": "amarilla", "fenomeno": "viento", "zonas": ["Vinchina"],
            "vence": "2026-10-24T02:59:59-03:00", "descripcion": "El área será afectada por vientos…", "actualizado": "…"},
 "dolar": {"fuente": "dolarapi.com", "brecha_blue_pct": 1.0,
           "cotizaciones": [{"casa": "oficial", "nombre": "Oficial", "compra": 1500.0, "venta": 1550.0, "actualizado": "…"}], "actualizado": "…"},
 "feriados": {"fuente": "argentina.gob.ar", "proximos": [{"fecha": "2026-11-23", "nombre": "Día de la Soberanía Nacional", "tipo": "trasladable"}], "actualizado": "…"},
 "pagos": {"fuente": "Hacienda La Rioja", "hoy": [PAGO], "proximos": [PAGO], "actualizado": "…"},
 "sismos": {"fuente": "INPRES", "ultimos_7_dias": [{"id": "20261023132557", "fecha": "2026-10-23T10:25:57-03:00", "magnitud": 2.7,
            "profundidad_km": 130, "lugar": "35 km al O de Cerro Bonete", "estado": "revisado"}], "actualizado": "…"},
 "cortes": {"fuente": "notas de La Voz Riojana", "avisos": [{"servicio": "luz", "titulo": "…", "zona": "Alpasinche",
            "url": "https://lavozriojana.com/noticias/…", "publicado": "…"}], "actualizado": "…"}}
```

- `alerta.estado`: `activa` o `sin_alerta` (entonces no trae nivel ni zonas).
  `tipo`: `alerta` o `aviso a muy corto plazo`. `nivel`: `amarilla`, `naranja`,
  `roja`. `zonas`: departamentos de La Rioja.
- `PAGO`: `{"fecha": "2026-10-15", "dia": "jueves", "concepto": "Quincena de octubre", "organismos": [{"banco": "Banco Rioja", "items": ["Salud", …]}], "url": "…hacienda…"}`.
  `hoy` vacío si hoy no se paga; `proximos` incluye el de hoy y hasta 6.
- `sismos`: sismos con provincia La Rioja de los últimos 7 días (cualquier
  magnitud); `estado`: `automático`, `revisado` o `sentido`. `lugar` sólo en
  los 3 más recientes (detalle de INPRES).
- `cortes`: avisos de luz, agua y rutas de las últimas 48 h tomados de notas
  propias; `zona` vacía si la nota no la dice.

## `actualizaciones.json`

Notas que actualizan otra del mismo hecho (`utils/same_event.py`), últimos 7
días. Sirve para poner un aviso en la nota vieja ("Actualización: …").

```json
{"items": [{"nota": {"titulo": "IMPUTAN POR HOMICIDIO…", "url": "https://lavozriojana.com/noticias/imputan-…", "publicada": "…"},
            "actualiza": {"titulo": "AVANZA LA INVESTIGACIÓN…", "url": "https://lavozriojana.com/noticias/avanza-…"},
            "novedad": "Imputaron a los cinco detenidos por el homicidio de Nancy Godoy"}]}
```

Para la nota que se está mostrando: buscar su URL en `items[].actualiza.url`.

## `videos.json`

Reels publicados en Instagram (videos de X y notas con video), los 30 más
nuevos con enlace verificado.

```json
{"items": [{"titulo": "Ataque a piedrazos contra una familia en Chamical", "publicado": "…", "origen": "nota",
            "instagram": {"url": "https://www.instagram.com/reel/…/", "miniatura": "https://scontent…", "tipo": "VIDEO"},
            "url_nota": "https://lavozriojana.com/noticias/…", "fuente_video": ""}]}
```

- `origen`: `nota` (nota propia con video) o `x` (video de X; `fuente_video`
  es el post original).
- `instagram.miniatura` es una URL firmada del CDN de Instagram que **vence en
  pocos días**: usarla sólo en el momento o resolver con el embed oficial de
  Instagram a partir de `instagram.url`.
