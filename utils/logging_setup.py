"""Logging rotativo, aislable por entorno y con redacción defensiva de secretos."""
from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler

from utils.paths import logs_dir


LOGS_DIR = str(logs_dir())

_SECRET_NAME_RE = re.compile(
    r"(?:TOKEN|SECRET|API_KEY|ACCESS_KEY|PRIVATE_KEY|PASSWORD)",
    re.IGNORECASE,
)
_INLINE_SECRET_RE = re.compile(
    r"(?i)\b(access_token|api[_-]?key|token|secret|password)=([^&\s]+)"
)


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _secret_values() -> tuple[str, ...]:
    values = {
        str(value)
        for name, value in os.environ.items()
        if _SECRET_NAME_RE.search(name)
        and value
        and str(value).strip()
        and str(value).strip().upper() != "PENDIENTE"
        and len(str(value)) >= 7
    }
    return tuple(sorted(values, key=len, reverse=True))


def redact_secrets(value: object) -> str:
    text = str(value)
    for secret in _secret_values():
        text = text.replace(secret, "[REDACTADO]")
    return _INLINE_SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTADO]", text)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        record.msg = redact_secrets(rendered)
        record.args = ()
        return True


def setup_logger(name: str, log_file: str | None = None, level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    directory = logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    signature = (str(directory), log_file, int(level))
    if getattr(logger, "_lvr_signature", None) == signature and logger.handlers:
        return logger

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redaction_filter = SecretRedactionFilter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redaction_filter)
    logger.addHandler(console)

    if log_file:
        path = directory / log_file
        file_handler = RotatingFileHandler(
            path,
            maxBytes=_positive_int("LOG_MAX_MB", 5) * 1024 * 1024,
            backupCount=_positive_int("LOG_BACKUP_COUNT", 3),
            encoding="utf-8",
            delay=True,
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction_filter)
        logger.addHandler(file_handler)

    logger._lvr_signature = signature
    return logger
