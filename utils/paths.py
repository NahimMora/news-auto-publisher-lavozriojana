"""Rutas operativas configurables para aislar producción de tests y diagnósticos."""
from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def _configured_dir(env_name: str, default_name: str) -> Path:
    raw = str(os.getenv(env_name) or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (ROOT_DIR / default_name).resolve()


def data_dir() -> Path:
    return _configured_dir("LVR_DATA_DIR", "data")


def logs_dir() -> Path:
    return _configured_dir("LVR_LOGS_DIR", "logs")


def output_dir() -> Path:
    return _configured_dir("LVR_OUTPUT_DIR", "output")


def photos_dir() -> Path:
    return _configured_dir("LVR_FOTOS_DIR", "FotosLVR")


def data_path(name: str) -> str:
    return str(data_dir() / name)


def log_path(name: str) -> str:
    return str(logs_dir() / name)
