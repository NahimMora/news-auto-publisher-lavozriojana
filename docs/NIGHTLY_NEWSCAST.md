# Noticiero de la Noche (Reel de las 21)

Reel 1080×1920 locutado con lo más importante del día en La Rioja. Aprobado
como formato fijo el 2026-10-30; prueba de 3 noches sin publicar antes de
activar la publicación automática.

## Flujo

1. **Selección** (`utils/nightly_newscast.collect_candidates`): notas propias
   publicadas en la web en las últimas `NIGHTLY_NEWSCAST_WINDOW_HOURS` (15),
   sólo fuentes riojanas (Nueva Rioja, Fénix, Medios Rioja, Tiempo Popular,
   Poder Judicial/MPF). Fuera: deportes, espectáculos y títulos sensibles
   (abuso, femicidio, menores, suicidio). Policiales primero. El texto y la
   foto salen de nuestra nota en lavozriojana.com (ya validada y con la foto
   procesada); el video, de `noticias_meta.json` (`video_url` o YouTube
   incrustado).
2. **Guion** (`write_script`, Gemini): 5 a 6 bloques, el primero es el
   policial más fuerte; agrupa en un bloque las notas del mismo hecho o tema;
   gancho de una oración con los 2–3 hechos fuertes + 3 titulares de pantalla.
3. **Control factual** (`validate_script`): cada cifra, nombre propio y día de
   la semana del guion tiene que estar en las notas del bloque (mismos
   extractores que el validador editorial web). Con observaciones, reintenta
   hasta 3 veces con esa devolución; si no pasa, no hay noticiero ese día
   (`script_rejected`). Nunca se relaja la barrera.
4. **Locución** (`synthesize`): Gemini Pro TTS, voz Orus, con dirección de
   tonada riojana (aprobada por el operador el 2026-10-30); se recortan
   silencios y se baja apenas el ritmo (`NIGHTLY_NEWSCAST_TEMPO`, 0.97). El
   cierre fijo se genera una vez y se reutiliza. Un 429 de cupo no se
   reintenta: la etapa queda `degraded` (`rate_limit`). Apertura y cierre fijos:
   "Son las nueve de la noche. Esto es lo que pasó hoy en La Rioja." / "Esto
   fue el noticiero de las nueve de La Voz Riojana. Seguinos…".
5. **Render** (`NightlyNewscastV2`, Remotion V2): apertura en frío con sirena,
   cortes rápidos y luces de patrullero; sello "21 H" con golpe; bloques con
   regleta, número, rótulo de sección (Policiales con banda roja y destello
   rojo/azul), lugar, titular y fuente; cambios de foto o video silenciado;
   cierre con sello, "Todas las noches, a las 21" y "Seguí @lavozriojana".
   Música de fondo que baja bajo la voz y cortinas entre bloques
   (`remotion/public/newscast/`, licencias en `CREDITS.md`).
6. **Salida**: `output/noticiero/<fecha>/noticiero-<fecha>.mp4` (−14 LUFS),
   `texto.txt` (caption) y `guion.json` (guion con las notas de cada bloque).
7. **Publicación** (sólo con `NIGHTLY_NEWSCAST_PUBLISH=true`): espera a las
   `NIGHTLY_NEWSCAST_HOUR` (21), sube a R2 temporal y publica Reel en IG y FB.
   Sin `external_id` no hay éxito; un resultado ambiguo de IG no se reintenta
   ni sigue a FB.

## Operación

- Tarea programada `LaVozRiojana-Noticiero`, diaria 20:30:
  `scripts/run_nightly_newscast.ps1` (registro: `-Register`).
- Manual: `venv\Scripts\python.exe meta\run_nightly_newscast.py --dry-run`
  (genera sin publicar) o `--force` (regenera la edición del día).
- Estado: `data/nightly_newscast_state.json` por fecha (`video`, `ig_id`,
  `fb_id`, `ambiguous`, `attempts`, `warnings`). Máximo 2 intentos por día.
- Log: `logs/nightly_newscast.log`.

## Flags

| Variable | Default | Uso |
|---|---|---|
| `NIGHTLY_NEWSCAST_ENABLED` | `false` | Interruptor general |
| `NIGHTLY_NEWSCAST_PUBLISH` | `false` | Publica en IG/FB; si no, sólo genera |
| `NIGHTLY_NEWSCAST_FACEBOOK` | `true` | Con publicación, también Facebook |
| `NIGHTLY_NEWSCAST_HOUR` | `21` | Hora de salida |
| `NIGHTLY_NEWSCAST_WINDOW_HOURS` | `15` | Ventana de notas del día |
| `NIGHTLY_NEWSCAST_MIN_BLOCKS` / `MAX_BLOCKS` | `4` / `6` | Bloques por edición |
| `NIGHTLY_NEWSCAST_MAX_VIDEOS` | `3` | Videos de notas por edición |
| `NIGHTLY_NEWSCAST_VOICE` | `Orus` | Voz de Gemini TTS |
| `NIGHTLY_NEWSCAST_TTS_MODEL` | `gemini-2.5-pro-preview-tts` | Modelo de locución |
| `NIGHTLY_NEWSCAST_TEMPO` | `0.97` | Ritmo de la locución |

Rollback: `NIGHTLY_NEWSCAST_ENABLED = "false"` en el script o deshabilitar la
tarea `LaVozRiojana-Noticiero`.

## V3 — plan audiovisual por hechos (2026-10-31)

Activa con `NIGHTLY_NEWSCAST_VISUAL=v3` (el script de la tarea la fija; el
default del código sigue en `v2`). Módulos: `utils/newscast_v3.py` (guion por
tramos, recursos, cartera, plan, render, inspección), `utils/newscast_align.py`
(subtítulos alineados) y `remotion/src/v2/newscast/` (`NightlyNewscastV3`).

Flujo: notas → **guion por tramos** (cada tramo es un hecho con sus ids; el
control factual corre por tramo contra SUS notas, no contra todo el bloque)
→ **inventario** de fotos/videos con procedencia y hash → **control visual**
(Gemini, una llamada por recurso con el título de la nota: pertinencia, tipo,
texto incrustado, caras, foco, nitidez; caché por hash) → **puertas** no
compensables (otro hecho, menor identificable, cara en policiales/sensibles,
estudio de TV, video sin verificar, ilegible) → puntaje entre elegibles
(relevancia 50, claridad 20, utilidad 15, encuadre 10, novedad 5) →
**cartera** por importancia (interés 30, novedad 20, impacto local 20,
utilidad 15, seguimiento 10, material 5) → **voz** por bloque (Orus, caché por
texto) → **alineamiento** local → **plan** en ms, convertido a frames en un
solo lugar (`ms_to_frame`) → `validate_plan` → render → `loudnorm` + limitador
→ inspección.

### Familias

| Familia | Cuándo | Qué se ve |
|---|---|---|
| `video` | video del hecho que gana a la mejor foto | pantalla completa si es vertical; ventana sin nada encima si es horizontal; tramos distintos del mismo video, nunca loop |
| `photo` | foto del hecho | pantalla completa con cámara lenta (3,5–6 %) si el recorte no amplía más de 2,4× ni corta texto o sujetos; si no, ventana; general → detalle sólo con ≥1000 px |
| `related` | 2–3 hechos distintos del mismo fenómeno | un hecho por vez con su lugar, su fuente y "n de m"; corte directo; cada hecho con su encuadre; un hecho sin material va tipográfico (nunca la foto del otro) |
| `timeline` | ≥2 momentos comprobados del mismo hecho | nodos que se activan cuando la voz llega a cada momento |
| `data` | cifra de la nota que también dice la voz | cifra grande con su valor final; con foto, banda superior con cámara lenta y su rótulo |
| `limited` | sin material propio elegible | titular grande y, después, la frase que se escucha en grande |
| `service` | acción, zona y vigencia textuales y no vencidas | papel con zona y vigencia |
| `principal` | primera historia (sobre su familia) | marca + descriptor + fecha y titular legibles desde el frame 0; firma f1–6, lugar f4–12, subrayado f8–15 |

Apertura: la noticia principal desde el frame 0 (sin sirena, flash, sello
"21 H", tres titulares ni recapitulación). Cierre: 1,5–3 s con marca y un CTA
verificado (`lavozriojana.com`; la cuenta real de IG es `@lavozriojana.ok`, por
eso el CTA no nombra un usuario). Pausa entre noticias: 380 ms.

### Subtítulos

whisper.cpp local (`scripts/install_newscast_aligner.py`, release `b5454`,
modelo `ggml-small-q5_1`, SHA-256 fijos, MIT) sobre el WAV final de cada
bloque. Sólo se le sugieren nombres propios. Mapeo monótono texto aprobado ↔
palabras reconocidas, comparando formas habladas (cifras, %, $, horas). Una
palabra sin par se ubica sólo entre dos anclas reales y queda `interpolated`.
Cobertura < 85 % o una palabra crítica (negación, cifra, nombre) sin ancla →
ese bloque va **sin subtítulos** y sin cortes por tramo (nunca tiempos
inventados). Cues de 3–7 palabras, ≤ 64 caracteres, sin separar artículo/
sustantivo, cifra/unidad, nombre/apellido ni negación/verbo. Caché por hash
del audio + texto + motor/modelo/versión. Se guarda `subtitulos.srt`.

### Salida adicional

`visual_plan.json` (plan versionado, alineamiento, recursos aceptados y
rechazados con motivo, ledger de tramos, diagnósticos, tiempos por etapa,
llamadas e inspección técnica) y `subtitulos.srt`. `guion.json` conserva las
claves de V2 (`gancho`, `titulares`, `bloques[].titulo/locucion/ids/notas`,
`cierre`) y agrega `version`, `tramos`, `tipo`, `titulo_corto`, `relevancia`.

### Temas sensibles

Desde el 2026-10-31 no se descartan (pedido del responsable): entran
marcados, con reglas reforzadas en el guion (sin nombres ni datos que
identifiquen víctimas o menores, sin detalles morbosos ni métodos) y sin
ninguna cara en el material. `NIGHTLY_NEWSCAST_SENSITIVE=exclude` vuelve al
filtro anterior.

### Flags V3

| Variable | Default | Uso |
|---|---|---|
| `NIGHTLY_NEWSCAST_VISUAL` | `v2` | `v3` activa esta versión |
| `NIGHTLY_NEWSCAST_SENSITIVE` | `include` | `exclude` descarta temas sensibles |
| `NIGHTLY_NEWSCAST_MIN_BLOCKS_V3` / `MAX_BLOCKS_V3` | `3` / `7` | historias por edición |
| `NIGHTLY_NEWSCAST_POOL_POLICIAL_SHARE` | `0.5` | tope policial del pool de candidatas |
| `NIGHTLY_NEWSCAST_POLICIAL_REVIEW_SHARE` | `0.65` | umbral de revisión trazable |
| `NIGHTLY_NEWSCAST_MAX_UPSCALE` | `2.4` | ampliación máxima a pantalla completa |
| `NIGHTLY_NEWSCAST_VIDEO_SECONDS` | `60` | segundos de video descargados por nota |
| `NIGHTLY_NEWSCAST_MUSIC` | `true` | música de fondo (ganancia medida: ~20 dB bajo la voz) |
| `NIGHTLY_NEWSCAST_MUSIC_UNDER_DB` | `20` | diferencia voz/música |
| `NIGHTLY_NEWSCAST_LUFS` | `-14` | normalización final (+ limitador a −2 dBFS) |
| `NIGHTLY_NEWSCAST_DESCRIPTOR` | `Resumen del día` | descriptor junto a la marca |
| `NIGHTLY_NEWSCAST_CTA` | `Notas completas en lavozriojana.com` | CTA del cierre |
| `NIGHTLY_NEWSCAST_ALIGNER_DIR` | `tools/whisper` | instalación del alineador |

Rollback: `NIGHTLY_NEWSCAST_VISUAL = "v2"` en `scripts/run_nightly_newscast.ps1`.
No hay que borrar nada: V2 no cambió (salvo la inclusión de temas sensibles,
que se revierte con `NIGHTLY_NEWSCAST_SENSITIVE=exclude`).

QA: `python scripts/newscast_inspect.py <mp4>` genera hoja 1 fps, apertura,
fronteras (antes/corte/después de cada toma y del cierre), vista 360×640 con
la interfaz sombreada e `inspeccion.json`.

## V4 — noticiero policial de 24 h (2026-10-31, misma bandera `v3`)

Corrección de dirección pedida por el responsable tras ver la V3 ("demasiado
estática, voz lenta, intro y outro pobres, pocas policiales"). Sigue detrás de
`NIGHTLY_NEWSCAST_VISUAL=v3`; V2 intacta para rollback.

**Selección.** Ventana de 24 h (`NIGHTLY_NEWSCAST_WINDOW_HOURS_V3`) desde la
biblioteca de notas propias: sección policiales, fuentes judiciales y sucesos
de sociedad/interior con palabra clave policial en el título (incendios,
choques, rescates). Sin cuota por sección. Guion de 8–12 hechos y 230–280
palabras (≈1:45); si queda corto, el validador pide sumar los hechos que
quedaron afuera; si se pasa de 290 palabras, pide recortar. Barrera nueva:
notas agrupadas como un mismo hecho tienen que compartir localidad o dos
palabras significativas del título (atrapó "Sanagasta" + "Zonda en el
aeropuerto"); el lugar no puede ser sólo la sede del tribunal. Duración final
≤ 1:59 (salen los hechos de menor puntaje, nunca los del gancho).

**Apertura** (`derive_hook`): títulos cortos de los hechos principales con imagen
propia, siempre abre uno con video si lo hay, máximo `HOOK_MAX_WORDS=10` palabras.
Si la toma deja la apertura en más de 7 s, sale la última frase y se rehace la
voz del gancho. `repair_short_title` repone preposiciones y artículos que el
título corto perdió ("tentativa femicidio" → "tentativa de femicidio"), tomados
del título completo o de la locución.

**Ningún hecho sin imagen** (`NIGHTLY_NEWSCAST_REQUIRE_MEDIA=true`, default).
Antes del guion, `prescreen_media` revisa la foto procesada de cada nota (y el
video sólo si la foto no sirve; tope `NIGHTLY_NEWSCAST_PRESCREEN_VIDEOS=8`) con
las mismas puertas del armado; las notas con pinta judicial se evalúan sin
retratos. Sólo las notas con imagen propia elegible llegan al guion, y en el
armado cualquier bloque que igual quede sin imagen sale. Si quedan menos de
`NIGHTLY_NEWSCAST_MIN_BLOCKS_V3` hechos, la edición queda `no_work`
(`pocos_hechos_con_imagen`). Los controles se guardan en la biblioteca: el
armado no vuelve a llamar al modelo. Con `false` vuelve la regla anterior.

**Biblioteca** (`utils/newscast_library.py`, `meta/run_newscast_library.py`).
`data/newscast_library.json` + `output/newscast_library/<clave>/`: policiales y
política de las últimas 36 h con cuerpo de la nota, foto ya procesada (copia de
`output/web_media`, sin volver a descargar), video preparado en 1080p (a
pedido) y controles visuales por hash. Retención 72 h. La corre el noticiero
antes del guion; puede programarse cada hora.

**Voz.** V3 medía ~121 palabras/min (V2 ~130). Dirección nueva
(`VOICE_DIRECTION_V4`): tonada riojana suave, ritmo de noticiero, sin
"entonación cantada y tranquila". La toma se mide y, sólo si sale lenta, se
ajusta con atempo hasta 1,12× (`NIGHTLY_NEWSCAST_TARGET_PPM`, 158). Medido en la
edición del 31/10: 135–181 ppm de origen. Pausa entre noticias ≈ 340 ms.

**Apertura (≈5–7 s).** Gancho determinista: títulos cortos ya validados de los
3 hechos más importantes con imagen propia (video primero), dichos por Orus;
cada frase corta a la imagen de SU hecho cuando se pronuncia, con titular por
máscara. Cierre de la apertura: barrido rojo, mosaico de esos hechos y marca.

**Fidelidad del título y del día (2026-11-01).** Título, título corto y frases
del gancho no pueden afirmar una situación procesal o desenlace que la nota no
dice (`status_drift`: demorado, detenido, imputado, procesado, condenado,
muerto): "demorado" nunca pasa a "detenido". Una nota publicada en la ventana
pero cuyo comienzo ubica el hecho dos o más días antes ("este miércoles" en la
edición del sábado; `stale_weekday`) no entra como candidata; queda en
`selection.stale` del reporte.

**Historias.** HUD (marca, "Policiales 24 H", contador y avance). Titular
grande que entra por máscara línea a línea con la palabra clave en caja roja;
en la primera pausa real se contrae en regleta. Datos que entran cuando la voz
los dice: lugar (sello con pin que queda como chip), cantidades ("2 JÓVENES",
"4 HECTÁREAS"), cifra del dato y término clave ("INCENDIO") — el término clave
nunca sobre retratos ni en historias judiciales y no se repite en la edición.
Familias: video protagonista (pantalla completa 1080p, tramos distintos del
mismo video), fotografía (pantalla completa o escenario superior con borde en
diagonal), hechos relacionados (número grande y lugar por hecho), judicial
(placa "Justicia" y panel claro), breve, datos, cronología, sin imagen
(tipografía viva, sólo con `NIGHTLY_NEWSCAST_REQUIRE_MEDIA=false`) y servicio. Subtítulos abajo (y≈1290–1450), centrados, con la
palabra que se dice resaltada.

**Transiciones y sonido.** Barrido en diagonal, cortina roja de marca, lugar a
pantalla completa e iris, rotando sin azar; *whoosh* en cada corte, acento
breve en cada dato (`tick.mp3`, sintetizado), música `bed.mp3` a −13 dB de la
voz (−8 dB más fuerte en la apertura), *sting* en el cierre. Sin sirenas.

**Cierre (≈3–4 s).** La voz y el texto grande dicen lo mismo ("Lo que pasa en La
Rioja, lo sabés acá. Seguinos."), cada línea cuando se pronuncia; handle
verificado `@lavozriojana.ok`. Ningún subtítulo de noticias sobre el cierre
(lo verifica `validate_plan`).

**Rostros.** Por pedido del responsable no se excluyen primeros planos de
adultos; sí menores identificables y cualquier rostro en temas sensibles.

**Créditos.** Las fuentes ya no se muestran en pantalla: van en `texto.txt`
("Información e imágenes: …").


## V5 — apertura en frío y edición por frases (2026-11-01, `NIGHTLY_NEWSCAST_VISUAL=v5`)

Corrección tras medir el Reel publicado el 31/10 (V4): a los ~85 min tenía 186
reproducciones, 152 cuentas y **6,7 s de visualización promedio sobre 118,9 s**;
la retención caía al 50 % en el primer segundo y al 18 % en el tercero. La
auditoría cuadro a cuadro de ese video (ver `docs/DECISIONS.md`, 2026-11-01)
encontró: frame 0 sin texto ni marca; titular genérico ("Incendios en la
provincia") que recién se lee a los 0,25 s; 45 % inferior de la pantalla vacío;
una placa de marca a los 4,3 s que interrumpe; la misma foto repetida al entrar
a la primera noticia; 9 de 10 historias con una sola foto quieta durante 8–13 s
(8 tramos estáticos ≥ 2,5 s); "Detenido" para un menor *demorado*; dos notas del
miércoles contadas como "últimas 24 h"; caption con dos bloques de hashtags y
la lista de fuentes; portada = cuadro de los 6 s.

V5 reutiliza toda la cadena de V4 (selección de 24 h, prefiltro de imágenes,
barreras factuales, control visual, caché de voz, alineamiento local) y cambia:

**Guion** (`SCRIPT_PROMPT_V5`, mismo validador con otros límites). Primero qué
pasó; la segunda oración sólo si suma consecuencia o respuesta de la Justicia;
6–10 bloques, 140–210 palabras, tope 36 por bloque; el primer bloque es el
hecho más contundente o útil y su primera oración se entiende sola en 3 s;
fuera lo que no tiene interés público; sin relleno burocrático; títulos
concretos (nunca "complican la jornada"). No hay locución de gancho aparte (un
TTS menos por edición).

**Apertura en frío.** El frame 0 ya es la noticia principal: foto, titular
grande (completo a los 0,25 s) y la marca como barra roja "La Voz Riojana ·
Resumen policial · La Rioja · fecha" que a los 1,4 s se contrae en el HUD
(contador 01/07 y avance). La voz dice el hecho desde el frame 2. Se compararon
tres aperturas sobre el mismo material (`NIGHTLY_NEWSCAST_OPENING`):
`headline` (elegida), `rundown` (tres titulares que se abren) y `map` (lugares
del día). `rundown` y `map` muestran un índice mientras la voz ya cuenta el
primer hecho y demoran la imagen de impacto ~1 s; quedan para pruebas A/B.

**Voz** (`tighten_voice`). Sobre el WAV de la caché: se acortan las pausas
medidas en el audio (deja 280 ms en punto, 160 en coma, 90 entre palabras) y,
si la toma sigue por debajo de `NIGHTLY_NEWSCAST_TARGET_PPM_V5` (168 ppm), se
ajusta con Rubber Band conservando formantes, tope `NIGHTLY_NEWSCAST_MAX_TEMPO_V5`
(1,08). Los tiempos de cada palabra se trasladan con el mismo mapa: no se
re-alinea ni se vuelve a sintetizar. Entre historias quedan ~220 ms.

**Tomas por frase** (`plan_story_v5`). Cada historia se corta en tomas de
~2,6 s (mínimo 1,5 s) en pausas reales del alineamiento: general → detalle →
contraplano. Modo por foto: `full` (pantalla completa, ampliación ≤ 2×),
`band` (franja nítida de 1150 px con la misma foto desenfocada arriba y abajo;
la cámara recorre la foto apaisada) o `card` (foto chica enmarcada en papel
sobre su fondo). El detalle nunca pasa 2,35× de ampliación; el video conserva
su movimiento.

**Mapa.** Si el lugar de un tramo es una localidad del nomenclador oficial
(`config/newscast_geo_la_rioja.json`, 90 localidades IGN/BAHRA; alias sólo
inequívocos: "Sanagasta", "capital"), entra una toma de 1,9 s con el contorno
de La Rioja, el pin, el departamento y la foto del hecho en chico, cuando la
voz nombra el lugar (o en la segunda frase). "barrio X", "Aeropuerto" o una
calle no se ubican nunca. `scripts/build_newscast_geo.py` regenera el contorno
y el nomenclador desde datos.gob.ar.

**Jerarquía de pantalla.** HUD y regleta arriba (y 228–380); datos, lugar y
mapa en el medio (y 430–1000); titular grande en el tercio inferior (fondo en
y 1248) sólo mientras se presenta el hecho, después sube a la regleta;
subtítulos cinéticos abajo (y 1318–1470): grupos de 1–4 palabras que aparecen
a medida que se dicen, una palabra clave por grupo sobre caja roja (lugar,
cifra o término clave, nunca la palabra que ya está en rojo en el titular ni
una edad). Datos (`4 HECTÁREAS`, cifras grandes que cuentan) entran cuando la
voz los dice; si el titular grande sigue en pantalla, esperan a que suba (≤ 0,9 s);
nunca sobre el mapa; una edad nunca es "dato".

**Transiciones.** La toma que entra es la primera de la historia siguiente
dibujada en su frame 0 (el corte no salta): diagonal de marca (`slash`),
deslizamiento lateral (`slide`) y subida (`lift`), con desenfoque de
movimiento; una cortina roja con el logo marca la mitad de la edición
(`brand`). *Whoosh* en cada cambio de historia, campana suave en el pin del
mapa (`ping.mp3`, sintetizado), *tick* en los datos, música más presente en el
primer segundo y medio. Textura común: grano propio (`grain.png`) y viñeta.

**Cierre (~4 s).** Mosaico con las fotos del día, banda roja con la frase que
dice la voz, `@lavozriojana.ok` y "Las notas completas, en lavozriojana.com".

**Portada** (`NewscastCoverV5`, `portada.jpg` 1080×1920). Mismo plan que el
video: foto principal, titular, "Además · n hechos más" con tres regletas y la
fecha; todo dentro del 3:4 central (grilla del perfil) y lo esencial dentro
del 1:1. Se publica como `cover_url` (R2 temporal); sin portada, el cuadro de
los 6 s como antes.

**Caption** (`caption_v5`). Primera línea: el texto validado del hecho que abre;
después "El resumen policial de La Rioja, en n hechos:" y un renglón por hecho (con
el lugar si la oración no lo dice), cierre y 4 hashtags fijos
(`#LaRioja #NoticiasLaRioja #Policiales #LaVozRiojana`). Sin fuentes, sin
emojis, siempre < 2200 caracteres. Se publica con `caption_complete` (no se
agrega un segundo bloque de hashtags).

**Ubicación.** El ítem lleva `locality = NIGHTLY_NEWSCAST_LOCATION` ("La Rioja")
y `utils/ig_location` pone el `location_id` de La Rioja (ubicación del medio,
no del hecho) si `IG_LOCATION_ENABLED=true` (lo fija el script de la tarea). Si
Meta rechaza la ubicación, se publica sin ella (comportamiento existente).
Facebook no recibe portada ni ubicación (su publicador no las soporta).

**Salida.** Además de lo de V4: `portada.jpg`; `visual_plan.json` agrega
`voice` (ppm antes/después, factor, ms de pausa quitados por historia).

**QA** (`scripts/newscast_inspect.py`, ampliado): `apertura.jpg` (0–3 s a 360 px),
`movil_ui.jpg` (cuadros clave con una interfaz de Reels simulada encima) y en
`inspeccion.json` la energía de movimiento por segundo, los tramos estáticos
(≥ 2,5 s con cambio medio < 1,2/255), silencios y duración/tomas por historia.
El procedimiento completo está en la skill `.claude/skills/lvr-video-qa`.

### Métricas (cómo saber si V5 funcionó)

Línea de base: edición del 31/10 (V4), leída con `scripts/newscast_metrics.py`
el 2026-11-01 ~03 h: 118,9 s, alcance 159, 197 reproducciones, **6,5 s de
visualización promedio (5,5 %)**, 1 me gusta, 0 comentarios, 0 compartidos, 0
guardados; en la app: 38 % de omisión, 50 % de retención a 1 s, 18 % a 3 s.

Hipótesis (comparar por promedio de al menos 5 ediciones V5, misma hora, no
una noche contra otra: las noticias cambian el resultado):

| Hipótesis | Métrica | Hoy (V4) | Objetivo V5 | Dónde |
|---|---|---|---|---|
| H1 · el frame 0 comunica | retención a 1 s / 3 s | 50 % / 18 % | ≥ 60 % / ≥ 30 % | app: estadísticas del Reel |
| H1 · menos omisión | tasa de omisión | 38 % | ≤ 30 % | app |
| H2 · más densidad, menos espera | tiempo promedio visto | 6,5 s | ≥ 12 s | `newscast_metrics.py` |
| H2 · se ve una mayor parte | % visto promedio | 5,5 % | ≥ 15 % | `newscast_metrics.py` |
| H3 · vale la pena compartirlo | compartidos + guardados cada 1000 cuentas | 0 | > 5 | `newscast_metrics.py` |
| H3 · convierte | seguidores desde el Reel | — | > 0 por edición | app |

Lectura: si sube H1 pero no H2, el gancho funciona y el cuerpo no (revisar
duración por historia y orden); si no sube H1, probar `NIGHTLY_NEWSCAST_OPENING`
(una semana `headline`, otra `rundown`) antes de cambiar el diseño. No atribuir
un resultado a un solo cambio: V5 cambió apertura, guion, voz y edición a la vez.

### Flags V5

| Variable | Default | Uso |
|---|---|---|
| `NIGHTLY_NEWSCAST_VISUAL` | `v2` | `v5` activa esta versión (el script de la tarea la fija) |
| `NIGHTLY_NEWSCAST_OPENING` | `headline` | `rundown` o `map` para pruebas A/B |
| `NIGHTLY_NEWSCAST_TARGET_PPM_V5` | `168` | ritmo objetivo de la locución |
| `NIGHTLY_NEWSCAST_MAX_TEMPO_V5` | `1.08` | ajuste máximo de ritmo |
| `NIGHTLY_NEWSCAST_MAX_MS_V5` | `110000` | duración máxima (salen las de menor puntaje, nunca la que abre) |
| `NIGHTLY_NEWSCAST_CTA_V5` | `@lavozriojana.ok` | cuenta del cierre |
| `NIGHTLY_NEWSCAST_LOCATION` | `La Rioja` | localidad para el `location_id` |

Rollback: `NIGHTLY_NEWSCAST_VISUAL = "v3"` en `scripts/run_nightly_newscast.ps1`
(V4 intacta; la publicación vuelve a `thumb_offset` y al caption anterior).
