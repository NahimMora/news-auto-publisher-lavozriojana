from scraping.base_tiempopopular import scrap_noticia as _scrap
from scraping.base_tiempopopular import scrap_noticia_result as _scrap_result

SECTION_NAME = "deportes"


def scrap_noticia(url: str) -> dict | None:
    return _scrap(url, SECTION_NAME)


def scrap_noticia_result(url: str):
    return _scrap_result(url, SECTION_NAME)
