# PRODUCT.md

## Qué problema resuelve

Publicar noticias locales de La Rioja (Argentina) de forma continua, en varios canales
(sitio web, Facebook, Instagram), sin que un humano tenga que redactar, clasificar,
diseñar la imagen y publicar cada nota manualmente.

Concretamente automatiza:

- **Recolección**: scrapea notas nuevas de sitios de noticias de la región
  (`tiempopopular.com.ar`, `nuevarioja.com.ar`) en las secciones locales, policiales,
  interior, deportes, política, sociedad e internacionales.
- **Reescritura editorial**: usa OpenAI para reescribir títulos, clasificar la nota en
  una categoría editorial y generar copies/captions para redes sociales, con reglas de
  estilo propias (no inventar datos, límite de caracteres, hashtag de localidad, etc.).
- **Generación de piezas visuales**: arma imágenes con diseño propio (feed de Instagram,
  OG de Facebook/web) y videos tipo Reel a partir del texto y las imágenes de la nota.
- **Publicación multicanal**: publica automáticamente en el CMS del sitio
  (lavozriojana.com), en la página de Facebook y en la cuenta de Instagram, respetando
  límites de frecuencia y evitando duplicados.
- **Operación 24/7 supervisada**: corre en loop continuo (ciclo horario por defecto),
  con reintentos, logs por módulo y un CLI simple para arrancar/parar/inspeccionar.

## Para quién

- **Uso primario**: el equipo/operador de "La Voz Riojana", un medio digital de La
  Rioja, que necesita mantener el sitio y las redes sociales activas con contenido
  frecuente sin dotación de redacción a tiempo completo.
- **Usuario técnico**: quien opera el pipeline (arranca/para el proceso, revisa logs,
  ajusta configuración vía `.env`) — hoy es una sola persona (el dueño del repo).
- No está pensado (todavía) como producto multi-tenant para otros medios, aunque la
  arquitectura por secciones/fuentes podría extenderse a otro medio con esfuerzo.

## Qué NO intenta resolver

- No es un CMS: el sitio público (`lavozriojana.com`) es una aplicación Node.js
  separada, fuera de este repositorio; este proyecto solo le empuja contenido vía API.
- No genera noticias originales ni hace periodismo de investigación: reescribe y
  reencuadra notas ya publicadas por otros medios de la región, no reemplaza reporteo.
- No modera comentarios, no gestiona la comunidad en redes, no responde mensajes.
- No tiene panel de administración visual completo (salvo herramientas locales
  puntuales como `video_reel_manager.py` y `preview_pipeline.py` para uso manual).
- No factura, no gestiona pauta publicitaria ni monetización directa.
- No garantiza exactitud editorial sin supervisión: el prompt de OpenAI pide
  explícitamente "no inventar datos", pero no hay verificación humana obligatoria antes
  de publicar (ver `KNOWN_ISSUES.md`).

## Cómo genera o podría generar valor

- **Valor actual**: ahorra el tiempo de un editor que debería buscar notas, redactarlas
  para el propio medio, armar el diseño y publicar manualmente en 3 canales, varias
  veces por hora, todos los días. A la fecha de este documento el sistema lleva
  publicados ~683 posts históricos en Facebook y mantiene una cola activa de cientos de
  notas procesadas.
- **Valor potencial**:
  - Tráfico y alcance para `lavozriojana.com` vía SEO (notas web) y redes (Facebook/IG).
  - Posicionamiento del medio como fuente rápida de noticias locales (velocidad de
    republicación frente a competidores).
  - Escalar a más fuentes/secciones o a otros medios regionales reusando la misma
    arquitectura de scraping + reescritura + publicación.
  - Reels automáticos como canal de alcance adicional (formato de mayor distribución
    orgánica en Instagram) sin costo de producción de video manual.
