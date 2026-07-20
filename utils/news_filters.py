import os
from utils.logging_setup import setup_logger
from utils.file_manager import load_json, save_json

logger = setup_logger("news_filters")

BLOCKED_KEYWORDS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "blocked_body_keywords.txt"
)
FILTERED_LOG = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "noticias_filtradas_body_keywords.json"
)


def _load_blocked_keywords() -> list[str]:
    if not os.path.exists(BLOCKED_KEYWORDS_FILE):
        return []
    with open(BLOCKED_KEYWORDS_FILE, "r", encoding="utf-8") as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]


def is_blocked(noticia: dict, stage: str = "unknown") -> bool:
    keywords = _load_blocked_keywords()
    if not keywords:
        return False

    body = " ".join(noticia.get("parrafos", []))
    title = noticia.get("titulo", "")
    full_text = f"{title} {body}".lower()

    matched = [kw for kw in keywords if kw.lower() in full_text]
    if matched:
        _log_filtered(noticia, matched, stage)
        logger.warning(f"Noticia bloqueada por keywords {matched}: {title[:60]}")
        return True
    return False


def _log_filtered(noticia: dict, matched: list, stage: str) -> None:
    from datetime import datetime

    entries = load_json(FILTERED_LOG, [])
    entries.append(
        {
            "noticia": {
                "titulo": noticia.get("titulo"),
                "url": noticia.get("url"),
            },
            "matched_keywords": matched,
            "stage": stage,
            "timestamp": datetime.now().isoformat(),
        }
    )
    save_json(FILTERED_LOG, entries)
