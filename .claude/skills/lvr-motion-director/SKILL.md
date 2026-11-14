---
name: lvr-motion-director
description: Gramática visual del Noticiero V5 de La Voz Riojana (Remotion, remotion/src/v2/newscast5/ y el plan de utils/newscast_v5.py). Usar al diseñar o cambiar tomas, titulares, subtítulos, datos, mapa, transiciones, apertura, cierre o portada del Reel, para mantener la identidad y no volver a la placa estática ni al efecto gratuito.
---

# Dirección de motion del Noticiero

El contenido decide el movimiento. Cada cambio en pantalla tiene que
corresponder a algo que dice la voz o a un cambio de hecho; nada se mueve
"para que se mueva". Profesional no es sobrio: el responsable pidió energía,
pero cada recurso tiene que informar.

## División del trabajo

- Python (`build_plan_v5`) decide **qué** y **cuándo**: tomas, modos, cortes en
  pausas reales, mapa, datos, palabras clave, transiciones, efectos. Es una
  función pura y testeada; los tiempos se cuantizan a frames en un solo lugar.
- Remotion (`NightlyNewscastV5`) decide **cómo se ve**: ejecuta el plan, sin
  azar, sin `Date`, todo función del frame. No clasifica ni llama modelos.

## Pantalla (1080×1920, perfil propio)

| Franja | Qué va |
|---|---|
| y < 200 | sólo imagen (barra de Instagram) |
| y 228–292 | HUD: marca, "Resumen policial · La Rioja", contador y avance |
| y 312–380 | regleta: titular contraído |
| y 430–1000 | datos, lugar, rótulo del mapa |
| y 820–1248 | titular grande (sólo mientras se presenta el hecho) |
| y 1318–1470 | subtítulos cinéticos |
| y > 1500, x > 930 | sólo imagen (usuario, caption, botones) |

## Identidad

- Tinta `#0A0E14`, rojo de marca `#D7192A` (un rojo protagonista por cuadro),
  papel hueso `#F3EFE6` para tarjetas y datos.
- Archivo condensado 900 en mayúsculas para titulares; Archivo semicondensado
  800 en caja normal para subtítulos; Source Serif itálica para fecha y
  departamento (la voz "de diario").
- Diagonal de marca (−6° a −19°) en transiciones y filetes; grano propio y
  viñeta suave en toda toma de foto.

## Tomas

- `full` (≤ 2× de ampliación), `band` (franja de 1150 px con la foto
  desenfocada como extensión; la cámara recorre la foto apaisada), `card`
  (foto chica enmarcada), `map` (contorno oficial + pin + departamento + foto
  chica). El modo lo elige la resolución, nunca el gusto.
- Patrón por historia: general → detalle → contraplano, cortes en pausas
  reales cada ~2,6 s (mínimo 1,5 s). Detalle ≤ 2,35× de ampliación.
- Cada reencuadre interno entra con un golpe de 1,05 → 1 en 6 frames.

## Texto

- Titular: entra por máscara línea a línea (3 frames de escalón), palabra
  clave en caja roja; en el gancho ya se lee a los 0,25 s. Sube a la regleta
  en la primera pausa real (gancho ≥ 3,3 s; siempre antes de un mapa).
- Subtítulos: grupos de 1–4 palabras, cada palabra aparece cuando se dice en
  su lugar reservado (no "baila"); una palabra clave por grupo en caja roja;
  nunca la misma palabra que ya está en rojo arriba; nunca una edad.
- Datos: cuando la voz los dice; esperan a que suba el titular (≤ 0,9 s);
  cifras ≥ 20 cuentan hasta su valor; nunca sobre el mapa.

## Transiciones y sonido

- La toma entrante se dibuja en su frame 0 durante 9 frames: `slash`, `slide`,
  `lift` en rotación; `brand` (cortina roja con logo) una vez, a mitad de la
  edición, y al entrar al cierre.
- *Whoosh* sólo en cambio de historia; campana en el pin; *tick* en datos;
  música más presente en el primer segundo y medio y bajo la voz después.

## No hacer

- Placas de marca que interrumpan el contenido; recapitulaciones al inicio.
- Una foto quieta más de ~3 s; el mismo encuadre en dos tomas seguidas.
- Efectos sin motivo (glitch, shake, flashes), emojis como íconos.
- Mapas por inferencia ("barrio X", "Aeropuerto", calles).
- Texto esencial fuera de las franjas; dos rojos compitiendo.

Antes de entregar cualquier cambio: skill `lvr-video-qa`.
