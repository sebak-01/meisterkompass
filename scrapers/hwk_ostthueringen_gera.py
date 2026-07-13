"""Scraper for HWK Ostthüringen's ODAV Meister course catalogues."""

import logging
import re
from io import BytesIO

from .base import RawCourseOffer, ScrapeResult, build_course_title
from .hwk_bayern import (
    BavariaCatalogue,
    BavariaOdavScraper,
    course_id_from_url,
    parse_format_and_mode,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-gera.de"
INFO_URL = f"{BASE_URL}/artikel/wege-zum-meistertitel-5,19,211.html"
FEES_PAGE_URL = f"{BASE_URL}/artikel/rechtsgrundlagen-5,0,116.html"
FEES_PDF_URL = (
    f"{BASE_URL}/downloads/gebuehren-und-entgeltverzeichnis-2026-der-handwerkskammer-"
    "fuer-ostthueringen-5,1483.pdf"
)
TOPICS = (49, 46, 50, 71)  # I+II, III, III+IV, IV

LEHESTEN_BASE = "https://dachdeckerschule-lehesten.de"
LEHESTEN_OVERVIEW_URL = f"{LEHESTEN_BASE}/de-de/meisterlehrgaenge/"
LEHESTEN_LOCATION = {
    "street": "Friedrichsbruch 3",
    "zip_code": "07349",
    "city": "Lehesten",
}
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
PRICE_RE = re.compile(r"([\d.]+),(\d{2})\s*€")
DURATION_RE = re.compile(r"ca\.\s*([\d.]+)\s*Stunden", re.IGNORECASE)

# HWK catalogue entries for these trades are partner pointers without fees.
PARTNER_COURSE_IDS = {"112543", "119286", "112548"}
LEHESTEN_COURSES = (
    {
        "trade_name": "Dachdecker",
        "overview_url": f"{LEHESTEN_BASE}/de-de/meisterlehrgaenge/dachdeckermeister-teil-1-2/",
        "run_url": (
            f"{LEHESTEN_BASE}/de-de/meisterlehrgaenge/"
            "meistervorbereitungslehrgang-dachdecker-teil-1-und-teil-2-3174697/"
        ),
    },
    {
        "trade_name": "Klempner",
        "overview_url": f"{LEHESTEN_BASE}/de-de/meisterlehrgaenge/klempnermeister-teil-1-2/",
        "run_url": (
            f"{LEHESTEN_BASE}/de-de/meisterlehrgaenge/"
            "meistervorbereitungslehrgang-klempner-teil-1-und-teil-2-6582935/"
        ),
    },
    {
        "trade_name": "Zimmerer",
        "overview_url": f"{LEHESTEN_BASE}/de-de/meisterlehrgaenge/zimmerermeister-teil-1-2/",
        "run_url": (
            f"{LEHESTEN_BASE}/de-de/meisterlehrgaenge/"
            "meistervorbereitungslehrgang-zimmerer-teil-1-und-teil-2-5100981/"
        ),
    },
)


def _iso_from_groups(groups: tuple[str, str, str]) -> str:
    day, month, year = groups
    return f"{year}-{month}-{day}"


def _parse_lehesten_fee(text: str) -> float | None:
    match = re.search(r"Lehrgangskosten\s+([\d.]+),(\d{2})\s*€", text, re.IGNORECASE)
    if not match:
        match = PRICE_RE.search(text)
    if not match:
        return None
    return float(match.group(1).replace(".", "") + "." + match.group(2))


def _parse_lehesten_duration(text: str) -> int | None:
    match = DURATION_RE.search(text)
    return int(match.group(1).replace(".", "")) if match else None


class HwkOstthueringenGeraScraper(BavariaOdavScraper):
    chamber_slug = "hwk-ostthueringen-gera"
    chamber_name = "Handwerkskammer für Ostthüringen"
    chamber_region = "Thüringen"
    chamber_website = BASE_URL
    source_url = INFO_URL
    catalogue = BavariaCatalogue(
        base_url=BASE_URL,
        list_url=(
            f"{BASE_URL}/5,0,courselist.html?search-filter-template=0"
            "&search-topic=49&limit={limit}&offset={offset}"
        ),
        default_city="Gera",
        page_size=100,
        implicit_trade_parts=True,
    )
    EXAM_FEES_FALLBACK = {1: 335.0, 2: 220.0, 3: 190.0, 4: 190.0}

    PART_FEE_PATTERNS = {
        1: re.compile(r"5\.1\s+Teil\s+I\s+([\d.]+),(\d{2})\s*€"),
        2: re.compile(r"5\.2\s+Teil\s+II\s+([\d.]+),(\d{2})\s*€"),
        3: re.compile(r"5\.3\s+Teil\s+III[\s\S]{0,160}?([\d.]+),(\d{2})\s*€"),
        4: re.compile(r"5\.4\s+Teil\s+IV[\s\S]{0,120}?([\d.]+),(\d{2})\s*€"),
    }

    def fetch_raw_courses(self):
        unique: dict[str, dict] = {}
        for topic in TOPICS:
            offset = 0
            while True:
                url = (
                    f"{BASE_URL}/5,0,courselist.html?search-filter-template=0"
                    f"&search-topic={topic}&limit={self.catalogue.page_size}&offset={offset}"
                )
                soup = self.parse_html(url)
                if soup is None:
                    logger.warning("HWK Ostthüringen topic %d failed at offset %d.", topic, offset)
                    break
                total = self._parse_total(soup)
                for card in self._parse_page(soup):
                    key = course_id_from_url(card["detail_url"]) or card["detail_url"]
                    unique[key] = card
                offset += self.catalogue.page_size
                if offset >= total:
                    break

        offers = []
        for card in unique.values():
            try:
                offer = self._enrich(card)
            except Exception as exc:
                logger.warning("Could not parse Gera course %s: %s", card["detail_url"], exc)
                continue
            if offer:
                offers.extend(offer if isinstance(offer, list) else [offer])

        offers = [
            offer for offer in offers
            if course_id_from_url(offer.source_url) not in PARTNER_COURSE_IDS
        ]
        try:
            lehesten_offers = self._fetch_lehesten_courses()
            logger.info("HWK Ostthüringen/Lehesten: %d course offers.", len(lehesten_offers))
            offers.extend(lehesten_offers)
        except Exception:
            logger.exception("HWK Ostthüringen/Lehesten: provider failed — skipping.")

        logger.info("HWK Ostthüringen: parsed %d unique course offers.", len(offers))
        return offers

    def _fetch_lehesten_courses(self) -> list[RawCourseOffer]:
        offers: list[RawCourseOffer] = []
        for spec in LEHESTEN_COURSES:
            try:
                offer = self._parse_lehesten_course(spec)
            except Exception as exc:
                logger.warning("Could not parse Lehesten course %s: %s", spec["run_url"], exc)
                continue
            if offer:
                offers.append(offer)
        return offers

    def _parse_lehesten_course(self, spec: dict) -> RawCourseOffer | None:
        overview = self.parse_html(spec["overview_url"])
        run_page = self.parse_html(spec["run_url"])
        if overview is None or run_page is None:
            logger.warning("Could not fetch Lehesten pages for %s.", spec["trade_name"])
            return None

        overview_text = overview.get_text("\n", strip=True)
        run_text = run_page.get_text("\n", strip=True)
        dates = DATE_RE.findall(run_text)
        if len(dates) < 2:
            logger.warning("No scheduled run found for Lehesten %s.", spec["trade_name"])
            return None

        start_date = _iso_from_groups(dates[0])
        end_date = _iso_from_groups(dates[1])
        format_key, teaching_mode = parse_format_and_mode(run_text)
        return RawCourseOffer(
            title=build_course_title(spec["trade_name"], [1, 2]),
            trade_name=spec["trade_name"],
            parts=[1, 2],
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=_parse_lehesten_duration(overview_text),
            course_fee=_parse_lehesten_fee(overview_text),
            city=LEHESTEN_LOCATION["city"],
            street=LEHESTEN_LOCATION["street"],
            zip_code=LEHESTEN_LOCATION["zip_code"],
            availability="available",
            source_url=spec["run_url"],
            scraped_raw={
                "provider": "Dachdeckerschule Lehesten",
                "provider_overview": LEHESTEN_OVERVIEW_URL,
                "hwk_partner": True,
            },
        )

    def postprocess_offer(self, offer):
        # The detail's "Kurs" amount is a course fee. Exam fees come from the
        # chamber's Gebühren- und Entgeltverzeichnis PDF (see collect()).
        offer.exam_fee_scraped = None
        offer.exam_fee_qualifier = ""
        return offer

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        for part, pattern in HwkOstthueringenGeraScraper.PART_FEE_PATTERNS.items():
            match = pattern.search(text)
            if not match:
                continue
            fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees if len(fees) == 4 else {}

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Ostthüringen: pypdf not installed — using fallback exam fees.")
            return {}

        response = self.get(FEES_PDF_URL)
        if response is None:
            logger.warning("HWK Ostthüringen: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Ostthüringen: could not parse Meister exam fees from PDF.")
        return fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        fees = self._fetch_exam_fees_from_pdf() or self.EXAM_FEES_FALLBACK
        result.exam_fee_rows.extend(
            {
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "",
                "source_url": FEES_PAGE_URL,
            }
            for part, fee in fees.items()
        )
        return result
