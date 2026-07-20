from scraping.base_tiempopopular import scrap_links as _scrap

SECTION_URL = "https://www.tiempopopular.com.ar/locales/"
SECTION_NAME = "locales"


def scrap_links() -> list[str]:
    return _scrap(SECTION_URL, SECTION_NAME)
