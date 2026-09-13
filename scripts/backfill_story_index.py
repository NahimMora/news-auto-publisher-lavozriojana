"""Backfill de story_key para notas publicadas existentes (Parte 43).

Por defecto es report-only: nunca modifica el CMS ni el índice derivado más
allá de lo que el Story Engine ya haría en un ciclo normal. ``--apply``
requiere opt-in explícito y aplica vía ``PATCH /api/private/posts/<id>``
(el mismo endpoint que ya usa el autopublicador para actualizar notas).

Uso:
    python scripts/backfill_story_index.py --report-only
    python scripts/backfill_story_index.py --apply --confirm
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

import requests

from editorial_context import archive_index as ai
from editorial_context import story_engine
from utils.logging_setup import setup_logger
from utils.safe_http import UnsafeURLError, safe_request

logger = setup_logger("backfill_story_index", "backfill_story_index.log")


def _webapp_config() -> tuple[str, str]:
    base_url = os.getenv("WEBAPP_BASE_URL", "").strip().rstrip("/")
    api_key = (os.getenv("PRIVATE_API_KEY", "").strip() or os.getenv("WEBAPP_API_KEY", "").strip())
    return base_url, api_key


def _apply_story_key(post_id: str, story_key: str, *, base_url: str, api_key: str) -> tuple[bool, str]:
    endpoint = f"{base_url}/api/private/posts/{post_id}"
    try:
        response = safe_request(
            "PATCH",
            endpoint,
            requester=requests.request,
            headers={"Content-Type": "application/json", "x-api-key": api_key},
            json={"storyKey": story_key},
            timeout=20,
        )
    except (UnsafeURLError, requests.RequestException) as exc:
        return False, f"error de red: {exc}"
    if response.status_code in (200, 201):
        return True, ""
    return False, f"http_status={response.status_code}"


def build_report(*, limit: int | None = None) -> list[dict]:
    """Evalúa candidatos de story_key sin modificar nada."""
    rows: list[dict] = []
    for article in ai.get_all_without_story_key(limit=limit):
        candidates = ai.candidate_retrieval(
            title=article.title,
            excerpt=article.excerpt,
            entities=article.entities,
            localities=article.localities,
            category=article.category,
            exclude_article_id=article.article_id,
        )
        assignment = None
        if candidates:
            assignment = story_engine.assign_story(
                article_id=article.article_id,
                title=article.title,
                excerpt=article.excerpt,
                category=article.category,
                entities=article.entities,
                localities=article.localities,
                published_at=article.published_at,
                candidates=candidates,
            )
        rows.append(
            {
                "post": article.post_id or article.article_id,
                "article_id": article.article_id,
                "title": article.title,
                "candidate_story": assignment.story_key if assignment else None,
                # assignment.relations ya viene ordenado por score descendente
                # (retrieval.rank_candidates): el primero es el más fuerte.
                "confidence": (assignment.relations[0].confidence if assignment and assignment.relations else ""),
                "reason": (assignment.relations[0].relation_reason if assignment and assignment.relations else ""),
            }
        )
    return rows


def apply_report(rows: list[dict]) -> list[dict]:
    """Aplica los candidatos vía PATCH al CMS. Requiere WEBAPP_BASE_URL y
    PRIVATE_API_KEY configurados; nunca se llama sin --apply --confirm."""
    base_url, api_key = _webapp_config()
    results = []
    if not base_url or base_url == "PENDIENTE" or not api_key or api_key == "PENDIENTE":
        logger.error("WEBAPP_BASE_URL/PRIVATE_API_KEY no configurados; no se aplica nada")
        return [{"post": row["post"], "applied": False, "error": "credenciales_no_configuradas"} for row in rows]

    for row in rows:
        if not row["candidate_story"] or not row["post"]:
            continue
        ok, error = _apply_story_key(row["post"], row["candidate_story"], base_url=base_url, api_key=api_key)
        if ok:
            ai.set_story_key(row["article_id"], row["candidate_story"])
        results.append({"post": row["post"], "applied": ok, "error": error})
        logger.info("post=%s story_key=%s applied=%s error=%s", row["post"], row["candidate_story"], ok, error)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report-only", action="store_true", default=True, help="Default: no modifica nada")
    mode.add_argument("--apply", action="store_true", help="Aplica los candidatos vía PATCH al CMS")
    parser.add_argument(
        "--confirm", action="store_true", help="Requerido junto con --apply para confirmar la escritura real"
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    report = build_report(limit=args.limit)

    if args.apply:
        if not args.confirm:
            print(json.dumps({"status": "blocked", "reason": "--apply requiere --confirm explícito"}, ensure_ascii=False, indent=2))
            return 1
        applied = apply_report([row for row in report if row["candidate_story"]])
        print(json.dumps({"status": "applied", "report": report, "applied": applied}, ensure_ascii=False, indent=2, default=str))
        return 0

    print(json.dumps({"status": "report_only", "report": report}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
