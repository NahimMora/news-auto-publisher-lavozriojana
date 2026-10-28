# Historias nativas de Instagram con stickers (2026-10-28)

Después de que una nota sale en el feed de @lavozriojana.ok, el pipeline puede
publicar UNA historia con tres stickers **nativos** (los dibuja Instagram, se
pueden tocar):

| Sticker | Qué hace al tocarlo | De dónde sale |
|---|---|---|
| Publicación del feed (`feed_media`) | abre el post original | ID de Graph en `ig_posted.json` → `permalink` (Graph, lectura) → shortcode → media pk (decodificación local, sin pedidos extra) |
| Enlace (`story_link`) | abre la nota en lavozriojana.com | `web_url` del registro o de la nota en `noticias_meta.json`; sólo `https` y hosts de `IG_NATIVE_STORY_LINK_HOSTS` |
| Ubicación (`location`) | abre el lugar | la que tiene **la publicación en Instagram**, leída con un pedido a la app (`media_info_v1`) antes de armar la historia; si el post no tiene ubicación, la historia tampoco. La vista previa (sin sesión) sale sin ubicación. Sin IA: ni Gemini ni OpenAI intervienen en la historia |

## Reglas editoriales (2026-10-28, pedido del operador)

- **Alcance**: notas policiales de cualquier provincia (`seccion` policiales) o con vínculo
  riojano determinístico (`utils/editorial_router.detect_riojan_link`:
  hashtag de localidad, fuente local, categoría interior o localidad riojana
  en título/bajada/caption). El resto no entra como candidato: no consume
  cupo ni deja estado (`utils/native_story.scope_of`).
- **Ubicación y personas**: sólo lo que ya tenía la publicación original. No
  se agregan menciones de cuentas ni de personas, ni hashtags.
- **Sólo reutilización**: la historia comparte el post tal cual (más el
  enlace a la nota); no se genera texto, imagen ni diseño nuevo.

**Los stickers de la API son invisibles** (prueba real del 2026-10-28): Instagram
sólo registra las zonas tocables; la app oficial pega el dibujo del sticker en la
imagen antes de subirla. Por eso `utils/native_story.compose_story` dibuja la
historia completa, con la paleta y tipografía del Visual System V2:

- fondo: la propia foto del post a sangre, desenfocada, con velo de tinta y grano;
- bloque editorial centrado en la zona segura (0,12–0,86): etiqueta de ubicación
  arriba alineada al borde del post, el post con sombra y esquinas redondeadas,
  y debajo el botón papel "LEÉ LA NOTA COMPLETA / en lavozriojana.com";
- etiqueta y botón en el color de bloque de la sección de la card (rojo en
  policiales, azul marino en interior/sociedad/etc.);
- sin cabecera propia: la card ya trae la marca e Instagram muestra la cuenta.

Cada zona tocable coincide con lo dibujado. Sin la imagen del post la historia no
sale (`post_image_unavailable`, se reintenta). La vista previa usa la misma
función.

Calidad: JPEG 1080×1920 calidad 97 con croma completo (4:4:4). instagrapi
volvía a codificar la imagen con calidad 75 y croma 4:2:0 antes de subirla;
`instagrapi_client._upload_as_is` envía nuestros bytes sin tocar.

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
- **Texto del enlace**: como el dibujo lo pone la imagen, el botón dice
  "LEÉ LA NOTA COMPLETA"; la zona tocable es el sticker de enlace real.
- **Posiciones**: son pedidos a Instagram; la app dibuja la tarjeta del post a
  su manera y puede ajustar tamaños.
- **Ubicación en la vista previa**: el dry-run no abre sesión en la app, así
  que no puede leer la ubicación del post y la vista previa sale sin ella.
- **Doble historia**: con `POST_STORIES_MANUAL=true` el operador sube a mano
  la historia del post; si se habilita esta etapa, dejar de subirla a mano
  para no duplicar.
