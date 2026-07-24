"""Esquema y diagnóstico seguro de configuración operativa."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit

from utils.stage_result import StageResult, StageStatus


_TRUE = {"1", "true", "yes", "on", "si", "sí"}
_FALSE = {"0", "false", "no", "off"}
_PLACEHOLDERS = {"", "PENDIENTE", "CHANGE_ME", "CHANGEME", "TODO"}

SECRET_FIELDS = {
    "PRIVATE_API_KEY",
    "WEBAPP_API_KEY",
    "OPENAI_API_KEY",
    "FB_PAGE_ACCESS_TOKEN",
    "FB_APP_SECRET",
    "IG_ACCESS_TOKEN",
    "IG_APP_SECRET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
}


@dataclass(frozen=True)
class ConfigIssue:
    severity: str
    code: str
    field: str
    message: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "field": self.field,
            "message": self.message,
        }


@dataclass
class ConfigReport:
    issues: list[ConfigIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ConfigIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ConfigIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, severity: str, code: str, field: str, message: str) -> None:
        self.issues.append(ConfigIssue(severity, code, field, message))

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
        }


def _value(env: Mapping[str, str], name: str, default: str = "") -> str:
    return str(env.get(name, default) or "").strip()


def _boolean(report: ConfigReport, env: Mapping[str, str], name: str, default: str) -> bool:
    raw = _value(env, name, default).lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    report.add("error", "invalid_boolean", name, f"{name} debe ser true/false o 1/0")
    return default.lower() in _TRUE


def _positive_int(
    report: ConfigReport,
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    raw = _value(env, name, str(default))
    try:
        value = int(raw)
    except ValueError:
        report.add("error", "invalid_positive_int", name, f"{name} debe ser un entero")
        return default
    if value < minimum or (maximum is not None and value > maximum):
        range_text = f">={minimum}" if maximum is None else f"entre {minimum} y {maximum}"
        report.add("error", "invalid_positive_int", name, f"{name} debe estar {range_text}")
        return default
    return value


def _float_range(
    report: ConfigReport,
    env: Mapping[str, str],
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = _value(env, name, str(default))
    try:
        value = float(raw)
    except ValueError:
        report.add("error", "invalid_float", name, f"{name} debe ser numérico")
        return default
    if not minimum <= value <= maximum:
        report.add(
            "error",
            "float_out_of_range",
            name,
            f"{name} debe estar entre {minimum} y {maximum}",
        )
    return value


def _choice(
    report: ConfigReport,
    env: Mapping[str, str],
    name: str,
    default: str,
    allowed: set[str],
) -> str:
    value = _value(env, name, default).lower()
    if value not in allowed:
        report.add(
            "error",
            "invalid_choice",
            name,
            f"{name} debe ser uno de: {', '.join(sorted(allowed))}",
        )
    return value


def _url(report: ConfigReport, env: Mapping[str, str], name: str, *, required: bool) -> str:
    value = _value(env, name)
    if value.upper() in _PLACEHOLDERS:
        if required:
            report.add("error", "required_value_missing", name, f"{name} es obligatoria")
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        parsed = None
    if (
        not parsed
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        report.add("error", "invalid_url", name, f"{name} debe ser una URL http/https válida")
    return value


def _required(report: ConfigReport, env: Mapping[str, str], name: str) -> str:
    value = _value(env, name)
    if value.upper() in _PLACEHOLDERS:
        report.add("error", "required_value_missing", name, f"{name} es obligatoria")
        return ""
    return value


def _required_any(
    report: ConfigReport,
    env: Mapping[str, str],
    names: tuple[str, ...],
) -> str:
    for name in names:
        value = _value(env, name)
        if value.upper() not in _PLACEHOLDERS:
            return value
    report.add(
        "error",
        "required_value_missing",
        names[0],
        f"Se requiere una de: {', '.join(names)}",
    )
    return ""


def _path_value(
    report: ConfigReport,
    env: Mapping[str, str],
    name: str,
    *,
    json_file: bool = False,
) -> None:
    value = _value(env, name)
    if not value:
        return
    if "\x00" in value:
        report.add("error", "invalid_path", name, f"{name} contiene un byte nulo")
    if json_file and not value.lower().endswith(".json"):
        report.add("error", "invalid_json_path", name, f"{name} debe terminar en .json")


def validate_config(
    values: Mapping[str, str] | None = None,
    *,
    scope: str = "all",
) -> ConfigReport:
    env: Mapping[str, str] = os.environ if values is None else values
    report = ConfigReport()

    interval = _positive_int(report, env, "PIPELINE_24X7_INTERVAL_SECONDS", 3600)
    heartbeat = _positive_int(report, env, "PIPELINE_24X7_HEARTBEAT_SECONDS", 30)
    stale = _positive_int(report, env, "PIPELINE_24X7_STALE_SECONDS", 900)
    if stale <= heartbeat:
        report.add(
            "error",
            "stale_not_greater_than_heartbeat",
            "PIPELINE_24X7_STALE_SECONDS",
            "El umbral stale debe ser mayor que el heartbeat",
        )
    if interval < heartbeat:
        report.add(
            "warning",
            "heartbeat_greater_than_cycle_interval",
            "PIPELINE_24X7_HEARTBEAT_SECONDS",
            "El heartbeat es mayor que el intervalo de ciclo",
        )

    _positive_int(report, env, "SCRAPER_MAX_LINKS", 8, maximum=100)
    _positive_int(report, env, "ARTICLE_MAX_AGE_DAYS", 1, maximum=365)
    _positive_int(report, env, "OPENAI_RETRY_COUNT", 4, maximum=20)
    _positive_int(report, env, "REWRITE_MAX_ATTEMPTS", 3, maximum=20)
    _positive_int(report, env, "WEBAPP_REQUEST_TIMEOUT", 30, maximum=600)
    _positive_int(report, env, "WEBAPP_REQUEST_RETRIES", 3, maximum=20)
    _positive_int(report, env, "JSON_BACKUP_RETENTION_COUNT", 20, maximum=1000)
    _positive_int(
        report,
        env,
        "JSON_BACKUP_MIN_INTERVAL_SECONDS",
        3600,
        minimum=0,
        maximum=86400 * 365,
    )
    _positive_int(report, env, "JSON_LOCK_STALE_SECONDS", 120, maximum=86400)
    _positive_int(report, env, "JSON_LOCK_TIMEOUT_SECONDS", 10, maximum=300)
    _positive_int(report, env, "LOG_MAX_MB", 5, maximum=1024)
    _positive_int(report, env, "LOG_BACKUP_COUNT", 3, maximum=100)
    _positive_int(report, env, "SOCIAL_TTL_HOURS", 48, maximum=24 * 365)
    _positive_int(report, env, "WEB_QUEUE_TTL_DAYS", 30, maximum=3650)
    _positive_int(report, env, "SOCIAL_QUEUE_TTL_DAYS", 30, maximum=3650)
    _positive_int(report, env, "QUEUE_EVENT_RETENTION_COUNT", 10000, minimum=100)
    _positive_int(report, env, "FB_REQUEST_TIMEOUT_SECONDS", 60, maximum=600)
    _positive_int(report, env, "FB_VIDEO_REQUEST_TIMEOUT_SECONDS", 120, maximum=1800)
    _positive_int(report, env, "FB_TEMP_BLOCK_BACKOFF_SECONDS", 1800, maximum=86400 * 7)
    _positive_int(report, env, "IG_REQUEST_TIMEOUT_SECONDS", 60, maximum=600)
    _positive_int(report, env, "IG_RATE_LIMIT_BACKOFF_SECONDS", 10800, maximum=86400 * 7)
    _positive_int(report, env, "IG_VIDEO_PROCESSING_TIMEOUT_SECONDS", 300, maximum=3600)
    _positive_int(report, env, "IG_VIDEO_PROCESSING_POLL_SECONDS", 10, maximum=300)
    _positive_int(report, env, "PUBLISH_MAX_PER_RUN", 10, maximum=1000)
    _positive_int(report, env, "IG_MAX_PER_RUN", 1, maximum=100)
    _positive_int(report, env, "IG_IMAGE_CONTAINER_WAIT_SECONDS", 5, minimum=0, maximum=600)
    _positive_int(report, env, "WEB_PUBLISH_MAX_PER_RUN", 0, minimum=0, maximum=1000)
    _positive_int(report, env, "WEB_MAX_DEPORTES_PER_RUN", 1, minimum=0, maximum=1000)
    _positive_int(report, env, "WEB_DEDUP_HISTORY_DAYS", 7, maximum=3650)
    _positive_int(report, env, "WEBAPP_RETRY_SLEEP_SECONDS", 5, minimum=0, maximum=3600)
    _positive_int(report, env, "WEB_PUBLIC_MEDIA_CHECK_ATTEMPTS", 5, maximum=100)
    _positive_int(
        report,
        env,
        "WEB_PUBLIC_MEDIA_CHECK_INITIAL_DELAY_SECONDS",
        2,
        minimum=0,
        maximum=3600,
    )
    _positive_int(
        report,
        env,
        "WEB_PUBLIC_MEDIA_CHECK_RETRY_SLEEP_SECONDS",
        5,
        minimum=0,
        maximum=3600,
    )
    _positive_int(report, env, "EDITORIAL_ENRICHER_MAX_REVISIONS", 5, maximum=50)
    _positive_int(report, env, "IMAGE_MIN_QUALITY", 5, maximum=95)
    _positive_int(report, env, "PUBLISH_BATCH_SIZE", 10, maximum=1000)
    _positive_int(
        report,
        env,
        "PUBLISH_BATCH_PAUSE_SECONDS",
        180,
        minimum=0,
        maximum=86400,
    )
    _positive_int(report, env, "MAX_DEPORTES_PER_RUN", 1, minimum=0, maximum=1000)
    _positive_int(report, env, "SOCIAL_MAX_DEPORTES_PER_RUN", 1, minimum=0, maximum=1000)
    image_min_width = _positive_int(report, env, "IMAGE_MIN_WIDTH", 700, maximum=10000)
    image_max_width = _positive_int(report, env, "IMAGE_MAX_WIDTH", 1400, maximum=20000)
    if image_max_width < image_min_width:
        report.add(
            "error",
            "invalid_image_dimensions",
            "IMAGE_MAX_WIDTH",
            "IMAGE_MAX_WIDTH debe ser mayor o igual a IMAGE_MIN_WIDTH",
        )
    _positive_int(report, env, "IMAGE_MAX_PIXELS", 40000000, maximum=500000000)
    _positive_int(report, env, "IMAGE_DOWNLOAD_MAX_BYTES", 20 * 1024 * 1024, maximum=1024**3)
    _positive_int(report, env, "IMAGE_MAX_FILESIZE_KB", 250, maximum=100000)
    _positive_int(report, env, "IMAGE_JPEG_QUALITY", 82, maximum=95)
    _positive_int(report, env, "VIDEO_DOWNLOAD_MAX_BYTES", 250 * 1024 * 1024, maximum=5 * 1024**3)
    _positive_int(report, env, "R2_RETRY_COUNT", 3, maximum=20)
    _positive_int(report, env, "R2_CONNECT_TIMEOUT_SECONDS", 10, maximum=600)
    _positive_int(report, env, "R2_READ_TIMEOUT_SECONDS", 30, maximum=1800)

    for name, default in (
        ("JSON_BACKUP_ENABLED", "true"),
        ("FB_PUBLISH_ENABLED", "false"),
        ("IG_PUBLISH_ENABLED", "false"),
        ("WEB_PUBLIC_MEDIA_CHECK_ENABLED", "true"),
        ("ENABLE_EDITORIAL_NEWS_ENRICHER", "true"),
        ("CUSTOM_POST_DRY_RUN", "false"),
        ("FB_ALLOW_DIRECT_TOKEN_FALLBACK", "false"),
        ("IG_ALLOW_ORIGINAL_IMAGE_FALLBACK", "false"),
        ("PUBLISH_THROTTLE_ENABLED", "true"),
        ("ENABLE_R2_OG_IMAGE", "true"),
        ("SCRAPER_LOCALES_ENABLED", "true"),
        ("SCRAPER_POLICIALES_ENABLED", "true"),
        ("SCRAPER_INTERIOR_ENABLED", "true"),
        ("SCRAPER_DEPORTES_ENABLED", "true"),
        ("SCRAPER_NUEVARIOJA_ENABLED", "true"),
        ("SCRAPER_NR_POLITICA_ENABLED", "true"),
        ("SCRAPER_NR_SOCIEDAD_ENABLED", "true"),
        ("SCRAPER_NR_POLICIALES_ENABLED", "true"),
        ("SCRAPER_NR_DEPORTES_ENABLED", "true"),
        ("SCRAPER_NR_INTERIOR_ENABLED", "true"),
        ("SCRAPER_NR_INTERNACIONALES_ENABLED", "true"),
    ):
        _boolean(report, env, name, default)

    _float_range(report, env, "EDITORIAL_ENRICHER_MIN_SCORE", 0.86, 0.0, 1.0)
    _float_range(report, env, "FEATURED_MIN_QUALITY_SCORE", 0.88, 0.0, 1.0)
    _float_range(report, env, "DEDUP_SIMILARITY_THRESHOLD", 0.5, 0.0, 1.0)
    _float_range(report, env, "IG_POSTED_DEDUP_THRESHOLD", 0.5, 0.0, 1.0)
    _float_range(report, env, "R2_RETRY_BACKOFF_SECONDS", 1.0, 0.0, 3600.0)
    delay_min = _float_range(report, env, "PUBLISH_DELAY_MIN_SECONDS", 20.0, 0.0, 86400.0)
    delay_max = _float_range(report, env, "PUBLISH_DELAY_MAX_SECONDS", 30.0, 0.0, 86400.0)
    if delay_min > delay_max:
        report.add(
            "error",
            "invalid_delay_range",
            "PUBLISH_DELAY_MAX_SECONDS",
            "PUBLISH_DELAY_MAX_SECONDS debe ser mayor o igual al mínimo",
        )

    target = _choice(
        report,
        env,
        "WEB_PUBLISH_TARGET",
        "off",
        {"off", "node_webapp"},
    )
    fallback_mode = _choice(
        report,
        env,
        "OPENAI_FALLBACK_MODE",
        "allow_non_sensitive",
        {"block", "allow_non_sensitive", "allow_all"},
    )
    _choice(
        report,
        env,
        "WEB_EDITORIAL_FALLBACK_MODE",
        "allow_non_sensitive",
        {"block", "allow_non_sensitive", "allow_all"},
    )
    if _value(env, "META_GRAPH_API"):
        _url(report, env, "META_GRAPH_API", required=False)

    for name in (
        "LVR_DATA_DIR",
        "LVR_LOGS_DIR",
        "LVR_OUTPUT_DIR",
        "LVR_FOTOS_DIR",
        "LVR_BACKUP_DIR",
        "LVR_QUARANTINE_DIR",
    ):
        _path_value(report, env, name)
    for name in (
        "LVR_QUEUE_EVENTS_PATH",
        "LVR_STAGE_RESULT_PATH",
        "META_QUEUE_PATH",
        "SOCIAL_QUEUE_PATH",
        "WEB_QUEUE_PATH",
        "WEB_PUBLISHED_HISTORY_PATH",
    ):
        _path_value(report, env, name, json_file=True)

    validate_web = scope in {"all", "web", "supervisor"} and target == "node_webapp"
    validate_fb = scope in {"all", "facebook", "supervisor"} and _value(
        env, "FB_PUBLISH_ENABLED", "false"
    ).lower() in _TRUE
    validate_ig = scope in {"all", "instagram", "supervisor"} and _value(
        env, "IG_PUBLISH_ENABLED", "false"
    ).lower() in _TRUE
    validate_openai = scope in {"rewrite", "all", "supervisor"} and fallback_mode == "block"

    if validate_web:
        _url(report, env, "WEBAPP_BASE_URL", required=True)
        _required_any(report, env, ("PRIVATE_API_KEY", "WEBAPP_API_KEY"))
        for name in (
            "R2_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET_NAME",
        ):
            _required(report, env, name)
        _url(report, env, "R2_PUBLIC_URL", required=True)

    if validate_fb:
        _required(report, env, "FB_PAGE_ID")
        _required(report, env, "FB_PAGE_ACCESS_TOKEN")

    if validate_ig:
        _required(report, env, "IG_ACCOUNT_ID")
        _required(report, env, "IG_ACCESS_TOKEN")
        allow_original = _value(
            env,
            "IG_ALLOW_ORIGINAL_IMAGE_FALLBACK",
            "false",
        ).lower() in _TRUE
        if not allow_original:
            for name in (
                "R2_ACCOUNT_ID",
                "R2_ACCESS_KEY_ID",
                "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET_NAME",
            ):
                _required(report, env, name)
            _url(report, env, "R2_PUBLIC_URL", required=True)

    if validate_openai:
        _required(report, env, "OPENAI_API_KEY")

    return report


def config_inventory() -> dict[str, list[str]]:
    return {
        "required": [],
        "conditional_required": sorted(
            {
                "OPENAI_API_KEY",
                "PRIVATE_API_KEY",
                "WEBAPP_API_KEY",
                "WEBAPP_BASE_URL",
                "FB_PAGE_ID",
                "FB_PAGE_ACCESS_TOKEN",
                "IG_ACCOUNT_ID",
                "IG_ACCESS_TOKEN",
                "R2_ACCOUNT_ID",
                "R2_ACCESS_KEY_ID",
                "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET_NAME",
                "R2_PUBLIC_URL",
            }
        ),
        "optional": sorted(
            {
                "ARTICLE_MAX_AGE_DAYS",
                "DEDUP_SIMILARITY_THRESHOLD",
                "EDITORIAL_ENRICHER_MAX_REVISIONS",
                "EDITORIAL_ENRICHER_MIN_SCORE",
                "EDITORIAL_ENRICHER_MODEL",
                "ENABLE_EDITORIAL_NEWS_ENRICHER",
                "ENABLE_R2_OG_IMAGE",
                "FB_ALLOW_DIRECT_TOKEN_FALLBACK",
                "FB_DISABLED_PAGE_IDS",
                "FB_PUBLISH_ENABLED",
                "FB_REQUEST_TIMEOUT_SECONDS",
                "FB_TEMP_BLOCK_BACKOFF_SECONDS",
                "FB_VIDEO_REQUEST_TIMEOUT_SECONDS",
                "FEATURED_MIN_QUALITY_SCORE",
                "IG_ALLOWED_CATEGORIES",
                "IG_ALLOW_ORIGINAL_IMAGE_FALLBACK",
                "IG_IMAGE_CONTAINER_WAIT_SECONDS",
                "IG_MAX_PER_RUN",
                "IG_POSTED_DEDUP_THRESHOLD",
                "IG_PUBLISH_ENABLED",
                "IG_RATE_LIMIT_BACKOFF_SECONDS",
                "IG_REQUEST_TIMEOUT_SECONDS",
                "IG_VIDEO_PROCESSING_POLL_SECONDS",
                "IG_VIDEO_PROCESSING_TIMEOUT_SECONDS",
                "IMAGE_DOWNLOAD_MAX_BYTES",
                "IMAGE_JPEG_QUALITY",
                "IMAGE_MAX_FILESIZE_KB",
                "IMAGE_MAX_PIXELS",
                "IMAGE_MAX_WIDTH",
                "IMAGE_MIN_QUALITY",
                "IMAGE_MIN_WIDTH",
                "JSON_BACKUP_ENABLED",
                "JSON_BACKUP_MIN_INTERVAL_SECONDS",
                "JSON_BACKUP_RETENTION_COUNT",
                "JSON_LOCK_STALE_SECONDS",
                "JSON_LOCK_TIMEOUT_SECONDS",
                "LOG_BACKUP_COUNT",
                "LOG_MAX_MB",
                "MAX_DEPORTES_PER_RUN",
                "META_GRAPH_API",
                "OPENAI_FALLBACK_MODE",
                "OPENAI_MODEL",
                "OPENAI_RETRY_COUNT",
                "OPENAI_RETRY_SLEEP",
                "OPENAI_TIMEOUT",
                "PIPELINE_24X7_INTERVAL_SECONDS",
                "PIPELINE_24X7_HEARTBEAT_SECONDS",
                "PIPELINE_24X7_STALE_SECONDS",
                "PUBLISH_BATCH_PAUSE_SECONDS",
                "PUBLISH_BATCH_SIZE",
                "PUBLISH_DELAY_MAX_SECONDS",
                "PUBLISH_DELAY_MIN_SECONDS",
                "PUBLISH_MAX_PER_RUN",
                "PUBLISH_THROTTLE_ENABLED",
                "QUEUE_EVENT_RETENTION_COUNT",
                "R2_CONNECT_TIMEOUT_SECONDS",
                "R2_READ_TIMEOUT_SECONDS",
                "R2_RETRY_BACKOFF_SECONDS",
                "R2_RETRY_COUNT",
                "REWRITE_MAX_ATTEMPTS",
                "SCRAPER_DEPORTES_ENABLED",
                "SCRAPER_INTERIOR_ENABLED",
                "SCRAPER_LOCALES_ENABLED",
                "SCRAPER_MAX_LINKS",
                "SCRAPER_NUEVARIOJA_ENABLED",
                "SCRAPER_NR_DEPORTES_ENABLED",
                "SCRAPER_NR_INTERIOR_ENABLED",
                "SCRAPER_NR_INTERNACIONALES_ENABLED",
                "SCRAPER_NR_POLICIALES_ENABLED",
                "SCRAPER_NR_POLITICA_ENABLED",
                "SCRAPER_NR_SOCIEDAD_ENABLED",
                "SCRAPER_POLICIALES_ENABLED",
                "SOCIAL_MAX_DEPORTES_PER_RUN",
                "SOCIAL_QUEUE_TTL_DAYS",
                "SOCIAL_TTL_HOURS",
                "VIDEO_DOWNLOAD_MAX_BYTES",
                "WEB_DEDUP_HISTORY_DAYS",
                "WEB_EDITORIAL_FALLBACK_MODE",
                "WEB_MAX_DEPORTES_PER_RUN",
                "WEB_PUBLIC_MEDIA_CHECK_ATTEMPTS",
                "WEB_PUBLIC_MEDIA_CHECK_ENABLED",
                "WEB_PUBLIC_MEDIA_CHECK_INITIAL_DELAY_SECONDS",
                "WEB_PUBLIC_MEDIA_CHECK_RETRY_SLEEP_SECONDS",
                "WEB_PUBLISH_MAX_PER_RUN",
                "WEB_PUBLISH_TARGET",
                "WEB_QUEUE_TTL_DAYS",
                "WEBAPP_DEFAULT_AUTHOR",
                "WEBAPP_REQUEST_RETRIES",
                "WEBAPP_REQUEST_TIMEOUT",
                "WEBAPP_RETRY_SLEEP_SECONDS",
            }
        ),
        "development": sorted(
            {
                "CUSTOM_POST_DRY_RUN",
                "LVR_BACKUP_DIR",
                "LVR_DATA_DIR",
                "LVR_FOTOS_DIR",
                "LVR_LOGS_DIR",
                "LVR_OUTPUT_DIR",
                "LVR_QUARANTINE_DIR",
                "LVR_QUEUE_EVENTS_PATH",
                "LVR_STAGE_RESULT_PATH",
                "META_QUEUE_PATH",
                "SOCIAL_QUEUE_PATH",
                "WEB_PUBLISHED_HISTORY_PATH",
                "WEB_QUEUE_PATH",
            }
        ),
        "obsolete": sorted(
            {
                "IG_CHROME_PROFILE_DIR",
                "IG_APP_ID",
                "IG_APP_SECRET",
                "FB_APP_ID",
                "FB_APP_SECRET",
                "IMAGE_LAYOUT",
                "SOCIAL_IMAGE_ENABLED",
                "SOCIAL_IMAGE_WIDTH",
                "SOCIAL_IMAGE_HEIGHT",
                "WATERMARK_ENABLED",
                "WATERMARK_IMAGE_PATH",
                "WATERMARK_POSITION",
                "WATERMARK_OPACITY",
                "WATERMARK_SCALE",
            }
        ),
    }


def safe_config_snapshot(values: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ if values is None else values
    snapshot: dict[str, str] = {}
    for name, value in sorted(env.items()):
        if not name.startswith(
            (
                "PIPELINE_",
                "SCRAPER_",
                "WEB",
                "PRIVATE_",
                "FB_",
                "IG_",
                "R2_",
                "OPENAI_",
                "EDITORIAL_",
                "JSON_",
                "LOG_",
                "LVR_",
                "CUSTOM_",
                "ARTICLE_",
                "DEDUP_",
                "PUBLISH_",
            )
        ):
            continue
        text = str(value or "")
        snapshot[name] = "[CONFIGURADO]" if name in SECRET_FIELDS and text else text
    return snapshot


def diagnose_environment(values: Mapping[str, str] | None = None, *, scope: str = "all") -> StageResult:
    report = validate_config(values, scope=scope)
    dependencies = {}
    for import_name in ("requests", "bs4", "PIL", "dotenv", "openai", "boto3", "botocore", "psutil"):
        dependencies[import_name] = importlib.util.find_spec(import_name) is not None
    binaries = {
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "yt-dlp": shutil.which("yt-dlp"),
    }
    missing_python = [name for name, present in dependencies.items() if not present]
    issues = len(report.errors) + len(missing_python)
    if issues:
        status = StageStatus.FAILED
        error_type = "configuration_or_dependency_error"
    elif report.warnings or not binaries["ffmpeg"] or not binaries["ffprobe"]:
        status = StageStatus.DEGRADED
        error_type = "optional_dependency_warning"
    else:
        status = StageStatus.SUCCESS
        error_type = None
    return StageResult(
        stage="doctor",
        status=status,
        received=len(report.issues) + len(dependencies),
        selected=len(dependencies),
        processed=len(dependencies),
        succeeded=sum(1 for present in dependencies.values() if present),
        failed=issues,
        error_type=error_type,
        details={
            "python": sys.version.split()[0],
            "config": report.to_dict(),
            "python_dependencies": dependencies,
            "system_binaries": binaries,
            "config_snapshot": safe_config_snapshot(values),
        },
    )
