# ROADMAP.md

> Roadmap inicial (2026-07-20), derivado del estado actual y del backlog. No hay fechas
> comprometidas formalmente todavía — se organiza por horizonte relativo. Actualizar a
> medida que se confirmen prioridades reales con el operador del sistema.

## Horizonte inmediato — estabilizar lo que ya existe

Objetivo: que el pipeline actual corra de forma confiable y observable, sin agregar
funcionalidad nueva todavía.

- Confirmar que el supervisor 24/7 está activo y recuperar visibilidad de logs
  recientes.
- Resolver el backlog creciente de publicaciones en Facebook (logging de errores real
  primero, luego causa raíz).
- Cerrar deuda técnica menor: `psutil` en `requirements.txt`, backups automáticos de
  `data/`.
- Consolidar este repo (`AutoPublicador_LaVozRiojana`) como repositorio git propio y
  aislado en GitHub (hecho el 2026-07-20, ver `DECISIONS.md`).

## Corto plazo — observabilidad y confianza en el contenido publicado

Objetivo: poder responder "¿cuánto se publicó, con qué éxito, y qué alcance tuvo?" sin
tener que leer logs a mano.

- Agregación simple de métricas de publicaciones/día y tasa de éxito por plataforma
  (ver `METRICS.md`).
- Integrar Meta Insights API para medir alcance/impresiones reales, no solo
  confirmación de publicación.
- Ampliar tests automatizados a scrapers y generación de imagen/video, para reducir
  dependencia de QA manual.

## Mediano plazo — mejorar calidad editorial y producto

Objetivo: mejorar la relevancia y confiabilidad del contenido, no solo el volumen.

- Evaluar un paso de aprobación humana opcional antes de publicar (hoy 100%
  automático), al menos para categorías sensibles (ej. policiales).
- Conectar analítica del sitio (`lavozriojana.com`) para medir visitas/CTR reales
  atribuibles a las notas de este pipeline.
- Revisar y documentar el contrato de la API del CMS externo para evitar roturas
  silenciosas de `pipeline/node_webapp/publisher.py`.

## Largo plazo — escalar el sistema

Objetivo exploratorio, sin compromiso de ejecución todavía.

- Evaluar reemplazar el almacenamiento en JSON planos por una base de datos liviana si
  el volumen lo justifica.
- Evaluar extender el sistema a más fuentes de scraping o a otros medios regionales,
  reusando la arquitectura actual (requeriría hacerla multi-tenant en configuración).
- Evaluar monetización o integración con pauta publicitaria, si se vuelve un objetivo
  de negocio (fuera de alcance del sistema hoy, ver `PRODUCT.md`).

## Fuera de alcance por ahora

- Moderación de comunidad / respuesta a comentarios en redes.
- Panel de administración web completo (más allá de las herramientas locales actuales).
- Multi-tenant real para más de un medio.
