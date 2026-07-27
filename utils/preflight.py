"""Preflight externo seguro, explícito y sin consumo de colas operativas."""
from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from utils.config import validate_config
from utils.deployment import deployment_plan
from utils.file_manager import (
    FileLock,
    JsonCorruptionError,
    backup_json,
    load_json,
    restore_json,
    save_json,
    update_json,
)
from utils.paths import data_dir, logs_dir
from utils.safe_http import UnsafeURLError, validate_public_http_url
from utils.stage_result import StageResult, StageStatus
from utils.url_normalization import canonical_url


PREFLIGHT_SCOPES = (
    "sources",
    "openai",
    "r2",
    "cms",
    "facebook",
    "instagram",
    "filesystem",
    "supervisor",
    "all",
)

SOURCE_SECTIONS = {
    "tiempopopular_locales": "https://www.tiempopopular.com.ar/locales/",
    "tiempopopular_policiales": "https://www.tiempopopular.com.ar/policiales/",
    "tiempopopular_interior": "https://www.tiempopopular.com.ar/interior/",
    "tiempopopular_deportes": "https://www.tiempopopular.com.ar/deportes/",
    "nuevarioja_politica": "https://nuevarioja.com.ar/politica",
    "nuevarioja_sociedad": "https://nuevarioja.com.ar/sociedad",
    "nuevarioja_policiales": "https://nuevarioja.com.ar/policiales",
    "nuevarioja_deportes": "https://nuevarioja.com.ar/deportes",
    "nuevarioja_interior": "https://nuevarioja.com.ar/interior",
    "nuevarioja_internacionales": "https://nuevarioja.com.ar/internacionales",
}

_PLACEHOLDERS = {"", "PENDIENTE", "CHANGE_ME", "CHANGEME", "TODO"}


def _configured(env: Mapping[str, str], name: str) -> str:
    value = str(env.get(name) or "").strip()
    return "" if value.upper() in _PLACEHOLDERS else value


def _blocked(stage: str, missing: list[str], *, reason: str = "missing_configuration") -> StageResult:
    return StageResult(
        stage,
        StageStatus.BLOCKED,
        error_type=reason,
        details={"missing": sorted(missing)},
    )


def _http_status_result(stage: str, status: int, *, next_retry_at=None) -> StageResult:
    if status == 401 or status == 403:
        return StageResult(
            stage,
            StageStatus.FAILED,
            failed=1,
            error_type="invalid_credential",
            error_code=status,
        )
    if status == 429:
        return StageResult(
            stage,
            StageStatus.DEGRADED,
            failed=1,
            error_type="rate_limit",
            error_code=status,
            next_retry_at=next_retry_at,
        )
    return StageResult(
        stage,
        StageStatus.FAILED,
        failed=1,
        error_type="http_error",
        error_code=status,
    )


def _json_response(response) -> dict | None:
    try:
        value = response.json()
    except (ValueError, TypeError, AttributeError):
        return None
    return value if isinstance(value, dict) else None


def _object_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error") if isinstance(response.get("Error"), dict) else {}
    metadata = (
        response.get("ResponseMetadata")
        if isinstance(response.get("ResponseMetadata"), dict)
        else {}
    )
    return str(error.get("Code") or "") in {"404", "NoSuchKey", "NotFound"} or int(
        metadata.get("HTTPStatusCode") or 0
    ) == 404


def _content_type(response) -> str:
    headers = getattr(response, "headers", {}) or {}
    return str(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()


def _candidate_links(section_url: str, html: str) -> list[str]:
    host = (urlsplit(section_url).hostname or "").lower().removeprefix("www.")
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    section_name = urlsplit(section_url).path.strip("/").split("/")[-1]
    if host == "tiempopopular.com.ar":
        from scraping.base_tiempopopular import _is_article_url as is_article
    else:
        from scraping.base_nuevarioja import _is_article_url as is_nueva_article

        is_article = lambda value: is_nueva_article(value, section_name)
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        absolute = canonical_url(urljoin(section_url, href))
        parsed = urlsplit(absolute)
        candidate_host = (parsed.hostname or "").lower().removeprefix("www.")
        if candidate_host != host:
            continue
        if is_article(href if host != "tiempopopular.com.ar" else absolute) and absolute not in found:
            found.append(absolute)
    return found


def _recognize_article(article_url: str, html: str) -> tuple[bool, bool]:
    soup = BeautifulSoup(html, "html.parser")
    host = (urlsplit(article_url).hostname or "").lower().removeprefix("www.")
    if host == "tiempopopular.com.ar":
        from scraping.base_tiempopopular import (
            _extract_image,
            _extract_paragraphs,
            _extract_title,
        )

        title = _extract_title(soup, article_url)
    else:
        from scraping.base_nuevarioja import (
            _extract_image,
            _extract_paragraphs,
            _extract_title,
        )

        title = _extract_title(soup)
    paragraphs = _extract_paragraphs(soup)
    image_url = str(_extract_image(soup) or "").strip()
    image_ok = False
    if image_url:
        try:
            validate_public_http_url(image_url)
            image_ok = True
        except UnsafeURLError:
            image_ok = False
    return bool(title and paragraphs), image_ok


def check_sources(
    *,
    http_get: Callable = requests.get,
    resolver: Callable = socket.getaddrinfo,
    sections: Mapping[str, str] | None = None,
) -> StageResult:
    started = time.monotonic()
    results: list[dict] = []
    failures = degraded = no_work = succeeded = 0
    for name, section_url in (sections or SOURCE_SECTIONS).items():
        item = {"source": name, "url": section_url}
        try:
            host = urlsplit(section_url).hostname or ""
            resolver(host, 443, type=socket.SOCK_STREAM)
            response = http_get(
                section_url,
                headers={"User-Agent": "LaVozRiojana-Preflight/1.0"},
                timeout=25,
            )
            status = int(getattr(response, "status_code", 0) or 0)
            item["http_status"] = status
            item["content_type"] = _content_type(response)
            if status < 200 or status >= 300:
                item["status"] = "failed"
                item["error_type"] = "http_error"
                failures += 1
            elif item["content_type"] not in {"text/html", "application/xhtml+xml"}:
                item["status"] = "failed"
                item["error_type"] = "unexpected_content_type"
                failures += 1
            else:
                links = _candidate_links(section_url, str(getattr(response, "text", "") or ""))
                item["links"] = len(links)
                if not links:
                    item["status"] = "no_work"
                    no_work += 1
                else:
                    article = http_get(
                        links[0],
                        headers={"User-Agent": "LaVozRiojana-Preflight/1.0"},
                        timeout=25,
                    )
                    article_status = int(getattr(article, "status_code", 0) or 0)
                    if article_status < 200 or article_status >= 300:
                        item["status"] = "failed"
                        item["error_type"] = "article_http_error"
                        item["article_http_status"] = article_status
                        failures += 1
                    else:
                        recognized, image_ok = _recognize_article(
                            links[0],
                            str(getattr(article, "text", "") or "")
                        )
                        item["article_url"] = links[0]
                        if not recognized:
                            item["status"] = "failed"
                            item["error_type"] = "selector_mismatch"
                            failures += 1
                        elif not image_ok:
                            item["status"] = "degraded"
                            item["error_type"] = "image_missing_or_unsafe"
                            degraded += 1
                        else:
                            item["status"] = "success"
                            succeeded += 1
        except requests.Timeout:
            item.update(status="failed", error_type="timeout")
            failures += 1
        except (requests.RequestException, OSError, UnsafeURLError) as exc:
            item.update(status="failed", error_type=type(exc).__name__)
            failures += 1
        results.append(item)

    selected = len(results)
    if failures:
        status = StageStatus.FAILED if succeeded == 0 and degraded == 0 and no_work == 0 else StageStatus.DEGRADED
    elif degraded:
        status = StageStatus.DEGRADED
    elif succeeded:
        status = StageStatus.SUCCESS
    else:
        status = StageStatus.NO_WORK
    return StageResult(
        "preflight_sources",
        status,
        received=selected,
        selected=selected,
        processed=selected,
        succeeded=succeeded,
        failed=failures,
        deferred=degraded,
        duration_seconds=time.monotonic() - started,
        error_type="source_check_failed" if failures else ("source_degraded" if degraded else None),
        details={"sources": results, "no_work": no_work, "degraded": degraded},
    )


def check_openai(
    values: Mapping[str, str] | None = None,
    *,
    client_factory=None,
) -> StageResult:
    env = os.environ if values is None else values
    key = _configured(env, "OPENAI_API_KEY")
    if not key:
        return _blocked("preflight_openai", ["OPENAI_API_KEY"])
    started = time.monotonic()
    try:
        if client_factory is None:
            from openai import OpenAI

            client_factory = OpenAI
        client = client_factory(
            api_key=key,
            timeout=float(env.get("OPENAI_TIMEOUT", "60")),
        )
        response = client.responses.create(
            model=str(env.get("OPENAI_MODEL", "gpt-4o-mini")),
            input=(
                "Respondé únicamente este JSON, sin markdown ni texto adicional: "
                '{"status":"ok","purpose":"lvr_preflight"}'
            ),
            max_output_tokens=40,
        )
        text = str(getattr(response, "output_text", "") or "").strip()
        payload = json.loads(text)
        if payload != {"status": "ok", "purpose": "lvr_preflight"}:
            raise ValueError("unexpected_structured_response")
        return StageResult(
            "preflight_openai",
            StageStatus.SUCCESS,
            received=1,
            selected=1,
            processed=1,
            succeeded=1,
            duration_seconds=time.monotonic() - started,
            details={
                "model": str(env.get("OPENAI_MODEL", "gpt-4o-mini")),
                "fallback_policy": str(env.get("OPENAI_FALLBACK_MODE", "allow_non_sensitive")),
            },
        )
    except Exception as exc:
        status_code = int(getattr(exc, "status_code", 0) or 0)
        if status_code in {401, 403}:
            return _http_status_result("preflight_openai", status_code)
        if status_code == 429:
            return _http_status_result("preflight_openai", 429)
        return StageResult(
            "preflight_openai",
            StageStatus.FAILED,
            failed=1,
            duration_seconds=time.monotonic() - started,
            error_type="invalid_response" if isinstance(exc, (ValueError, json.JSONDecodeError)) else type(exc).__name__,
        )


def check_r2(
    values: Mapping[str, str] | None = None,
    *,
    client_factory=None,
    http_get: Callable = requests.get,
    clock: Callable[[], float] = time.time,
) -> StageResult:
    env = os.environ if values is None else values
    required = (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_PUBLIC_URL",
    )
    missing = [name for name in required if not _configured(env, name)]
    if missing:
        return _blocked("preflight_r2", missing)
    started = time.monotonic()
    timestamp = datetime.fromtimestamp(clock(), timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"healthchecks/{timestamp}-{uuid.uuid4().hex}.json"
    bucket = _configured(env, "R2_BUCKET_NAME")
    cleanup_error = None
    client = None
    try:
        if client_factory is None:
            from utils.r2_storage import _get_client

            client_factory = _get_client
        client = client_factory()
        payload = json.dumps({"check": "lvr", "timestamp": timestamp}).encode("utf-8")
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=payload,
            ContentType="application/json",
            CacheControl="no-store",
        )
        client.head_object(Bucket=bucket, Key=key)
        public_url = validate_public_http_url(
            f"{_configured(env, 'R2_PUBLIC_URL').rstrip('/')}/{key}"
        )
        response = http_get(public_url, timeout=20)
        if int(getattr(response, "status_code", 0) or 0) != 200:
            raise RuntimeError("public_read_failed")
    except Exception as exc:
        status_code = int(
            getattr(getattr(exc, "response", {}), "get", lambda *_: {})("ResponseMetadata", {}).get(
                "HTTPStatusCode", 0
            )
            if getattr(exc, "response", None)
            else getattr(exc, "status_code", 0)
            or 0
        )
        result = _http_status_result("preflight_r2", status_code) if status_code in {401, 403, 429} else StageResult(
            "preflight_r2",
            StageStatus.FAILED,
            failed=1,
            error_type=type(exc).__name__,
        )
    else:
        result = StageResult(
            "preflight_r2",
            StageStatus.SUCCESS,
            received=1,
            selected=1,
            processed=1,
            succeeded=1,
            details={"object_key": key, "public_read": True},
        )
    finally:
        if client is not None:
            try:
                client.delete_object(Bucket=bucket, Key=key)
                try:
                    client.head_object(Bucket=bucket, Key=key)
                except Exception as exc:
                    if not _object_not_found(exc):
                        cleanup_error = "deletion_confirmation_failed"
                else:
                    cleanup_error = "object_still_exists"
            except Exception as exc:
                cleanup_error = type(exc).__name__
    result.duration_seconds = round(time.monotonic() - started, 6)
    result.details["cleanup_error"] = cleanup_error
    if cleanup_error:
        result.status = StageStatus.FAILED if result.status == StageStatus.FAILED else StageStatus.DEGRADED
        result.error_type = "cleanup_error"
        result.failed = max(1, result.failed)
    return result


def check_cms(
    values: Mapping[str, str] | None = None,
    *,
    http_get: Callable = requests.get,
) -> StageResult:
    env = os.environ if values is None else values
    base = _configured(env, "WEBAPP_BASE_URL")
    token = _configured(env, "PRIVATE_API_KEY") or _configured(env, "WEBAPP_API_KEY")
    path = _configured(env, "WEBAPP_PREFLIGHT_PATH")
    missing = [
        name
        for name, value in (
            ("WEBAPP_BASE_URL", base),
            ("PRIVATE_API_KEY|WEBAPP_API_KEY", token),
            ("WEBAPP_PREFLIGHT_PATH", path),
        )
        if not value
    ]
    if missing:
        reason = "safe_endpoint_not_configured" if not path else "missing_configuration"
        return _blocked("preflight_cms", missing, reason=reason)
    started = time.monotonic()
    try:
        endpoint = validate_public_http_url(urljoin(base.rstrip("/") + "/", path.lstrip("/")))
        response = http_get(
            endpoint,
            headers={"Authorization": f"Bearer {token}", "X-API-Key": token},
            timeout=int(env.get("WEBAPP_REQUEST_TIMEOUT", "30")),
        )
        status = int(getattr(response, "status_code", 0) or 0)
        if status < 200 or status >= 300:
            return _http_status_result("preflight_cms", status)
        payload = _json_response(response)
        if payload is None:
            return StageResult(
                "preflight_cms",
                StageStatus.FAILED,
                failed=1,
                error_type="non_json_response",
            )
        if payload.get("ok") is False:
            return StageResult(
                "preflight_cms",
                StageStatus.FAILED,
                failed=1,
                error_type="ok_false",
            )
        contract = payload.get("contract_version") or payload.get("version")
        capabilities = payload.get("capabilities") or {}
        can_receive = bool(
            payload.get("can_receive_post_payload")
            or (isinstance(capabilities, dict) and capabilities.get("posts_create"))
        )
        status_value = StageStatus.SUCCESS if can_receive else StageStatus.DEGRADED
        return StageResult(
            "preflight_cms",
            status_value,
            received=1,
            selected=1,
            processed=1,
            succeeded=1,
            duration_seconds=time.monotonic() - started,
            error_type=None if can_receive else "capability_not_declared",
            details={"contract_version": contract, "can_receive_post_payload": can_receive},
        )
    except requests.Timeout:
        return StageResult("preflight_cms", StageStatus.FAILED, failed=1, error_type="timeout")
    except (requests.RequestException, UnsafeURLError) as exc:
        return StageResult(
            "preflight_cms",
            StageStatus.FAILED,
            failed=1,
            error_type=type(exc).__name__,
        )


def _meta_get(
    stage: str,
    endpoint: str,
    token: str,
    *,
    http_get: Callable,
    timeout: int,
    fields: str,
) -> tuple[StageResult | None, dict | None]:
    try:
        validate_public_http_url(endpoint)
        response = http_get(
            endpoint,
            params={"fields": fields, "access_token": token},
            timeout=timeout,
        )
    except requests.Timeout:
        return StageResult(stage, StageStatus.FAILED, failed=1, error_type="timeout"), None
    except (requests.RequestException, UnsafeURLError) as exc:
        return StageResult(stage, StageStatus.FAILED, failed=1, error_type=type(exc).__name__), None
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        return _http_status_result(stage, status), None
    payload = _json_response(response)
    if payload is None:
        return StageResult(stage, StageStatus.FAILED, failed=1, error_type="non_json_response"), None
    if payload.get("error"):
        code = int((payload.get("error") or {}).get("code") or 0)
        return _http_status_result(stage, 401 if code == 190 else status), None
    return None, payload


def _meta_permissions(
    stage: str,
    graph: str,
    token: str,
    required: set[str],
    *,
    http_get: Callable,
    timeout: int,
) -> tuple[StageResult | None, list[str]]:
    try:
        response = http_get(
            f"{graph.rstrip('/')}/me/permissions",
            params={"access_token": token},
            timeout=timeout,
        )
    except requests.Timeout:
        return StageResult(stage, StageStatus.FAILED, failed=1, error_type="timeout"), []
    except requests.RequestException as exc:
        return StageResult(stage, StageStatus.FAILED, failed=1, error_type=type(exc).__name__), []
    status = int(getattr(response, "status_code", 0) or 0)
    if status < 200 or status >= 300:
        return _http_status_result(stage, status), []
    payload = _json_response(response)
    if payload is None:
        return StageResult(stage, StageStatus.FAILED, failed=1, error_type="non_json_response"), []
    data = payload.get("data")
    if not isinstance(data, list):
        return (
            StageResult(
                stage,
                StageStatus.DEGRADED,
                error_type="permission_evidence_unavailable",
            ),
            [],
        )
    granted = {
        str(item.get("permission") or "")
        for item in data
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "granted"
    }
    missing = sorted(required - granted)
    if missing:
        return (
            StageResult(
                stage,
                StageStatus.FAILED,
                failed=1,
                error_type="missing_permission",
                details={"missing_permissions": missing},
            ),
            sorted(granted),
        )
    return None, sorted(granted)


def check_facebook(
    values: Mapping[str, str] | None = None,
    *,
    http_get: Callable = requests.get,
) -> StageResult:
    env = os.environ if values is None else values
    page_id = _configured(env, "FB_PAGE_ID")
    token = _configured(env, "FB_PAGE_ACCESS_TOKEN")
    missing = [name for name, value in (("FB_PAGE_ID", page_id), ("FB_PAGE_ACCESS_TOKEN", token)) if not value]
    if missing:
        return _blocked("preflight_facebook", missing)
    graph = _configured(env, "META_GRAPH_API") or "https://graph.facebook.com/v19.0"
    error, payload = _meta_get(
        "preflight_facebook",
        f"{graph.rstrip('/')}/{page_id}",
        token,
        http_get=http_get,
        timeout=int(env.get("FB_REQUEST_TIMEOUT_SECONDS", "60")),
        fields="id,name",
    )
    if error:
        return error
    actual_id = str((payload or {}).get("id") or "")
    if actual_id != page_id:
        return StageResult(
            "preflight_facebook",
            StageStatus.FAILED,
            failed=1,
            error_type="identity_mismatch",
            details={"expected_id": page_id, "actual_id": actual_id},
        )
    tasks: set[str] = set()
    permission_error, permissions = _meta_permissions(
        "preflight_facebook",
        graph,
        token,
        {"pages_manage_posts"},
        http_get=http_get,
        timeout=int(env.get("FB_REQUEST_TIMEOUT_SECONDS", "60")),
    )
    if permission_error and "CREATE_CONTENT" not in tasks:
        permission_error.details.setdefault("page_id", actual_id)
        return permission_error
    return StageResult(
        "preflight_facebook",
        StageStatus.SUCCESS,
        received=1,
        selected=1,
        processed=1,
        succeeded=1,
        details={
            "page_id": actual_id,
            "identity_verified": True,
            "read_access": True,
            "page_tasks": sorted(tasks),
            "permissions": permissions,
            "publish_permission_verified": "CREATE_CONTENT" in tasks
            or "pages_manage_posts" in permissions,
        },
    )


def check_instagram(
    values: Mapping[str, str] | None = None,
    *,
    http_get: Callable = requests.get,
) -> StageResult:
    env = os.environ if values is None else values
    account_id = _configured(env, "IG_ACCOUNT_ID")
    page_id = _configured(env, "FB_PAGE_ID")
    token = _configured(env, "IG_ACCESS_TOKEN") or _configured(env, "FB_PAGE_ACCESS_TOKEN")
    missing = [
        name
        for name, value in (
            ("IG_ACCOUNT_ID", account_id),
            ("FB_PAGE_ID", page_id),
            ("IG_ACCESS_TOKEN|FB_PAGE_ACCESS_TOKEN", token),
        )
        if not value
    ]
    if missing:
        return _blocked("preflight_instagram", missing)
    graph = _configured(env, "META_GRAPH_API") or "https://graph.facebook.com/v19.0"
    timeout = int(env.get("IG_REQUEST_TIMEOUT_SECONDS", "60"))
    error, identity = _meta_get(
        "preflight_instagram",
        f"{graph.rstrip('/')}/{account_id}",
        token,
        http_get=http_get,
        timeout=timeout,
        fields="id,username,media_count",
    )
    if error:
        return error
    error, relation = _meta_get(
        "preflight_instagram",
        f"{graph.rstrip('/')}/{page_id}",
        token,
        http_get=http_get,
        timeout=timeout,
        fields="id,instagram_business_account",
    )
    if error:
        return error
    related = str(((relation or {}).get("instagram_business_account") or {}).get("id") or "")
    actual = str((identity or {}).get("id") or "")
    if actual != account_id or related != account_id:
        return StageResult(
            "preflight_instagram",
            StageStatus.FAILED,
            failed=1,
            error_type="identity_or_relation_mismatch",
            details={"expected_id": account_id, "actual_id": actual, "related_id": related},
        )
    permission_error, permissions = _meta_permissions(
        "preflight_instagram",
        graph,
        token,
        {"instagram_content_publish"},
        http_get=http_get,
        timeout=timeout,
    )
    if permission_error:
        return permission_error
    return StageResult(
        "preflight_instagram",
        StageStatus.SUCCESS,
        received=2,
        selected=2,
        processed=2,
        succeeded=2,
        details={
            "account_id": actual,
            "page_id": page_id,
            "username": str((identity or {}).get("username") or ""),
            "relation_verified": True,
            "permissions": permissions,
            "publish_permission_verified": True,
        },
    )


@contextmanager
def _temporary_environment(values: Mapping[str, str]):
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update({name: str(value) for name, value in values.items()})
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def check_filesystem(
    *,
    root: str | os.PathLike[str] | None = None,
    min_free_mb: int | None = None,
) -> StageResult:
    started = time.monotonic()
    operational_root = Path(root or data_dir()).resolve()
    required_mb = int(min_free_mb or os.getenv("DISK_FREE_MIN_MB", "1024"))
    try:
        operational_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".lvr-preflight-", dir=str(operational_root)) as temp:
            work = Path(temp)
            state = work / "state.json"
            backups = work / "backups"
            quarantine = work / "quarantine"
            env = {
                "LVR_BACKUP_DIR": str(backups),
                "LVR_QUARANTINE_DIR": str(quarantine),
                "JSON_BACKUP_ENABLED": "true",
                "JSON_BACKUP_MIN_INTERVAL_SECONDS": "0",
            }
            with _temporary_environment(env):
                save_json(str(state), [])
                with FileLock(str(work / "lock-probe.json")):
                    pass

                def append(value: int) -> None:
                    update_json(
                        str(state),
                        lambda items: [*items, value],
                        [],
                        expected_type=list,
                    )

                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(append, range(20)))
                if sorted(load_json(str(state), [], expected_type=list)) != list(range(20)):
                    raise RuntimeError("concurrent_update_lost")

                backup = backup_json(str(state), str(backups))
                save_json(str(state), [{"changed": True}])
                restore_json(str(backup), str(state))
                if sorted(load_json(str(state), [], expected_type=list)) != list(range(20)):
                    raise RuntimeError("restore_mismatch")

                corrupt = work / "truncated.json"
                corrupt.write_text("[", encoding="utf-8")
                try:
                    load_json(str(corrupt), [], expected_type=list)
                except JsonCorruptionError as exc:
                    if not exc.quarantine_path or not Path(exc.quarantine_path).is_file():
                        raise RuntimeError("quarantine_missing") from exc
                else:
                    raise RuntimeError("corruption_not_detected")

            usage = shutil.disk_usage(operational_root)
            free_mb = int(usage.free / (1024 * 1024))
            network_share = str(operational_root).startswith("\\\\")
            status = StageStatus.SUCCESS if free_mb >= required_mb else StageStatus.FAILED
            return StageResult(
                "preflight_filesystem",
                status,
                received=7,
                selected=7,
                processed=7,
                succeeded=7 if status == StageStatus.SUCCESS else 6,
                failed=0 if status == StageStatus.SUCCESS else 1,
                duration_seconds=time.monotonic() - started,
                error_type=None if status == StageStatus.SUCCESS else "disk_space_low",
                details={
                    "root": str(operational_root),
                    "free_mb": free_mb,
                    "required_free_mb": required_mb,
                    "network_share_detected": network_share,
                    "atomic_replace": True,
                    "fsync": True,
                    "concurrent_writers": 2,
                    "backup_restore": True,
                    "corruption_quarantine": True,
                },
            )
    except (OSError, RuntimeError, JsonCorruptionError) as exc:
        return StageResult(
            "preflight_filesystem",
            StageStatus.FAILED,
            failed=1,
            duration_seconds=time.monotonic() - started,
            error_type=type(exc).__name__,
            details={"root": str(operational_root)},
        )


def check_supervisor(values: Mapping[str, str] | None = None) -> StageResult:
    env = os.environ if values is None else values
    started = time.monotonic()
    report = validate_config(env, scope="supervisor")
    plan = deployment_plan(env)
    if not report.ok:
        return StageResult(
            "preflight_supervisor",
            StageStatus.FAILED,
            failed=len(report.errors),
            duration_seconds=time.monotonic() - started,
            error_type="configuration_error",
            details={"config": report.to_dict(), "deployment": plan.to_dict()},
        )
    roots = (Path(_configured(env, "LVR_DATA_DIR") or data_dir()), Path(_configured(env, "LVR_LOGS_DIR") or logs_dir()))
    try:
        checks = []
        for root in roots:
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".lvr-supervisor-preflight-", dir=str(root)) as temp:
                probe = Path(temp) / "probe.json"
                save_json(str(probe), {"pid": os.getpid(), "heartbeat": time.time()})
                checks.append(load_json(str(probe), {}, expected_type=dict))
        return StageResult(
            "preflight_supervisor",
            StageStatus.SUCCESS,
            received=2,
            selected=2,
            processed=2,
            succeeded=2,
            duration_seconds=time.monotonic() - started,
            details={
                "deployment": plan.to_dict(),
                "heartbeat_seconds": int(env.get("PIPELINE_24X7_HEARTBEAT_SECONDS", "30")),
                "stale_seconds": int(env.get("PIPELINE_24X7_STALE_SECONDS", "900")),
                "pid_write": bool(checks[0]),
                "heartbeat_write": bool(checks[0]),
                "logs_write": bool(checks[1]),
                "supervisor_started": False,
            },
        )
    except (OSError, JsonCorruptionError) as exc:
        return StageResult(
            "preflight_supervisor",
            StageStatus.FAILED,
            failed=1,
            error_type=type(exc).__name__,
            details={"supervisor_started": False, "deployment": plan.to_dict()},
        )


def aggregate_preflight(results: list[StageResult]) -> StageResult:
    statuses = {result.status for result in results}
    if StageStatus.FAILED in statuses:
        status = StageStatus.FAILED
    elif StageStatus.DEGRADED in statuses:
        status = StageStatus.DEGRADED
    elif StageStatus.BLOCKED in statuses:
        status = StageStatus.BLOCKED
    elif StageStatus.SUCCESS in statuses:
        status = StageStatus.SUCCESS
    else:
        status = StageStatus.NO_WORK
    return StageResult(
        "preflight_all",
        status,
        received=sum(item.received for item in results),
        selected=sum(item.selected for item in results),
        processed=sum(item.processed for item in results),
        succeeded=sum(item.succeeded for item in results),
        failed=sum(item.failed for item in results),
        deferred=sum(item.deferred for item in results),
        duration_seconds=sum(item.duration_seconds for item in results),
        error_type=(
            "preflight_failed"
            if StageStatus.FAILED in statuses
            else "preflight_degraded"
            if StageStatus.DEGRADED in statuses
            else "preflight_blocked"
            if StageStatus.BLOCKED in statuses
            else None
        ),
        details={"checks": [item.to_dict() for item in results]},
    )


def run_preflight(
    scope: str,
    values: Mapping[str, str] | None = None,
    *,
    overrides: Mapping[str, Callable[[], StageResult]] | None = None,
) -> StageResult:
    if scope not in PREFLIGHT_SCOPES:
        return StageResult(
            "preflight",
            StageStatus.FAILED,
            failed=1,
            error_type="invalid_scope",
            details={"scope": scope},
        )
    env = os.environ if values is None else values
    custom = dict(overrides or {})
    checks: dict[str, Callable[[], StageResult]] = {
        "sources": lambda: check_sources(),
        "openai": lambda: check_openai(env),
        "r2": lambda: check_r2(env),
        "cms": lambda: check_cms(env),
        "facebook": lambda: check_facebook(env),
        "instagram": lambda: check_instagram(env),
        "filesystem": lambda: check_filesystem(
            root=_configured(env, "LVR_DATA_DIR") or data_dir(),
            min_free_mb=int(env.get("DISK_FREE_MIN_MB", "1024")),
        ),
        "supervisor": lambda: check_supervisor(env),
    }
    checks.update(custom)
    if scope == "all":
        return aggregate_preflight([checks[name]() for name in PREFLIGHT_SCOPES if name != "all"])
    return checks[scope]()
