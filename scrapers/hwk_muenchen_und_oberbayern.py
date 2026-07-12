"""Courses from the Handwerkskammer für München und Oberbayern."""

from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper


class HwkMuenchenUndOberbayernScraper(BavariaOdavScraper):
    chamber_slug = "hwk-muenchen-und-oberbayern"
    chamber_name = "Handwerkskammer für München und Oberbayern"
    chamber_website = "https://www.hwk-muenchen.de"
    source_url = (
        "https://www.hwk-muenchen.de/74,0,courselist.html"
        "?search-filter-template=0&search-type=6"
    )
    catalogue = BavariaCatalogue(
        base_url="https://www.hwk-muenchen.de",
        list_url=source_url + "&limit={limit}&offset={offset}",
        default_city="München",
        default_street="Mühldorfstraße 6",
        default_zip="81671",
    )
