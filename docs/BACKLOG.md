# BACKLOG.md

> Backlog inicial derivado de gaps encontrados al documentar el sistema
> (2026-07-20). No tiene aún priorización formal por sprint/fecha — usar como punto de
> partida y reordenar según necesidad real del operador.

## Alta prioridad (operación)

- [ ] Confirmar y restaurar la ejecución continua del supervisor (`python cli.py
      status`) — el log no muestra actividad desde 2026-07-13.
- [ ] Diagnosticar y resolver el backlog creciente de publicaciones en Facebook
      (ver `KNOWN_ISSUES.md`).
- [ ] Enrutar los loggers de `meta/fb_client.py` y `meta/facebook_token_manager.py` a
      archivo (hoy solo consola, se pierden con `stdout=DEVNULL`).
- [ ] Agregar `psutil` a `requirements.txt` (se usa en `cli.py` pero no está declarado).

## Media prioridad (observabilidad y calidad)

- [ ] Definir y calcular métricas agregadas de publicaciones/día y tasa de éxito por
      plataforma (ver `METRICS.md`) en vez de leerlas del log crudo.
- [ ] Integrar Meta Insights API para medir alcance/impresiones reales por post, no solo
      confirmación de publicación.
- [ ] Automatizar backups periódicos de `data/` (hoy son manuales/ad hoc, solo 3
      snapshots existentes).
- [ ] Ampliar cobertura de tests: hoy solo `pipeline/node_webapp` y clientes de
      Meta/social_queue tienen tests; scrapers, generación de imagen/video y el
      supervisor/CLI no tienen tests automatizados.

## Media prioridad (producto)

- [ ] Evaluar agregar verificación/aprobación humana opcional antes de publicar (hoy es
      100% automático una vez que la nota pasa el filtro editorial de OpenAI).
- [ ] Conectar analítica del sitio (`lavozriojana.com`) para medir visitas/CTR
      atribuibles a las notas publicadas por este pipeline.
- [ ] Evaluar extender fuentes de scraping más allá de `tiempopopular.com.ar` y
      `nuevarioja.com.ar`.

## Baja prioridad / exploratorio

- [ ] Evaluar reemplazo del almacenamiento en JSON planos por una base de datos liviana
      (ej. SQLite) si el volumen de notas/colas empieza a generar problemas de
      integridad o performance.
- [ ] Investigar si `IG_CHROME_PROFILE_DIR` (hook de Selenium sin implementar,
      actualmente `PENDIENTE` en `.env`) sigue siendo necesario o se puede eliminar.
- [ ] Documentar formalmente el contrato de la API privada que expone el CMS externo
      (`WEBAPP_BASE_URL`), para que cambios ahí no rompan `pipeline/node_webapp/publisher.py`
      sin aviso.

## Deuda técnica

- [ ] `.git` de este proyecto estaba roto/mezclado con otro repo (Desktop-level) al
      momento de crear esta documentación — verificar que el nuevo repo dedicado quede
      correctamente aislado y no vuelva a mezclarse con otros proyectos del mismo disco.
- [ ] No hay README.md en el repo — considerar uno breve que apunte a `/docs` y
      `AGENTS.md` como punto de entrada.
