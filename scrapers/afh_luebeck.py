"""
Parser for Meistervorbereitungskurse at the Akademie für Hörakustik (AFH) Lübeck.

HWK Rheinhessen (and HWK Halle) examine Hörakustiker candidates, but the
preparation courses run at AFH campuses — primarily Lübeck, plus hybrid/online
formats in Würzburg and elsewhere.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import RawCourseOffer, build_course_title
from .format_keys import parse_format_key

PORTAL_BASE = "https://portal.afh-luebeck.de"
AFH_OVERVIEW_URL = "https://www.afh-luebeck.de/en/meistervorbereitung/"
AFH_SEARCH_URL = f"{PORTAL_BASE}/kurse/suche/?traeger=2&search_text=meister"
PROVIDER_NAME = "Akademie für Hörakustik"

AFH_LUEBECK = {
    "street": "Bessemerstraße 3",
    "zip_code": "23562",
    "city": "Lübeck",
}
AFH_WUERZBURG = {
    "street": "Dieselstr. 12",
    "zip_code": "97082",
    "city": "Würzburg",
}

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
DATE_RANGE_RE = re.compile(
    r"(\d{2}\.\d{2}\.\d{4})\s*(?:[—–\-]+|bis)\s*(\d{2}\.\d{2}\.\d{4})"
)
EURO_RE = re.compile(r"([\d.]+),(\d{2})\s*(?:€|&euro;|EUR)", re.IGNORECASE)
ZIP_CITY_RE = re.compile(r"(\d{5})\s+([A-ZÄÖÜa-zäöüß][^\n<]{1,60})")
STREET_BEFORE_ZIP_RE = re.compile(
    r"(?:<br\s*/?>\s*)?"
    r"([A-ZÄÖÜa-zäöüß][^\n<]{2,60}\s+\d+[a-zA-Z]?)\s*<br\s*/?>\s*(\d{5})",
    re.IGNORECASE,
)
MEISTER_TITLE_RE = re.compile(
    r"meister|mvik|meistervollzeit|meistervorbereitung",
    re.IGNORECASE,
)
PARTS_ROMAN_RE = re.compile(
    r"teile?\s*(?:i\s*[-+&/]\s*iv|i\s*[-+&/]\s*ii|iii\s*[-+&/]\s*iv|"
    r"i\s*[-+&/]\s*iii|1\s*[-+&/]\s*4|1\s*[-+&/]\s*2|iii|iv|ii|i)",
    re.IGNORECASE,
)


def _iso_date(raw: str) -> str:
    day, month, year = raw.split(".")
    return f"{year}-{month}-{day}"


def _parse_euro(text: str) -> float | None:
    match = EURO_RE.search(text)
    if match:
        return float(match.group(1).replace(".", "") + "." + match.group(2))
    plain = re.search(r"([\d.]+),(\d{2})", text)
    if plain:
        return float(plain.group(1).replace(".", "") + "." + plain.group(2))
    return None


def _search_field(card: Tag, label: str) -> str | None:
    for key in card.select(".searchhit-text-item-key"):
        if label.lower() not in key.get_text(" ", strip=True).lower():
            continue
        value = key.find_next_sibling(class_="searchhit-text-item-value")
        if value is not None:
            return value.get_text(" ", strip=True)
    return None


def infer_parts(title: str, description: str = "") -> list[int]:
    text = f"{title} {description}".lower()
    if re.search(r"teile?\s*i\s*[-+&/]\s*iv|teile?\s*1\s*[-+&/]\s*4|teile?\s*i\s*-\s*iv", text):
        return [1, 2, 3, 4]
    if re.search(r"iii\s*[-+&/]\s*iv|iii/iv|teile?\s*iii", text):
        return [3, 4]
    if re.search(r"teile?\s*i\s*[-+&/]\s*ii|teile?\s*1\s*[-+&/]\s*2|mvik(?!\s*iii)", text):
        return [1, 2]
    if "meistervollzeit" in text or "meisterstudium" in text:
        return [1, 2, 3, 4]
    return [1, 2]


def infer_format_and_mode(title: str, location_label: str, description: str = "") -> tuple[str, str]:
    text = f"{title} {location_label} {description}"
    format_key = parse_format_key(text, default="part_time")
    lower = text.lower()
    if "hybrid" in lower:
        return format_key, "hybrid"
    if location_label.strip().upper() == "ONLINE" or re.search(r"\bonline\b", lower):
        return format_key, "online"
    return format_key, "presence"


def resolve_location(location_label: str, title: str, detail_html: str = "") -> dict[str, str]:
    label = location_label.strip()
    upper = label.upper()
    if upper == "ONLINE":
        return {"street": "", "zip_code": "", "city": "Online"}
    if "würzburg" in label.lower() or "wurzburg" in title.lower():
        parsed = _parse_address_from_html(detail_html)
        if parsed:
            return parsed
        return dict(AFH_WUERZBURG)
    parsed = _parse_address_from_html(detail_html)
    if parsed:
        return parsed
    return dict(AFH_LUEBECK)


def _parse_address_from_html(html: str) -> dict[str, str] | None:
    if not html:
        return None
    match = STREET_BEFORE_ZIP_RE.search(html)
    if match:
        street = re.sub(r"^br/?>\s*", "", match.group(1).strip(), flags=re.IGNORECASE)
        zip_code = match.group(2)
        city_match = ZIP_CITY_RE.search(html[match.start(): match.start() + 200])
        city = city_match.group(2).strip() if city_match else ""
        if city:
            return {"street": street, "zip_code": zip_code, "city": city}
    match = ZIP_CITY_RE.search(html)
    if match:
        return {"street": "", "zip_code": match.group(1), "city": match.group(2).strip()}
    return None


def parse_search_listing(card: Tag) -> dict | None:
    header = card.select_one(".searchhit-header h3 a")
    if header is None:
        return None
    title = header.get_text(" ", strip=True)
    if not MEISTER_TITLE_RE.search(title):
        return None
    if re.search(r"repetitionskurs|praxistraining", title, re.IGNORECASE):
        return None

    href = header.get("href", "")
    detail_url = urljoin(PORTAL_BASE, href)
    location_label = ""
    lead = card.select_one(".searchhit-text p.lead")
    if lead is not None:
        location_label = lead.get_text(" ", strip=True)
    description = ""
    desc = card.select_one(".searchhit-text p.margin-right-l")
    if desc is not None:
        description = desc.get_text(" ", strip=True)

    start_raw = _search_field(card, "Termin")
    fee_raw = _search_field(card, "Gebühren")
    start_date = _iso_date(start_raw) if start_raw and DATE_RE.fullmatch(start_raw.strip()) else None
    course_fee = _parse_euro(fee_raw or "")

    parts = infer_parts(title, description)
    format_key, teaching_mode = infer_format_and_mode(title, location_label, description)

    return {
        "title": title,
        "detail_url": detail_url,
        "location_label": location_label,
        "description": description,
        "start_date": start_date,
        "course_fee": course_fee,
        "parts": parts,
        "format_key": format_key,
        "teaching_mode": teaching_mode,
    }


def parse_search_page(soup: BeautifulSoup) -> list[dict]:
    listings: list[dict] = []
    for header in soup.select(".searchhit-header"):
        card = header.parent
        if card is None:
            continue
        listing = parse_search_listing(card)
        if listing is not None:
            listings.append(listing)
    return listings


def enrich_listing_from_detail(listing: dict, soup: BeautifulSoup) -> dict:
    overview = soup.select_one("#uebersicht") or soup.select_one(".tab-content") or soup
    text = overview.get_text("\n", strip=True)
    html = str(overview)

    date_match = DATE_RANGE_RE.search(text)
    if date_match:
        listing["start_date"] = _iso_date(date_match.group(1))
        listing["end_date"] = _iso_date(date_match.group(2))

    duration_match = re.search(r"Seminardauer\s*\n?\s*(\d+)\s*Stunden", text, re.IGNORECASE)
    if duration_match:
        listing["duration_hours"] = int(duration_match.group(1))

    fee_match = re.search(r"Gebühr\s*\n?\s*([\d.]+,\d{2})", text, re.IGNORECASE)
    if fee_match:
        listing["course_fee"] = _parse_euro(fee_match.group(0))

    listing["location"] = resolve_location(
        listing.get("location_label", ""),
        listing.get("title", ""),
        html,
    )

    buy_form = overview.select_one("form.uni_warenkorb_buy_form")
    waitlist = buy_form.select_one('input[name="waitlist"]') if buy_form else None
    if buy_form is None:
        listing["availability"] = "unknown"
    elif waitlist is not None and waitlist.get("value", "").lower() == "true":
        listing["availability"] = "waitlist"
    else:
        listing["availability"] = "available"

    return listing


def listing_to_offer(listing: dict) -> RawCourseOffer:
    location = listing.get("location") or resolve_location(
        listing.get("location_label", ""),
        listing.get("title", ""),
    )
    trade_name = "Hörakustiker"
    parts = listing["parts"]
    return RawCourseOffer(
        title=build_course_title(trade_name, parts),
        trade_name=trade_name,
        parts=parts,
        format_key=listing["format_key"],
        teaching_mode=listing["teaching_mode"],
        start_date=listing.get("start_date"),
        end_date=listing.get("end_date"),
        duration_hours=listing.get("duration_hours"),
        course_fee=listing.get("course_fee"),
        city=location["city"],
        street=location.get("street", ""),
        zip_code=location.get("zip_code", ""),
        availability=listing.get("availability", "unknown"),
        source_url=listing["detail_url"],
        scraped_raw={
            "provider": PROVIDER_NAME,
            "provider_overview": AFH_OVERVIEW_URL,
            "afh_listing_title": listing["title"],
            "afh_location_label": listing.get("location_label", ""),
        },
    )
