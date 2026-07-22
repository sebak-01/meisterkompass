"""Courses from the Handwerkskammer für Schwaben."""

from .base import RawCourseOffer
from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper


class HwkSchwabenScraper(BavariaOdavScraper):
    chamber_slug = "hwk-schwaben"
    chamber_name = "Handwerkskammer für Schwaben"
    chamber_website = "https://www.hwk-schwaben.de"
    source_url = (
        "https://www.bildungschwaben.de/3711,0,courselist.html"
        "?search-filter-template=0&search-type=6"
    )
    catalogue = BavariaCatalogue(
        base_url="https://www.bildungschwaben.de",
        list_url=source_url + "&limit={limit}&offset={offset}",
        default_city="Augsburg",
        default_street="Siebentischstraße 54",
        default_zip="86161",
        implicit_trade_parts=True,
    )

    def postprocess_offer(self, offer: RawCourseOffer) -> RawCourseOffer:
        # Base Prüfungsgebühr (e.g. Teil I+II = 500 €) is authoritative.
        # Do not surface "zzgl. gewerkspezifischer Prüfungsgebühr" as a note.
        offer.exam_fee_qualifier = ""
        return offer
