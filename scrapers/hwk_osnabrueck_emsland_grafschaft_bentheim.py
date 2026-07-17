"""Scraper for BTZ Osnabrück Meister courses (HWK Osnabrück-Emsland-Grafschaft Bentheim)."""

import logging
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title, normalize_trade
from .hwk_bayern import parse_parts, parse_trade

logger = logging.getLogger(__name__)

BASE_URL = "https://www.btz-osnabrueck.de"
OVERVIEW_URL = f"{BASE_URL}/meisterkurse/"
EXAM_FEES_PAGE_URL = "https://www.hwk-osnabrueck.de/der-weg-zum-meister/"
GENERIC_EXAM_FEES = {1: 450.0, 2: 380.0, 3: 260.0, 4: 300.0}

DATE_RE = re.compile(
    r"^(\d{2})\.(\d{2})\.(\d{4})\s*[—–-]\s*(\d{2})\.(\d{2})\.(\d{4})"
)
PRICE_RE = re.compile(
    r"\(ohne Aufstiegs-BAföG:\s*([\d.]+),(\d{2})\s*€\)",
    re.IGNORECASE,
)
COURSE_NO_RE = re.compile(r"Kursnummer\s+(\d+)", re.IGNORECASE)
DEFAULT_LOCATION = {
    "street": "Bramscher Straße 134-136",
    "zip_code": "49088",
    "city": "Osnabrück",
}

OSN_TRADE_ALIASES = {
    "tischler": "Tischler",
    "dachdecker": "Dachdecker",
    "maurer": "Maurer und Betonbauer",
    "betonbauer": "Maurer und Betonbauer",
    "zimmerer": "Zimmerer",
    "installateur": "Installateur- und Heizungsbauer",
    "heizungsbauer": "Installateur- und Heizungsbauer",
    "elektrotechniker": "Elektrotechniker",
    "kfz": "Kfz.-Techniker",
    "kraftfahrzeug": "Kfz.-Techniker",
    "maler": "Maler und Lackierer",
    "lackierer": "Maler und Lackierer",
    "metallbauer": "Metallbauer",
    "friseur": "Friseur",
    "bäcker": "Bäcker",
    "baecker": "Bäcker",
    "konditor": "Konditor",
    "fliesen": "Fliesen-, Platten- und Mosaikleger",
    "zimmer": "Zimmerer",
}


def _canonical_seminar_url(href: str) -> str:
    split = urlsplit(urljoin(BASE_URL, href))
    path = split.path.rstrip("/") + "/"
    return urlunsplit((split.scheme, split.netloc, path, "", ""))


def parse_osn_title(title: str) -> tuple[list[int], str | None]:
    cleaned = re.sub(r"\*+", "", title).strip()
    parts = parse_parts(cleaned, implicit_trade_parts=True)
    if not parts:
        if re.search(r"meisterkurs\s+teil\s+iii", cleaned, re.IGNORECASE):
            parts = [3]
        elif re.search(r"meisterkurs\s+teil\s+iv", cleaned, re.IGNORECASE):
            parts = [4]

    if not parts:
        return [], None

    trade = parse_trade(cleaned, parts)
    if not trade:
        lower = cleaned.lower()
        for source, canonical in OSN_TRADE_ALIASES.items():
            if re.search(rf"\b{re.escape(source)}\b", lower):
                trade = canonical
                break

    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_link(title: str) -> bool:
    lower = title.lower()
    if any(value in lower for value in ("infoabend", "informationsveranstaltung", "meisterbonus")):
        return False
    return "meister" in lower and "industriemeister" not in lower


def _availability(text: str) -> str:
    lower = text.lower()
    if "keine plätze mehr frei" in lower or "ausgebucht" in lower:
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "freie plätze" in lower:
        return "available"
    return "unknown"


def _location(text: str, teaching_mode: str) -> tuple[str, str, str]:
    if teaching_mode == "online":
        return "", "", "Online"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if line.lower() == "ort":
            block = lines[index + 1:]
            street = ""
            zip_code = ""
            city = ""
            for block_index, block_line in enumerate(block):
                zip_match = re.match(r"(\d{5})\s+(.+)", block_line)
                if zip_match:
                    zip_code = zip_match.group(1)
                    city = zip_match.group(2).strip()
                    if block_index > 0:
                        candidate = block[block_index - 1]
                        if re.search(r"\d", candidate):
                            street = candidate
                    return street, zip_code, city
            break
    return DEFAULT_LOCATION["street"], DEFAULT_LOCATION["zip_code"], DEFAULT_LOCATION["city"]


def _run_row(heading: Tag) -> Tag | None:
    node: Tag | None = heading
    for _ in range(8):
        node = node.parent if node is not None else None
        if node is None or not isinstance(node, Tag):
            return None
        if node.name == "div" and "row" in (node.get("class") or []):
            return node
    return None


class HwkOsnabrueckEmslandGrafschaftBentheimScraper(BaseScraper):
    chamber_slug = "hwk-osnabrueck-emsland-grafschaft-bentheim"
    chamber_name = "Handwerkskammer Osnabrück-Emsland-Grafschaft Bentheim"
    chamber_region = "Niedersachsen"
    chamber_website = "https://www.hwk-osnabrueck.de"
    source_url = OVERVIEW_URL
    request_delay = 0.5

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        soup = self.parse_html(OVERVIEW_URL)
        if soup is None:
            logger.error("Could not fetch BTZ Osnabrück Meister course overview.")
            return []

        courses = self._discover(soup)
        offers: list[RawCourseOffer] = []
        for title, url in courses:
            detail = self.parse_html(url)
            if detail is None:
                logger.warning("Could not fetch Osnabrück course %s.", url)
                continue
            try:
                parsed = self._parse_course(detail, title, url)
            except Exception as exc:
                logger.warning("Could not parse Osnabrück course %s: %s", url, exc)
                continue
            offers.extend(parsed)
        logger.info(
            "HWK Osnabrück-Emsland-Grafschaft Bentheim: parsed %d offers from %d courses.",
            len(offers),
            len(courses),
        )
        return offers

    @staticmethod
    def _discover(soup: BeautifulSoup) -> list[tuple[str, str]]:
        found: dict[str, str] = {}
        for link in soup.select('a[href^="/seminar/"]'):
            title = " ".join(link.get_text(" ", strip=True).split())
            href = link.get("href", "")
            if not href or not _is_meister_link(title):
                continue
            found.setdefault(_canonical_seminar_url(href), title)
        return [(title, url) for url, title in found.items()]

    def _parse_course(
        self, soup: BeautifulSoup, discovery_title: str, url: str
    ) -> list[RawCourseOffer]:
        main = soup.select_one("main") or soup
        h1 = main.select_one("h1")
        source_title = h1.get_text(" ", strip=True) if h1 else discovery_title
        parts, trade = parse_osn_title(f"{source_title} {discovery_title}")
        if not parts:
            logger.debug("Skipping unknown Osnabrück title %r.", source_title)
            return []

        lower_title = f"{source_title} {discovery_title}".lower()
        default_format = "full_time" if "vollzeit" in lower_title else "part_time"
        if "online" in lower_title and "vollzeit" in lower_title:
            default_teaching = "online"
        elif "online" in lower_title:
            default_teaching = "hybrid"
        else:
            default_teaching = "presence"

        offers: list[RawCourseOffer] = []
        seen: set[tuple[str, str]] = set()

        for heading in main.find_all("h4"):
            if heading.get_text(strip=True) != "Termin":
                continue
            row = _run_row(heading)
            if row is None:
                continue
            text = row.get_text("\n", strip=True)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            date_line = next(
                (line for line in lines if DATE_RE.match(line)),
                None,
            )
            if not date_line:
                continue
            date_match = DATE_RE.match(date_line)
            if not date_match:
                continue

            number_match = COURSE_NO_RE.search(text)
            number = number_match.group(1) if number_match else ""
            start = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
            key = (start, number)
            if key in seen:
                continue
            seen.add(key)

            lower = f"{source_title} {text}".lower()
            format_key = "full_time" if "vollzeit" in lower else default_format
            if "online" in lower and "präsenz" not in lower and "praesenz" not in lower:
                teaching_mode = "online"
            elif "online" in lower:
                teaching_mode = "hybrid"
            else:
                teaching_mode = default_teaching

            street, zip_code, city = _location(text, teaching_mode)
            price_match = PRICE_RE.search(text)
            offers.append(RawCourseOffer(
                title=build_course_title(trade, parts),
                trade_name=trade,
                parts=parts,
                format_key=format_key,
                teaching_mode=teaching_mode,
                start_date=start,
                end_date=f"{date_match.group(6)}-{date_match.group(5)}-{date_match.group(4)}",
                duration_hours=None,
                course_fee=(
                    float(price_match.group(1).replace(".", "") + "." + price_match.group(2))
                    if price_match else None
                ),
                city=city,
                street=street,
                zip_code=zip_code,
                availability=_availability(text),
                source_url=f"{url}#kurs-{number}" if number else url,
                scraped_raw={"title": source_title, "course_no": number, "run_text": text[:1000]},
            ))

        if offers:
            return offers

        street, zip_code, city = _location(main.get_text("\n", strip=True), default_teaching)
        return [RawCourseOffer(
            title=build_course_title(trade, parts),
            trade_name=trade,
            parts=parts,
            format_key=default_format,
            teaching_mode=default_teaching,
            start_date=None,
            end_date=None,
            duration_hours=None,
            course_fee=None,
            city=city,
            street=street,
            zip_code=zip_code,
            availability="unknown",
            source_url=url,
            scraped_raw={"title": source_title, "note": "Keine Termine veröffentlicht"},
        )]

    @staticmethod
    def parse_meister_exam_fees(text: str) -> dict[int, float]:
        fees: dict[int, float] = {}
        patterns = (
            (1, r"Teil\s+I\b[^0-9€]*([\d.]+),(\d{2})\s*(?:Euro|€)"),
            (2, r"Teil\s+II\b[^0-9€]*([\d.]+),(\d{2})\s*(?:Euro|€)"),
            (3, r"Teil\s+III\b[^0-9€]*([\d.]+),(\d{2})\s*(?:Euro|€)"),
            (4, r"Teil\s+IV\b[^0-9€]*([\d.]+),(\d{2})\s*(?:Euro|€)"),
        )
        for part, pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                fees[part] = float(match.group(1).replace(".", "") + "." + match.group(2))
        return fees

    def published_exam_fee_rows(self) -> list[dict]:
        response = self.get(EXAM_FEES_PAGE_URL)
        fees: dict[int, float] = {}
        if response is not None:
            text = BeautifulSoup(response.text, "html.parser").get_text("\n", strip=True)
            fees = self.parse_meister_exam_fees(text)
        if not fees:
            fees = GENERIC_EXAM_FEES
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

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result
