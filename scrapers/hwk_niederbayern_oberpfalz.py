"""Courses from the Handwerkskammer Niederbayern-Oberpfalz."""

from collections import Counter

from .base import RawCourseOffer
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

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        offers = super().fetch_raw_courses()
        return self._disambiguate_parallel_runs(offers)

    @staticmethod
    def _disambiguate_parallel_runs(offers: list[RawCourseOffer]) -> list[RawCourseOffer]:
        """Parallel runs share a title/date/fee but take place in different cities."""
        counts = Counter((offer.title, offer.start_date, offer.course_fee) for offer in offers)
        disambiguated: list[RawCourseOffer] = []
        for offer in offers:
            if counts[(offer.title, offer.start_date, offer.course_fee)] > 1 and offer.city:
                offer.title = f"{offer.title} — {offer.city}"
            disambiguated.append(offer)
        return disambiguated
