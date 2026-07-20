# USERS.md

## Perfiles de usuario

### 1. Operador del pipeline (usuario principal, hoy: el dueño del repo)
- **Quién es**: la persona responsable de que "La Voz Riojana" tenga contenido nuevo
  publicado en el sitio y redes sociales de forma constante.
- **Qué necesita**:
  - Que el proceso corra solo, sin intervención diaria.
  - Poder arrancar/parar el sistema y ver su estado con comandos simples
    (`python cli.py start|stop|status|logs`).
  - Detectar rápido si algo se rompió (scraper caído, publicación fallando, cola
    creciendo sin bajar).
  - Ajustar configuración (qué secciones scrapear, ritmo de publicación, límites por
    plataforma) vía `.env`, sin tocar código.
- **Nivel técnico**: sabe usar terminal/CLI y editar `.env`, pero no necesariamente lee
  logs Python en detalle todos los días.

### 2. Editor/curador manual (uso ocasional)
- **Quién es**: alguien que quiere publicar algo puntual que el pipeline automático no
  captó (una nota de otra fuente, un video propio) usando las mismas herramientas de
  diseño/publicación.
- **Qué necesita**:
  - `video_reel_manager.py` (UI local en `127.0.0.1:8765`) para pegar un link, generar
    título/caption con IA, armar un video Reel y publicarlo manualmente.
  - `pipeline/custom_post.py` para publicar una nota "a mano" (título/cuerpo propio)
    reusando el mismo pipeline de publicación web/redes.
  - `preview_pipeline.py` para ver cómo van a quedar las imágenes de Instagram/Facebook
    de las últimas notas antes de que se publiquen solas (control de calidad visual).

### 3. Lectores finales de "La Voz Riojana" (usuarios indirectos)
- **Quiénes son**: audiencia del sitio `lavozriojana.com` y de las cuentas de Facebook
  e Instagram del medio — vecinos de La Rioja interesados en noticias locales,
  policiales, deportivas y de interior.
- **Qué esperan implícitamente** (aunque no interactúan con este repo):
  - Notas rápidas, relevantes a su localidad (por eso el hashtag de localidad en los
    títulos/captions).
  - Contenido no duplicado ni "spammy" (por eso existe deduplicación por similitud y
    límites de publicaciones por corrida).
  - Información sin datos inventados (regla explícita en los prompts de reescritura).

### 4. Futuro: otros medios/secciones (usuario potencial, no implementado)
- Si el sistema se extiende a otros medios regionales, este perfil pasaría a ser un
  "operador" adicional con su propia configuración de fuentes, credenciales de
  Facebook/Instagram y branding de imágenes — hoy la configuración es single-tenant
  (un solo medio, una sola cuenta de cada plataforma) vía variables de entorno.
