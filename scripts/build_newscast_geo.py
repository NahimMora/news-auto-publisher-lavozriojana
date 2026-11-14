"""Genera el mapa de ubicación del noticiero (V5) desde datos oficiales.

Entradas (descargar una vez; datos abiertos del Servicio de Normalización de
Datos Geográficos de Argentina, fuente IGN/BAHRA):
  - provincias: https://infra.datos.gob.ar/georef/provincias.geojson
  - localidades: https://apis.datos.gob.ar/georef/api/localidades?provincia=46&max=1000&campos=id,nombre,centroide,departamento.nombre,categoria

Salidas (versionadas, el render no descarga nada):
  - ``remotion/src/v2/newscast5/laRioja.ts``: contorno de la provincia como
    path SVG en un viewBox propio;
  - ``config/newscast_geo_la_rioja.json``: nomenclador (nombre plegado →
    nombre, departamento, x/y en el mismo viewBox) y alias explícitos.

Proyección equirectangular con corrección por coseno de la latitud central:
para una provincia es indistinguible de una cónica y no necesita librerías.

Uso:
    python scripts/build_newscast_geo.py provincias.geojson localidades.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TS_OUT = os.path.join(ROOT, "remotion", "src", "v2", "newscast5", "laRioja.ts")
JSON_OUT = os.path.join(ROOT, "config", "newscast_geo_la_rioja.json")
VIEW_W = 1000
PAD = 20

# Sólo alias inequívocos: cómo lo escribe una nota → nombre oficial.
ALIASES = {
    "sanagasta": "Villa Sanagasta",
    "capital": "La Rioja",
    "la rioja capital": "La Rioja",
    "ciudad de la rioja": "La Rioja",
    "villa union": "Villa Unión",
    "vinchina": "Villa San José de Vinchina",
    "castelli": "Villa Castelli",
    "mazan": "Villa Mazán",
}


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(text or "")) if unicodedata.category(c) != "Mn").lower().strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mapa de La Rioja para el noticiero")
    parser.add_argument("provincias")
    parser.add_argument("localidades")
    opts = parser.parse_args(argv)
    with open(opts.provincias, encoding="utf-8") as fh:
        provinces = json.load(fh)
    feature = next(f for f in provinces["features"] if str(f["properties"].get("id")) == "46")
    geometry = feature["geometry"]
    rings = [geometry["coordinates"][0]] if geometry["type"] == "Polygon" else [poly[0] for poly in geometry["coordinates"]]
    lons = [p[0] for ring in rings for p in ring]
    lats = [p[1] for ring in rings for p in ring]
    lat0 = (min(lats) + max(lats)) / 2
    kx = math.cos(math.radians(lat0))
    span_x = (max(lons) - min(lons)) * kx
    span_y = max(lats) - min(lats)
    scale = (VIEW_W - 2 * PAD) / span_x
    view_h = int(round(span_y * scale + 2 * PAD))

    def project(lon: float, lat: float) -> tuple[float, float]:
        return (round(PAD + (lon - min(lons)) * kx * scale, 1), round(PAD + (max(lats) - lat) * scale, 1))

    path = " ".join(
        "M" + " L".join(f"{x},{y}" for x, y in (project(lon, lat) for lon, lat in ring)) + " Z" for ring in rings
    )
    with open(opts.localidades, encoding="utf-8") as fh:
        raw = json.load(fh)["localidades"]
    # "Localidad simple" gana sobre "Entidad" con el mismo nombre.
    raw.sort(key=lambda loc: (loc["categoria"] != "Localidad simple", loc["nombre"]))
    places: dict[str, dict] = {}
    for loc in raw:
        key = fold(loc["nombre"])
        if key in places:
            continue
        x, y = project(loc["centroide"]["lon"], loc["centroide"]["lat"])
        places[key] = {"name": loc["nombre"], "department": loc["departamento"]["nombre"], "x": x, "y": y,
                       "lat": round(loc["centroide"]["lat"], 4), "lon": round(loc["centroide"]["lon"], 4)}
    aliases = {k: fold(v) for k, v in ALIASES.items() if fold(v) in places}
    capital = places["la rioja"]
    os.makedirs(os.path.dirname(TS_OUT), exist_ok=True)
    with open(TS_OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(
            "// Generado por scripts/build_newscast_geo.py desde datos abiertos del\n"
            "// Servicio de Normalización de Datos Geográficos (IGN). No editar a mano.\n"
            f"export const LA_RIOJA_VIEW = {{ w: {VIEW_W}, h: {view_h} }} as const;\n"
            f"export const LA_RIOJA_CAPITAL = {{ x: {capital['x']}, y: {capital['y']} }} as const;\n"
            f"export const LA_RIOJA_PATH = \"{path}\";\n"
        )
    with open(JSON_OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({
            "_doc": "Nomenclador del mapa del noticiero: x/y en el viewBox de remotion/src/v2/newscast5/laRioja.ts. Generado por scripts/build_newscast_geo.py (IGN/BAHRA vía datos.gob.ar).",
            "view": {"w": VIEW_W, "h": view_h},
            "aliases": aliases,
            "places": places,
        }, fh, ensure_ascii=False, indent=1)
    print(f"{len(places)} localidades, viewBox {VIEW_W}×{view_h}, {sum(len(r) for r in rings)} vértices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
