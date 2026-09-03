"""Courses from the Handwerkskammer für Schwaben."""

import logging

from .base import RawCourseOffer
from .exam_fee_tariff import (
    download_pdf_text,
    parse_bavaria_b_iv_meister_fees,
    part_fee_rows,
    resolve_pdf_url_from_page,
)
from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper

logger = logging.getLogger(__name__)

EXAM_FEES_PAGE_URL = "https://www.hwk-schwaben.de/artikel/gebuehrenordnung-3711,0,85.html"
EXAM_FEES_FALLBACK = {1: 270.0, 2: 230.0, 3: 175.0, 4: 175.0}


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
        return super().postprocess_offer(offer)

    def published_exam_fee_rows(self) -> list[dict]:
        pdf_url = resolve_pdf_url_from_page(
            self,
            EXAM_FEES_PAGE_URL,
            href_substrings=("gebuehrenordnung", "gebührenordnung"),
            label="HWK Schwaben",
        )
        text = download_pdf_text(self, pdf_url, label="HWK Schwaben") if pdf_url else ""
        fees = parse_bavaria_b_iv_meister_fees(text) if text else {}
        if not fees:
            logger.warning("HWK Schwaben: using fallback Meister exam fees.")
            fees = EXAM_FEES_FALLBACK
        return part_fee_rows(
            self.chamber_slug,
            fees,
            source_url=EXAM_FEES_PAGE_URL,
        )
