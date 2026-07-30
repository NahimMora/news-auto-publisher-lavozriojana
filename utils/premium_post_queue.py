"""Persistencia de paquetes premium: un único store, drafts y publicados.

Sigue el patrón de ``utils/manual_post_queue.py`` (mismo ``file_manager``,
mismas garantías atómicas) pero en un archivo propio para no mezclar
identidades ni cupos con el flujo "Publicaciones" existente
(``pipeline/custom_post.py``) ni con el lote automático.
"""
from __future__ import annotations

import copy
import time

from utils.file_manager import update_json
from utils.paths import data_dir
from utils.premium_contract import new_package

PACKAGES_PATH = str(data_dir() / "premium_packages.json")


def _packages_path() -> str:
    return PACKAGES_PATH


def create_draft(**overrides) -> dict:
    package = new_package(**overrides)
    save_package(package)
    return package


def save_package(package: dict) -> dict:
    """Upsert por ``id``. Guarda incluso si el paquete no es publicable aún
    (un borrador debe ser recuperable aunque tenga errores de validación)."""
    package = copy.deepcopy(package)
    package["updated_at_ts"] = int(time.time())

    def mutate(packages):
        if not isinstance(packages, list):
            raise ValueError("premium_packages.json debe contener una lista")
        for index, existing in enumerate(packages):
            if isinstance(existing, dict) and existing.get("id") == package.get("id"):
                packages[index] = package
                return packages
        packages.append(package)
        return packages

    update_json(_packages_path(), mutate, [], expected_type=list)
    return package


def get_package(package_id: str) -> dict | None:
    for package in list_packages():
        if package.get("id") == package_id:
            return package
    return None


def list_packages(*, status: str | None = None) -> list[dict]:
    from utils.file_manager import load_json

    packages = load_json(_packages_path(), [], expected_type=list)
    rows = [item for item in packages if isinstance(item, dict)]
    if status:
        rows = [item for item in rows if item.get("status") == status]
    rows.sort(key=lambda item: int(item.get("updated_at_ts") or 0), reverse=True)
    return rows


def update_package_fields(package_id: str, **fields) -> dict:
    outcome: dict = {}

    def mutate(packages):
        for item in packages:
            if isinstance(item, dict) and item.get("id") == package_id:
                item.update(fields)
                item["updated_at_ts"] = int(time.time())
                outcome["item"] = copy.deepcopy(item)
                break
        else:
            raise KeyError(f"paquete no encontrado: {package_id}")
        return packages

    update_json(_packages_path(), mutate, [], expected_type=list)
    return outcome["item"]
