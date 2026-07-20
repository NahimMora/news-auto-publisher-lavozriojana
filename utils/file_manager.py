import json
import os
import shutil
from datetime import datetime
from typing import Any


def load_json(path: str, default=None) -> Any:
    if default is None:
        default = []
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    shutil.move(tmp, path)


def backup_json(path: str, backup_dir: str) -> None:
    if not os.path.exists(path):
        return
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = os.path.basename(path)
    dest = os.path.join(backup_dir, f"{ts}_{name}")
    shutil.copy2(path, dest)
