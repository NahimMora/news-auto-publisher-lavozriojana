"""Estrategias de descubrimiento por fuente (Parte 21): RSS, sitemap, HTML index.

No hay un scraper único: cada fuente declara en el registry qué estrategia
usar (``fetch_strategy``) y estos módulos son genéricos/reutilizables, no un
script por sitio.
"""
