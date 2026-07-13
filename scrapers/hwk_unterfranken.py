"""Courses from the Handwerkskammer für Unterfranken."""

from .base import RawCourseOffer
from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper, normalize_base_trade_offer


class HwkUnterfrankenScraper(BavariaOdavScraper):
    chamber_slug = "hwk-unterfranken"
    chamber_name = "Handwerkskammer für Unterfranken"
    chamber_website = "https://www.hwk-ufr.de"
    source_url = (
        "https://www.hwk-ufr.de/kurse/liste-78,0,courselist.html"
        "?search-topic=1"
    )
    catalogue = BavariaCatalogue(
        base_url="https://www.hwk-ufr.de",
        list_url=source_url + "&search-startdate={today}&limit={limit}&offset={offset}",
        default_city="Würzburg",
        default_street="Dieselstraße 12",
        default_zip="97082",
    )

    def postprocess_offer(self, offer: RawCourseOffer) -> RawCourseOffer:
        return normalize_base_trade_offer(offer)
