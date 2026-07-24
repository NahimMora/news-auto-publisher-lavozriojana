"""Persistencia JSON segura: locks, reemplazo atómico, cuarentena y backups."""
from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


class JsonStateError(RuntimeError):
    """Error base de persistencia de estado."""


class JsonReadError(JsonStateError):
    pass


class JsonWriteError(JsonStateError):
    pass


class JsonCorruptionError(JsonReadError):
    def __init__(self, path: str, quarantine_path: str | None, cause: Exception):
        self.path = path
        self.quarantine_path = quarantine_path
        self.cause = cause
        suffix = f"; copia preservada en {quarantine_path}" if quarantine_path else ""
        super().__init__(f"JSON corrupto en {path}{suffix}: {cause}")


class JsonLockTimeout(JsonStateError):
    pass


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    return raw in {"1", "true", "yes", "on", "si", "sí"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _lock_owner_active(lock_path: str) -> bool | None:
    """True si el PID del lock sigue siendo el mismo proceso; None si no se sabe."""
    try:
        with open(lock_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        pid = int(payload["pid"])
        lock_created = float(payload["created_at"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False
    try:
        import psutil
    except ImportError:
        return None
    try:
        process = psutil.Process(pid)
        # Un PID reutilizado tendrá una fecha de creación posterior a la del lock.
        return process.is_running() and process.create_time() <= lock_created + 1.0
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, psutil.Error):
        return None


class FileLock:
    """Lock interproceso portable basado en creación exclusiva de un archivo."""

    def __init__(
        self,
        target_path: str | os.PathLike[str],
        *,
        timeout: float | None = None,
        poll_interval: float = 0.02,
        stale_seconds: float | None = None,
    ):
        self.target_path = os.fspath(target_path)
        self.lock_path = f"{self.target_path}.lock"
        self.timeout = timeout if timeout is not None else _env_float("JSON_LOCK_TIMEOUT_SECONDS", 10.0)
        self.poll_interval = poll_interval
        self.stale_seconds = (
            stale_seconds
            if stale_seconds is not None
            else _env_float("JSON_LOCK_STALE_SECONDS", 120.0)
        )
        self._acquired = False

    def acquire(self) -> "FileLock":
        parent = os.path.dirname(os.path.abspath(self.lock_path))
        os.makedirs(parent, exist_ok=True)
        deadline = time.monotonic() + max(0.0, self.timeout)
        payload = json.dumps(
            {"pid": os.getpid(), "created_at": time.time()},
            ensure_ascii=False,
        ).encode("utf-8")

        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, payload)
                    os.fsync(fd)
                except OSError:
                    os.close(fd)
                    fd = -1
                    try:
                        os.unlink(self.lock_path)
                    except OSError:
                        pass
                    raise
                finally:
                    if fd >= 0:
                        os.close(fd)
                self._acquired = True
                return self
            except (FileExistsError, PermissionError) as exc:
                # En Windows, CreateFile puede traducir un O_EXCL contendiente a
                # PermissionError mientras otro hilo todavía tiene abierto el lock.
                # Sólo se trata como contención si el archivo existe realmente.
                if isinstance(exc, PermissionError) and not os.path.exists(self.lock_path):
                    raise JsonWriteError(
                        f"No se pudo crear lock {self.lock_path}: {exc}"
                    ) from exc
                try:
                    age = time.time() - os.path.getmtime(self.lock_path)
                    if age > self.stale_seconds:
                        owner_active = _lock_owner_active(self.lock_path)
                        if owner_active is False:
                            os.unlink(self.lock_path)
                            continue
                except FileNotFoundError:
                    continue
                except OSError:
                    pass

                if time.monotonic() >= deadline:
                    raise JsonLockTimeout(f"Timeout esperando lock {self.lock_path}")
                time.sleep(self.poll_interval)
            except OSError as exc:
                raise JsonWriteError(f"No se pudo crear lock {self.lock_path}: {exc}") from exc

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            os.unlink(self.lock_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise JsonWriteError(f"No se pudo liberar lock {self.lock_path}: {exc}") from exc
        finally:
            self._acquired = False

    def __enter__(self) -> "FileLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class MultiFileLock:
    """Adquiere locks en orden estable para evitar deadlocks."""

    def __init__(self, paths: Iterable[str | os.PathLike[str]], *, timeout: float | None = None):
        self.paths = sorted({os.path.abspath(os.fspath(path)) for path in paths})
        self.timeout = timeout
        self._stack: ExitStack | None = None

    def __enter__(self) -> "MultiFileLock":
        self._stack = ExitStack()
        try:
            for path in self.paths:
                self._stack.enter_context(FileLock(path, timeout=self.timeout))
        except Exception:
            self._stack.close()
            self._stack = None
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self._stack is not None
        self._stack.__exit__(exc_type, exc, tb)
        self._stack = None


def _default_value(default: Any) -> Any:
    return copy.deepcopy([] if default is None else default)


def _quarantine_dir(path: str) -> str:
    configured = str(os.getenv("LVR_QUARANTINE_DIR") or "").strip()
    if configured:
        return os.path.abspath(configured)
    return os.path.join(os.path.dirname(os.path.abspath(path)), "quarantine")


def _quarantine_corrupt(path: str, cause: Exception) -> str | None:
    try:
        directory = _quarantine_dir(path)
        os.makedirs(directory, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = os.path.join(
            directory,
            f"{os.path.basename(path)}.{timestamp}.{uuid.uuid4().hex[:8]}.corrupt",
        )
        shutil.copy2(path, destination)
        return destination
    except OSError:
        return None


def _load_json_unlocked(path: str, default=None, *, expected_type: type | tuple[type, ...] | None = None) -> Any:
    if not os.path.exists(path):
        return _default_value(default)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except json.JSONDecodeError as exc:
        quarantine = _quarantine_corrupt(path, exc)
        raise JsonCorruptionError(path, quarantine, exc) from exc
    except OSError as exc:
        raise JsonReadError(f"No se pudo leer {path}: {exc}") from exc

    if expected_type is not None and not isinstance(value, expected_type):
        exc = TypeError(f"se esperaba {expected_type}, se obtuvo {type(value).__name__}")
        quarantine = _quarantine_corrupt(path, exc)
        raise JsonCorruptionError(path, quarantine, exc)
    return value


def load_json(path: str, default=None, *, expected_type: type | tuple[type, ...] | None = None) -> Any:
    with FileLock(path):
        return _load_json_unlocked(path, default, expected_type=expected_type)


def _backup_directory(path: str, backup_dir: str | None = None) -> str:
    if backup_dir:
        return os.path.abspath(backup_dir)
    configured = str(os.getenv("LVR_BACKUP_DIR") or "").strip()
    if configured:
        return os.path.abspath(configured)
    return os.path.join(os.path.dirname(os.path.abspath(path)), "backups")


def _latest_backup_age(path: str, backup_dir: str) -> float | None:
    if not os.path.isdir(backup_dir):
        return None
    prefix = f"{os.path.basename(path)}."
    candidates = [
        os.path.join(backup_dir, name)
        for name in os.listdir(backup_dir)
        if name.startswith(prefix) and name.endswith(".json")
    ]
    if not candidates:
        return None
    latest = max(os.path.getmtime(candidate) for candidate in candidates)
    return max(0.0, time.time() - latest)


def _prune_backups(path: str, backup_dir: str) -> None:
    try:
        keep = max(1, int(os.getenv("JSON_BACKUP_RETENTION_COUNT", "20")))
    except ValueError:
        keep = 20
    prefix = f"{os.path.basename(path)}."
    candidates = sorted(
        (
            os.path.join(backup_dir, name)
            for name in os.listdir(backup_dir)
            if name.startswith(prefix) and name.endswith(".json")
        ),
        key=os.path.getmtime,
        reverse=True,
    )
    for candidate in candidates[keep:]:
        try:
            os.unlink(candidate)
        except OSError:
            pass


def _backup_json_unlocked(
    path: str,
    backup_dir: str | None = None,
    *,
    force: bool = False,
) -> str | None:
    if not os.path.exists(path):
        return None
    directory = _backup_directory(path, backup_dir)
    os.makedirs(directory, exist_ok=True)
    if not force:
        minimum = _env_float("JSON_BACKUP_MIN_INTERVAL_SECONDS", 3600.0)
        age = _latest_backup_age(path, directory)
        if age is not None and age < minimum:
            return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = os.path.join(
        directory,
        f"{os.path.basename(path)}.{timestamp}.{uuid.uuid4().hex[:8]}.json",
    )
    try:
        shutil.copy2(path, destination)
        _prune_backups(path, directory)
        return destination
    except OSError as exc:
        raise JsonWriteError(f"No se pudo respaldar {path}: {exc}") from exc


def backup_json(path: str, backup_dir: str | None = None) -> str | None:
    with FileLock(path):
        # Validar antes de copiar: un backup nuevo no debe legitimar corrupción.
        _load_json_unlocked(path, None)
        return _backup_json_unlocked(path, backup_dir, force=True)


def _save_json_unlocked(
    path: str,
    data: Any,
    *,
    backup: bool = True,
    allow_overwrite_corrupt: bool = False,
) -> None:
    absolute = os.path.abspath(path)
    parent = os.path.dirname(absolute)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise JsonWriteError(f"No se pudo crear el directorio de {path}: {exc}") from exc

    if os.path.exists(absolute):
        if not allow_overwrite_corrupt:
            _load_json_unlocked(absolute, None)
        if backup and _env_bool("JSON_BACKUP_ENABLED", True):
            _backup_json_unlocked(absolute)

    fd = -1
    temp_path = ""
    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(absolute)}.",
            suffix=".tmp",
            dir=parent,
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd = -1
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, absolute)
        temp_path = ""

        # En POSIX sincroniza también la entrada de directorio; en Windows puede fallar.
        if os.name != "nt":
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except (OSError, TypeError, ValueError) as exc:
        raise JsonWriteError(f"No se pudo escribir atómicamente {path}: {exc}") from exc
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def save_json(path: str, data: Any) -> None:
    with FileLock(path):
        _save_json_unlocked(path, data)


def update_json(
    path: str,
    updater: Callable[[Any], Any | None],
    default=None,
    *,
    expected_type: type | tuple[type, ...] | None = None,
) -> Any:
    """Mantiene el lock durante todo el ciclo read-modify-write."""
    with FileLock(path):
        current = _load_json_unlocked(path, default, expected_type=expected_type)
        working = copy.deepcopy(current)
        updated = updater(working)
        value = working if updated is None else updated
        _save_json_unlocked(path, value)
        return value


def update_json_files(
    specs: dict[str, tuple[Any, type | tuple[type, ...] | None]],
    updater: Callable[[dict[str, Any]], dict[str, Any] | None],
    *,
    save_order: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Actualiza varios JSON bajo locks ordenados, evitando carreras cruzadas.

    Cada escritura individual es atómica. ``save_order`` permite persistir primero
    el destino durable y después retirar el origen, para que un corte no pierda
    elementos aunque pueda requerir deduplicación idempotente al reiniciar.
    """
    paths = list(specs)
    order = list(save_order or paths)
    if set(order) != set(paths):
        raise ValueError("save_order debe contener exactamente los paths de specs")
    with MultiFileLock(paths):
        current = {
            path: _load_json_unlocked(
                path,
                default,
                expected_type=expected_type,
            )
            for path, (default, expected_type) in specs.items()
        }
        working = copy.deepcopy(current)
        updated = updater(working)
        values = working if updated is None else updated
        if set(values) != set(paths):
            raise ValueError("El updater debe devolver todos los paths originales")
        for path in order:
            _save_json_unlocked(path, values[path])
        return values


def append_json_items(
    path: str,
    items: Iterable[Any],
    *,
    key: Callable[[Any], str] | None = None,
) -> int:
    incoming = list(items)
    added = 0

    def append(existing):
        nonlocal added
        if not isinstance(existing, list):
            raise JsonReadError(f"{path} debe contener una lista")
        known = {key(item) for item in existing} if key else set()
        for item in incoming:
            item_key = key(item) if key else None
            if key and item_key in known:
                continue
            existing.append(copy.deepcopy(item))
            added += 1
            if key:
                known.add(item_key)
        return existing

    update_json(path, append, [], expected_type=list)
    return added


def restore_json(backup_path: str, target_path: str) -> None:
    backup_data = _load_json_unlocked(os.path.abspath(backup_path), None)
    with FileLock(target_path):
        if os.path.exists(target_path):
            _load_json_unlocked(target_path, None)
            _backup_json_unlocked(target_path, force=True)
        _save_json_unlocked(target_path, backup_data, backup=False)
