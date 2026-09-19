@AGENTS.md

## Segundo Cerebro (gestión de conocimiento)

Este repo está trackeado por el "Segundo Cerebro" personal (app aparte,
`AutoPublicadores/2doCerebro`) bajo el proyecto **LVR** (La Voz Riojana),
módulo **Autopublicador**.

- **Documentación**: `README.md`, este archivo, `AGENTS.md` y todo
  `docs/**/*.md` (incluye `KNOWN_ISSUES.md`, `BACKLOG.md`, `DECISIONS.md`,
  `ROADMAP.md`, etc.) se sincronizan de **solo lectura** hacia el Segundo
  Cerebro — nada de eso cambia de lugar ni se duplica ahí, simplemente queda
  buscable desde el dashboard.
- **Pendientes reales**: seguí usando `docs/KNOWN_ISSUES.md` /
  `docs/BACKLOG.md` como hasta ahora (ver `AGENTS.md`). Si además querés que
  algo aparezca en el dashboard del Segundo Cerebro, agregalo ahí como
  captura — no hace falta mantener las dos listas manualmente sincronizadas.
- **IDs**: si un ítem del Segundo Cerebro ya existe para lo que estás
  resolviendo (formato `LVR-BUG-0007`), referencialo en el commit:
  `fix: ... [LVR-BUG-0007]`.
- Esto es solo lectura desde afuera — nada en este repo depende del Segundo
  Cerebro para funcionar, y las reglas operativas de `AGENTS.md` (sobre todo
  la de nunca correr publicadores fuera de la PC de producción) siguen
  siendo la autoridad final.
