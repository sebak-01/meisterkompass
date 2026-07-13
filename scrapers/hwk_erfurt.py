"""Scraper for the curated HWK Erfurt Meister course overview."""

import logging

from bs4 import Tag

from .hwk_bayern import BavariaCatalogue, BavariaOdavScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-erfurt.de"
OVERVIEW_URL = (
    f"{BASE_URL}/artikel/kurse-seminare-kurse-2026-jetzt-online-und-buchbar"
    "-4,779,1087.html#Meisterkurse"
)


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
