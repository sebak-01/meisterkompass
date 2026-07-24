"""Courses from the Handwerkskammer für Mittelfranken."""

from copy import deepcopy
import logging
import re

from .base import RawCourseOffer, build_course_title
from .exam_fee_tariff import (
    download_pdf_text,
    parse_bavaria_b_iv_meister_fees,
    part_fee_rows,
    resolve_pdf_url_from_page,
)
from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper

logger = logging.getLogger(__name__)

EXAM_FEES_PAGE_URL = "https://www.hwk-mittelfranken.de/artikel/gebuehrenordnung-3751,0,85.html"
EXAM_FEES_FALLBACK = {1: 340.0, 2: 290.0, 3: 165.0, 4: 165.0}


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
        if not re.search(
            r"feinwerkmechanikerhandwerk\s+und\s+metallbauerhandwerk", lower
        ):
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

    def published_exam_fee_rows(self) -> list[dict]:
        pdf_url = resolve_pdf_url_from_page(
            self,
            EXAM_FEES_PAGE_URL,
            href_substrings=("gebuehrenordnung", "gebührenordnung"),
            label="HWK Mittelfranken",
        )
        text = download_pdf_text(self, pdf_url, label="HWK Mittelfranken") if pdf_url else ""
        fees = parse_bavaria_b_iv_meister_fees(text) if text else {}
        if not fees:
            logger.warning("HWK Mittelfranken: using fallback Meister exam fees.")
            fees = EXAM_FEES_FALLBACK
        return part_fee_rows(
            self.chamber_slug,
            fees,
            source_url=EXAM_FEES_PAGE_URL,
        )
