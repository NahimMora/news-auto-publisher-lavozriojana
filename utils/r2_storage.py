"""
Almacenamiento temporal en Cloudflare R2 para imágenes de Instagram.
Sube la imagen, retorna la URL pública, y borra después de publicar.

Variables de entorno requeridas:
  R2_ACCOUNT_ID        - ID de cuenta Cloudflare
  R2_ACCESS_KEY_ID     - Access key del API token R2
  R2_SECRET_ACCESS_KEY - Secret key del API token R2
  R2_BUCKET_NAME       - Nombre del bucket
  R2_PUBLIC_URL        - URL base pública del bucket (sin slash final)
                         Ej: https://pub-xxxx.r2.dev  o  https://media.tudominio.com
"""
import os
import uuid
import time
import boto3
from botocore.config import Config
from utils.logging_setup import setup_logger

logger = setup_logger("r2_storage", "r2_storage.log")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    account_id = os.getenv("R2_ACCOUNT_ID", "")
    access_key = os.getenv("R2_ACCESS_KEY_ID", "")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "")

    if not all([account_id, access_key, secret_key]) or "PENDIENTE" in [account_id, access_key, secret_key]:
        raise ValueError("R2 no configurado: faltan R2_ACCOUNT_ID, R2_ACCESS_KEY_ID o R2_SECRET_ACCESS_KEY")

    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    return _client


def is_configured() -> bool:
    required = ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET_NAME", "R2_PUBLIC_URL"]
    return all(
        os.getenv(k, "PENDIENTE") not in ("", "PENDIENTE")
        for k in required
    )


def upload_temp(image_path: str, ttl_hint: str = "ig") -> tuple[str, str]:
    """
    Sube una imagen a R2 y retorna (public_url, object_key).
    ttl_hint se usa como prefijo de carpeta para organizar.
    Lanza excepción si falla.
    """
    client     = _get_client()
    bucket     = os.getenv("R2_BUCKET_NAME")
    public_url = os.getenv("R2_PUBLIC_URL", "").rstrip("/")

    key = f"tmp/{ttl_hint}/{int(time.time())}_{uuid.uuid4().hex[:8]}.jpg"

    client.upload_file(
        image_path,
        bucket,
        key,
        ExtraArgs={"ContentType": "image/jpeg"},
    )

    url = f"{public_url}/{key}"
    logger.info(f"Subido a R2: {url}")
    return url, key


def upload_file(
    image_path: str,
    key: str,
    content_type: str,
    *,
    cache_control: str | None = None,
) -> tuple[str, str]:
    """
    Sube un archivo a R2 con una key permanente y retorna (public_url, object_key).
    """
    client = _get_client()
    bucket = os.getenv("R2_BUCKET_NAME")
    public_url = os.getenv("R2_PUBLIC_URL", "").rstrip("/")

    if not key or key.startswith("/") or ".." in key.split("/"):
        raise ValueError(f"Key R2 invalida: {key!r}")

    extra_args = {"ContentType": content_type}
    if cache_control:
        extra_args["CacheControl"] = cache_control

    client.upload_file(
        image_path,
        bucket,
        key,
        ExtraArgs=extra_args,
    )

    url = f"{public_url}/{key}"
    logger.info(f"Subido a R2: {url}")
    return url, key


def delete(object_key: str) -> None:
    """Elimina un objeto de R2. No lanza excepción si falla."""
    try:
        client = _get_client()
        bucket = os.getenv("R2_BUCKET_NAME")
        client.delete_object(Bucket=bucket, Key=object_key)
        logger.info(f"Eliminado de R2: {object_key}")
    except Exception as e:
        logger.warning(f"No se pudo eliminar de R2 ({object_key}): {e}")
