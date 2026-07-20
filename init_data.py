"""
Inicializa los archivos de datos vacíos necesarios para arrancar el sistema.
Ejecutar una sola vez antes del primer ciclo.
"""
import os
import json

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
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
    "noticias_meta.json": [],
    "noticias_web_pending.json": [],
    "noticias_sociales_pendientes.json": [],
    "videos_manuales_borradores.json": [],
    "fb_posted.json": {"posted": {}, "page_backoff": {}},
    "ig_posted.json": {"posted": {}},
    "pipeline_resume_state.json": {"stages": {}},
    "noticias_filtradas_body_keywords.json": [],
}

for filename, default in FILES.items():
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
        print(f"Creado: {filename}")
    else:
        print(f"Ya existe: {filename}")

print("\nInicialización completa.")
