"""Medición de crecimiento (T01 del plan maestro, P08 mínimo).

Une, sin duplicar, las publicaciones de los registros que ya existen
(``ig_posted.json``, ``premium_ig_posted.json``, ``paparazzi_reels_posted.json``,
``social_formats_state.json``) con las mediciones de ``ig_media_insights.json``
y arma una comparación simple por edad, formato, fuente y categoría.

Reglas de honestidad:

* sólo lectura; no hay base nueva ni cola nueva;
* un dato ausente es ``None`` (``"ND"`` en texto), nunca cero;
* el formato es ``unknown`` salvo que lo confirme Graph (``web_feed_state``)
  o el publicador que creó el contenedor (Reel/carrusel); nunca se asume
  "imagen";
* la cohorte de una medición sale de su edad real: una lectura a las 11 h no
  es "72 h";
* no se atribuyen seguidores a publicaciones individuales.

La escritura de cohortes y de la metadata de render queda detrás de
``GROWTH_METRICS_ENABLED`` (default ``false``); el reporte puede leerse
siempre (con lo que haya).
"""
from __future__ import annotations

import os
import statistics
import time
from collections.abc import Mapping

from utils.file_manager import JsonStateError, load_json
from utils.paths import data_dir

ENABLED_ENV = "GROWTH_METRICS_ENABLED"
_TRUE = {"1", "true", "yes", "on", "si", "sí"}

# (edad mínima en horas, etiqueta). La etiqueta de una medición es el umbral
# más alto que su edad real ya alcanzó.
COHORTS = ((0, "lt24h"), (24, "24h"), (72, "72h"), (168, "7d"))
COHORT_HOURS = {label: hours for hours, label in COHORTS}
# Factor sobre la mediana de la cohorte para marcar una pieza extraordinaria.
EXTRAORDINARY_FACTOR = 3.0


def growth_metrics_enabled(values: Mapping[str, str] | None = None) -> bool:
    env = os.environ if values is None else values
    return str(env.get(ENABLED_ENV, "false")).strip().lower() in _TRUE


def cohort_for(age_hours: float | None) -> str | None:
    if age_hours is None or age_hours < 0:
        return None
    label = COHORTS[0][1]
    for hours, name in COHORTS:
        if age_hours >= hours:
            label = name
    return label


def update_cohorts(record: dict, *, at: int, reach, interactions) -> None:
    """Agrega la medición a ``record["cohorts"]`` según su edad real.

    ``lt24h`` guarda la última lectura temprana; desde 24 h se conserva la
    PRIMERA lectura de cada cohorte (la más cercana al umbral), para comparar
    piezas a edades parecidas.
    """
    posted_at = int(record.get("posted_at") or 0)
    if not posted_at:
        return
    age_h = round((at - posted_at) / 3600, 2)
    label = cohort_for(age_h)
    if label is None:
        return
    cohorts = record.setdefault("cohorts", {})
    if label != "lt24h" and label in cohorts:
        return
    cohorts[label] = {"at": at, "age_h": age_h, "reach": reach, "interactions": interactions}


# ── Inventario unificado ─────────────────────────────────────────────────
def _load(name: str, default, kind):
    try:
        return load_json(str(data_dir() / name), default, expected_type=kind)
    except JsonStateError:
        return default


def _posted(name: str) -> dict:
    posted = _load(name, {"posted": {}}, dict).get("posted")
    return posted if isinstance(posted, dict) else {}


_GRAPH_FORMAT = {"IMAGE": "image", "VIDEO": "video", "CAROUSEL_ALBUM": "carousel"}


def _format(record: Mapping, graph: Mapping | None) -> tuple[str, str]:
    """(formato, fuente del dato). ``unknown`` si nadie lo confirma."""
    declared = str(record.get("media_type") or "").lower()
    graph_type = str((graph or {}).get("media_type") or "").upper()
    product = str((graph or {}).get("media_product_type") or "").upper()
    if product == "REELS":
        return "reel", "graph"
    if declared == "reel":
        # El publicador creó un contenedor REELS (paparazzi/x/local reels).
        return "reel", "publisher"
    if declared == "carousel":
        return "carousel", "publisher"
    if graph_type in _GRAPH_FORMAT:
        return _GRAPH_FORMAT[graph_type], "graph"
    return "unknown", "none"


def load_inventory() -> list[dict]:
    """Publicaciones de Instagram de todos los workflows, una por media_id."""
    graph = _load("web_feed_state.json", {}, dict).get("permalinks") or {}
    items: dict[str, dict] = {}

    def add(media_id, record: Mapping, workflow: str, **extra) -> None:
        media_id = str(media_id or "").strip()
        if not media_id:
            return
        current = items.get(media_id)
        if current is not None:
            # Mismo ID en dos registros (p. ej. Reel de Paparazzi en
            # ig_posted y paparazzi_reels_posted): una sola pieza.
            if current["workflow"] == "automatic":
                # ig_posted.json también guarda los Reels: el flujo específico manda.
                current["also_in"].append("automatic")
                current["workflow"] = workflow
            else:
                current["also_in"].append(workflow)
            for key, value in extra.items():
                current.setdefault(key, value)
            return
        content_type, type_source = _format({**record, **extra}, graph.get(media_id))
        items[media_id] = {
            "platform": "instagram",
            "media_id": media_id,
            "workflow": workflow,
            "also_in": [],
            "posted_at": int(record.get("posted_at") or 0) or _graph_time(graph.get(media_id)),
            "source": str(record.get("source") or "") or None,
            "category": _category(record.get("seccion")),
            "title": record.get("titulo_instagram") or record.get("titulo") or None,
            "caption": record.get("texto_instagram") or None,
            "content_type": content_type,
            "content_type_source": type_source,
            "story_key": record.get("dedup_key") or record.get("meta_queue_key") or record.get("canonical_url") or None,
            "render": record.get("growth_render") or None,
            "permalink": (graph.get(media_id) or {}).get("permalink") or None,
            **extra,
        }

    for key, record in _posted("ig_posted.json").items():
        if isinstance(record, dict):
            add(record.get("external_id"), {"dedup_key": key, **record}, "automatic")
    for key, record in _posted("paparazzi_reels_posted.json").items():
        if isinstance(record, dict):
            add(record.get("instagram_id"), {"dedup_key": key, "source": "paparazzi", "media_type": "reel", **record}, "paparazzi_reels")
    for key, record in _posted("premium_ig_posted.json").items():
        if isinstance(record, dict):
            add(record.get("external_id"), {"dedup_key": key, "media_type": "carousel", **record}, "premium")
    formats = _load("social_formats_state.json", {}, dict)
    for kind in ("brief", "weekly"):
        for day, record in (formats.get(kind) or {}).items():
            if isinstance(record, dict) and record.get("ig_id"):
                # El estado no guarda la hora de publicación: sólo Graph la da.
                add(record["ig_id"], {"dedup_key": f"{kind}:{day}", "source": "lvr", "media_type": "carousel" if kind == "brief" else ""}, f"social_{kind}")
    return list(items.values())


def _graph_time(graph: Mapping | None) -> int | None:
    from datetime import datetime

    raw = str((graph or {}).get("timestamp") or "")
    try:
        return int(datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z").timestamp()) if raw else None
    except ValueError:
        return None


def _category(value) -> str | None:
    if not value:
        return None
    from utils.editorial_priority import normalize_category

    return normalize_category(value)


# ── Reporte ──────────────────────────────────────────────────────────────
def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _observation(item: dict, media: Mapping) -> dict:
    """Mediciones por cohorte; la última lectura sin cohorte se ubica por edad."""
    record = media.get(item["media_id"]) or {}
    observed: dict[str, dict] = {}
    for label, snap in (record.get("cohorts") or {}).items():
        observed[label] = {"reach": _num(snap.get("reach")), "interactions": _num(snap.get("interactions")), "age_h": snap.get("age_h")}
    if record and item["posted_at"] and record.get("updated_at"):
        age_h = round((int(record["updated_at"]) - item["posted_at"]) / 3600, 2)
        label = cohort_for(age_h)
        if label and label not in observed:
            observed[label] = {"reach": _num(record.get("reach")), "interactions": _num(record.get("interactions")), "age_h": age_h}
    return observed


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "median": None, "p75": None, "total": None}
    ordered = sorted(values)
    p75 = ordered[min(len(ordered) - 1, int(round(0.75 * (len(ordered) - 1))))]
    return {"n": len(ordered), "median": round(statistics.median(ordered), 1), "p75": round(p75, 1), "total": round(sum(ordered), 1)}


def growth_report(*, days: int = 30, now: float | None = None, inventory: list[dict] | None = None, media: Mapping | None = None) -> dict:
    """Comparación por edad comparable. Sólo lectura."""
    current = time.time() if now is None else now
    since = current - days * 86400
    items = [i for i in (load_inventory() if inventory is None else inventory) if (i.get("posted_at") or 0) >= since]
    if media is None:
        media = _load("ig_media_insights.json", {"media": {}}, dict).get("media") or {}

    coverage = {"publications": len(items), "with_any_measurement": 0, "by_cohort": {label: 0 for _h, label in COHORTS}}
    by_dim: dict[str, dict[str, dict[str, list[float]]]] = {"content_type": {}, "source": {}, "category": {}, "workflow": {}}
    cohort_reach: dict[str, list[tuple[float, dict]]] = {label: [] for _h, label in COHORTS}
    evolution = []
    for item in items:
        observed = _observation(item, media)
        if observed:
            coverage["with_any_measurement"] += 1
        for label, obs in observed.items():
            coverage["by_cohort"][label] += 1
            if obs["reach"] is None:
                continue
            cohort_reach[label].append((obs["reach"], item))
            for dim in by_dim:
                key = str(item.get(dim) or "ND")
                by_dim[dim].setdefault(key, {}).setdefault(label, []).append(obs["reach"])
        ordered = sorted(((COHORT_HOURS[k], v) for k, v in observed.items() if v["reach"] is not None), key=lambda kv: kv[0])
        if len(ordered) >= 2:
            first, last = ordered[0][1], ordered[-1][1]
            evolution.append({
                "media_id": item["media_id"], "title": (item.get("title") or "")[:90],
                "from_age_h": first["age_h"], "to_age_h": last["age_h"],
                "reach_from": first["reach"], "reach_to": last["reach"],
            })

    extraordinary = {}
    for label, pairs in cohort_reach.items():
        values = [r for r, _ in pairs]
        if len(values) < 5:
            extraordinary[label] = {"n": len(values), "threshold": None, "outliers": [], "share_of_total": None}
            continue
        median = statistics.median(values)
        threshold = median * EXTRAORDINARY_FACTOR
        outliers = sorted(((r, i) for r, i in pairs if median > 0 and r >= threshold), key=lambda p: -p[0])
        total = sum(values)
        extraordinary[label] = {
            "n": len(values),
            "median": round(median, 1),
            "threshold": round(threshold, 1),
            "habitual": _stats([r for r, _ in pairs if r < threshold]),
            "outliers": [{"media_id": i["media_id"], "reach": r, "title": (i.get("title") or "")[:90], "content_type": i["content_type"], "source": i.get("source")} for r, i in outliers[:10]],
            "share_of_total": round(sum(r for r, _ in outliers) / total, 3) if total else None,
        }

    return {
        "generated_at": int(current),
        "days": days,
        "coverage": coverage,
        "content_types": _count(items, "content_type"),
        "by": {dim: {key: {label: _stats(vals) for label, vals in cohorts.items()} for key, cohorts in groups.items()} for dim, groups in by_dim.items()},
        "extraordinary": extraordinary,
        "evolution": sorted(evolution, key=lambda e: -(e["reach_to"] or 0))[:15],
        "notes": [
            "Alcance sumado no es audiencia única; seguidores no se atribuyen por publicación.",
            "ND = dato no disponible (no es cero). Formato 'unknown' = sin confirmación de Graph ni del publicador.",
        ],
    }


def _count(items: list[dict], field: str) -> dict:
    out: dict[str, int] = {}
    for item in items:
        key = str(item.get(field) or "ND")
        out[key] = out.get(key, 0) + 1
    return out


def due_for_cohort(inventory: list[dict], media: Mapping, *, now: float, exclude: set[str], limit: int) -> list[dict]:
    """Piezas que cruzaron 24 h / 72 h / 7 d y todavía no tienen esa cohorte.

    Prioriza la cohorte más cercana a vencer su ventana (la de menor edad).
    """
    due = []
    for item in inventory:
        if not item.get("posted_at") or item["media_id"] in exclude:
            continue
        age_h = (now - item["posted_at"]) / 3600
        label = cohort_for(age_h)
        if label in (None, "lt24h") or age_h > 24 * 10:
            continue
        cohorts = (media.get(item["media_id"]) or {}).get("cohorts") or {}
        if label not in cohorts:
            due.append((age_h, item))
    due.sort(key=lambda pair: pair[0])
    return [item for _age, item in due[: max(0, limit)]]
