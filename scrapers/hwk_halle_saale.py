"""Scraper for HWK Halle (Saale)'s WordPress seminar catalogue."""

import logging
import re
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, ScrapeResult, build_course_title, normalize_trade
from .hwk_bayern import parse_parts, parse_trade

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hwkhalle.de"
OVERVIEW_URL = f"{BASE_URL}/meisterkurse/"
EXAM_FEES_PDF_URL = f"{BASE_URL}/wp-content/uploads/Gebuehrenverzeichnis-1.pdf"
DATE_RE = re.compile(
    r"^(\d{2})\.(\d{2})\.(\d{4})\s*[—–-]\s*(\d{2})\.(\d{2})\.(\d{4})"
)
PRICE_RE = re.compile(r"([\d.]+),(\d{2})\s*(?:€|Euro)", re.IGNORECASE)
DURATION_RE = re.compile(
    r"Seminardauer\s+([\d.]+)\s+Unterrichtseinheiten", re.IGNORECASE
)
COURSE_NO_RE = re.compile(r"Kursnummer\s+([A-Za-z0-9_-]+)", re.IGNORECASE)
DEFAULT_LOCATION = {
    "street": "Straße der Handwerker 2",
    "zip_code": "06132",
    "city": "Halle (Saale)",
}

# Titles use trade nouns without the usual "Meister im …-Handwerk" wording.
HALLE_TRADE_ALIASES = {
    "elektrotechnik": "Elektrotechniker",
    "kraftfahrzeugtechnik": "Kfz.-Techniker",
    "maler": "Maler und Lackierer",
}

HALLE_PART_I_FALLBACK = {
    "Elektrotechniker": 430.0,
    "Kfz.-Techniker": 370.0,
    "Installateur- und Heizungsbauer": 421.0,
    "Maurer und Betonbauer": 398.0,
    "Metallbauer": 428.0,
    "Zimmerer": 406.0,
    "Maler und Lackierer": 489.0,
    "Fahrzeuglackierer": 489.0,
}
GENERIC_EXAM_FEES = {2: 323.0, 3: 208.0, 4: 210.0}


def _canonical_seminar_url(href: str) -> str:
    split = urlsplit(urljoin(BASE_URL, href))
    path = split.path.rstrip("/") + "/"
    return urlunsplit((split.scheme, split.netloc, path, "", ""))


def parse_halle_title(title: str) -> tuple[list[int], str | None]:
    parts = parse_parts(title, implicit_trade_parts=True)
    if not parts:
        return [], None
    trade = parse_trade(title, parts)
    if not trade:
        lower = title.lower()
        for source, canonical in HALLE_TRADE_ALIASES.items():
            if re.search(rf"\b{re.escape(source)}\b", lower):
                trade = canonical
                break
    if set(parts) <= {3, 4}:
        return parts, None
    return (parts, trade) if trade else ([], None)


def _is_meister_link(title: str) -> bool:
    lower = title.lower()
    if any(value in lower for value in (
        "mathematik für meister", "infoabend", "informationsveranstaltung",
        "meisterbonus", "meisterprämie",
    )):
        return False
    return (
        "meistervorbereitungslehrgang" in lower
        or ("meister" in lower and "industriemeister" not in lower)
    )


def _availability(text: str) -> str:
    lower = text.lower()
    if any(value in lower for value in (
        "keine plätze mehr frei", "bereits ausgebucht",
        "buchung ist nicht mehr möglich", "eine buchung ist nicht mehr möglich",
    )):
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "freie plätze" in lower or "in den warenkorb" in lower:
        return "available"
    return "unknown"


def _location(text: str, teaching_mode: str) -> tuple[str, str, str]:
    if teaching_mode == "online":
        return "", "", "Online"
    street_match = re.search(
        r"([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .-]+(?:straße|str\.|weg|platz|gasse)\s+\d+[A-Za-z]?)"
        r"\s+(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß ()-]+?)"
        r"(?=\s+(?:Kosten|Kursnummer|Kurstyp|Eine|Telefon|E-Mail|Seminardauer|Teilnehmer|Zeiten|Ihr)\b|$)",
        text,
        re.IGNORECASE,
    )
    if street_match:
        return (
            street_match.group(1).strip(),
            street_match.group(2),
            street_match.group(3).strip(),
        )
    zip_match = re.search(
        r"\b(\d{5})\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß ()-]+?)"
        r"(?=\s+(?:Kosten|Kursnummer|Kurstyp|Eine|Telefon|E-Mail|Seminardauer|Teilnehmer|Zeiten|Ihr)\b|$)",
        text,
    )
    if zip_match:
        return "", zip_match.group(1), zip_match.group(2).strip()
    return DEFAULT_LOCATION["street"], DEFAULT_LOCATION["zip_code"], DEFAULT_LOCATION["city"]


class HwkHalleSaaleScraper(BaseScraper):
    chamber_slug = "hwk-halle-saale"
    chamber_name = "Handwerkskammer Halle (Saale)"
    chamber_region = "Sachsen-Anhalt"
    chamber_website = BASE_URL
    source_url = OVERVIEW_URL
    request_delay = 0.8

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        soup = self.parse_html(OVERVIEW_URL)
        if soup is None:
            logger.error("Could not fetch HWK Halle course overview.")
            return []

        courses = self._discover(soup)
        offers: list[RawCourseOffer] = []
        for title, url in courses:
            detail = self.parse_html(url)
            if detail is None:
                logger.warning("Could not fetch Halle course %s.", url)
                continue
            try:
                parsed = self._parse_course(detail, title, url)
            except Exception as exc:
                logger.warning("Could not parse Halle course %s: %s", url, exc)
                continue
            offers.extend(parsed)
        logger.info("HWK Halle (Saale): parsed %d offers from %d courses.", len(offers), len(courses))
        return offers

    @staticmethod
    def _discover(soup: BeautifulSoup) -> list[tuple[str, str]]:
        found: dict[str, str] = {}
        for link in soup.select("a[href*='/seminar/']"):
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
        parts, trade = parse_halle_title(f"{source_title} {discovery_title}")
        if not parts:
            logger.debug("Skipping unknown Halle title %r.", source_title)
            return []

        page_text = main.get_text(" ", strip=True)
        duration_match = DURATION_RE.search(page_text)
        duration = int(duration_match.group(1).replace(".", "")) if duration_match else None
        lower_title = f"{source_title} {discovery_title}".lower()
        default_format = "full_time" if "vollzeit" in lower_title else "part_time"
        offers: list[RawCourseOffer] = []
        seen: set[tuple[str, str]] = set()

        for heading in main.find_all("h4"):
            heading_text = heading.get_text(" ", strip=True)
            date_match = DATE_RE.match(heading_text)
            if not date_match:
                continue
            container = self._run_container(heading)
            if container is None:
                continue
            text = container.get_text(" ", strip=True)
            number_match = COURSE_NO_RE.search(text)
            number = number_match.group(1) if number_match else ""
            start = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
            key = (start, number)
            if key in seen:
                continue
            seen.add(key)

            lower = f"{source_title} {text}".lower()
            format_key = "full_time" if "vollzeit" in lower else default_format
            if "hybrid" in lower or ("online" in lower and "präsenz" in lower):
                teaching_mode = "hybrid"
            elif "online" in lower and "keine onlineschulung" not in lower:
                teaching_mode = "online"
            else:
                teaching_mode = "presence"
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
                duration_hours=duration,
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
        street, zip_code, city = _location(page_text, "presence")
        return [RawCourseOffer(
            title=build_course_title(trade, parts),
            trade_name=trade,
            parts=parts,
            format_key=default_format,
            teaching_mode="presence",
            start_date=None,
            end_date=None,
            duration_hours=duration,
            course_fee=None,
            city=city,
            street=street,
            zip_code=zip_code,
            availability="unknown",
            source_url=url,
            scraped_raw={"title": source_title, "note": "Keine Termine veröffentlicht"},
        )]

    @staticmethod
    def _run_container(heading: Tag) -> Tag | None:
        node: Tag | None = heading
        for _ in range(6):
            node = node.parent if node is not None else None
            if node is None or not isinstance(node, Tag):
                return None
            text = node.get_text(" ", strip=True)
            if "Kursnummer" in text and ("Kosten" in text or "Kurstyp" in text):
                return node
        return None

    @staticmethod
    def parse_part_i_exam_fees(text: str) -> dict[str, float]:
        fees: dict[str, float] = {}
        for match in re.finditer(
            r"Meisterprüfung:\s*([^\d]+?)\s+([\d.]+),(\d{2})\s*€",
            text,
            re.IGNORECASE,
        ):
            trade_label = match.group(1).strip(" :")
            amount = float(match.group(2).replace(".", "") + "." + match.group(3))
            lower = trade_label.lower()
            if "kraftfahrzeug" in lower:
                fees["Kfz.-Techniker"] = amount
            elif "elektrotechnik" in lower:
                fees["Elektrotechniker"] = amount
            elif "installateur" in lower:
                fees["Installateur- und Heizungsbauer"] = amount
            elif "maurer" in lower:
                fees["Maurer und Betonbauer"] = amount
            elif "metallbauer" in lower:
                fees["Metallbauer"] = amount
            elif "zimmerer" in lower:
                fees["Zimmerer"] = amount
            elif "maler" in lower or "lackierer" in lower:
                fees["Maler und Lackierer"] = amount
            elif "friseur" in lower:
                fees["Friseur"] = amount
            elif "tischler" in lower:
                fees["Tischler"] = amount
        return fees

    def _fetch_exam_fees_from_pdf(self) -> dict[str, float]:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("HWK Halle: pypdf not installed — using fallback exam fees.")
            return {}

        response = self.get(EXAM_FEES_PDF_URL)
        if response is None:
            logger.warning("HWK Halle: could not fetch exam-fee PDF.")
            return {}

        text = ""
        for page in PdfReader(BytesIO(response.content)).pages:
            text += (page.extract_text() or "") + "\n"
        fees = self.parse_part_i_exam_fees(text)
        if not fees:
            logger.warning("HWK Halle: could not parse trade-specific Teil-I exam fees from PDF.")
        return fees

    def collect(self) -> ScrapeResult:
        result = super().collect()
        result.exam_fee_rows.extend(self.published_exam_fee_rows())
        return result

    def published_exam_fee_rows(self) -> list[dict]:
        part_i_fees = self._fetch_exam_fees_from_pdf() or HALLE_PART_I_FALLBACK
        rows: list[dict] = []
        for trade_name, fee in part_i_fees.items():
            rows.append({
                "chamber_slug": self.chamber_slug,
                "trade_slug": normalize_trade(trade_name)[0],
                "part": 1,
                "fee": fee,
                "qualifier": "",
                "source_url": EXAM_FEES_PDF_URL,
            })
        for part, fee in GENERIC_EXAM_FEES.items():
            rows.append({
                "chamber_slug": self.chamber_slug,
                "trade_slug": None,
                "part": part,
                "fee": fee,
                "qualifier": "",
                "source_url": EXAM_FEES_PDF_URL,
            })
        return rows
