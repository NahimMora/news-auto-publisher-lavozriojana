# Ajustes operativos solicitados — 2026-07-27

## Alcance y estado

El corte de colas y los cambios de código se realizaron con el supervisor detenido y
la tarea watchdog 24/7 pausada. La suite automatizada permaneció aislada, sin
publicaciones ni llamadas externas. Después de validar el perfil y por autorización
explícita del operador, se reanudó el servicio real; la evidencia de ese ciclo se
separa de los resultados mockeados.

### Hechos comprobados

- Web tenía 33 pendientes y Meta 37; todos tenían timestamp durable.
- Las 20 identidades más recientes estaban presentes en ambas colas.
- El feedback a OpenAI incluía warnings pero no el intento previo.
- El sexto resultado se descartaba y se reemplazaba por fallback original.
- Facebook podía omitir el título y no precalentaba la nota/imagen.
- El supervisor imponía un elemento por canal/ciclo y Web había crecido 24→33.

### Inferencias

- El cupo de uno fue el cuello de botella principal del backlog observado.
- Precalentar CMS y R2 reduce fallos de preview, pero no controla la caché interna de
  Meta.

### Información desconocida y bloqueos externos

- No se puede reconstruir la causa del rechazo histórico de Instagram anterior a
  `LVR-069`.
- El CMS sigue sin endpoint read-only de capacidades.
- El comportamiento real del nuevo cupo requiere observar próximos ciclos.

## Hallazgos

| ID | Severidad | Causa | Corrección | Test/evidencia | Estado |
|---|---|---|---|---|---|
| LVR-071 | alta | cutoff basado en fecha externa incompleta | ventana durable últimas 20, archivo/eventos | `tests.test_queue_cutover`; 33→20 Web, 37→20 Meta | corregido |
| LVR-072 | alta | revisión sin intento anterior y descarte del sexto | feedback completo, diff material, último seguro degradado | `EditorialTests` | corregido |
| LVR-073 | media | mensaje divergente y preview no verificado | caption compartido y prewarm OG | `FacebookClientTests` | corregido |
| LVR-074 | alta operativa | límite 1 menor al ingreso | Web ilimitada, Meta 8/ciclo | `tests.test_deployment_modes` | mitigado; observar |
| LVR-075 | media | inicio de oración tratado como entidad | regla estructural de posición y regresión interna | `EditorialTests` + ciclo #8 | corregido |
| LVR-076 | media | números en palabras no equivalían a dígitos | normalización numérica española | dos regresiones editoriales + ciclo #8 | corregido |
| LVR-077 | baja | éxito de prewarm sólo inferible | log estructurado sin URL/token | `FacebookClientTests` | corregido |

## Priorización

Escala 1–5. Puntaje orientativo:
`impacto × confianza × alineación × reutilización / (esfuerzo × riesgo)`.

| ID | Impacto | Confianza | Alineación | Reutilización | Ahorro | Esfuerzo | Riesgo | Mantenimiento | Puntaje |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LVR-071 | 5 | 5 | 5 | 4 | 4 | 3 | 2 | 2 | 83,3 |
| LVR-072 | 5 | 5 | 5 | 4 | 4 | 3 | 3 | 3 | 55,6 |
| LVR-073 | 4 | 5 | 4 | 4 | 4 | 2 | 2 | 2 | 80,0 |
| LVR-074 | 5 | 5 | 5 | 5 | 5 | 1 | 2 | 1 | 312,5 |
| LVR-075 | 3 | 5 | 4 | 4 | 3 | 1 | 2 | 2 | 120,0 |
| LVR-076 | 3 | 5 | 4 | 4 | 3 | 1 | 2 | 2 | 120,0 |
| LVR-077 | 2 | 5 | 4 | 4 | 3 | 1 | 1 | 1 | 160,0 |

## Evidencia de cola

```text
backup: success
report inicial: Web 33 (13 anteriores), Meta 37 (17 anteriores), unknown_order=0
apply: web_archived=13, meta_archived=17, social_states_excluded=0
report final: Web=20, Meta=20, unique_items=20, unknown_order=0
```

Los archivos operativos no se versionan. La evidencia durable queda en
`data/backups/`, `data/queue_cutover_archive.json` y `data/queue_events.json`.

## Evidencia del primer ciclo con los nuevos límites

```text
ciclo #8
scraping/rewrite: success 16/16
Web: degraded 24/26, 2 terminales sensibles, cola final 0
Facebook: success 8/8, 16 diferidas por cupo
Instagram: success 8/8, 5 diferidas
resultado del ciclo: degraded, 3/4 etapas aceptables
```

El `degraded` es correcto: no se convirtió 24/26 en éxito. Las dos noticias sensibles
no desaparecieron ni se marcaron publicadas. Facebook respetó exactamente el límite
de ocho y sólo llegó a Graph después de verificar página/OG porque el prewarm estaba
habilitado; Instagram también respetó ocho. Las noticias incorporadas durante el
scraping explican el crecimiento transitorio de 20 a 26 antes de vaciar Web.

El ciclo también reprodujo `LVR-075` y `LVR-076`. Los correctivos se realizaron
después de que terminara el lote y se cargan mediante reinicio controlado; no se
reescribió la evidencia histórica del ciclo.

## Validación final aislada

```text
python -W error::DeprecationWarning -m unittest discover tests
Ran 235 tests in 17.327s — OK

python -m pip check
No broken requirements found.

python -m compileall -q .
exit 0

python cli.py doctor --scope core --json
success 8/8

python cli.py run-once --dry-run --json
verify_ci_safety.py: production_calls=false

git diff --check
exit 0 (sólo advertencias informativas LF/CRLF de Git)

python scripts/verify_ci_safety.py --base origin/main
sin artefactos operativos ni secretos obvios
```

La ejecución usó `PYTHON_DOTENV_DISABLED=1`, kill switches apagados y directorios
temporales separados para datos, logs, fotos, outputs, backups y cuarentena. Ningún
test consumió las colas reales ni llamó a CMS, Meta, R2 u OpenAI productivos.
