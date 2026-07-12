"""Courses from the Handwerkskammer für Mittelfranken."""

from copy import deepcopy

from .base import RawCourseOffer, build_course_title
from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper


class HwkMittelfrankenScraper(BavariaOdavScraper):
    chamber_slug = "hwk-mittelfranken"
    chamber_name = "Handwerkskammer für Mittelfranken"
    chamber_website = "https://www.hwk-mittelfranken.de"
    source_url = (
        "https://www.hwk-akademie.de/kurse/liste-3751,0,courselist.html"
        "?search-type=6"
    )
    catalogue = BavariaCatalogue(
        base_url="https://www.hwk-akademie.de",
        list_url=source_url + "&search-startdate={today}&limit={limit}&offset={offset}",
        default_city="Nürnberg",
        default_street="Sulzbacher Straße 11-15",
        default_zip="90489",
    )

    def transform_offer(
        self, offer: RawCourseOffer, detail_text: str
    ) -> RawCourseOffer | list[RawCourseOffer]:
        """The academy sells one shared Feinwerkmechaniker/Metallbauer run."""
        lower = detail_text.lower()
        if "feinwerkmechanikerhandwerk und metallbauerhandwerk" not in lower:
            return offer

        result: list[RawCourseOffer] = []
        for trade, fragment in (
            ("Feinwerkmechaniker", "trade-feinwerkmechaniker"),
            ("Metallbauer", "trade-metallbauer"),
        ):
            split = deepcopy(offer)
            split.trade_name = trade
            split.title = build_course_title(trade, split.parts)
            split.source_url = f"{offer.source_url}#{fragment}"
            result.append(split)
        return result
