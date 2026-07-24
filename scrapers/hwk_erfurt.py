"""Scraper for the curated HWK Erfurt Meister course overview."""

import logging

from bs4 import Tag

from .exam_fee_tariff import (
    download_pdf_text,
    parse_thuringia_meister_fees,
    part_fee_rows,
    resolve_pdf_url_from_page,
)
from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-erfurt.de"
OVERVIEW_URL = (
    f"{BASE_URL}/artikel/kurse-seminare-kurse-2026-jetzt-online-und-buchbar"
    "-4,779,1087.html#Meisterkurse"
)
FEES_PAGE_URL = f"{BASE_URL}/artikel/rechtsgrundlagen-4,0,116.html"
FEES_PDF_FALLBACK = (
    f"{BASE_URL}/downloads/gebuehren-und-entgeltverzeichnis-2026-der-handwerkskammer-erfurt-4,1483.pdf"
)
EXAM_FEES_FALLBACK = {1: 380.0, 2: 380.0, 3: 340.0, 4: 340.0}


class HwkErfurtScraper(BavariaOdavScraper):
    chamber_slug = "hwk-erfurt"
    chamber_name = "Handwerkskammer Erfurt"
    chamber_region = "Thüringen"
    chamber_website = BASE_URL
    source_url = OVERVIEW_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=OVERVIEW_URL,
        default_city="Erfurt",
    )

    def fetch_raw_courses(self):
        soup = self.parse_html(OVERVIEW_URL)
        if soup is None:
            logger.error("Could not fetch HWK Erfurt Meister course overview.")
            return []

        cards = self._parse_page(soup)
        offers = []
        for card in cards:
            try:
                offer = self._enrich(card)
            except Exception as exc:
                logger.warning("Could not parse Erfurt course %s: %s", card["detail_url"], exc)
                continue
            if offer:
                offers.extend(offer if isinstance(offer, list) else [offer])
        logger.info("HWK Erfurt: parsed %d course offers.", len(offers))
        return offers

    def _parse_card(self, link: Tag, detail_url: str | None = None):
        card = super()._parse_card(link, detail_url)
        if card is not None:
            return card

        # The one Erfurt title that omits the word "Meister" is still under
        # the explicit "Meisterkurs Teil I und II" heading.
        title = link.get_text(" ", strip=True)
        if "friseur-handwerk" not in title.lower():
            return None
        # Replace only the link's display content; its href and surrounding
        # listing card remain intact for the shared parser.
        link.clear()
        link.append(f"Meisterkurs Friseur {title}")
        card = super()._parse_card(link, detail_url)
        if card:
            card["raw_title"] = title
            card["trade_name"] = "Friseur"
        return card

    def postprocess_offer(self, offer):
        # Detail pages label only the Lehrgang fee; chamber exam fees are not
        # stated there and must not be inferred from unrelated page prose.
        offer.exam_fee_scraped = None
        offer.exam_fee_qualifier = ""
        return offer

    def published_exam_fee_rows(self) -> list[dict]:
        pdf_url = resolve_pdf_url_from_page(
            self,
            FEES_PAGE_URL,
            fallback_url=FEES_PDF_FALLBACK,
            href_substrings=("gebuehren", "entgelt"),
            label="HWK Erfurt",
        ) or FEES_PDF_FALLBACK
        text = download_pdf_text(self, pdf_url, label="HWK Erfurt")
        fees = parse_thuringia_meister_fees(text) if text else {}
        if not fees:
            logger.warning("HWK Erfurt: using fallback Meister exam fees.")
            fees = EXAM_FEES_FALLBACK
        return part_fee_rows(
            self.chamber_slug,
            fees,
            source_url=FEES_PAGE_URL,
        )
