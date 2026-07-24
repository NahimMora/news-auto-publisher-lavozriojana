"""Almacenamiento R2 con resultados tipados, reintentos y validación."""
from __future__ import annotations

import mimetypes
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from utils.logging_setup import setup_logger
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus

logger = setup_logger("r2_storage", "r2_storage.log")

_client = None


def _configured_value(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    return "" if value == "PENDIENTE" else value


def _get_client():
    global _client
    if _client is not None:
        return _client
    account_id = _configured_value("R2_ACCOUNT_ID")
    access_key = _configured_value("R2_ACCESS_KEY_ID")
    secret_key = _configured_value("R2_SECRET_ACCESS_KEY")
    if not all((account_id, access_key, secret_key)):
        raise ValueError("R2 no configurado")
    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            connect_timeout=int(os.getenv("R2_CONNECT_TIMEOUT_SECONDS", "10")),
            read_timeout=int(os.getenv("R2_READ_TIMEOUT_SECONDS", "30")),
            retries={"max_attempts": 1},
        ),
        region_name="auto",
    )
    return _client


def reset_client() -> None:
    """Sólo para diagnóstico/tests cuando cambia el entorno."""
    global _client
    _client = None


def is_configured() -> bool:
    required = (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_PUBLIC_URL",
    )
    return all(_configured_value(name) for name in required)


def _valid_key(key: str) -> bool:
    return bool(key) and not key.startswith("/") and ".." not in key.split("\\") and ".." not in key.split("/")


def _public_base() -> str:
    value = _configured_value("R2_PUBLIC_URL").rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("R2_PUBLIC_URL debe ser una URL HTTP(S) absoluta")
    return value


def _upload_detailed(
    file_path: str,
    key: str,
    content_type: str,
    *,
    cache_control: str | None = None,
) -> OperationResult:
    path = Path(file_path)
    if not path.is_file():
        return OperationResult(StageStatus.FAILED, error_type="file_not_found")
    if not _valid_key(key):
        return OperationResult(StageStatus.FAILED, error_type="invalid_object_key")
    if not content_type or "/" not in content_type:
        return OperationResult(StageStatus.FAILED, error_type="invalid_content_type")
    try:
        client = _get_client()
        bucket = _configured_value("R2_BUCKET_NAME")
        base = _public_base()
    except ValueError:
        return OperationResult(StageStatus.FAILED, error_type="missing_configuration")

    retries = max(1, int(os.getenv("R2_RETRY_COUNT", "3")))
    backoff = max(0.0, float(os.getenv("R2_RETRY_BACKOFF_SECONDS", "1")))
    extra = {"ContentType": content_type}
    if cache_control:
        extra["CacheControl"] = cache_control
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            client.upload_file(str(path), bucket, key, ExtraArgs=extra)
            url = f"{base}/{key}"
            logger.info("Archivo subido a R2: key=%s", key)
            return OperationResult(
                StageStatus.SUCCESS,
                public_url=url,
                details={"object_key": key, "attempts": attempt},
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            last_error = type(exc).__name__
            logger.error("R2 upload intento %s/%s falló: %s", attempt, retries, last_error)
            if attempt < retries and backoff:
                time.sleep(backoff * attempt)
    return OperationResult(
        StageStatus.DEGRADED,
        error_type="r2_upload_error",
        error_code=last_error,
        retryable=True,
        details={"object_key": key, "attempts": retries},
    )


def upload_file_detailed(
    file_path: str,
    key: str,
    content_type: str,
    *,
    cache_control: str | None = None,
) -> OperationResult:
    return _upload_detailed(
        file_path,
        key,
        content_type,
        cache_control=cache_control,
    )


def upload_file(
    image_path: str,
    key: str,
    content_type: str,
    *,
    cache_control: str | None = None,
) -> tuple[str, str]:
    result = upload_file_detailed(
        image_path,
        key,
        content_type,
        cache_control=cache_control,
    )
    if not result.ok:
        raise RuntimeError(result.error_type or "r2_upload_error")
    return result.public_url, str(result.details["object_key"])


def upload_temp(image_path: str, ttl_hint: str = "ig") -> tuple[str, str]:
    suffix = Path(image_path).suffix.lower() or ".jpg"
    content_type = mimetypes.guess_type(f"x{suffix}")[0] or "application/octet-stream"
    key = f"tmp/{ttl_hint}/{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix}"
    return upload_file(image_path, key, content_type)


def delete_detailed(object_key: str) -> OperationResult:
    if not _valid_key(object_key):
        return OperationResult(StageStatus.FAILED, error_type="invalid_object_key")
    try:
        client = _get_client()
        bucket = _configured_value("R2_BUCKET_NAME")
        client.delete_object(Bucket=bucket, Key=object_key)
        logger.info("Objeto eliminado de R2: key=%s", object_key)
        return OperationResult(StageStatus.SUCCESS, details={"object_key": object_key})
    except ValueError:
        return OperationResult(StageStatus.FAILED, error_type="missing_configuration")
    except (BotoCoreError, ClientError, OSError) as exc:
        logger.error("No se pudo eliminar objeto R2 %s: %s", object_key, type(exc).__name__)
        return OperationResult(
            StageStatus.DEGRADED,
            error_type="r2_delete_error",
            error_code=type(exc).__name__,
            retryable=True,
            details={"object_key": object_key},
        )


def delete(object_key: str) -> OperationResult:
    """Wrapper histórico: el fallo queda visible en log y resultado detallado."""
    return delete_detailed(object_key)
