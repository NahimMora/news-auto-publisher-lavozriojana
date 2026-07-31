"""Wrapper Python para renders estáticos de Remotion (Fase 4 + rediseño
"Editorial Cinemática Riojana").

Centraliza la invocación de Remotion para las composiciones
``PremiumSlide``/``AutomaticInstagramCard``/``FacebookOgCard``, con
detección de disponibilidad cacheada y el fallback explícito controlado
por ``STATIC_RENDER_ENGINE`` (ver docs/DECISIONS.md).

``render_still()`` intenta primero el servidor de render persistente
(``render_server.mjs``, bundlea una vez por proceso y reusa un browser
Chromium — resuelve docs/KNOWN_ISSUES.md #69, donde cada
``npx remotion still`` re-bundleaba desde cero, ~19s/render) y cae al
``subprocess`` viejo si el servidor no puede levantar por cualquier motivo.
Firma y contrato de retorno sin cambios: cualquier caller existente (tests,
``utils/premium_renderer.py``) sigue funcionando igual.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

import requests

from utils.logging_setup import setup_logger

logger = setup_logger("remotion_renderer", "remotion_renderer.log")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
REMOTION_DIR = os.path.join(BASE_DIR, "remotion")
AVAILABILITY_CACHE_SECONDS = int(os.getenv("REMOTION_AVAILABILITY_CACHE_SECONDS", "300"))

_availability_cache: dict[str, tuple[bool, float]] = {}

# ── Servidor de render persistente ──────────────────────────────────────
RENDER_SERVER_SCRIPT = os.path.join(REMOTION_DIR, "render_server.mjs")
RENDER_SERVER_INFO_PATH = os.path.join(REMOTION_DIR, ".render-server.json")
RENDER_SERVER_HEALTH_TIMEOUT = float(os.getenv("REMOTION_RENDER_SERVER_HEALTH_TIMEOUT", "1.5"))
RENDER_SERVER_STARTUP_TIMEOUT = float(os.getenv("REMOTION_RENDER_SERVER_STARTUP_TIMEOUT", "90"))
RENDER_SERVER_DISABLED = os.getenv("REMOTION_RENDER_SERVER_DISABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

_server_lock = threading.Lock()


def _read_server_info() -> dict | None:
    try:
        with open(RENDER_SERVER_INFO_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _server_health_check(port: int) -> bool:
    try:
        response = requests.get(f"http://127.0.0.1:{port}/health", timeout=RENDER_SERVER_HEALTH_TIMEOUT)
        return response.status_code == 200 and response.json().get("ok") is True
    except (requests.RequestException, ValueError):
        return False


def _spawn_render_server() -> bool:
    popen_kwargs: dict = {
        "cwd": REMOTION_DIR,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        popen_kwargs["start_new_session"] = True
    try:
        # 'node' es un ejecutable real en PATH (a diferencia de 'npx', que en
        # Windows es un .cmd y necesita el wrapper _npx_args) — no hace falta
        # invocarlo vía cmd /c.
        subprocess.Popen(["node", RENDER_SERVER_SCRIPT, "--port=0"], **popen_kwargs)
        return True
    except OSError as exc:
        logger.warning("No se pudo lanzar render_server.mjs: %s", exc)
        return False


def ensure_render_server() -> int | None:
    """Puerto de un servidor de render persistente saludable, o ``None`` si
    no se pudo levantar (el llamador debe caer al ``subprocess`` viejo).
    Idempotente y seguro entre hilos: si ya hay uno saludable, lo reusa sin
    lanzar un segundo proceso.
    """
    if RENDER_SERVER_DISABLED or not os.path.isfile(RENDER_SERVER_SCRIPT):
        return None

    info = _read_server_info()
    if info and _server_health_check(info.get("port", -1)):
        return info["port"]

    with _server_lock:
        info = _read_server_info()
        if info and _server_health_check(info.get("port", -1)):
            return info["port"]

        if not _spawn_render_server():
            return None

        started = time.monotonic()
        while time.monotonic() - started < RENDER_SERVER_STARTUP_TIMEOUT:
            info = _read_server_info()
            if info and _server_health_check(info.get("port", -1)):
                logger.info("servidor de render persistente listo en el puerto %s", info["port"])
                return info["port"]
            time.sleep(0.4)

        logger.warning(
            "render_server.mjs no respondió /health dentro de %ss, se usa el subprocess viejo",
            RENDER_SERVER_STARTUP_TIMEOUT,
        )
        return None


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


# Cada workflow tiene su propia variable y su propio default seguro.
# ``STATIC_RENDER_ENGINE`` (legacy) sólo aplica si el workflow no tiene su
# propia variable definida explícitamente — nunca debe cambiar en silencio
# el motor del flujo automático productivo.
# Ver docs/DECISIONS.md "Política de renderers por workflow" y "Editorial
# Cinemática Riojana" (corrección del default de "automatic").
#
# "automatic" pasó de "pillow" a "auto" (2026-07-31): con el servidor de
# render persistente (render_server.mjs, ver docs/KNOWN_ISSUES.md #69) un
# render Remotion pasó de ~19s a ~1s, viable para el volumen del flujo
# automático (hasta 8/ciclo). "auto" intenta Remotion primero para subir la
# calidad visual y cae a Pillow sin bloquear una publicación real si el
# servidor Node tiene un problema puntual — nunca "remotion" estricto acá,
# que haría fallar la publicación entera ante cualquier hiccup de Node.
# "og" (Facebook/web) no se tocó en esta entrega — fuera de alcance.
WORKFLOW_DEFAULT_ENGINE = {
    "automatic": "auto",
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
    a una ruta local real. Intenta primero el servidor de render persistente
    (``ensure_render_server``/``_render_still_via_server`` — bundlea una vez
    por proceso, ver docs/KNOWN_ISSUES.md #69) y cae al ``subprocess`` de
    ``npx remotion still`` si el servidor no está disponible por cualquier
    motivo. Firma y contrato de retorno idénticos en ambos caminos — ningún
    caller existente necesita saber cuál se usó.
    """
    if not os.path.isdir(REMOTION_DIR):
        raise RemotionRenderError("carpeta remotion/ no encontrada")

    server_result = _render_still_via_server(composition_id, props, asset_paths=asset_paths, timeout=timeout)
    if server_result is not None:
        return server_result

    return _render_still_via_subprocess(composition_id, props, asset_paths=asset_paths, timeout=timeout)


def _render_still_via_server(
    composition_id: str,
    props: dict,
    *,
    asset_paths: dict[str, str] | None,
    timeout: int,
) -> tuple[bytes, dict] | None:
    """Devuelve ``(png_bytes, metadata)`` vía el servidor persistente, o
    ``None`` si el servidor no está disponible (el llamador debe caer al
    subprocess viejo). Un render que sí llegó al servidor pero falló de
    verdad (composición inválida, etc.) levanta ``RemotionRenderError`` en
    vez de degradar en silencio — sólo la *disponibilidad* del servidor
    dispara el fallback, no un error de render legítimo."""
    port = ensure_render_server()
    if port is None:
        return None

    started = time.monotonic()
    payload = {
        "compositionId": composition_id,
        "inputProps": props,
        "assetPaths": asset_paths or {},
    }
    try:
        response = requests.post(
            f"http://127.0.0.1:{port}/render",
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning(
            "servidor de render persistente no respondió para %s, cae al subprocess viejo: %s",
            composition_id,
            exc,
        )
        return None

    duration = time.monotonic() - started
    if response.status_code != 200:
        detail = ""
        try:
            detail = str(response.json().get("error", ""))
        except ValueError:
            detail = response.text[:500]
        raise RemotionRenderError(f"servidor de render persistente falló para {composition_id}: {detail}")

    return response.content, {
        "engine": "remotion",
        "duration_seconds": round(duration, 3),
        "render_path": "persistent_server",
    }


def _render_still_via_subprocess(
    composition_id: str,
    props: dict,
    *,
    asset_paths: dict[str, str] | None = None,
    timeout: int = 180,
) -> tuple[bytes, dict]:
    """Camino histórico (Fase 4): ``npx remotion still`` por render, re-bundlea
    cada vez. Se conserva como red de seguridad interna cuando el servidor
    persistente no puede levantar (ver ``render_still``)."""
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
        return data, {"engine": "remotion", "duration_seconds": round(duration, 3), "render_path": "subprocess"}
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
