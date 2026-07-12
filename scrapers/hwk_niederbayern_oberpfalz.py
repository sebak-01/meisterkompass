"""Courses from the Handwerkskammer Niederbayern-Oberpfalz."""

from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper


class HwkNiederbayernOberpfalzScraper(BavariaOdavScraper):
    chamber_slug = "hwk-niederbayern-oberpfalz"
    chamber_name = "Handwerkskammer Niederbayern-Oberpfalz"
    chamber_website = "https://www.hwkno.de"
    source_url = (
        "https://www.hwkno.de/76,0,courselist.html"
        "?search-filter-template=0&search-type=6"
    )
    catalogue = BavariaCatalogue(
        base_url="https://www.hwkno.de",
        list_url=source_url + "&limit={limit}&offset={offset}",
        default_city="Regensburg",
        default_street="Ditthornstraße 10",
        default_zip="93055",
    )
