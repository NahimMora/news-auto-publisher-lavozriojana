# WhatsApp: canal, grupo e historia "Sumate"

Desde el 2026-10-30 el pipeline publica en WhatsApp sin navegador, con
[Baileys](https://github.com/WhiskeySockets/Baileys) 6.7.24 (protocolo de
WhatsApp por websocket, la misma versión que usa HolaSalta).

| Pieza | Qué hace |
|---|---|
| `whatsapp/wa.mjs` | Proceso Node de una sola corrida: `login`, `info`, `join`, `create-channel`, `send`. Conecta, hace lo pedido y termina. |
| `whatsapp/auth/` | Sesión vinculada (secreto; ignorado por git). |
| `utils/whatsapp_feed.py` | Qué se envía y con qué texto; estado en `data/whatsapp_state.json`. |
| `meta/run_whatsapp.py` | Etapa del ciclo (después de los Reels; sigue el interruptor de Facebook): encola los mensajes y lanza el envío espaciado. |
| `meta/whatsapp_worker.py` | Proceso aparte: envía de a un mensaje, último momento primero, con 90–240 s al azar entre mensajes (`WHATSAPP_GAP_SECONDS`), para que no lleguen en chorro. |
| `utils/wa_join_story.py` + `meta/run_wa_join_story.py` | Historia de Instagram con sticker de enlace al canal, lunes, miércoles y viernes de 20 a 23 h, una por día. |

## Qué sale y dónde

- **Grupo** (`WHATSAPP_GROUP_JID`): todo lo que salió en Facebook — notas con
  link y Reels de notas con video (como link a la nota con "🎥 VIDEO").
- **Canal** (`WHATSAPP_CHANNEL_JID`): sólo último momento.
- Texto sin IA: título, copete en último momento y link con
  `utm_source=whatsapp&utm_medium=grupo|canal`. Vista previa con miniatura
  generada localmente (Pillow).
- Sin historial al arrancar; nada más viejo que `WHATSAPP_MAX_AGE_HOURS` (3);
  de 0 a 7 h (`WHATSAPP_QUIET_HOURS`) sólo último momento. Hasta
  `WHATSAPP_MAX_PER_CYCLE` (15) por ciclo, de a uno y con 90–240 s entre mensajes.
- Estados: `queued` y `sending` (en el envío espaciado), `sent` (con `message_id`), `failed` (hasta 3 intentos),
  `dead_letter`, `unverified` (se cortó sin confirmación: nunca se reenvía a
  ciegas), `skipped_stale`.

## Vincular o volver a vincular

Si la etapa termina `failed/invalid_credential`, la sesión se cerró desde el
teléfono. Con el supervisor corriendo no hace falta detenerlo:

```powershell
cd C:\LVR\whatsapp
node wa.mjs login --status $env:TEMP\wa_status.json --qr-png $env:TEMP\wa_qr.png --minutes 10
# o, sin QR: --phone 549380XXXXXXX (código de 8 caracteres para "Vincular con número")
node wa.mjs info --out $env:TEMP\wa_info.json --channel-invite <código> --group-invite <código>
```

La cuenta tiene que poder escribir en el grupo y ser admin del canal.

## Rollback

`WHATSAPP_ENABLED=false` y `WA_JOIN_STORY_ENABLED=false` en
`scripts/start_24x7_production.ps1`; reiniciar el supervisor. Para cerrar la
sesión: borrar `whatsapp/auth/` o desvincular el dispositivo desde el teléfono.

## Riesgo

Baileys no es la API oficial: WhatsApp puede restringir el número si detecta
envíos masivos. Se envía sólo a un grupo y un canal propios, con pausas y sin
mensajes a personas.
