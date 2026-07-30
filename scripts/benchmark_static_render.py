"""Benchmark reproducible: Remotion vs Pillow para slides premium (Fase 4).

Renderiza diez paquetes de fixture (títulos cortos/largos, con/sin imagen,
las tres plantillas) una vez con cada motor (llamando directamente a
``render_package_bytes``/``render_package_remotion``, sin pasar por
``resolve_engine``), y reporta tiempo de render, tamaño, dimensiones,
éxito/fallo, uso de fallback y advertencias — todo medido en esta corrida,
nunca inventado. Estos son los mismos dos motores entre los que decide
``PREMIUM_STATIC_RENDER_ENGINE`` (default ``remotion`` para el Estudio
Premium; ver docs/DECISIONS.md y docs/RUNBOOK.md para la política completa
por workflow, distinta para automático/OG).

Uso:
    python scripts/benchmark_static_render.py [--output benchmark.json]

No publica nada ni toca `data/` productivo.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()

from PIL import Image

from utils.premium_contract import add_slide, new_package


def _fixtures() -> list[dict]:
    fixtures = []

    def make(title, *, template="lvr_cronica", section="interior", slides=None, highlight=None):
        package = new_package(title=title, section=section, template=template)
        package["highlight_terms"] = highlight or []
        for slide_type, kwargs in (slides or [("closing", {})]):
            add_slide(package, slide_type, **kwargs)
        return package

    fixtures.append(make("Un incendio afecta un comercio en Chilecito", highlight=["incendio", "Chilecito"],
                          slides=[("cover", {"title": "Un incendio afecta un comercio en Chilecito"}), ("closing", {})]))
    fixtures.append(make("Alerta meteorológica por temporal en Villa Unión", section="interior",
                          highlight=["Villa Unión"], slides=[("cover", {}), ("key_points", {"items": ["Vientos fuertes", "Caída de árboles"]})]))
    fixtures.append(make("La Legislatura aprobó el presupuesto 2026 tras un debate de diez horas",
                          template="lvr_datos", section="politica",
                          slides=[("cover", {}), ("number", {"items": ["10"], "text": "horas de debate"}), ("closing", {})]))
    fixtures.append(make(
        "El Gobierno provincial presentó un plan integral de obras públicas que incluye "
        "pavimentación, alumbrado, desagües pluviales y refacción de escuelas en distintos "
        "departamentos durante los próximos dieciocho meses",  # título largo a propósito
        template="lvr_datos", section="economia",
        slides=[("cover", {}), ("key_points", {"items": ["Pavimentación", "Alumbrado", "Desagües", "Escuelas"]})],
    ))
    fixtures.append(make("Chilecito celebra su Fiesta de la Vendimia", template="lvr_visual", section="cultura",
                          highlight=["Chilecito"], slides=[("cover", {}), ("full_image", {}), ("closing", {})]))
    fixtures.append(make("Un club riojano clasificó a la final regional", template="lvr_visual", section="deportes",
                          slides=[("cover", {}), ("quote", {"text": "Estamos muy contentos", "title": "El DT"})]))
    fixtures.append(make("Detuvieron a un hombre tras un allanamiento en Aimogasta", section="policiales",
                          highlight=["Aimogasta"], slides=[("cover", {}), ("closing", {})]))
    fixtures.append(make("", section="sociedad", slides=[("cover", {}), ("closing", {})]))  # título vacío a propósito
    fixtures.append(make("Sin imagen asignada: nota sólo con texto", section="sociedad",
                          slides=[("key_points", {"items": ["Uno", "Dos", "Tres"]}), ("closing", {})]))
    fixtures.append(make("Nueva alerta: reabrió la ruta provincial tras el temporal", section="interior",
                          highlight=["reabrió"], slides=[("cover", {}), ("number", {"items": ["3"], "text": "días cortada"}), ("closing", {})]))
    return fixtures


def _measure_pillow(package: dict) -> dict:
    from utils.premium_renderer import render_package_bytes

    started = time.monotonic()
    try:
        images, warnings = render_package_bytes(package)
        duration = time.monotonic() - started
        dims = []
        for image_bytes in images:
            with Image.open(io.BytesIO(image_bytes)) as opened:
                dims.append(opened.size)
        return {
            "engine": "pillow",
            "success": True,
            "duration_seconds": round(duration, 3),
            "slide_count": len(images),
            "total_bytes": sum(len(b) for b in images),
            "dimensions": dims,
            "warnings": warnings,
        }
    except Exception as exc:  # pragma: no cover - benchmark diagnostics
        return {
            "engine": "pillow",
            "success": False,
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _measure_remotion(package: dict) -> dict:
    from utils.premium_renderer import render_package_remotion
    from utils.remotion_renderer import RemotionRenderError, remotion_available

    if not remotion_available(force_recheck=True):
        return {"engine": "remotion", "success": False, "error": "remotion_unavailable_in_this_environment"}

    started = time.monotonic()
    try:
        images, warnings = render_package_remotion(package)
        duration = time.monotonic() - started
        dims = []
        for image_bytes in images:
            with Image.open(io.BytesIO(image_bytes)) as opened:
                dims.append(opened.size)
        return {
            "engine": "remotion",
            "success": True,
            "duration_seconds": round(duration, 3),
            "slide_count": len(images),
            "total_bytes": sum(len(b) for b in images),
            "dimensions": dims,
            "warnings": warnings,
        }
    except RemotionRenderError as exc:
        return {
            "engine": "remotion",
            "success": False,
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": str(exc),
        }


def run_benchmark() -> dict:
    fixtures = _fixtures()
    rows = []
    for index, package in enumerate(fixtures):
        title = package.get("title") or "(título vacío)"
        pillow_result = _measure_pillow(package)
        remotion_result = _measure_remotion(package)
        rows.append(
            {
                "fixture_index": index,
                "title": title,
                "template": package.get("template"),
                "slide_count": len(package.get("slides") or []),
                "long_title": len(title) > 100,
                "has_image_assigned": any(s.get("asset_id") for s in package.get("slides") or []),
                "pillow": pillow_result,
                "remotion": remotion_result,
            }
        )
    return {
        "generated_at_ts": int(time.time()),
        "fixture_count": len(rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Ruta opcional para guardar el JSON del benchmark")
    args = parser.parse_args()

    report = run_benchmark()
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
