"""Shared parser for Bavaria's ODAV-powered HWK course catalogues."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawCourseOffer, build_course_title

logger = logging.getLogger(__name__)

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "dezember": 12,
}
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
MONTH_DATE_RE = re.compile(
    rf"\b({'|'.join(MONTHS)})\s+(\d{{4}})\b", re.IGNORECASE
)
NUMERIC_MONTH_RE = re.compile(r"\b(0[1-9]|1[0-2])\.(\d{4})\b")
TENTATIVE_DATE_NOTE = "Genauer Termin steht noch nicht fest."
PRICE_RE = re.compile(r"([\d.]+),(\d{2})[\s\xa0]*€")
DURATION_UNIT = r"(?:UE|U-?Std\.?|Std\.?)"
DURATION_RE = re.compile(rf"([\d.]+)[\s\xa0]*{DURATION_UNIT}", re.IGNORECASE)
PARTS_RE = re.compile(
    r"Teile?\s*(?P<parts>(?:IV|III|II|I|[1-4])"
    r"(?:\s*(?:\+|und|u\.?|/|bis|-|–)\s*(?:IV|III|II|I|[1-4]))*)",
    re.IGNORECASE,
)

# Long/specific keys must precede their shorter forms.
TRADE_ALIASES = {
    "rollladen- und sonnenschutztechniker": "Rollladen- und Sonnenschutztechniker",
    "ofen- und luftheizungsbauer": "Ofen- und Luftheizungsbauer",
    "orthopädieschuhmacher": "Orthopädieschuhmacher",
    "orthopädietechniker": "Orthopädietechniker",
    "augenoptiker": "Augenoptiker",
    "glasapparatebauer": "Glasapparatebauer",
    "holzbildhauer": "Holzbildhauer",
    "land- und baumaschinenmechatroniker": "Land- und Baumaschinenmechatroniker",
    "installateur- und heizungsbauer": "Installateur- und Heizungsbauer",
    "installateur und heizungsbauer": "Installateur- und Heizungsbauer",
    "installateur- und heizungsbau": "Installateur- und Heizungsbauer",
    "installateur-/ heizungsbauer": "Installateur- und Heizungsbauer",
    "installateur-/": "Installateur- und Heizungsbauer",
    "karosserie- u. fahrzeugbauer": "Karosserie- und Fahrzeugbauer",
    "karosserie- und fahrzeugbauer": "Karosserie- und Fahrzeugbauer",
    "zweiradmechaniker": "Zweiradmechaniker",
    "fliesen-, platten- und mosaikleger": "Fliesen-, Platten- und Mosaikleger",
    "maurer- und betonbauer": "Maurer und Betonbauer",
    "maurer und betonbauer": "Maurer und Betonbauer",
    "maler- und lackierer": "Maler und Lackierer",
    "maler und lackierer": "Maler und Lackierer",
    "kraftfahrzeugtechniker": "Kfz.-Techniker",
    "kfz-techniker": "Kfz.-Techniker",
    "elektrotechniker": "Elektrotechniker",
    "elektrotechnikmeister": "Elektrotechniker",
    "feinwerkmechaniker": "Feinwerkmechaniker",
    "fahrzeuglackierer": "Fahrzeuglackierer",
    "metallbauer": "Metallbauer",
    "metallbaumeister": "Metallbauer",
    "schreiner-/tischler": "Tischler",
    "schreiner": "Tischler",
    "tischler": "Tischler",
    "spengler-/klempner": "Klempner",
    "klempner": "Klempner",
    "metzger-/fleischer": "Fleischer",
    "fleischer": "Fleischer",
    "zahntechniker": "Zahntechniker",
    "raumausstatter": "Raumausstatter",
    "gerüstbauer": "Gerüstbauer",
    "brauer- und mälzer": "Brauer und Mälzer",
    "fliesenleger": "Fliesen-, Platten- und Mosaikleger",
    "kosmetiker": "Kosmetiker",
    "stuckateur": "Stuckateur",
    "zimmerer": "Zimmerer",
    "konditor": "Konditor",
    "friseur": "Friseur",
    "bäcker": "Bäcker",
    "dachdecker": "Dachdecker",
    "glaser": "Glaser",
}


def parse_euro(text: str, label: str | None = None) -> float | None:
    pattern = PRICE_RE if label is None else re.compile(
        rf"{label}(?:sgebühr|gebühr)?\s*:\s*([\d.]+),(\d{{2}})[\s\xa0]*€",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    return float(match.group(1).replace(".", "") + "." + match.group(2))


def parse_parts(title: str, *, implicit_trade_parts: bool = False) -> list[int]:
    lower = title.lower()
    match = PARTS_RE.search(title)
    if match:
        tokens = re.findall(r"IV|III|II|I|[1-4]", match.group("parts").upper())
        values = [ROMAN.get(token, int(token) if token.isdigit() else 0) for token in tokens]
        if len(values) == 2 and re.search(r"(?:bis|-|–)", match.group("parts")):
            lo, hi = sorted(values)
            return list(range(lo, hi + 1))
        # Some catalogues repeat the marker ("Teil I / Teil II"). The main
        # pattern stops before the second marker, so merge all explicit
        # marker/token pairs found in the title.
        repeated = re.findall(r"\bTeile?\s*(IV|III|II|I|[1-4])\b", title, re.IGNORECASE)
        values.extend(
            ROMAN.get(token.upper(), int(token) if token.isdigit() else 0)
            for token in repeated
        )
        return sorted(set(value for value in values if value))

    if "ausbildereignung" in lower or re.search(r"\b(?:ada|aevo)\b", lower):
        return [4]
    if "kaufmännische betriebsführung" in lower or re.search(r"fach(?:mann|frau).+hwo", lower):
        return [3]

    if implicit_trade_parts and "meister" in lower:
        return [1, 2]
    return []


# Parenthetical trade suffixes that are format labels, not Fachrichtungen.
_FORMAT_ONLY_TRADE_SPEC_RE = re.compile(
    r"^(?:neu\s*:\s*)?(?:vollzeit|teilzeit|abend|wochenende|blended(?:\s*learning)?|online(?:/hybrid)?|präsenz|praesenz)$",
    re.IGNORECASE,
)


def _trade_specialization(title: str, canonical: str) -> str:
    match = re.search(
        rf"{re.escape(canonical)}(?:meister/in|meister|meisterschule)?\s*\(([^)]+)\)",
        title,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"(?:meister/in|meister)\s*\(([^)]+)\)\s*-",
            title,
            re.IGNORECASE,
        )
    if not match:
        return canonical
    spec = match.group(1).strip()
    if spec.lower().startswith("fachrichtung "):
        spec = spec.split(None, 1)[1]
    if _FORMAT_ONLY_TRADE_SPEC_RE.fullmatch(spec):
        return canonical
    return f"{canonical} ({spec})"


# Issue #54: some chambers list Elektrotechniker/Feinwerkmechaniker without Fachrichtung.
_BASE_TRADE_RE = {
    "Elektrotechniker": re.compile(r"^Elektrotechniker\b", re.IGNORECASE),
    "Feinwerkmechaniker": re.compile(r"^Feinwerkmechaniker\b", re.IGNORECASE),
}


def normalize_base_trade_offer(offer: RawCourseOffer) -> RawCourseOffer:
    if offer.trade_name:
        for base, pattern in _BASE_TRADE_RE.items():
            if pattern.match(offer.trade_name):
                offer.trade_name = base
                offer.title = build_course_title(base, offer.parts)
                break
    return offer


def parse_trade(title: str, parts: list[int]) -> str | None:
    if not parts or set(parts) <= {3, 4}:
        return None
    lower = title.lower()
    if "meister" not in lower and not re.match(r"\s*mk\b", lower):
        return None
    # The specialization is the actual trade in this Oberfranken title.
    if "fachrichtung fahrzeuglackierer" in lower:
        return "Fahrzeuglackierer"
    for source, canonical in TRADE_ALIASES.items():
        if source in lower:
            return _trade_specialization(title, canonical)
    return None


def parse_dates_with_note(text: str) -> tuple[str | None, str | None, str]:
    exact = DATE_RE.findall(text)
    if exact:
        values = [f"{year}-{month}-{day}" for day, month, year in exact[:2]]
        return values[0], values[1] if len(values) > 1 else None, ""

    months = MONTH_DATE_RE.findall(text)
    if months:
        values = [f"{year}-{MONTHS[name.lower()]:02d}-01" for name, year in months[:2]]
        return values[0], values[1] if len(values) > 1 else None, TENTATIVE_DATE_NOTE
    numeric = NUMERIC_MONTH_RE.findall(text)
    if numeric:
        values = [f"{year}-{month}-01" for month, year in numeric[:2]]
        return values[0], values[1] if len(values) > 1 else None, TENTATIVE_DATE_NOTE
    return None, None, ""


def parse_dates(text: str) -> tuple[str | None, str | None]:
    start, end, _ = parse_dates_with_note(text)
    return start, end


def parse_format_and_mode(text: str) -> tuple[str, str]:
    lower = text.lower()
    format_key = "full_time" if "vollzeit" in lower else "part_time"
    has_online = any(word in lower for word in ("online", "e-learning", "virtuell"))
    has_presence = any(word in lower for word in ("präsenz", "praesenz", "blended", "hybrid"))
    if has_online and has_presence:
        mode = "hybrid"
    elif has_online:
        mode = "online"
    else:
        mode = "presence"
    return format_key, mode


def parse_availability(text: str) -> str:
    lower = text.lower()
    if "ausgebucht" in lower:
        return "full"
    if "warteliste" in lower:
        return "waitlist"
    if "freie plätze" in lower or "freie plaetze" in lower or "wenige plätze" in lower:
        return "available"
    return "unknown"


def canonical_detail_url(base_url: str, href: str) -> str:
    absolute = urljoin(base_url, href)
    split = urlsplit(absolute)
    course_id = parse_qs(split.query).get("id", [""])[0]
    if not course_id:
        return absolute
    prefix_match = re.search(r"(\d+),0,coursedetail\.html", split.path)
    if prefix_match:
        prefix = prefix_match.group(1)
    else:
        prefix = parse_qs(split.query).get("search-onr", ["0"])[0]
    path = f"/{prefix},0,coursedetail.html"
    return urlunsplit((split.scheme, split.netloc, path, urlencode({"id": course_id}), ""))


def course_id_from_url(url: str) -> str:
    return parse_qs(urlsplit(url).query).get("id", [""])[0]


def _section_text(text: str, heading: str, *, stop_headings: tuple[str, ...]) -> str:
    index = text.lower().find(heading.lower())
    if index < 0:
        return ""
    block = text[index:]
    end = len(block)
    for stop in stop_headings:
        pos = block.find(f"\n{stop}\n")
        if pos > 0:
            end = min(end, pos)
    return block[:end]


def parse_address(text: str) -> tuple[str, str, str] | None:
    block = _section_text(
        text,
        "Lehrgangsort",
        stop_headings=("Kontakt", "Details", "Angebotsnummer", "Unterricht", "Information"),
    )
    if not block:
        return None
    lines = [
        line.strip()
        for line in block.splitlines()
        if line.strip() and line.strip().lower() != "lehrgangsort"
    ]
    for index, line in enumerate(lines):
        match = re.match(r"(\d{5})\s+(.+)", line)
        if not match or match.group(1) == "00000":
            continue
        street = ""
        if index > 0 and re.search(r"\d", lines[index - 1]):
            street = lines[index - 1]
        return street, match.group(1), match.group(2).strip(" ,")
    if lines:
        city = lines[0]
        if city and len(city) < 60 and not re.search(r"@|tel\.|telefon|--at--", city, re.I):
            return "", "", city
    return None


def _amount_from_match(match: re.Match, whole_group: int, cents_group: int) -> float:
    cents = match.group(cents_group) or "00"
    return float(match.group(whole_group).replace(".", "") + "." + cents)


def parse_exam_fee(text: str, parts: list[int]) -> tuple[float | None, str]:
    """Parse Bavarian ODAV exam-fee prose and structured fee blocks."""
    structured = parse_euro(text, "Prüfung")
    if structured is not None:
        return structured, ""

    lower = text.lower()
    qualifier = ""
    if any(word in lower for word in ("zirka", "ca.", "circa")):
        qualifier = "ca."
    elif re.search(r"zzgl\.\s+gewerkspezif", lower):
        qualifier = "ca."

    part_amounts: dict[int, float] = {}
    patterns = (
        r"Prüfungsgebühr(?:\s+für)?\s+(?:den\s+)?Teil\s+(I{1,3}|IV)\s*"
        r"(?:[:：]\s*(?:€\s*)?|[-–—]\s*)([\d.]+),(\d{2})(?:\s*(?:€|Euro))?",
        r"Prüfungsgebühr\s+([\d.]+),(\d{2})\s*Euro\s+Teil\s+(I{1,3}|IV)",
        r"([\d.]+),(\d{2})\s*Euro\s+Teil\s+(I{1,3}|IV)\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if pattern.startswith(r"Prüfungsgebühr(?:\s+für)?"):
                part = ROMAN[match.group(1).upper()]
                amount = _amount_from_match(match, 2, 3)
            elif pattern.startswith(r"Prüfungsgebühr\s+"):
                part = ROMAN[match.group(3).upper()]
                amount = _amount_from_match(match, 1, 2)
            else:
                part = ROMAN[match.group(3).upper()]
                amount = _amount_from_match(match, 1, 2)
            part_amounts[part] = amount

    # Leipzig-style whole-euro amounts on the next line, e.g. "Teil I:\n395 Euro".
    for match in re.finditer(
        r"Prüfungsgebühr(?:\s+für)?\s+(?:den\s+)?Teil\s+(I{1,3}|IV)\s*[:：]?\s*"
        r"(?:\n|\s)*(?:€\s*)?([\d.]+)\s*(?:€|Euro)\b",
        text,
        re.IGNORECASE,
    ):
        part = ROMAN[match.group(1).upper()]
        part_amounts.setdefault(
            part,
            float(match.group(2).replace(".", "")),
        )

    if not part_amounts:
        combo = re.search(
            r"Prüfungsgebühr\s+Teile?\s+(?:I\s+und\s+II|III\s+und\s+IV|I{1,3}\s+und\s+II)"
            r".*?\(?\s*(?:zirka|ca\.|circa)?\s*([\d.]+),(\d{2})\s*€",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if combo and set(parts) <= {1, 2, 3, 4}:
            return _amount_from_match(combo, 1, 2), "ca." if combo.group(0).lower().find("zirka") >= 0 or "ca." in combo.group(0).lower() else qualifier

    if set(parts) == {3, 4}:
        generic = re.search(
            r"Prüfungsgebühr.*?(?:Teile?\s+III\s+und\s+IV|die\s+Teile\s+III\s+und\s+IV).*?"
            r"(?:je\s*)?(?:€\s*)?([\d.]+),(\d{2})",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if generic:
            return _amount_from_match(generic, 1, 2) * 2, qualifier

    values = [part_amounts[part] for part in parts if part in part_amounts]
    if len(values) == len(parts) and values:
        return sum(values), qualifier

    prose_total = re.search(
        r"Prüfungsgebühr(?:\s*:\s*|\s+)([\d.]+),(\d{2})\s*(?:Euro|€)",
        text,
        re.IGNORECASE,
    )
    if prose_total:
        return _amount_from_match(prose_total, 1, 2), qualifier

    # HWK Aachen ODAV: "Prüfungsgebühr: 610 Euro" (whole euros, no cents).
    whole_euro = re.search(
        r"Prüfungsgebühr\s*:\s*([\d.]+)\s*Euro\b",
        text,
        re.IGNORECASE,
    )
    if whole_euro:
        line = whole_euro.group(0)
        line_qual = "ca." if re.search(r"zirka|ca\.|circa", line, re.I) else ""
        return float(whole_euro.group(1).replace(".", "")), line_qual

    # HWK Düsseldorf ODAV: "zurzeit 1.470,00 Euro Prüfungsgebühren".
    plural_total = re.search(
        r"(?:zurzeit\s+)?([\d.]+),(\d{2})\s*Euro\s+Prüfungsgebühren",
        text,
        re.IGNORECASE,
    )
    if plural_total:
        q = "ca." if "zurzeit" in plural_total.group(0).lower() else qualifier
        return _amount_from_match(plural_total, 1, 2), q

    return None, ""


@dataclass(frozen=True)
class BavariaCatalogue:
    base_url: str
    list_url: str
    default_city: str
    default_street: str = ""
    default_zip: str = ""
    page_size: int = 100
    implicit_trade_parts: bool = False
    details_required: bool = True


class BavariaOdavScraper(BaseScraper):
    """Configurable two-pass scraper for the six Bavarian HWK catalogues."""

    catalogue: BavariaCatalogue
    chamber_region = "Bayern"

    def fetch_raw_courses(self) -> list[RawCourseOffer]:
        first_url = self._list_url(0)
        first = self.parse_html(first_url)
        if first is None:
            logger.error("Could not fetch %s course list.", self.chamber_name)
            return []

        total = self._parse_total(first)
        cards = self._parse_page(first)
        for offset in range(self.catalogue.page_size, total, self.catalogue.page_size):
            soup = self.parse_html(self._list_url(offset))
            if soup is None:
                logger.warning("%s listing failed at offset %d.", self.chamber_slug, offset)
                continue
            cards.extend(self._parse_page(soup))

        unique: dict[str, dict] = {}
        for card in cards:
            course_id = course_id_from_url(card["detail_url"])
            if course_id:
                unique[course_id] = card
            else:
                unique[card["detail_url"]] = card
        offers = [self._enrich(card) for card in unique.values()]
        result = [offer for group in offers for offer in (group if isinstance(group, list) else [group]) if offer]
        logger.info("%s: parsed %d of %d catalogue entries.", self.chamber_name, len(result), total)
        return result

    def _list_url(self, offset: int) -> str:
        return self.catalogue.list_url.format(
            offset=offset,
            limit=self.catalogue.page_size,
            today=date.today().strftime("%d.%m.%Y"),
        )

    @staticmethod
    def _parse_total(soup: BeautifulSoup) -> int:
        match = re.search(r"von\s+(\d+);\s*Seite", soup.get_text(" ", strip=True))
        return int(match.group(1)) if match else len(soup.select("a[href*='coursedetail']"))

    def _parse_page(self, soup: BeautifulSoup) -> list[dict]:
        cards: list[dict] = []
        seen: set[str] = set()
        for link in soup.select("a[href*='coursedetail']"):
            detail_url = canonical_detail_url(self.catalogue.base_url, link.get("href", ""))
            course_id = course_id_from_url(detail_url) or detail_url
            if not detail_url or course_id in seen:
                continue
            seen.add(course_id)
            card = self._parse_card(link, detail_url)
            if card:
                cards.append(card)
        return cards

    def _parse_card(self, link: Tag, detail_url: str | None = None) -> dict | None:
        raw_title = link.get_text(" ", strip=True)
        parts = parse_parts(raw_title, implicit_trade_parts=self.catalogue.implicit_trade_parts)
        trade_name = parse_trade(raw_title, parts)
        if not parts or (not trade_name and not set(parts) <= {3, 4}):
            logger.debug("Skipping non-Meister or unknown title %r", raw_title)
            return None
        row = link.find_parent("div", class_="row")
        heading = link.find_parent("h3")
        text = row.get_text("\n", strip=True) if row else raw_title
        heading_text = heading.get_text(" ", strip=True) if heading else text
        start_date, end_date = parse_dates(heading_text)
        format_key, teaching_mode = parse_format_and_mode(f"{heading_text} {raw_title}")
        duration = DURATION_RE.search(text)
        return {
            "raw_title": raw_title,
            "parts": parts,
            "trade_name": trade_name,
            "start_date": start_date,
            "end_date": end_date,
            "format_key": format_key,
            "teaching_mode": teaching_mode,
            "duration_hours": int(duration.group(1).replace(".", "")) if duration else None,
            "course_fee": parse_euro(text),
            "availability": parse_availability(text),
            "detail_url": detail_url or canonical_detail_url(
                self.catalogue.base_url, link.get("href", "")
            ),
            "card_text": text[:1000],
        }

    def _enrich(self, card: dict) -> RawCourseOffer | list[RawCourseOffer] | None:
        soup = self.parse_html(card["detail_url"]) if self.catalogue.details_required else None
        text = soup.get_text("\n", strip=True) if soup else ""
        main_text = (soup.select_one("main") or soup).get_text("\n", strip=True) if soup else text
        detail_title_tag = soup.select_one("h1") if soup else None
        detail_title = detail_title_tag.get_text(" ", strip=True) if detail_title_tag else card["raw_title"]
        parts = parse_parts(detail_title, implicit_trade_parts=self.catalogue.implicit_trade_parts) or card["parts"]
        trade_name = parse_trade(detail_title, parts) or card["trade_name"]
        if not trade_name and not set(parts) <= {3, 4}:
            return None

        start_date, end_date, start_date_note = self.resolve_schedule_dates(soup, card, main_text)
        format_key, teaching_mode = parse_format_and_mode(
            f"{detail_title}\n{main_text[:3000]}"
        )
        duration = re.search(
            rf"Lehrgangsdauer\s+([\d.]+)\s*{DURATION_UNIT}", main_text, re.IGNORECASE
        )
        address = parse_address(main_text)
        if address:
            street, zip_code, city = address
        else:
            street, zip_code, city = self.listing_location(card, teaching_mode)

        course_fee = parse_euro(main_text, "Kurs") if soup else card["course_fee"]
        exam_fee, exam_fee_qualifier = (
            parse_exam_fee(main_text, parts) if soup else (None, "")
        )
        if course_fee is None and not self.catalogue.details_required:
            course_fee = card["course_fee"]
        offer_number = None
        if soup:
            offer_number_match = re.search(
                r"Angebotsnummer\s+([A-Za-z0-9-]+)", main_text, re.IGNORECASE
            )
            offer_number = offer_number_match.group(1) if offer_number_match else None

        offer = RawCourseOffer(
            title=build_course_title(trade_name, parts),
            trade_name=trade_name,
            parts=parts,
            format_key=format_key if soup else card["format_key"],
            teaching_mode=teaching_mode if soup else card["teaching_mode"],
            start_date=start_date or card["start_date"],
            end_date=end_date or card["end_date"],
            duration_hours=(
                int(duration.group(1).replace(".", "")) if duration else card["duration_hours"]
            ),
            course_fee=course_fee,
            exam_fee_scraped=exam_fee,
            exam_fee_qualifier=exam_fee_qualifier,
            start_date_note=start_date_note,
            city=city,
            street=street,
            zip_code=zip_code,
            availability=parse_availability(main_text) if soup else card["availability"],
            source_url=card["detail_url"],
            scraped_raw={
                "title": detail_title,
                "card_text": card["card_text"],
                "guaranteed": "garantierte durchführung" in main_text.lower(),
                "offer_number": offer_number,
            },
        )
        result = self.transform_offer(offer, main_text)
        if isinstance(result, list):
            return [self.postprocess_offer(item) for item in result]
        return self.postprocess_offer(result) if result else None

    def postprocess_offer(self, offer: RawCourseOffer) -> RawCourseOffer:
        """Hook for chamber-specific offer normalization."""
        return offer

    def resolve_schedule_dates(
        self,
        soup: BeautifulSoup | None,
        card: dict,
        main_text: str,
    ) -> tuple[str | None, str | None, str]:
        """Hook for chamber-specific schedule parsing."""
        return parse_dates_with_note(main_text)

    def listing_location(self, card: dict, teaching_mode: str) -> tuple[str, str, str]:
        """Resolve a location when no detail-page address is available."""
        if teaching_mode == "online":
            return "", "", "Online"
        return (
            self.catalogue.default_street,
            self.catalogue.default_zip,
            self.catalogue.default_city,
        )

    def transform_offer(
        self, offer: RawCourseOffer, detail_text: str
    ) -> RawCourseOffer | list[RawCourseOffer]:
        """Hook for a chamber-specific exceptional course."""
        return offer
