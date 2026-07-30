"""
Inicializa los archivos de datos vacíos necesarios para arrancar el sistema.
Ejecutar una sola vez antes del primer ciclo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from utils.paths import data_dir
from utils.file_manager import save_json

DATA_DIR = str(data_dir())
os.makedirs(DATA_DIR, exist_ok=True)

FILES = {
    "noticias_ejecutadas_locales.json": [],
    "noticias_ejecutadas_policiales.json": [],
    "noticias_ejecutadas_interior.json": [],
    "noticias_ejecutadas_deportes.json": [],
    "noticias_norewrite_locales.json": [],
    "noticias_norewrite_policiales.json": [],
    "noticias_norewrite_interior.json": [],
    "noticias_norewrite_deportes.json": [],
    "noticias_norewrite_nuevarioja.json": [],
    "noticias_ejecutadas_nuevarioja_politica.json": [],
    "noticias_ejecutadas_nuevarioja_sociedad.json": [],
    "noticias_ejecutadas_nuevarioja_policiales.json": [],
    "noticias_ejecutadas_nuevarioja_deportes.json": [],
    "noticias_ejecutadas_nuevarioja_interior.json": [],
    "noticias_ejecutadas_nuevarioja_internacionales.json": [],
    "noticias_meta.json": [],
    "noticias_web_pending.json": [],
    "noticias_sociales_pendientes.json": [],
    "videos_manuales_borradores.json": [],
    "publicaciones_manuales_borradores.json": [],
    "publicaciones_manuales_publicadas.json": [],
    "fb_posted.json": {"posted": {}, "page_backoff": {}},
    "ig_posted.json": {"posted": {}},
    "ig_rate_limit.json": {},
    "rewrite_queue_state.json": {
        "version": 1,
        "name": "rewrite",
        "pending": [],
        "processing": [],
        "completed": [],
        "failed": [],
        "expired": [],
        "dead_letter": [],
    },
    "queue_events.json": [],
    "noticias_filtradas_body_keywords.json": [],
    "editorial_candidates.json": [],
    "editorial_routing_events.json": [],
    "topic_publication_state.json": {},
    "media_library.json": [],
    "premium_packages.json": [],
}

for filename, default in FILES.items():
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        save_json(path, default)
        print(f"Creado: {filename}")
    else:
        print(f"Ya existe: {filename}")

print("\nInicialización completa.")
