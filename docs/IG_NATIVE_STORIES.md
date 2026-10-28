# Historias nativas de Instagram con stickers (2026-10-28)

Después de que una nota sale en el feed de @lavozriojana.ok, el pipeline puede
publicar UNA historia con tres stickers **nativos** (los dibuja Instagram, se
pueden tocar):

| Sticker | Qué hace al tocarlo | De dónde sale |
|---|---|---|
| Publicación del feed (`feed_media`) | abre el post original | ID de Graph en `ig_posted.json` → `permalink` (Graph, lectura) → shortcode → media pk (decodificación local, sin pedidos extra) |
| Enlace (`story_link`) | abre la nota en lavozriojana.com | `web_url` del registro o de la nota en `noticias_meta.json`; sólo `https` y hosts de `IG_NATIVE_STORY_LINK_HOSTS` |
| Ubicación (`location`) | abre el lugar | el `location_id` que llevó el post (`ig_location_id` en `ig_posted.json`) o, para registros viejos, la misma tabla `config/ig_locations.json` con la localidad de la nota |

Fondo liso #111318 de 1080×1920, sin textos ni marcas. Posiciones relativas:
enlace (0,50; 0,17), ubicación (0,50; 0,25), post centrado en y≈0,57 con hasta
el 88 % del ancho, sin pisar los stickers de arriba ni la caja de respuesta
(zona segura 0,12–0,86) y conservando la proporción real de la imagen.

## Por qué instagrapi

La API Graph no admite stickers en historias (ni link, ni ubicación, ni post
compartido) y las historias por Graph cuentan para el tope de 100
publicaciones por 24 h. La app sí los admite: `instagrapi==3.1.0` (API privada
de la app) arma los tres en un único `photo_upload_to_story`. Esa versión ya
incluye las dos correcciones de la incidencia #2320 (todos los
`story_sticker_ids`, no sólo el primero, y lectura de `story_link_stickers`).

Detalles verificados en el código de 3.1.0:

- el `location_id` del sticker es `external_id or pk` de la ubicación: el
  `facebook_places_id` que ya usa el post es exactamente ese ID. Para no pedir
  lat/lng ni arriesgar `LocationNotFound`, `meta/instagrapi_client.py` evita
  `location_complete` cuando el ID ya está cargado;
- el sticker de enlace no admite texto propio: Instagram muestra el dominio
  con su diseño nativo (no se puede forzar "Noticia completa aquí");
- `media_share_to_story()` sólo arma el post compartido: por eso se usa
  `photo_upload_to_story()` con `medias`, `links` y `locations`.

## Flujo

Etapa `meta/run_native_stories.py` (en el supervisor, después de
`meta/run_stories.py`):

1. candidatos: publicaciones de `ig_posted.json` de las últimas
   `IG_NATIVE_STORY_LOOKBACK_HOURS` con al menos `IG_NATIVE_STORY_MIN_AGE_SECONDS`
   de antigüedad (que el post ya sea accesible) y sin historia nativa;
2. se omite la que ya tiene historia de Graph en Instagram (último momento);
3. sin enlace válido a la web, no sale (`skipped`); sin ubicación, sale con
   enlace y post y se registra el motivo (`location_skipped_reason`);
4. se valida el payload (tres cajas en zona segura, sin superposición);
5. `processing` → publicación → `story_info` para confirmar que Instagram
   devuelve enlace, post y ubicación → `completed` con `story_pk`, `story_url`
   y `missing_stickers` (vacío si están los tres);
6. el fondo temporal se borra siempre.

Secuencial, `IG_NATIVE_STORY_MAX_PER_CYCLE` (2) por ciclo y
`IG_NATIVE_STORY_MAX_PER_DAY` (40) por día; lock propio; horario de silencio
`STORY_QUIET_HOURS`. Un fallo nunca toca la publicación de la nota.

### Estados (`data/ig_native_stories.json`)

| Estado | Significado | Qué pasa después |
|---|---|---|
| `processing` | se estaba enviando | si el proceso murió, se reconcilia como `unverified` |
| `unverified` | error después de enviar: pudo haber salido | pasados 10 min se busca entre las historias vigentes de la cuenta; si está → `completed`; si no → `failed` |
| `failed` | no salió | reintento con backoff `IG_NATIVE_STORY_RETRY_BASE_SECONDS` × 2ⁿ |
| `dead_letter` | agotó `IG_NATIVE_STORY_MAX_ATTEMPTS` | no se reintenta |
| `skipped` | nunca va a salir (sin enlace válido, ya tiene historia de Graph) | — |
| `completed` | publicada, con `story_pk` | nunca se vuelve a publicar |

`blocked_until`/`block_reason`: challenge, "feedback required", "please wait",
rate limit → se frena todo por `IG_NATIVE_STORY_BLOCK_HOURS` (24 h) sin gastar
intentos. Sesión inválida → `failed`/`invalid_credential` y pausa de 1 h. No se
intenta evadir ningún control: un challenge se resuelve a mano con
`python cli.py native-stories login`.

## Variables de entorno

| Variable | Default | Uso |
|---|---|---|
| `IG_NATIVE_STORIES_ENABLED` | `false` | interruptor de la etapa |
| `IG_NATIVE_STORIES_DRY_RUN` | `true` | sólo vista previa + payload, sin conectarse |
| `IG_NATIVE_STORY_INCLUDE_REELS` | `false` | incluir Reels (ver limitaciones) |
| `IG_NATIVE_STORY_MAX_PER_CYCLE` / `_MAX_PER_DAY` | `2` / `40` | cupos propios |
| `IG_NATIVE_STORY_LOOKBACK_HOURS` | `6` | ventana de candidatos |
| `IG_NATIVE_STORY_MIN_AGE_SECONDS` | `120` | espera desde la publicación del post |
| `IG_NATIVE_STORY_MAX_ATTEMPTS` | `3` | intentos antes de dead-letter |
| `IG_NATIVE_STORY_RETRY_BASE_SECONDS` | `900` | base del backoff |
| `IG_NATIVE_STORY_BLOCK_HOURS` | `24` | pausa ante challenge/bloqueo |
| `IG_NATIVE_STORY_LINK_HOSTS` | `lavozriojana.com,www.lavozriojana.com` | hosts válidos del enlace |
| `IG_NATIVE_STORY_LIVE_TEST` | `false` | habilita la prueba real controlada |
| `INSTAGRAPI_USERNAME` / `INSTAGRAPI_PASSWORD` | — | sólo en `.env`; la contraseña se usa sólo si la sesión guardada deja de servir |
| `INSTAGRAPI_SESSION_PATH` | `data/secrets/instagrapi_session.json` | sesión persistente (cookies: secreto, fuera del repo) |
| `INSTAGRAPI_READ_TIMEOUT_SECONDS` | `25` | timeout HTTP |

## Operación

```powershell
# Estado (no toca Instagram)
python cli.py native-stories status

# Vista previa sin publicar: PNG + payload en output/native_stories_preview/
python cli.py native-stories preview                         # candidatos actuales
python cli.py native-stories preview --media-id 1817935...  # un post puntual

# Crear o renovar la sesión (interactivo; pide código si Instagram lo exige)
python cli.py native-stories login

# Prueba real controlada (publica UNA historia y la verifica)
$env:IG_NATIVE_STORY_LIVE_TEST = "true"
python cli.py native-stories live-test --media-id <ID Graph> --confirm-external-publication
python cli.py native-stories delete --story-pk <pk> --confirm-external-publication
```

Habilitar en producción (`scripts/start_24x7_production.ps1`), en dos pasos:

1. `IG_NATIVE_STORIES_ENABLED=true` con `IG_NATIVE_STORIES_DRY_RUN=true`: revisar
   las vistas previas de un día.
2. Tras la prueba real verificada a mano, `IG_NATIVE_STORIES_DRY_RUN=false`.

Deshabilitar: `IG_NATIVE_STORIES_ENABLED=false` y reiniciar el supervisor.

Validación manual exigida antes del paso 2 (en la app, sobre la historia de
`live-test`): tocar el post abre la publicación; tocar el enlace abre la nota;
tocar la ubicación abre el lugar; los tres se ven sobre el fondo y funcionan a
la vez. `live-test` también compara con `story_info` lo que Instagram devolvió.

## Limitaciones

- **API privada**: no es la API oficial de Meta. Instagram puede pedir
  verificación, limitar o suspender la sesión, y un cambio en la app puede
  romper los stickers sin aviso. Por eso: flag apagado, dry-run por defecto,
  cupos bajos, pausa de 24 h ante cualquier control y sesión persistente (no
  se inicia sesión en cada ciclo).
- **Sin prueba real todavía**: al 2026-10-28 no hubo credenciales de la app ni
  cuenta de prueba en esta sesión. Está probado que instagrapi arma los tres
  `tap_models` correctos (test con su `photo_configure_to_story` real, sin
  red) y que el ID de ubicación es el que pide el sticker; que Instagram los
  muestre y funcionen al tocarlos **no está verificado** hasta correr
  `live-test`.
- **Reels**: instagrapi envía el post compartido con `product_type="feed"`
  siempre. Compartir un Reel así no está verificado; por eso
  `IG_NATIVE_STORY_INCLUDE_REELS=false` hasta probarlo con `live-test` sobre
  un Reel.
- **Texto del enlace**: el sticker de link usa la presentación nativa de
  Instagram (el dominio); la API no deja poner "Noticia completa aquí".
- **Posiciones**: son pedidos a Instagram; la app dibuja la tarjeta del post a
  su manera y puede ajustar tamaños.
- **Ubicación en registros viejos**: los posts publicados antes de este cambio
  no guardaron la localidad calculada al renderizar la card
  (`LOCALITY_DECK_LAZY_ENABLED`), así que sus historias salen sin ubicación.
  Desde este cambio `ig_posted.json` guarda `locality`, `ig_location_id` y
  `web_url`.
- **Doble historia**: con `POST_STORIES_MANUAL=true` el operador sube a mano
  la historia del post; si se habilita esta etapa, dejar de subirla a mano
  para no duplicar.
