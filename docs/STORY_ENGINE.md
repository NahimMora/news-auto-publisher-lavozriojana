# Story Engine

Agrupa notas altamente relacionadas en una historia longitudinal
(`story_key`), muy conservador por diseño: nunca agrupa por sola
coincidencia de categoría, persona o localidad. Código:
`editorial_context/story_engine.py`.

## `topic_key` vs `story_key`

`utils/editorial_router.py::compute_topic_key` (prefijo `topic:`) es un
concepto **distinto y anterior**: fingerprint de "mismo acontecimiento" de
ciclo corto, usado sólo para el cap de 12h por tema en la selección
automática de Instagram y el conteo `topic_post_number`. No se tocó su
semántica.

`story_key` (prefijo `story:`) es una **historia longitudinal** — puede
abarcar semanas o meses (ej. "obra avenida X" vs. el `topic_key` de "corte
de tránsito del 10 de septiembre", que es un evento puntual dentro de esa
historia). Ambos conceptos conviven sin acoplarse: `news_dedup.py` no usa
`topic_key`, y `story_engine.py` no depende de `editorial_router.py`.

## Algoritmo

`assign_story(article_id, title, excerpt, category, entities, localities,
published_at, candidates)`:

1. Si no hay candidatos del archivo (`candidate_retrieval`), devuelve
   `None` — una noticia nueva sin antecedentes **no es un error** (Parte 53:
   nunca se exige `archive_match_required=true` para publicar).
2. Puntúa los candidatos (`retrieval.rank_candidates`) y filtra a los que
   superan la barra de su categoría (`RelationScore.meets_category_bar`,
   ver `docs/EDITORIAL_CONTEXT.md`).
3. Si no queda ninguno calificado, devuelve `None`.
4. Si alguno de los calificados ya tiene `story_key`, la reutiliza
   (`created_new=False`) — así una historia puede crecer indefinidamente.
5. Si ninguno tiene `story_key`, crea uno nuevo determinístico:
   `story:<sha1(article_id_del_predecesor)[:12]>` — la clave nace atada a un
   artículo real específico, no a un término que podría colisionar entre
   historias distintas del mismo tema genérico.
6. Persiste la relación (`story_relations`: `relation_score`,
   `relation_reason`, `matched_entities`, `matched_terms`,
   `time_distance_days`, `confidence`) tanto para el predecesor (si recién
   se le asignó story_key) como para el artículo actual.

## Umbrales por categoría

| Categoría | Umbral | Evidencia exigida |
|---|---:|---|
| `policiales`, `espectaculos`, `deportes` | 0.55 | entidad **Y** término compartido |
| resto (`politica`, `economia`, `salud`, `interior`, `sociedad`, `cultura`, `educacion`) | 0.45 | entidad **O** localidad específica |

La exigencia doble en las categorías estrictas es la salvaguarda central de
la Parte 10: una misma persona/equipo/artista **no alcanza** por sí sola.

## Ejemplos por categoría (Parte 9)

- **Política**: misma ley/programa/medida en distintas etapas (ej.
  "aprobó en primera vuelta" → "convirtió en ley") agrupa; dos leyes
  distintas del mismo funcionario, no.
- **Policiales/judiciales**: misma causa/hecho (detención → condena del
  mismo expediente) agrupa; dos causas distintas de la misma persona, no
  — ver caso de test "Juan Pérez asumió un cargo" vs. "Juan Pérez participó
  de un festival": comparten entidad, no comparten ningún término temático,
  no agrupa.
- **Deportes**: mismo equipo + misma competencia/torneo agrupa (ej.
  "ganó el primer partido del torneo regional" → "clasificó a la final del
  torneo regional"); el mismo equipo en competencias distintas, no.
- **Espectáculos**: mismo artista + evento concreto (ej. anuncio de
  separación → declaraciones posteriores sobre lo mismo) agrupa; 20 notas
  distintas del mismo famoso por compartir sólo el nombre, no.
- **Obras/Sociedad/Economía/Salud**: anuncio → inicio → etapas → corte →
  finalización de la misma obra/programa/campaña agrupa con el umbral no
  estricto (entidad o localidad específica alcanza, dado que estas
  historias suelen ser más institucionales/geográficas que personales).

## Bug real encontrado y corregido durante el desarrollo de tests

Al escribir el caso "mismo famoso, eventos distintos, muchas notas" se
detectó que `retrieval.significant_terms()` excluía la entidad completa
normalizada ("maria becerra") del cálculo de términos compartidos, pero
**no** las palabras sueltas que la componen ("maria", "becerra"). El propio
nombre se colaba como si fuera un "término temático compartido"
independiente, permitiendo que dos notas sin ningún vínculo temático real
(sólo el nombre) superaran el umbral estricto. Corregido excluyendo también
las palabras individuales de cada entidad excluida
(`tests/test_editorial_context_story_engine.py::test_same_celebrity_different_unrelated_events_no_story_even_with_many_notes`).

## Timeline (Partes 11/12)

`editorial_context/timeline.py::build_timeline(story_key, exclude_article_id)`:

- Exige al menos **2 artículos previos** en la historia (además del
  actual) y **al menos una relación de confianza `high`** dentro de esa
  historia — un umbral alto explícito, no sólo "pertenecer a la misma
  historia".
- Máximo **5 items**, orden cronológico, la nota actual nunca aparece en
  su propia lista.
- Si no se cumplen las condiciones, devuelve una lista vacía — "no
  quiero timelines basura" (Parte 12) se aplica literalmente: sin
  timeline, no hay módulo "Seguí esta historia" en la web
  (`components/news/StoryTimeline.tsx` se autooculta con `< 2` items de
  todas formas, como segunda capa de seguridad).

## Persistencia en el CMS

`Post.storyKey` (nullable, indexado `[storyKey, publishedAt]`) es lo único
que necesita el CMS: la página de la nota consulta
`getStoryTimeline(storyKey, excludePostId)` para armar el timeline en el
momento de render, sin duplicar datos entre el índice Python y la base de
datos del CMS. Ver el repo `LaVozRiojana`,
`prisma/migrations/20260910130000_add_post_story_key/`.

## Backfill de historias existentes (Parte 43)

`scripts/backfill_story_index.py`:

```powershell
python scripts/backfill_story_index.py --report-only   # default, nunca escribe
python scripts/backfill_story_index.py --apply --confirm --limit 50
```

Recorre `archive_articles` sin `story_key`, evalúa candidatos con el mismo
`assign_story` del flujo en vivo, y reporta `post / candidate_story /
confidence / reason`. `--apply` requiere `--confirm` explícito y actualiza
tanto el índice local como el CMS real vía `PATCH /api/private/posts/<id>`
(mismo endpoint que ya usa el autopublicador). Sin credenciales
(`WEBAPP_BASE_URL`/`PRIVATE_API_KEY`) configuradas, no escribe nada y lo
reporta como error explícito.
