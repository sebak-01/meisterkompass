"""Courses from the Handwerkskammer für Oberfranken."""

from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper


class HwkOberfrankenScraper(BavariaOdavScraper):
    chamber_slug = "hwk-oberfranken"
    chamber_name = "Handwerkskammer für Oberfranken"
    chamber_website = "https://www.hwk-oberfranken.de"
    source_url = (
        "https://www.hwk-oberfranken.de/72,0,courselist.html"
        "?search-filter-template=0&search-type=6"
    )
    catalogue = BavariaCatalogue(
        base_url="https://www.hwk-oberfranken.de",
        list_url=source_url + "&limit={limit}&offset={offset}",
        default_city="Bayreuth",
        default_street="Kerschensteinerstraße 8-10",
        default_zip="95448",
    )
