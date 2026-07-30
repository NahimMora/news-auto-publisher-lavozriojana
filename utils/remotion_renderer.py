"""Wrapper Python para renders estáticos de Remotion (Fase 4).

Centraliza la invocación de ``npx remotion still`` para las composiciones
``PremiumSlide``/``AutomaticInstagramCard``/``FacebookOgCard``, con
detección de disponibilidad cacheada y el fallback explícito controlado
por ``STATIC_RENDER_ENGINE`` (ver docs/DECISIONS.md).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid

from utils.logging_setup import setup_logger

logger = setup_logger("remotion_renderer", "remotion_renderer.log")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
REMOTION_DIR = os.path.join(BASE_DIR, "remotion")
AVAILABILITY_CACHE_SECONDS = int(os.getenv("REMOTION_AVAILABILITY_CACHE_SECONDS", "300"))

_availability_cache: dict[str, tuple[bool, float]] = {}


class RemotionRenderError(RuntimeError):
    pass


def _npx_args(args: list[str]) -> list[str]:
    """En Windows, npx es un .cmd — subprocess sin shell no lo ejecuta directamente."""
    if os.name == "nt":
        return ["cmd", "/c", "npx", *args]
    return ["npx", *args]


def remotion_available(*, force_recheck: bool = False) -> bool:
    """True si Remotion/Node están disponibles en este entorno.

    Cacheado unos minutos: spawnear un proceso Node para chequear
    disponibilidad no es gratis (bundling), y ``resolve_engine()`` puede
    llamarse por cada slide.
    """
    cached = _availability_cache.get("available")
    if cached and not force_recheck and (time.time() - cached[1]) < AVAILABILITY_CACHE_SECONDS:
        return cached[0]
    if not os.path.isdir(REMOTION_DIR):
        _availability_cache["available"] = (False, time.time())
        return False
    try:
        result = subprocess.run(
            _npx_args(["remotion", "versions"]),
            cwd=REMOTION_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        available = result.returncode == 0
    except Exception as exc:
        logger.warning("No se pudo verificar disponibilidad de Remotion: %s", exc)
        available = False
    _availability_cache["available"] = (available, time.time())
    return available


# Cada workflow tiene su propia variable y su propio default seguro. El
# flujo automático y el OG de Facebook/web deben conservar Pillow salvo
# habilitación explícita; el estudio premium (manual, bajo volumen) usa
# Remotion por defecto. ``STATIC_RENDER_ENGINE`` (legacy) sólo aplica si el
# workflow no tiene su propia variable definida explícitamente — nunca debe
# cambiar en silencio el motor del flujo automático productivo.
# Ver docs/DECISIONS.md "Política de renderers por workflow".
WORKFLOW_DEFAULT_ENGINE = {
    "automatic": "pillow",
    "premium": "remotion",
    "og": "pillow",
}
WORKFLOW_ENV_VARS = {
    "automatic": "AUTOMATIC_STATIC_RENDER_ENGINE",
    "premium": "PREMIUM_STATIC_RENDER_ENGINE",
    "og": "OG_STATIC_RENDER_ENGINE",
}
LEGACY_ENGINE_ENV_VAR = "STATIC_RENDER_ENGINE"


def resolve_engine(workflow: str) -> str:
    """Resuelve el motor efectivo para ``workflow`` (``automatic``,
    ``premium`` u ``og``).

    Precedencia:

    1. la variable específica del workflow (``AUTOMATIC_STATIC_RENDER_ENGINE``,
       ``PREMIUM_STATIC_RENDER_ENGINE``, ``OG_STATIC_RENDER_ENGINE``), si está
       definida explícitamente (no vacía);
    2. ``STATIC_RENDER_ENGINE`` (legacy), sólo si está definida explícitamente;
    3. el default seguro del workflow (``WORKFLOW_DEFAULT_ENGINE``).

    Devuelve ``"remotion"``, ``"pillow"`` o ``"remotion_unavailable"`` (modo
    ``remotion`` — explícito o por default de ``premium`` — pero Remotion no
    está disponible; el llamador debe reportar fallo, nunca caer en silencio
    a Pillow en ese caso). Cada resolución queda registrada en el log
    rotativo con ``workflow``, ``engine_requested``, ``engine_used`` y, si
    corresponde, ``fallback_reason``.
    """
    if workflow not in WORKFLOW_DEFAULT_ENGINE:
        raise ValueError(f"workflow desconocido: {workflow!r} (esperado uno de {sorted(WORKFLOW_DEFAULT_ENGINE)})")

    specific_var = WORKFLOW_ENV_VARS[workflow]
    specific_raw = os.getenv(specific_var)
    legacy_raw = os.getenv(LEGACY_ENGINE_ENV_VAR)

    if specific_raw is not None and specific_raw.strip():
        mode = specific_raw.strip().lower()
        source = specific_var
    elif legacy_raw is not None and legacy_raw.strip():
        mode = legacy_raw.strip().lower()
        source = f"{LEGACY_ENGINE_ENV_VAR} (legacy override)"
    else:
        mode = WORKFLOW_DEFAULT_ENGINE[workflow]
        source = "default"

    if mode not in {"auto", "remotion", "pillow"}:
        logger.warning(
            "Valor inválido en %s=%r para workflow=%s; se usa el default seguro", source, mode, workflow
        )
        mode = WORKFLOW_DEFAULT_ENGINE[workflow]
        source = "default (valor inválido ignorado)"

    fallback_reason = None
    if mode == "pillow":
        engine = "pillow"
    elif mode == "remotion":
        available = remotion_available()
        engine = "remotion" if available else "remotion_unavailable"
        if not available:
            fallback_reason = "remotion_mode_explicit_but_unavailable"
    else:  # auto
        available = remotion_available()
        engine = "remotion" if available else "pillow"
        if not available:
            fallback_reason = "auto_mode_fallback_remotion_unavailable"

    logger.info(
        "engine resolve: workflow=%s engine_requested=%s engine_used=%s source=%s fallback_reason=%s",
        workflow,
        mode,
        engine,
        source,
        fallback_reason,
    )
    return engine


def render_still(
    composition_id: str,
    props: dict,
    *,
    asset_paths: dict[str, str] | None = None,
    timeout: int = 180,
) -> tuple[bytes, dict]:
    """Renderiza una composición still y devuelve ``(png_bytes, metadata)``.

    ``asset_paths`` mapea el nombre del prop de asset (p.ej. ``"assetFile"``)
    a una ruta local real. Remotion sólo puede leer archivos dentro de
    ``public/``, así que se copian ahí bajo ``public/tmp/`` con un nombre
    único y se borran al terminar — no queda contenido de terceros dando
    vueltas en el repo.
    """
    if not os.path.isdir(REMOTION_DIR):
        raise RemotionRenderError("carpeta remotion/ no encontrada")

    render_id = uuid.uuid4().hex
    working_props = dict(props)
    copied_assets: list[str] = []
    props_path = os.path.join(tempfile.gettempdir(), f"_remotion_props_{render_id}.json")
    output_path = os.path.join(tempfile.gettempdir(), f"_remotion_still_{render_id}.png")
    started = time.monotonic()

    try:
        for prop_name, local_path in (asset_paths or {}).items():
            if not local_path:
                continue
            ext = os.path.splitext(local_path)[1] or ".jpg"
            rel_path = f"tmp/{render_id}_{prop_name}{ext}"
            dest = os.path.join(REMOTION_DIR, "public", rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(local_path, dest)
            copied_assets.append(dest)
            working_props[prop_name] = rel_path

        with open(props_path, "w", encoding="utf-8") as handle:
            json.dump(working_props, handle)

        try:
            result = subprocess.run(
                _npx_args(["remotion", "still", composition_id, output_path, f"--props={props_path}"]),
                cwd=REMOTION_DIR,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RemotionRenderError(f"timeout renderizando {composition_id}") from exc

        duration = time.monotonic() - started
        if result.returncode != 0 or not os.path.isfile(output_path):
            raise RemotionRenderError(
                f"remotion still falló para {composition_id} (exit={result.returncode}): "
                f"{result.stderr[-500:]}"
            )

        with open(output_path, "rb") as handle:
            data = handle.read()
        return data, {"engine": "remotion", "duration_seconds": round(duration, 3)}
    finally:
        for path in copied_assets:
            try:
                os.unlink(path)
            except OSError:
                pass
        for path in (props_path, output_path):
            try:
                os.unlink(path)
            except OSError:
                pass
