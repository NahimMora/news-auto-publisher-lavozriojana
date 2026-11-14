[CmdletBinding()]
param(
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot "venv\Scripts\python.exe"
$cli = Join-Path $repoRoot "cli.py"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "No existe el entorno virtual esperado: $python"
}

# Perfil operativo explícito. Los secretos permanecen exclusivamente en .env;
# estas variables sólo establecen gates, límites y trazabilidad del despliegue.
$env:PIPELINE_DEPLOYMENT_MODE = "all"
$env:WEB_PUBLISH_TARGET = "node_webapp"
$env:FB_PUBLISH_ENABLED = "true"
$env:IG_PUBLISH_ENABLED = "true"
# La línea de base se decide por timestamp durable de cola, no por la fecha
# editorial (que puede faltar). El cutoff histórico queda explícitamente apagado.
$env:ARTICLE_NOT_BEFORE_DATE = ""
# Reset de cola social del 2026-10-01 (queue-cutover --social-reset): ninguna
# noticia ni promoción manual anterior a este epoch vuelve a entrar a FB/IG.
$env:SOCIAL_BOOTSTRAP_NOT_BEFORE_TS = "1792108924"
$env:EDITORIAL_FINAL_ATTEMPT_ACTION = "publish_last_safe"
$env:FB_LINK_PREWARM_ENABLED = "true"
$env:FB_LINK_PREWARM_TIMEOUT_SECONDS = "20"
$env:FB_LINK_PREWARM_MAX_BYTES = "5242880"
# LVR-086: espaciar posts para no encadenar ráfagas del crawler de Meta sobre el sitio.
$env:FB_INTER_POST_DELAY_SECONDS = "30"
# LVR-IMPROVEMENT-0001: caption de IG/FB desde la versión editorial web (sin IA extra).
$env:IG_CAPTION_FROM_WEB_ENABLED = "true"
# Gemini: localidad/bajada sólo para notas que renderizan la card de IG (2026-10-17).
$env:LOCALITY_DECK_LAZY_ENABLED = "true"
# Visual System V2 aprobado el 2026-10-17 (Reel, card IG y OG). Rollback: "v1".
$env:VISUAL_STYLE_VERSION = "v2"
# Plan maestro T01/T02 (aprobado 2026-10-30, docs/GROWTH_T01_T02.md): medición por
# cohortes de edad y reglas visuales del V2 (montajes, destacados, legibilidad).
# Rollback: ambos en "false".
$env:GROWTH_METRICS_ENABLED = "true"
$env:GROWTH_IMAGE_RULES_ENABLED = "true"
$env:GROWTH_IMAGE_RULES_WORKFLOWS = "instagram,og"
# LVR-BUG-0006 (2026-10-22): dedup de IG por título sólo dentro de 72 h. Rollback: "0".
$env:IG_POSTED_DEDUP_WINDOW_HOURS = "72"
# Portada propia de Reels (2026-10-18): cover_url en IG, miniatura en FB.
$env:REEL_COVER_ENABLED = "true"
$env:REEL_COVER_FACEBOOK_ENABLED = "true"
# Formatos sociales (2026-10-18): historias IG+FB (misma imagen), servicio
# para La Rioja, carrusel de las 8, Reel de los domingos y seguimiento.
$env:IG_STORIES_ENABLED = "true"
$env:FB_STORIES_ENABLED = "true"
# Historias "Nueva publicación" y de Reel en Instagram: las sube el operador (tope de 100 por día de Meta).
$env:POST_STORIES_MANUAL = "true"
# Historias nativas con stickers post + enlace + ubicación (2026-10-28, docs/IG_NATIVE_STORIES.md):
# reemplazan la historia manual del post. Sólo policiales y notas riojanas. Rollback: ENABLED="false".
$env:IG_NATIVE_STORIES_ENABLED = "true"
$env:IG_NATIVE_STORIES_DRY_RUN = "false"
# 2026-10-30: 4 por ciclo (antes 2: en 48 h quedaron 34 de 59 posts sin historia).
$env:IG_NATIVE_STORY_MAX_PER_CYCLE = "4"
# WhatsApp (2026-10-30, Baileys sin navegador: whatsapp/wa.mjs; sesión en whatsapp/auth).
# Grupo: todo lo que sale en Facebook (Reels como link "VIDEO"); canal: último momento.
# Historia "Sumate al canal" lunes, miércoles y viernes a las 20.
# Rollback: WHATSAPP_ENABLED y WA_JOIN_STORY_ENABLED en "false".
$env:WHATSAPP_ENABLED = "true"
$env:WHATSAPP_DRY_RUN = "false"
$env:WHATSAPP_NODE = "C:\Users\PC\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.22_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v22.23.2-win-x64\node.EXE"
$env:WHATSAPP_GROUP_JID = "120363411983964612@g.us"
$env:WHATSAPP_CHANNEL_JID = "120363412496683508@newsletter"
$env:WHATSAPP_JOIN_URL = "https://whatsapp.com/channel/0029VbDz1k88aKvAjsK6Su2j"
$env:WA_JOIN_STORY_ENABLED = "true"
# Grupos de Facebook por localidad (2026-10-30, config/fb_groups.json): la página comparte
# cada nota riojana en los grupos de su localidad (Capital si no nombra otra), de 9 a 21 h,
# 12-25 min entre publicaciones, 1 por grupo por ciclo (techo 12/día); ante cualquier aviso frena 48 h.
# Sesión en fb_groups/profile. Rollback: FB_GROUPS_ENABLED "false".
$env:FB_GROUPS_ENABLED = "true"
$env:FB_GROUPS_DRY_RUN = "false"
# Etiquetas del Gobierno (config/gov_directory.json) y ubicación (config/ig_locations.json) en Instagram.
$env:GOV_TAGS_ENABLED = "true"
$env:IG_LOCATION_ENABLED = "true"
$env:SOCIAL_FORMATS_INSTAGRAM_ENABLED = "true"
$env:SOCIAL_FORMATS_FACEBOOK_ENABLED = "true"
$env:MORNING_BRIEF_ENABLED = "true"
$env:WEEKLY_RECAP_ENABLED = "true"
$env:STORY_UPDATES_ENABLED = "true"
# Mismo hecho entre fuentes (2026-10-23): duplicado no sale; dato nuevo sale como
# ACTUALIZACIÓN. Alertas meteorológicas sólo del feed CAP del SMN.
$env:SAME_EVENT_CHECK_ENABLED = "true"
# 2026-10-30: el mismo hecho sin ancla comprobable sale en la Web y en Facebook,
# pero no se repite en Instagram si la nota anterior ya salió ahí. Rollback: "".
$env:SAME_EVENT_SOCIAL_SKIP = "instagram"
$env:WEATHER_ALERT_NEWS_SMN_ONLY = "true"
# Datos para la web en R2 (docs/WEB_FEED.md).
$env:WEB_FEED_ENABLED = "true"
# Placas de servicio v2 (2026-10-23): cronograma de pagos de Hacienda (historia
# cada día de pago desde las 7; post IG el primer día, FB todos) y sismos con
# epicentro en La Rioja (INPRES, magnitud >= 4,0, a cualquier hora).
$env:PAYMENT_POSTS_ENABLED = "true"
$env:QUAKE_POSTS_ENABLED = "true"
$env:QUAKE_MIN_MAGNITUDE = "4.0"
# Primera semana: las respuestas se proponen y se revisan (cli.py comment-replies).
$env:COMMENT_REPLIES_MODE = "suggest"
# Imágenes estáticas de IG fuera de 0-7 h (alcance mediano de madrugada ~20 vs ~200
# a la tarde); Reels sin cambios. Ver docs/DECISIONS.md (2026-10-04).
$env:IG_STATIC_QUIET_HOURS = "0-7"
# Videos de X enviados por el backend de HolaSalta (C:/sources/x_video_sources.json): sólo Reel.
$env:X_VIDEO_REELS_ENABLED = "true"
# 0 = sin tope por ciclo: se publican todos los videos, cortando por tiempo
# (VIDEO_STAGE_TIME_BUDGET_SECONDS) y dejando el resto para el ciclo siguiente.
$env:X_VIDEO_MAX_PER_CYCLE = "0"
$env:X_VIDEO_MAX_AGE_HOURS = "24"
# Reels automáticos (X, paparazzi e Infobae): sólo plantilla Remotion, sin overlay
# clásico de ffmpeg. Todos los videos se publican: sin puntaje editorial y fuera
# de los cupos del lote. Ver docs/DECISIONS.md (2026-10-15 y 2026-10-16).
$env:REEL_REQUIRE_REMOTION = "true"
$env:REEL_SOURCE_NORMALIZE_ENABLED = "true"
$env:REMOTION_REEL_TIMEOUT_MS = "120000"
$env:REMOTION_REEL_ATTEMPTS = "2"
$env:REEL_EDITORIAL_SCORE_ENABLED = "false"
$env:VIDEO_STAGE_TIME_BUDGET_SECONDS = "480"
# Criterio editorial del lote (ver docs/DECISIONS.md 2026-10-16):
# - paparazzi: todas a la Web, sin cupo;
# - paparazzi con video: en redes sólo el Reel (sin link en Facebook ni imagen);
# - paparazzi sin video: en redes sólo con relevancia >= 6/10;
# - Infobae con video: Reel en redes y artículo Web; sin video, nota normal;
# - internacionales: balde propio, sólo alto impacto (>= 8/10), 1 por ciclo;
# - Instagram: locales sólo último momento, policiales y sociedad (interior como
#   relleno con el cupo libre del ciclo), máx. 30 por día.
$env:PAPARAZZI_VIDEO_ONLY_ENABLED = "true"
$env:PAPARAZZI_VIDEO_MAX_PER_CYCLE = "0"
$env:PAPARAZZI_VIDEO_MAX_AGE_HOURS = "24"
$env:PUBLISH_PAPARAZZI_WEB_ALL = "true"
$env:INFOBAE_VIDEO_ONLY_ENABLED = "true"
$env:PUBLISH_PAPARAZZI_MIN_SCORE = "6"
$env:PUBLISH_INTERNATIONAL_BUCKET_ENABLED = "true"
$env:PUBLISH_INTERNATIONAL_MIN_SCORE = "8"
$env:PUBLISH_INTERNATIONAL_MAX_PER_RUN = "1"
# 2026-10-30: sociedad ampliada (salud, educación) y relleno con toda nota con
# vínculo riojano; tope 40 repartido en el día (antes se llenaba a media tarde y
# de noche sólo salían Reels). Las imágenes esperan con el tope de Meta en 88/100
# para no frenar los Reels. Rollback: "policiales,sociedad", RIOJAN "false",
# MAX "30", SLACK "0", CEILING "0". Ver docs/DECISIONS.md (2026-10-30).
$env:IG_LOCAL_CATEGORIES = "policiales,sociedad,salud,educacion"
$env:IG_LOCAL_FILL_CATEGORIES = "interior"
$env:IG_LOCAL_FILL_RIOJAN = "true"
$env:IG_LOCAL_DAILY_MAX = "40"
$env:IG_LOCAL_PACING_SLACK = "4"
$env:IG_LOCAL_PACING_MAX_AGE_HOURS = "6"
$env:IG_STATIC_QUOTA_CEILING = "88"
# 2026-11-13: hasta 12 piezas de Instagram por ciclo (antes 8 fijo en
# utils/deployment.py). Las descartadas ya no ocupan lugar del ciclo.
# Rollback: "8". Ver docs/DECISIONS.md (2026-11-13).
$env:PIPELINE_IG_MAX_PER_CYCLE = "12"
# Fénix 95.1 (Locales): sólo notas con vínculo riojano. Ver docs/DECISIONS.md 2026-10-22.
$env:SCRAPER_FENIX_ENABLED = "1"
$env:SCRAPER_MEDIOSRIOJA_ENABLED = "1"
# Locales de policiales/interior con YouTube incrustado: Reel sólo en Instagram
# (Facebook sigue con link). Ver docs/DECISIONS.md 2026-10-22.
$env:LOCAL_VIDEO_REEL_ENABLED = "true"
$env:LOCAL_VIDEO_REEL_CATEGORIES = "policiales,interior"
# MPF y Función Judicial: sólo puntaje >= 7 y sin casos ya cubiertos en 72 h.
$env:SCRAPER_JUDICIALES_ENABLED = "1"
$env:JUDICIAL_MIN_SCORE = "7"
$env:CANARY_ENABLED = "false"
$env:ALERTS_ENABLED = "true"
$env:ALERT_WEBHOOK_URL = ""
$env:DISK_FREE_MIN_MB = "2048"
$env:LVR_RELEASE_TAG = "unreleased-reliability-baseline"
$env:LVR_DEPLOYED_AT = (Get-Date).ToUniversalTime().ToString("o")
$env:LVR_DEPLOYMENT_OPERATOR = $env:USERNAME
$env:LVR_BACKUP_REFERENCE = "pre-24x7-cutover-2026-07-27"

Set-Location -LiteralPath $repoRoot

& $python $cli doctor --scope supervisor --json
if ($LASTEXITCODE -ne 0) {
    throw "El doctor del supervisor falló; no se inicia el pipeline."
}

if ($ValidateOnly) {
    Write-Output "Perfil 24/7 válido; no se inició el supervisor."
    exit 0
}

& $python $cli start
exit $LASTEXITCODE
