from scraping.base_tiempopopular import scrap_noticia as _scrap

SECTION_NAME = "policiales"


def scrap_noticia(url: str) -> dict | None:
    return _scrap(url, SECTION_NAME)
