"""Política explícita de arranque progresivo y kill switches por integración."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Mapping


_TRUE = {"1", "true", "yes", "on", "si", "sí"}


class DeploymentMode(str, Enum):
    OBSERVE = "observe"
    WEB_ONLY = "web_only"
    WEB_FACEBOOK = "web_facebook"
    WEB_INSTAGRAM = "web_instagram"
    ALL = "all"


_MODE_CHANNELS = {
    DeploymentMode.OBSERVE: frozenset(),
    DeploymentMode.WEB_ONLY: frozenset({"web"}),
    DeploymentMode.WEB_FACEBOOK: frozenset({"web", "facebook"}),
    DeploymentMode.WEB_INSTAGRAM: frozenset({"web", "instagram"}),
    DeploymentMode.ALL: frozenset({"web", "facebook", "instagram"}),
}


@dataclass(frozen=True)
class DeploymentPlan:
    mode: DeploymentMode
    requested_channels: frozenset[str]
    enabled_channels: frozenset[str]
    kill_switches: dict[str, bool]
    errors: tuple[dict[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    def channel_enabled(self, channel: str) -> bool:
        return channel in self.enabled_channels

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "requested_channels": sorted(self.requested_channels),
            "enabled_channels": sorted(self.enabled_channels),
            "kill_switches": dict(self.kill_switches),
            "errors": list(self.errors),
            "limits": {
                "web_per_cycle": 1 if "web" in self.enabled_channels else 0,
                "facebook_per_cycle": 1 if "facebook" in self.enabled_channels else 0,
                "instagram_per_cycle": 1 if "instagram" in self.enabled_channels else 0,
            },
        }


def _value(values: Mapping[str, str], name: str, default: str = "") -> str:
    return str(values.get(name, default) or "").strip()


def _enabled(values: Mapping[str, str], name: str, default: str = "false") -> bool:
    return _value(values, name, default).lower() in _TRUE


def deployment_plan(values: Mapping[str, str] | None = None) -> DeploymentPlan:
    env = os.environ if values is None else values
    raw_mode = _value(env, "PIPELINE_DEPLOYMENT_MODE", DeploymentMode.OBSERVE.value).lower()
    try:
        mode = DeploymentMode(raw_mode)
    except ValueError:
        mode = DeploymentMode.OBSERVE
        return DeploymentPlan(
            mode=mode,
            requested_channels=frozenset(),
            enabled_channels=frozenset(),
            kill_switches={
                "web": False,
                "facebook": False,
                "instagram": False,
            },
            errors=(
                {
                    "code": "invalid_deployment_mode",
                    "field": "PIPELINE_DEPLOYMENT_MODE",
                    "message": (
                        "PIPELINE_DEPLOYMENT_MODE debe ser observe, web_only, "
                        "web_facebook, web_instagram o all"
                    ),
                },
            ),
        )

    target = _value(env, "WEB_PUBLISH_TARGET", "off").lower()
    switches = {
        "web": target == "node_webapp",
        "facebook": _enabled(env, "FB_PUBLISH_ENABLED"),
        "instagram": _enabled(env, "IG_PUBLISH_ENABLED"),
    }
    requested = _MODE_CHANNELS[mode]
    enabled = frozenset(channel for channel in requested if switches[channel])
    errors: list[dict[str, str]] = []

    for channel in sorted(requested):
        if switches[channel]:
            continue
        field = {
            "web": "WEB_PUBLISH_TARGET",
            "facebook": "FB_PUBLISH_ENABLED",
            "instagram": "IG_PUBLISH_ENABLED",
        }[channel]
        errors.append(
            {
                "code": "deployment_kill_switch_off",
                "field": field,
                "message": (
                    f"El modo {mode.value} solicita {channel}, pero su kill switch "
                    "individual está apagado"
                ),
            }
        )

    unexpected = sorted(channel for channel, value in switches.items() if value and channel not in requested)
    for channel in unexpected:
        field = {
            "web": "WEB_PUBLISH_TARGET",
            "facebook": "FB_PUBLISH_ENABLED",
            "instagram": "IG_PUBLISH_ENABLED",
        }[channel]
        errors.append(
            {
                "code": "deployment_unexpected_channel_enabled",
                "field": field,
                "message": (
                    f"El kill switch de {channel} está encendido, pero el modo "
                    f"{mode.value} no habilita ese canal"
                ),
            }
        )

    return DeploymentPlan(
        mode=mode,
        requested_channels=requested,
        enabled_channels=enabled,
        kill_switches=switches,
        errors=tuple(errors),
    )


def stage_environment(channel: str, plan: DeploymentPlan) -> dict[str, str]:
    """Límites conservadores inyectados por el supervisor en cada subproceso."""
    if not plan.channel_enabled(channel):
        return {}
    if channel == "web":
        return {"WEB_PUBLISH_MAX_PER_RUN": "1"}
    if channel == "facebook":
        return {"PUBLISH_MAX_PER_RUN": "1"}
    if channel == "instagram":
        return {"IG_MAX_PER_RUN": "1"}
    return {}


def configuration_fingerprint(values: Mapping[str, str] | None = None) -> str:
    """Hash estable de configuración operativa sin incluir secretos."""
    env = os.environ if values is None else values
    prefixes = (
        "PIPELINE_",
        "SCRAPER_",
        "WEB_PUBLISH_",
        "FB_PUBLISH_",
        "IG_PUBLISH_",
        "JSON_",
        "ALERT",
        "DISK_",
    )
    snapshot = {
        key: str(value)
        for key, value in env.items()
        if key.startswith(prefixes)
        and not any(token in key for token in ("TOKEN", "SECRET", "KEY", "PASSWORD"))
    }
    snapshot.setdefault("PIPELINE_DEPLOYMENT_MODE", DeploymentMode.OBSERVE.value)
    snapshot.setdefault("WEB_PUBLISH_TARGET", "off")
    snapshot.setdefault("FB_PUBLISH_ENABLED", "false")
    snapshot.setdefault("IG_PUBLISH_ENABLED", "false")
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@lru_cache(maxsize=1)
def current_commit_sha() -> str:
    configured = str(os.getenv("LVR_COMMIT_SHA") or "").strip()
    if configured:
        return configured
    root = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def deployment_metadata(values: Mapping[str, str] | None = None) -> dict:
    env = os.environ if values is None else values
    plan = deployment_plan(env)
    return {
        "commit_sha": current_commit_sha(),
        "release_tag": _value(env, "LVR_RELEASE_TAG", "unreleased"),
        "deployed_at": _value(env, "LVR_DEPLOYED_AT") or None,
        "deployment_mode": plan.mode.value,
        "configuration_fingerprint": configuration_fingerprint(env),
        "operator": _value(env, "LVR_DEPLOYMENT_OPERATOR") or None,
        "backup_reference": _value(env, "LVR_BACKUP_REFERENCE") or None,
    }
