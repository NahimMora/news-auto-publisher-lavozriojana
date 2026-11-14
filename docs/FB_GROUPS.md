# Grupos de Facebook por localidad

Desde el 2026-10-30 la página **La Voz Riojana - Noticias** comparte cada nota
riojana que salió en Facebook en los grupos de su localidad. La Graph API ya no
publica en grupos (2024), así que se usa Chrome sin ventana con la sesión del
operador (perfil en `fb_groups/profile`, secreto, ignorado por git).

| Pieza | Qué hace |
|---|---|
| `config/fb_groups.json` | Localidades, palabras que las reconocen y 1–2 grupos por localidad. |
| `utils/fb_groups.py` | Localidad de la nota (título y copete, palabra completa; sin localidad del interior → Capital), texto y cola en `data/fb_groups_state.json`. |
| `meta/run_fb_groups.py` | Etapa del ciclo: encola y lanza el publicador si hace falta. |
| `meta/fb_groups_worker.py` | Proceso aparte: publica de a una como la página, con pausas. |
| `meta/fb_groups_browser.py` | Chrome con el perfil de la sesión. |
| `scripts/fb_groups_cookies.py` | Importa la sesión del navegador del operador (`--paste`). |
| `scripts/fb_groups_list.py` / `fb_groups_probe.py` | Listar grupos y explorar pantallas sin publicar. |

## Ritmo

De 9 a 21 h (`FB_GROUPS_HOURS`), 12–25 min al azar entre publicaciones
(`FB_GROUPS_GAP_MINUTES`), una por grupo por ciclo (al menos 50 min entre dos
publicaciones en el mismo grupo, `FB_GROUPS_GROUP_GAP_MINUTES`) con un techo de
seguridad de 12 por grupo por día (`FB_GROUPS_MAX_PER_GROUP_DAY`, 0 = sin techo),
sólo notas de menos de 8 h, la más reciente primero. Texto: título, copete y link limpio (la tarjeta usa el `og:image` que
Facebook ya leyó al publicar la nota en la página).

## Seguridad

- Antes de publicar verifica que el editor diga "La Voz Riojana"; si no, frena
  (nunca publica como el perfil personal).
- Captcha, verificación, "actividad inusual" o rechazo por spam: frena todo 48 h
  (`FB_GROUPS_BLOCK_HOURS`) y queda en `blocked_reason`.
- Si algo falla después de tocar "Publicar", queda `unverified` y no se repite.
- Evidencia de cada publicación: captura en `output/fb_groups/`.
- El inicio de sesión automático con usuario y contraseña recibió un captcha:
  no se resuelve automáticamente. La sesión se importa del navegador del
  operador.

## Rollback

`FB_GROUPS_ENABLED=false` en `scripts/start_24x7_production.ps1` y reinicio.
Para cortar un publicador en curso: terminar el proceso cuyo PID está en
`data/fb_groups_worker.pid`. Para cerrar la sesión: borrar `fb_groups/profile`.
