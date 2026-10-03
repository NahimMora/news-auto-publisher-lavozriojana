"""KPIs semanales de redes (LVR-NOTE-0001): seguidores, volumen y rendimiento.

Sólo mide; nunca publica ni toca colas. Reutiliza los insights por publicación
que ``meta/ig_insights.py`` ya consulta en cada ciclo y suma una única
consulta diaria de seguidores por red.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Callable

from utils.file_manager import load_json, update_json
from utils.paths import data_dir

KPI_DAILY_PATH = str(data_dir() / "kpi_daily.json")
MEDIA_INSIGHTS_PATH = str(data_dir() / "ig_media_insights.json")
DAILY_RETENTION_DAYS = 400
MEDIA_RETENTION_DAYS = 120


def _today() -> str:
    return date.today().isoformat()


def record_media_insights(entries: list[dict], *, now: float | None = None) -> int:
    """Guarda alcance/interacciones por publicación de IG (último valor visto)."""
    current = int(time.time() if now is None else now)
    cutoff = current - MEDIA_RETENTION_DAYS * 86400

    def mutate(state):
        media = state.setdefault("media", {})
        for entry in entries:
            media_id = str(entry.get("media_id") or "")
            if not media_id:
                continue
            media[media_id] = {
                "posted_at": int(entry.get("posted_at") or 0),
                "seccion": str(entry.get("seccion") or ""),
                "reach": float(entry.get("reach") or 0),
                "interactions": float(entry.get("interactions") or 0),
                "updated_at": current,
            }
        state["media"] = {
            key: value
            for key, value in media.items()
            if int(value.get("posted_at") or 0) >= cutoff
        }
        return state

    update_json(MEDIA_INSIGHTS_PATH, mutate, {"media": {}}, expected_type=dict)
    return len(entries)


def followers_snapshot_due(*, today: str | None = None) -> bool:
    day = today or _today()
    state = load_json(KPI_DAILY_PATH, {"days": {}}, expected_type=dict)
    return "followers" not in (state.get("days", {}).get(day) or {})


def record_followers_snapshot(
    fetchers: dict[str, Callable[[], int | None]],
    *,
    today: str | None = None,
) -> dict[str, int]:
    """Una vez por día: seguidores por red. Un fetch fallido no inventa un valor."""
    day = today or _today()
    if not followers_snapshot_due(today=day):
        return {}
    values = {}
    for network, fetch in fetchers.items():
        value = fetch()
        if value is not None:
            values[network] = int(value)
    if not values:
        return {}
    cutoff = (date.fromisoformat(day) - timedelta(days=DAILY_RETENTION_DAYS)).isoformat()

    def mutate(state):
        days = state.setdefault("days", {})
        days.setdefault(day, {})["followers"] = values
        state["days"] = {key: value for key, value in days.items() if key >= cutoff}
        return state

    update_json(KPI_DAILY_PATH, mutate, {"days": {}}, expected_type=dict)
    return values


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _posted_days(path: str) -> list[date]:
    state = load_json(path, {"posted": {}}, expected_type=dict)
    posted = state.get("posted") if isinstance(state.get("posted"), dict) else {}
    days = []
    for record in posted.values():
        if isinstance(record, dict) and record.get("posted_at") and record.get("external_id"):
            days.append(datetime.fromtimestamp(int(record["posted_at"])).date())
    return days


def weekly_report(weeks: int = 4, *, today: date | None = None) -> list[dict]:
    """Semanas (lunes a domingo) más recientes primero, incluida la actual."""
    current = today or date.today()
    starts = [_week_start(current) - timedelta(weeks=offset) for offset in range(max(1, weeks))]
    daily = load_json(KPI_DAILY_PATH, {"days": {}}, expected_type=dict).get("days", {})
    media = load_json(MEDIA_INSIGHTS_PATH, {"media": {}}, expected_type=dict).get("media", {})
    ig_days = _posted_days(str(data_dir() / "ig_posted.json"))
    fb_days = _posted_days(str(data_dir() / "fb_posted.json"))

    report = []
    for start in starts:
        end = start + timedelta(days=6)
        in_week = lambda day: start <= day <= end  # noqa: E731
        followers = {}
        week_days = sorted(key for key in daily if start.isoformat() <= key <= end.isoformat())
        for network in ("instagram", "facebook"):
            series = [
                daily[key]["followers"][network]
                for key in week_days
                if network in (daily[key].get("followers") or {})
            ]
            if series:
                followers[network] = {"start": series[0], "end": series[-1], "delta": series[-1] - series[0]}
        week_media = [
            value
            for value in media.values()
            if value.get("posted_at") and in_week(datetime.fromtimestamp(int(value["posted_at"])).date())
        ]
        reach = sum(item.get("reach", 0) for item in week_media)
        interactions = sum(item.get("interactions", 0) for item in week_media)
        report.append(
            {
                "week_start": start.isoformat(),
                "week_end": end.isoformat(),
                "followers": followers,
                "posts": {
                    "instagram": sum(1 for day in ig_days if in_week(day)),
                    "facebook": sum(1 for day in fb_days if in_week(day)),
                },
                "instagram": {
                    "measured_posts": len(week_media),
                    "avg_reach": round(reach / len(week_media), 1) if week_media else None,
                    "engagement_rate": round(interactions / reach, 4) if reach else None,
                },
            }
        )
    return report
