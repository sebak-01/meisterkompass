"""Scraper for HWK Dortmund's WooCommerce Events Meister courses."""

from __future__ import annotations

import logging
import re
import json
from io import BytesIO
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title, normalize_trade
from .hwk_bayern import parse_parts, parse_trade

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwk-do.de"
SOURCE_URL = f"{BASE_URL}/meister/meisterkurse/"
EXAM_FEES_PAGE_URL = f"{BASE_URL}/meister/"
FEES_PDF_URL = f"{BASE_URL}/wp-content/uploads/Gebuehrenverzeichnis.pdf"
PRODUCT_CAT_API = f"{BASE_URL}/wp-json/wp/v2/product_cat"
PRODUCT_API = f"{BASE_URL}/wp-json/wp/v2/product"
GENERIC_EXAM_FEES = {1: 400.0, 2: 320.0, 3: 240.0, 4: 220.0}

DISPLAY_PRICE_RE = re.compile(r'"display_price":(\d+)')
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
DURATION_RE = re.compile(
    r"([\d.]+)\s+(?:Unterrichtseinheiten|Unterrichtsstunden|UE|Std\.)",
    re.IGNORECASE,
)
BUE_PRICES_RE = re.compile(r'"bue_additional_prices"\s*:\s*(\[[^\]]+\])')
EXAM_FEE_TABLE_RE = re.compile(
    r"Pr[üu]fungsgeb[üu]hr\s*:\s*<\/strong><\/td>\s*<td>\s*([\d.]+),(\d{2})",
    re.IGNORECASE,
)

DEFAULT_LOCATION = {
    "street": "Schützenstraße 32-34",
    "zip_code": "44147",
    "city": "Dortmund",
}

EXCLUDE_TITLE_RE = re.compile(
    r"infoveranstaltung|industriemeister|vorkurs zum augenoptikermeister",
    re.IGNORECASE,
)


def parse_dortmund_title(title: str) -> tuple[list[int], str | None]:
    cleaned = re.sub(r"<[^>]+>", " ", title)
    cleaned = re.sub(r"\*+", "", cleaned).strip()
    parts = parse_parts(cleaned, implicit_trade_parts=True)
    if not parts:
        if "aevo" in cleaned.lower() or "ausbilder" in cleaned.lower():
            parts = [4]
        elif "teil iii" in cleaned.lower() or "betriebsführung" in cleaned.lower():
            parts = [3]

    if not parts:
        return [], None

    trade = parse_trade(cleaned, parts)
    if not trade:
        trade = parse_trade(cleaned.replace("Teilzeitlehrgang", "Meister"), parts)
    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


class HwkDortmundScraper(BaseScraper):
    chamber_slug = "hwk-dortmund"
    chamber_name = "Handwerkskammer Dortmund"
    chamber_region = "Nordrhein-Westfalen"
    chamber_website = BASE_URL
    source_url = SOURCE_URL
    request_delay = 0.3

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        product_links = self._discover_product_links()
        offers: list[RawCourseOffer] = []
        for link in product_links:
            response = self.get(link)
            if response is None:
                logger.warning("Could not fetch Dortmund event %s.", link)
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            try:
                offer = self._parse_event_page(soup, link, response.text)
            except Exception as exc:
                logger.warning("Could not parse Dortmund event %s: %s", link, exc)
                continue
            if offer:
                offers.append(offer)
        logger.info("HWK Dortmund: parsed %d course offers.", len(offers))
        return offers

    def _discover_product_links(self) -> list[str]:
        response = self.get(f"{PRODUCT_CAT_API}?search=Meisterkurse&per_page=100")
        if response is None:
            logger.error("Could not fetch Dortmund product categories.")
            return []

        links: dict[str, str] = {}
        for category in response.json():
            name = category.get("name", "")
            if not name.startswith("Meisterkurse/"):
                continue
            cat_id = category["id"]
            page = 1
            while True:
                products_response = self.get(
                    f"{PRODUCT_API}?product_cat={cat_id}&per_page=100&page={page}"
                )
                if products_response is None:
                    break
                products = products_response.json()
                if not products:
                    break
                for product in products:
                    title = product.get("title", {}).get("rendered", "")
                    if EXCLUDE_TITLE_RE.search(title):
                        continue
                    link = product.get("link")
                    if link:
                        links[link] = title
                if len(products) < 100:
                    break
                page += 1
        return list(links.keys())

    def _parse_event_page(
        self, soup: BeautifulSoup, url: str, html: str
    ) -> RawCourseOffer | None:
        h1 = soup.select_one("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
        if not title or EXCLUDE_TITLE_RE.search(title):
            return None

        parts, trade = parse_dortmund_title(title)
        if not parts:
            return None

        page_text = soup.get_text("\n", strip=True)
        duration_match = DURATION_RE.search(page_text) or DURATION_RE.search(html)
        duration = int(duration_match.group(1).replace(".", "")) if duration_match else None
        price_match = DISPLAY_PRICE_RE.search(html)
        course_fee = float(price_match.group(1)) if price_match else None
        if course_fee == 0:
            course_fee = None
        exam_fee = self._parse_exam_fee(html)

        dates = DATE_RE.findall(page_text)
        start_date = end_date = None
        if len(dates) >= 2:
            start = dates[0]
            end = dates[1]
            start_date = f"{start[2]}-{start[1]}-{start[0]}"
            end_date = f"{end[2]}-{end[1]}-{end[0]}"
        elif len(dates) == 1:
            start = dates[0]
            start_date = f"{start[2]}-{start[1]}-{start[0]}"

        lower = f"{title} {page_text}".lower()
        format_key = "full_time" if "vollzeit" in lower else "part_time"
        if "online" in lower and "präsenz" not in lower:
            teaching_mode = "online"
        elif "hybrid" in lower:
            teaching_mode = "hybrid"
        else:
            teaching_mode = "presence"

        availability = "unknown"
        if "ausgebucht" in lower or "keine plätze" in lower:
            availability = "full"
        elif "interessentenliste" in lower or "warteliste" in lower:
            availability = "waitlist"
        elif "freie plätze" in lower:
            availability = "available"

        return RawCourseOffer(
            title=build_course_title(trade, parts),
            trade_name=trade,
            parts=parts,
            format_key=format_key,
            teaching_mode=teaching_mode,
            start_date=start_date,
            end_date=end_date,
            duration_hours=duration,
            course_fee=course_fee,
            exam_fee_scraped=exam_fee,
            city=DEFAULT_LOCATION["city"],
            street=DEFAULT_LOCATION["street"],
            zip_code=DEFAULT_LOCATION["zip_code"],
            availability=availability,
            source_url=url,
            scraped_raw={"title": title, "exam_fee_source": "course_page" if exam_fee else "tariff"},
        )

    @staticmethod
    def _parse_exam_fee(html: str) -> float | None:
        prices_match = BUE_PRICES_RE.search(html)
        if prices_match:
            try:
                for row in json.loads(prices_match.group(1)):
                    label = row.get("bezeichnung", "")
                    if "prüfungsgebühr" in label.lower():
                        return float(row["gebuehr"])
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        table_match = EXAM_FEE_TABLE_RE.search(html)
        if table_match:
            return float(
                table_match.group(1).replace(".", "") + "." + table_match.group(2)
            )
        return None

    @staticmethod
    def parse_generic_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        for part, roman in ((1, "I"), (2, "II"), (3, "III"), (4, "IV")):
            match = re.search(
                rf"Teil\s+{roman}.*?([\d.]+),(\d{{2}})\s*€",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def _resolve_exam_fees_pdf_url(self) -> str:
        soup = self.parse_html(EXAM_FEES_PAGE_URL)
        if soup is None:
            return FEES_PDF_URL
        for link in soup.select("a[href*='gebuehr'], a[href*='Gebuehr']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf"):
                return urljoin(BASE_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(self) -> dict[int, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Dortmund: pypdf not installed — using fallback exam fees.")
            return {}

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Dortmund: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_generic_exam_fees(text)
        if not fees:
            logger.warning("HWK Dortmund: could not parse exam fees from PDF.")
        return fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        fees = self._fetch_exam_fees_from_pdf() or GENERIC_EXAM_FEES
        return [
            {
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "",
                "source_url": EXAM_FEES_PAGE_URL,
            }
            for part, fee in fees.items()
        ]
