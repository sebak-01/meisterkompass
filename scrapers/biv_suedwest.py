"""Shared parser for ADB/BIV Südwest Bäcker Meistervorbereitung courses."""

from __future__ import annotations

import re
from typing import Literal

from .base import RawCourseOffer, build_course_title

BAKER_COURSE_URL = "https://bivsuedwest.de/meistervorbereitungskurse/"

STUTTGART_LOCATION = {
    "street": "Wilhelmstraße 7",
    "zip_code": "70182",
    "city": "Stuttgart",
}
KARLSRUHE_LOCATION = {
    "street": "Ottostr. 9",
    "zip_code": "76227",
    "city": "Karlsruhe",
}

_LOCATION_CONFIG = {
    "stuttgart": {
        "section_pattern": (
            r"Standort Stuttgart\s+\(Vollzeitkurs\)\s*:"
            r"(.*?)(?:Standort Karlsruhe|©|$)"
        ),
        "parts": [1, 2, 3, 4],
        "format_key": "full_time",
        "location": STUTTGART_LOCATION,
        "provider": "ADB Südwest e.V. Standort Stuttgart",
    },
    "karlsruhe": {
        "section_pattern": (
            r"Standort Karlsruhe\s+\(Teilzeitkurs\)\s*:"
            r"(.*?)(?:©|$)"
        ),
        "parts": [1, 2],
        "format_key": "part_time",
        "location": KARLSRUHE_LOCATION,
        "provider": "ADB Südwest e.V. Standort Karlsruhe",
    },
}


def parse_baker_offers(
    text: str,
    *,
    location: Literal["stuttgart", "karlsruhe"],
    source_url: str,
) -> list[RawCourseOffer]:
    """Parse a chamber-specific Bäcker course when the provider page lists it clearly."""
    config = _LOCATION_CONFIG[location]
    section_match = re.search(
        config["section_pattern"],
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if section_match is None:
        return []

    section = section_match.group(1)
    dates = re.search(
        r"Teile\s*1\s*-\s*4\s*:\s*(\d{2})\.(\d{2})\.\s*bis\s*"
        r"(\d{2})\.(\d{2})\.(\d{4})",
        section,
        re.IGNORECASE,
    )
    if dates is None:
        dates = re.search(
            r"Teile\s*1\s*-\s*2\s*:\s*(\d{2})\.(\d{2})\.\s*bis\s*"
            r"(\d{2})\.(\d{2})\.(\d{4})",
            section,
            re.IGNORECASE,
        )
    if dates is None:
        return []

    fee_match = re.search(
        r"gesamte Kursgebühr.*?beträgt\s*([\d.]+,\d{2})\s*Euro",
        section,
        re.IGNORECASE | re.DOTALL,
    )
    year = dates.group(5)
    fee = float(fee_match.group(1).replace(".", "").replace(",", ".")) if fee_match else None
    location_data = config["location"]
    return [RawCourseOffer(
        title=build_course_title("Bäcker", config["parts"]),
        trade_name="Bäcker",
        parts=config["parts"],
        format_key=config["format_key"],
        teaching_mode="presence",
        start_date=f"{year}-{dates.group(2)}-{dates.group(1)}",
        end_date=f"{year}-{dates.group(4)}-{dates.group(3)}",
        duration_hours=None,
        course_fee=fee,
        city=location_data["city"],
        street=location_data["street"],
        zip_code=location_data["zip_code"],
        availability="unknown",
        source_url=source_url,
        scraped_raw={
            "provider": config["provider"],
            "course_text": section[:700],
        },
    )]
