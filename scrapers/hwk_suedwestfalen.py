"""Scraper for BBZ Arnsberg Meister courses (HWK Südwestfalen)."""

from __future__ import annotations

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title, normalize_trade
from .hwk_bayern import parse_parts, parse_trade

logger = logging.getLogger(__name__)

BBZ_BASE = "https://www.bbz-arnsberg.de"
CHAMBER_URL = "https://www.hwk-swf.de"
LISTING_URL = f"{BBZ_BASE}/kurse"
MEISTER_HUB_URL = f"{BBZ_BASE}/meisterkurse"
EXAM_FEES_PAGE_URL = f"{CHAMBER_URL}/artikel/rechtsgrundlagen-38,0,100.html"
FEES_PDF_URL = (
    f"{CHAMBER_URL}/downloads/gebuehrentarif-der-handwerkskammer-suedwestfalen-38,1087.pdf"
)
GENERIC_EXAM_FEES = {
    1: {"fee": 380.0, "fee_max": 2300.0},
    2: {"fee": 250.0, "fee_max": 400.0},
    3: {"fee": 250.0, "fee_max": 400.0},
    4: {"fee": 250.0, "fee_max": 400.0},
}
GENERIC_COMBO_EXAM_FEE = {"fee": 580.0, "fee_max": 2500.0}

PRICE_RE = re.compile(r"([\d.]+),(\d{2})\s*€")
DURATION_RE = re.compile(r"([\d.]+)\s+Unterrichtsstunden", re.IGNORECASE)
DATE_RANGE_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s*[—–\-]+\s*(\d{2})\.(\d{2})\.(\d{4})"
)
EXAM_FEE_BRACKET_RE = re.compile(
    r"\(zzgl\.\s*Prüfungsgebühr\s*([\d.]+),(\d{2})\s*€\s*\)",
    re.IGNORECASE,
)
EXAM_FEE_OVERVIEW_RE = re.compile(
    r"Prüfungsgebühr:\s*([\d.]+)\s*EUR",
    re.IGNORECASE,
)
COURSE_LINK_RE = re.compile(
    r"/kurse/(meisterkurs-|gepruefte-|ausbildung-der-ausbilder)[^\"'\s#]+",
    re.IGNORECASE,
)

DEFAULT_LOCATION = {
    "street": "Im Hülsenfeld 42",
    "zip_code": "59755",
    "city": "Arnsberg",
}

SWF_TRADE_ALIASES = {
    "elektrotechnik": "Elektrotechniker",
    "kfz": "Kfz.-Techniker",
    "kraftfahrzeugtechniker": "Kfz.-Techniker",
    "installateur": "Installateur- und Heizungsbauer",
    "heizungsbauer": "Installateur- und Heizungsbauer",
    "maler": "Maler und Lackierer",
    "lackierer": "Maler und Lackierer",
    "fahrzeuglackierer": "Fahrzeuglackierer",
    "maurer": "Maurer und Betonbauer",
    "betonbauer": "Maurer und Betonbauer",
    "feinwerkmechaniker/metallbauer": "Metallbauer",
    "feinwerkmechaniker": "Feinwerkmechaniker",
    "metallbauer": "Metallbauer",
    "tischler": "Tischler",
    "zimmerer": "Zimmerer",
    "stuckateur": "Stuckateur",
    "fliesenleger": "Fliesen-, Platten- und Mosaikleger",
    "fliesen-": "Fliesen-, Platten- und Mosaikleger",
    "friseur": "Friseur",
}

KNOWN_MEISTER_COURSE_PATHS = (
    "meisterkurs-elektrotechnik-vollzeit",
    "meisterkurs-elektrotechnik-teilzeit",
    "meisterkurs-maurer-und-betonbauer",
    "meisterkurs-maler-und-lackierer",
    "meisterkurs-maler-und-lackierer-fahrzeuglackierer",
    "meisterkurs-feinwerkmechaniker-metallbauer",
    "meisterkurs-feinwerkmechaniker-metallbauer-2",
    "meisterkurs-tischler",
    "meisterkurs-zimmerer",
    "meisterkurs-stuckateure",
    "meisterkurs-fliesen-platten-und-mosaikleger",
    "meisterkurs-friseure",
    "meisterkurs-installateure-und-heizungsbauer-vollzeit",
    "meisterkurs-installateure-und-heizungsbauer-teilzeit",
    "meisterkurs-kraftfahrzeugtechniker-vollzeit",
    "meisterkurs-kraftfahrzeugtechniker-teilzeit",
    "meisterkurs-kraftfahrzeugtechniker-nfz-vollzeit",
    "meisterkurs-kraftfahrzeugtechniker-blockunterricht",
    "meisterkurs-kraftfahrzeugtechniker-teil-ii-blockunterricht",
    "gepruefte-r-fachfrau-fachmann-fuer-kaufmaennische-betriebsfuehrung-hwo",
    "ausbildung-der-ausbilder-nach-aevo",
)


def parse_suedwestfalen_title(title: str) -> tuple[list[int], str | None]:
    cleaned = re.sub(r"\*+", "", title).strip()
    parts = parse_parts(cleaned, implicit_trade_parts=True)
    if not parts:
        lower = cleaned.lower()
        if "betriebsführung" in lower or "betriebsfuehrung" in lower:
            parts = [3]
        elif "teil iii" in lower:
            parts = [3]
        elif "teil iv" in lower or "aevo" in lower or "ausbilder" in lower:
            parts = [4]

    if not parts:
        return [], None

    trade = parse_trade(cleaned, parts)
    if not trade:
        lower = cleaned.lower()
        for source, canonical in SWF_TRADE_ALIASES.items():
            if source in lower:
                trade = canonical
                break
    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_course(title: str, url: str = "") -> bool:
    lower = f"{title} {url}".lower()
    if any(value in lower for value in ("industriemeister", "infoabend", "infoveranstaltung")):
        return False
    if "meisterkurs" in lower or "meisterschule" in lower:
        return True
    if "betriebsführung" in lower or "betriebsfuehrung" in lower:
        return True
    if "ausbilder" in lower and ("aevo" in lower or "teil iv" in lower):
        return True
    return False


def title_from_course_url(url: str) -> str:
    """Turn ``.../kurse/meisterkurs-elektrotechnik-vollzeit`` into a parseable title."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").strip()


def resolve_course_title(soup: BeautifulSoup, url: str) -> str:
    """
    BBZ course pages use a generic ``<h1>Kursangebot</h1>``; the real course
    name lives in an ``h2``/``h3``, ``og:title``, or the document title.
    """
    candidates: list[str] = []
    for selector in ("h1", "h2", "h3", "h4"):
        for tag in soup.select(selector):
            text = tag.get_text(" ", strip=True)
            if text:
                candidates.append(text)
    og = soup.select_one("meta[property='og:title']")
    if og and og.get("content"):
        candidates.append(og["content"].strip())
    if soup.title:
        candidates.append(soup.title.get_text(" ", strip=True))
    candidates.append(title_from_course_url(url))

    for candidate in candidates:
        if not _is_meister_course(candidate, ""):
            continue
        parts, _trade = parse_suedwestfalen_title(candidate)
        if parts:
            return candidate
    # Last resort: slug text (even if parts cannot be resolved yet).
    return title_from_course_url(url)


class HwkSuedwestfalenScraper(BaseScraper):
    chamber_slug = "hwk-suedwestfalen"
    chamber_name = "Handwerkskammer Südwestfalen"
    chamber_region = "Nordrhein-Westfalen"
    chamber_website = CHAMBER_URL
    source_url = MEISTER_HUB_URL

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        course_urls = self._discover_course_urls()
        offers: list[RawCourseOffer] = []
        fetched = 0
        for url in sorted(course_urls):
            soup = self.parse_html(url)
            if soup is None:
                # Stale seed slugs 404; discovery from the listing usually heals this.
                logger.debug("Could not fetch Südwestfalen course %s.", url)
                continue
            fetched += 1
            try:
                offers.extend(self._parse_course_page(soup, url))
            except Exception as exc:
                logger.warning("Could not parse Südwestfalen course %s: %s", url, exc)
        logger.info(
            "HWK Südwestfalen: parsed %d offers from %d/%d course pages.",
            len(offers),
            fetched,
            len(course_urls),
        )
        return offers

    def _discover_course_urls(self) -> set[str]:
        """Prefer live listing links; fall back to known slugs if blocked."""
        urls: set[str] = set()
        for page_url in (LISTING_URL, MEISTER_HUB_URL):
            soup = self.parse_html(page_url)
            if soup is None:
                continue
            urls.update(self._course_urls_from_soup(soup))
            for link in self._discover_trade_pages(soup):
                trade_soup = self.parse_html(link)
                if trade_soup is not None:
                    urls.update(self._course_urls_from_soup(trade_soup))
        if not urls:
            logger.warning(
                "HWK Südwestfalen: listing discovery failed — using known course paths."
            )
            urls = {f"{BBZ_BASE}/kurse/{slug}" for slug in KNOWN_MEISTER_COURSE_PATHS}
        else:
            # Keep known paths as soft extras so renamed hubs still catch new courses.
            urls.update(f"{BBZ_BASE}/kurse/{slug}" for slug in KNOWN_MEISTER_COURSE_PATHS)
        return urls

    @staticmethod
    def _course_urls_from_soup(soup: BeautifulSoup) -> set[str]:
        urls: set[str] = set()
        for link in soup.select("a[href*='/kurse/']"):
            href = urljoin(BBZ_BASE, link.get("href", ""))
            path = href.split("?", 1)[0].rstrip("/")
            slug = path.rsplit("/", 1)[-1]
            title = link.get_text(" ", strip=True)
            if not _is_meister_course(title, slug):
                continue
            if slug.startswith(("meisterkurs-", "gepruefte-", "ausbildung-der-ausbilder")):
                urls.add(path)
        return urls

    @staticmethod
    def _discover_trade_pages(soup: BeautifulSoup) -> list[str]:
        pages: list[str] = []
        for link in soup.select("a[href*='/meisterkurse/']"):
            href = urljoin(BBZ_BASE, link.get("href", ""))
            if href.rstrip("/") != MEISTER_HUB_URL.rstrip("/"):
                pages.append(href)
        return pages

    def _parse_course_page(self, soup: BeautifulSoup, url: str) -> list[RawCourseOffer]:
        title = resolve_course_title(soup, url)
        if not title or not _is_meister_course(title, url):
            return []

        parts, trade = parse_suedwestfalen_title(title)
        if not parts:
            # Slug-derived titles usually still parse; keep a defensive fallback.
            parts, trade = parse_suedwestfalen_title(title_from_course_url(url))
        if not parts:
            return []

        page_text = soup.get_text("\n", strip=True)
        duration_match = DURATION_RE.search(page_text)
        duration = int(duration_match.group(1).replace(".", "")) if duration_match else None
        course_fee, exam_fee = self._parse_fees(page_text)
        lower = f"{title} {url}".lower()
        format_key = "full_time" if "vollzeit" in lower else "part_time"
        teaching_mode = "presence"

        runs = self._parse_runs(soup, page_text)
        if not runs:
            return [RawCourseOffer(
                title=build_course_title(trade, parts),
                trade_name=trade,
                parts=parts,
                format_key=format_key,
                teaching_mode=teaching_mode,
                start_date=None,
                end_date=None,
                duration_hours=duration,
                course_fee=course_fee,
                exam_fee_scraped=exam_fee,
                city=DEFAULT_LOCATION["city"],
                street=DEFAULT_LOCATION["street"],
                zip_code=DEFAULT_LOCATION["zip_code"],
                availability="unknown",
                source_url=url,
                scraped_raw={"title": title, "note": "Keine Termine auf der Kursseite"},
            )]

        offers: list[RawCourseOffer] = []
        seen: set[tuple[str, str]] = set()
        for index, (start_date, end_date, availability) in enumerate(runs):
            key = (start_date, end_date)
            if key in seen:
                continue
            seen.add(key)
            offers.append(RawCourseOffer(
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
                source_url=f"{url}#termin-{index + 1}",
                scraped_raw={"title": title, "run_label": f"{start_date} - {end_date}"},
            ))
        return offers

    @staticmethod
    def _parse_fees(text: str) -> tuple[float | None, float | None]:
        course_fee = None
        exam_fee = None

        bracket = EXAM_FEE_BRACKET_RE.search(text)
        if bracket:
            exam_fee = float(bracket.group(1).replace(".", "") + "." + bracket.group(2))

        overview = EXAM_FEE_OVERVIEW_RE.search(text)
        if overview:
            exam_fee = float(overview.group(1).replace(".", ""))

        price_match = PRICE_RE.search(text)
        if price_match:
            course_fee = float(
                price_match.group(1).replace(".", "") + "." + price_match.group(2)
            )
        return course_fee, exam_fee

    @staticmethod
    def _availability_from_block(block: str) -> str:
        lower = block.lower()
        if "warteliste" in lower:
            return "waitlist"
        if "ausgebucht" in lower or "keine plätze" in lower:
            return "full"
        if any(word in lower for word in ("freie plätze", "anmelden", "buchbar", "verfügbar")):
            return "available"
        return "unknown"

    @classmethod
    def _parse_runs(cls, soup: BeautifulSoup, page_text: str) -> list[tuple[str, str, str]]:
        runs: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()

        for heading in soup.select("h4"):
            text = heading.get_text(" ", strip=True)
            match = DATE_RANGE_RE.search(text)
            if not match:
                continue
            start = f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
            end = f"{match.group(6)}-{match.group(5)}-{match.group(4)}"
            if int(start[:4]) < 2020 or int(start[:4]) > 2035:
                continue
            block = text
            sibling = heading.find_next_sibling()
            if sibling is not None:
                block = f"{text}\n{sibling.get_text(' ', strip=True)}"
            availability = cls._availability_from_block(block)
            key = (start, end)
            if key not in seen:
                seen.add(key)
                runs.append((start, end, availability))

        if runs:
            return runs

        matches = list(DATE_RANGE_RE.finditer(page_text))
        for index, match in enumerate(matches):
            start = f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
            end = f"{match.group(6)}-{match.group(5)}-{match.group(4)}"
            if int(start[:4]) < 2020 or int(start[:4]) > 2035:
                continue
            block_end = matches[index + 1].start() if index + 1 < len(matches) else match.end() + 120
            block = page_text[match.start():block_end]
            availability = cls._availability_from_block(block)
            key = (start, end)
            if key not in seen:
                seen.add(key)
                runs.append((start, end, availability))
        return runs

    @staticmethod
    def _amount_pair(match: re.Match) -> dict[str, float]:
        return {
            "fee": float(match.group(1).replace(".", "") + "." + match.group(2)),
            "fee_max": float(match.group(3).replace(".", "") + "." + match.group(4)),
        }

    @classmethod
    def parse_meister_exam_fees(
        cls, text: str
    ) -> tuple[dict[int, dict[str, float]], dict[str, float] | None]:
        """Parse Gebührentarif Meisterprüfung ranges (Teil I / I+II / theoretical)."""
        fees: dict[int, dict[str, float]] = {}
        combo: dict[str, float] | None = None
        section = re.search(
            r"4\.\s*Meisterprüfung(.*?)(?:Für Wiederholungsprüfungen|V\.\s*Sonstige)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        chunk = section.group(1) if section else text

        part_i = re.search(
            r"Teil I\s+([\d.]+),(\d{2})\s*[–\-]\s*([\d.]+),(\d{2})",
            chunk,
            re.IGNORECASE,
        )
        if part_i:
            fees[1] = cls._amount_pair(part_i)

        combo_match = re.search(
            r"Teile I und II\s+([\d.]+),(\d{2})\s*[–\-]\s*([\d.]+),(\d{2})",
            chunk,
            re.IGNORECASE,
        )
        if combo_match:
            combo = cls._amount_pair(combo_match)

        theoretical = re.search(
            r"ein theoretischer Teil\s+([\d.]+),(\d{2})\s*[–\-]\s*([\d.]+),(\d{2})",
            chunk,
            re.IGNORECASE,
        )
        if theoretical:
            values = cls._amount_pair(theoretical)
            for part in (2, 3, 4):
                fees[part] = dict(values)
        return fees, combo

    def _resolve_exam_fees_pdf_url(self) -> str:
        soup = self.parse_html(EXAM_FEES_PAGE_URL)
        if soup is None:
            return FEES_PDF_URL
        for link in soup.select("a[href*='gebuehrentarif'], a[href*='gebuehr']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf") and "gebuehrentarif" in href.lower():
                return urljoin(CHAMBER_URL, href)
        for link in soup.select("a[href*='gebuehr'], a[href*='Gebuehr']"):
            href = link.get("href", "")
            if href.lower().endswith(".pdf"):
                return urljoin(CHAMBER_URL, href)
        return FEES_PDF_URL

    def _fetch_exam_fees_from_pdf(
        self,
    ) -> tuple[dict[int, dict[str, float]], dict[str, float] | None] | None:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Südwestfalen: pypdf not installed — using fallback exam fees.")
            return None

        pdf_url = self._resolve_exam_fees_pdf_url()
        response = self.get(pdf_url)
        if response is None:
            logger.warning("HWK Südwestfalen: could not fetch exam-fee PDF.")
            return None

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees, combo = self.parse_meister_exam_fees(text)
        if not fees:
            logger.warning("HWK Südwestfalen: could not parse exam fees from PDF.")
            return None
        return fees, combo

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        fetched = self._fetch_exam_fees_from_pdf()
        if fetched:
            fees, combo = fetched
        else:
            fees, combo = GENERIC_EXAM_FEES, GENERIC_COMBO_EXAM_FEE
        if combo is None:
            combo = GENERIC_COMBO_EXAM_FEE

        rows: list[dict] = [
            {
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": values["fee"],
                "fee_max": values.get("fee_max"),
                "qualifier": "",
                "source_url": EXAM_FEES_PAGE_URL,
            }
            for part, values in fees.items()
        ]
        rows.append({
            "chamber_slug": self.chamber_slug,
            "trade_slug": None,
            "parts": [1, 2],
            "fee": combo["fee"],
            "fee_max": combo.get("fee_max"),
            "qualifier": "",
            "source_url": EXAM_FEES_PAGE_URL,
        })
        return rows
