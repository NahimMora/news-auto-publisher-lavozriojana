"""Entry point estructurado del scraper de infobae.com/sociedad/policiales/."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from scraping.base_infobae import scrap_links_result, scrap_noticia_result
from scraping.runner import run_section
from utils.editorial_router import detect_riojan_link
from utils.logging_setup import setup_logger
from utils.paths import data_dir
from utils.stage_result import emit_stage_result

logger = setup_logger("main_infobae_policiales", "main_infobae_policiales.log")


def _keep_if_video_or_riojan(article: dict) -> tuple[bool, str]:
    """Política editorial de esta fuente: sólo se publica lo que tiene video
    propio o vínculo riojano — el resto de policiales nacional de Infobae se
    descarta en el scraping, antes de gastar reescritura/IA en algo que de
    todos modos no se va a publicar."""
    if article.get("video_url"):
        return False, ""
    has_link, _reason = detect_riojan_link(article)
    if has_link:
        return False, ""
    return True, "infobae_sin_video_ni_vinculo_riojano"


def main():
    root = data_dir()
    result = run_section(
        stage="scrape_infobae_policiales",
        enabled=os.getenv("SCRAPER_INFOBAE_POLICIALES_ENABLED", "0") == "1",
        history_path=str(root / "noticias_ejecutadas_infobae_policiales.json"),
        output_path=str(root / "noticias_norewrite_infobae_policiales.json"),
        fetch_links=scrap_links_result,
        fetch_article=scrap_noticia_result,
        extra_discard=_keep_if_video_or_riojan,
    )
    logger.info(
        "Infobae Policiales status=%s %s/%s", result.status.value, result.succeeded, result.selected
    )
    return result


if __name__ == "__main__":
    raise SystemExit(emit_stage_result(main()))
