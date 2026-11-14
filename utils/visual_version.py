"""Selector central de versión visual (Visual System V1 / V2).

Contrato: ``visual_style_version = "v1" | "v2"`` para los tres workflows
visuales — ``reel``, ``instagram`` y ``og``. El default es SIEMPRE ``v1``:
desplegar este código no cambia ninguna pieza hasta que el host defina
explícitamente ``VISUAL_STYLE_VERSION=v2`` (ver docs/design/VISUAL_SYSTEM_V2.md,
sección "Activación futura").

Precedencia (de mayor a menor):

1. Rollback: si la configuración efectiva es ``v1`` por una variable explícita,
   gana sobre cualquier fijación ``v2`` de la pieza (v1 es el estado seguro).
2. Fijación de la pieza (``item["visual_style_version"]``): una pieza que ya
   empezó a renderizarse con una versión la conserva en reintentos, para no
   cambiar de diseño en medio del procesamiento.
3. Variable por workflow (``REEL_VISUAL_STYLE_VERSION``,
   ``INSTAGRAM_VISUAL_STYLE_VERSION``, ``OG_VISUAL_STYLE_VERSION``): sólo
   para una divergencia EXPLÍCITA entre canales; queda registrada con warning.
4. Variable global ``VISUAL_STYLE_VERSION``.
5. Default ``v1``.

El módulo no renderiza nada: devuelve la versión, la composición Remotion que
corresponde y metadatos reproducibles para registrar junto a cada pieza.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from utils.logging_setup import setup_logger

logger = setup_logger("visual_version", "visual_version.log")

VALID_VERSIONS = ("v1", "v2")
DEFAULT_VERSION = "v1"
GLOBAL_ENV = "VISUAL_STYLE_VERSION"
WORKFLOW_ENV = {
    "reel": "REEL_VISUAL_STYLE_VERSION",
    "instagram": "INSTAGRAM_VISUAL_STYLE_VERSION",
    "og": "OG_VISUAL_STYLE_VERSION",
}
ITEM_FIELD = "visual_style_version"

# Registro de composiciones por (workflow, versión). V1 de Reels depende del
# flag histórico REEL_CINEMATIC_VISUAL_STYLE_ENABLED (EditorialReel vs Main),
# que este selector no reemplaza ni modifica.
COMPOSITIONS = {
    ("reel", "v2"): "EditorialReelV2",
    ("instagram", "v1"): "AutomaticInstagramCard",
    ("instagram", "v2"): "AutomaticInstagramCardV2",
    ("og", "v1"): "FacebookOgCard",
    ("og", "v2"): "FacebookOgCardV2",
}


@dataclass(frozen=True)
class VisualVersionDecision:
    workflow: str
    version: str
    source: str
    composition: str

    def as_metadata(self) -> dict:
        """Metadatos para guardar junto a la pieza (reproducibilidad)."""
        data = asdict(self)
        data["visual_style_version"] = data.pop("version")
        return data


def _clean(value: object) -> str:
    return str(value or "").strip().lower()


def composition_for(workflow: str, version: str, *, reel_cinematic: bool = True) -> str:
    if workflow == "reel" and version == "v1":
        return "EditorialReel" if reel_cinematic else "Main"
    try:
        return COMPOSITIONS[(workflow, version)]
    except KeyError as exc:
        raise ValueError(f"combinación visual desconocida: {workflow}/{version}") from exc


def resolve_visual_version(
    workflow: str,
    item: Mapping[str, object] | None = None,
    values: Mapping[str, str] | None = None,
    *,
    reel_cinematic: bool = True,
) -> VisualVersionDecision:
    """Resuelve la versión visual efectiva para ``workflow`` y una pieza."""
    if workflow not in WORKFLOW_ENV:
        raise ValueError(f"workflow visual desconocido: {workflow!r} (esperado {sorted(WORKFLOW_ENV)})")
    env = os.environ if values is None else values

    configured = DEFAULT_VERSION
    source = "default"
    explicit = False
    global_raw = _clean(env.get(GLOBAL_ENV))
    if global_raw:
        if global_raw in VALID_VERSIONS:
            configured, source, explicit = global_raw, GLOBAL_ENV, True
        else:
            logger.warning("Valor inválido %s=%r; se usa %s", GLOBAL_ENV, global_raw, DEFAULT_VERSION)

    workflow_var = WORKFLOW_ENV[workflow]
    workflow_raw = _clean(env.get(workflow_var))
    if workflow_raw:
        if workflow_raw in VALID_VERSIONS:
            if workflow_raw != configured:
                logger.warning(
                    "Divergencia visual explícita: %s=%s mientras la versión global es %s",
                    workflow_var,
                    workflow_raw,
                    configured,
                )
            configured, source, explicit = workflow_raw, workflow_var, True
        else:
            logger.warning("Valor inválido %s=%r; se ignora", workflow_var, workflow_raw)

    version = configured
    pinned = _clean((item or {}).get(ITEM_FIELD))
    if pinned in VALID_VERSIONS and pinned != configured:
        if configured == "v1" and explicit:
            source = f"{source} (rollback sobre fijación {pinned})"
        else:
            version, source = pinned, f"{ITEM_FIELD} fijada en la pieza"

    decision = VisualVersionDecision(
        workflow=workflow,
        version=version,
        source=source,
        composition=composition_for(workflow, version, reel_cinematic=reel_cinematic),
    )
    logger.info(
        "visual version: workflow=%s version=%s composition=%s source=%s",
        decision.workflow,
        decision.version,
        decision.composition,
        decision.source,
    )
    return decision
