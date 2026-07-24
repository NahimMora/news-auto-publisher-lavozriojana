from scraping.base_tiempopopular import scrap_links as _scrap
from scraping.base_tiempopopular import scrap_links_result as _scrap_result

SECTION_URL = "https://www.tiempopopular.com.ar/interior-2/"
SECTION_NAME = "interior"


def scrap_links() -> list[str]:
    return _scrap(SECTION_URL, SECTION_NAME)


def scrap_links_result():
    return _scrap_result(SECTION_URL, SECTION_NAME)
