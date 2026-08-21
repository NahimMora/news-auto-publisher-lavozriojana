# Plan — panel remoto ops.lavozriojana.com

Última actualización: 2026-08-20.

Estado: **planificación, sin implementar**. Este documento no autoriza ningún cambio
de código ni de infraestructura; registra la dirección acordada para cuando se decida
empezar. Ver `docs/MIGRACION_PC_COMPARTIDA.md` para el paso intermedio que sí se
ejecuta ahora (túnel SSH sobre la UI manual existente).

## Contexto

`AutoPublicador_LaVozRiojana` va a correr en la misma PC Windows que
`WebApp_HolaSalta` (`C:\HolaSalta\WebApp_HolaSalta`), accedida por SSH. Ese proyecto
hermano ya resolvió el mismo problema — operar un sistema local sin exponer sus
puertos hacia afuera — con la arquitectura **HolaSalta Ops**
(`C:\HolaSalta\Ops\docs\ARCHITECTURE.md`): un panel en la nube (Hostinger: Fastify +
React + MySQL) al que el navegador del operador habla directamente, y un **agente
local que hace polling saliente** hacia ese panel y ejecuta los comandos contra el
backend real en `127.0.0.1`. El backend de HolaSalta "ya no expone su puerto ni sirve
una UI propia" (`WebApp_HolaSalta/README.md`).

Este plan adapta ese mismo patrón a `AutoPublicador_LaVozRiojana`, con las diferencias
reales entre ambos proyectos explicitadas más abajo — no es un copy-paste.

## Diferencias de partida con HolaSalta

| | HolaSalta | LaVozRiojana |
|---|---|---|
| Superficie operativa actual | API FastAPI (`127.0.0.1:8000`) + Playwright con sesiones persistentes (WhatsApp/X) | CLI (`cli.py`: start/stop/status/doctor/preflight/canary/reconcile/backup) + UI HTTP manual (`video_reel_manager.py`, sólo loopback) |
| Contrato de resultado | estados propios de `automation_jobs` | `StageResult` ya estandarizado: `success/no_work/degraded/failed/blocked` (`docs/ARCHITECTURE.md`) — se puede reusar tal cual, sin inventar un vocabulario nuevo para el panel |
| Requiere sesión Windows interactiva | Sí, por los perfiles de Playwright (WhatsApp/X necesitan un browser real logueado) | No — el supervisor 24/7 y la UI manual no dependen de una sesión de escritorio abierta, ya corren hoy como tareas programadas sin usuario interactivo |
| Qué expone hoy hacia el operador | nada (puerto cerrado, sólo agente saliente) | UI manual en `127.0.0.1:8765`, restringida por código a loopback con protección anti-DNS-rebinding (`video_reel_manager.py`) |

La ausencia del requisito de sesión interactiva es una simplificación real a favor de
este plan: un agente saliente para LaVozRiojana no depende de que la PC tenga el
usuario con la sesión de Windows abierta, sólo de que el proceso pueda correr (ya es
el caso hoy vía Task Scheduler).

## Qué NO cambia

- El contrato `StageResult` y los estados `success/no_work/degraded/failed/blocked`
  siguen siendo la fuente de verdad; el panel remoto los consume, no los reemplaza.
- `video_reel_manager.py` sigue rechazando binds fuera de loopback. El agente local le
  habla por `127.0.0.1`, igual que hoy le habla un operador con el túnel SSH.
- `cli.py` sigue siendo el punto de entrada real de doctor/preflight/canary/backup;
  el panel no reimplementa esa lógica, la invoca.
- Los kill switches (`FB_PUBLISH_ENABLED`, `IG_PUBLISH_ENABLED`, `WEB_PUBLISH_TARGET`)
  y `PIPELINE_DEPLOYMENT_MODE` siguen siendo autoritativos y locales al `.env` de la
  PC — el panel remoto no los puede pisar por su cuenta, sólo reflejarlos.

## Arquitectura propuesta

| Componente | Ejecuta | No ejecuta |
|---|---|---|
| Panel remoto (`ops.lavozriojana.com`) | login, UI, cola de comandos, historial/auditoría | scraping, render, publicación, credenciales de CMS/Meta |
| Agente local (nuevo, PC de LaVozRiojana) | polling saliente, heartbeat, adapta comandos del panel a llamadas contra `cli.py`/`video_reel_manager.py` locales | interfaz pública, no abre puertos entrantes |
| `cli.py` / `run_24x7.py` / `video_reel_manager.py` | lógica real: scraping, cola, render, publicación | exposición pública (sigue siendo loopback-only) |
| Persistencia JSON local (`data/`) | estado operativo real | no se sincroniza en crudo al panel |

## Flujo de un comando (calco del patrón Ops)

1. El operador dispara una acción en `ops.lavozriojana.com` (ej. "reintentar
   Facebook", "correr preflight", "publicar borrador Premium").
2. El panel valida y encola el comando con una clave de idempotencia.
3. El agente local hace `claim` en su próximo polling.
4. El agente traduce el comando a la llamada local correspondiente:
   `python cli.py <comando> --json` o una request a `127.0.0.1:8765` para acciones
   del Estudio Premium/Reels.
5. El agente parsea el `StageResult`/respuesta HTTP y lo reporta de vuelta al panel.
6. El panel actualiza el estado visible; el navegador nunca habla directo con la PC.

Los estados `degraded`/`blocked` viajan tal cual al panel — no se traducen a
"éxito"/"error" binario, para no perder la semántica que ya existe
(`docs/ARCHITECTURE.md`, sección "Contrato de resultados").

## Seguridad

- El agente es el único componente con salida a internet hacia el panel; nunca abre
  un puerto entrante. Esto reemplaza al túnel SSH de la fase intermedia, no lo apila.
- `video_reel_manager.py` conserva su rechazo a binds no-loopback como defensa en
  profundidad, aunque el agente sea local — ver `docs/MIGRACION_PC_COMPARTIDA.md`
  sobre por qué esto no se relaja nunca, ni siquiera para el agente.
- Credenciales de CMS/Meta/OpenAI siguen sólo en el `.env` local; el panel remoto no
  las recibe ni las necesita — igual que Hostinger nunca ve las sesiones de
  WhatsApp/X de HolaSalta.
- Token del agente propio, distinto y no compartido con el agente de HolaSalta Ops,
  aunque convivan en la misma PC.

## Decisión abierta: infraestructura propia vs. multi-tenant sobre Ops existente

No se decide en este documento. Dos caminos razonables:

- **Extender HolaSalta Ops** (mismo Hostinger, Fastify, React, MySQL) como
  multi-tenant, con LaVozRiojana como un segundo "proyecto" dentro del mismo panel o
  en un subdominio servido por la misma infraestructura ya paga. Menor costo y
  reutiliza autenticación/infra ya operativa; requiere que Ops deje de asumir "una
  PC, un backend" en su modelo de datos.
- **Proyecto propio** (`ops.lavozriojana.com` con su propia infraestructura). Aísla
  completamente los dos sistemas — un incidente en uno no puede afectar al otro por
  diseño — a costa de duplicar la infraestructura de control (login, cola, MySQL).

La sección "Escalabilidad realista" de `Ops\docs\ARCHITECTURE.md` ya advierte
explícitamente: *"Antes de agregar una segunda PC hay que asignar
capacidades/recursos y probar la semántica de cada integración externa; no debe
agregarse otro agente con todas las capacidades por defecto"* — este plan es
justamente ese caso, y hay que revisarlo con quien mantiene Ops antes de elegir.

## Fases

| Fase | Qué incluye | Estado |
|---|---|---:|
| 0 | Migrar el programa a la PC compartida, acceso vía túnel SSH sobre la UI loopback existente | en curso, ver `docs/MIGRACION_PC_COMPARTIDA.md` |
| 1 | Agente local de LaVozRiojana: polling saliente, primer comando end-to-end (`status`/`doctor` read-only) | no iniciada |
| 2 | Cobertura de comandos operativos completos (preflight, canary, reconcile, backup) + acciones del Estudio Premium/Reels | no iniciada |
| 3 | Panel remoto visible en `ops.lavozriojana.com` (o subpath de Ops, según la decisión abierta) | no iniciada |
| 4 | Retirar el túnel SSH de la Fase 0 una vez el panel cubre el uso diario real | no iniciada |

No hay fecha objetivo fijada — la Fase 1 arranca cuando el uso real en Fase 0 muestre
qué comandos se usan de verdad y con qué frecuencia, en vez de adivinar el alcance de
antemano.

## Límites conscientes (calco de Ops, adaptado)

- Si la PC está apagada, el panel muestra el último estado conocido pero no puede
  ejecutar nada nuevo — igual que Ops hoy con HolaSalta.
- El agente no reintenta un `claim` de red perdido si la respuesta pudo contener una
  lease válida (mismo criterio de Ops); sólo heartbeats y lecturas usan backoff.
- Los estados terminales de publicación (Facebook/Instagram/CMS) siguen siendo
  autoritativos en cada plataforma, no en el panel — el panel refleja
  `noticias_web_publicadas.json`/`fb_posted.json`/`ig_posted.json`, no los reemplaza.

## Qué no decide este documento

- Nombre de dominio final ni si vive bajo la infraestructura de Ops o aparte.
- Stack del panel (se asume reutilizar Fastify/React/MySQL de Ops por default, pero
  no está confirmado).
- Alcance exacto de comandos expuestos en la Fase 2 — se define con uso real de la
  Fase 0/1, no de antemano.
