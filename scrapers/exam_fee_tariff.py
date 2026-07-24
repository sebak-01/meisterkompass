"""
Shared helpers for chamber Gebührenverzeichnis / Gebührentarif scraping.

Course-page ``exam_fee_scraped`` always wins at resolve time. These helpers
only build chamber-wide tariff rows used as a fallback (and for AFBG tables).
"""

from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}

# Kassel's Gebührenverzeichnis PDF uses a Symbol-font encoding that pypdf
# extracts as Greek letters. Map known fee tokens observed in the 2025 PDF.
KASSEL_SYMBOL_FEES = {
    "ψφτ": 420.0,
    "χψτ": 340.0,
    "φχω": 235.0,
    "ϋχτ": 730.0,
    "ψύτ": 490.0,
    "όφτ": 820.0,
}


def german_amount(whole: str, cents: str | None = None) -> float:
    return float(whole.replace(".", "") + "." + (cents or "00"))


def extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf not installed — cannot parse exam-fee PDF.")
        return ""
    text = ""
    for page in PdfReader(BytesIO(content)).pages:
        text += (page.extract_text() or "") + "\n"
    return text


def download_pdf_text(scraper, pdf_url: str, *, label: str) -> str:
    response = scraper.get(pdf_url)
    if response is None:
        logger.warning("%s: could not fetch exam-fee PDF (%s).", label, pdf_url)
        return ""
    text = extract_pdf_text(response.content)
    if not text.strip():
        logger.warning("%s: empty text from exam-fee PDF (%s).", label, pdf_url)
    return text


def resolve_pdf_url_from_page(
    scraper,
    page_url: str,
    *,
    fallback_url: str | None = None,
    href_substrings: tuple[str, ...] = ("gebuehrenverzeichnis", "gebührenverzeichnis"),
    prefer_last: bool = False,
    skip_substrings: tuple[str, ...] = (),
    label: str = "exam-fee",
) -> str | None:
    """Find a PDF href on a chamber Rechtsgrundlagen / Gebühren page."""
    soup = scraper.parse_html(page_url)
    if soup is None:
        return fallback_url
    candidates: list[str] = []
    for link in soup.select("a[href]"):
        href = link.get("href") or ""
        low = href.lower()
        if not low.endswith(".pdf") and ".pdf" not in low:
            continue
        if skip_substrings and any(s in low for s in skip_substrings):
            continue
        text = " ".join(link.get_text(" ", strip=True).split()).lower()
        blob = f"{low} {text}"
        if any(s in blob for s in href_substrings):
            candidates.append(urljoin(page_url, href))
    if not candidates:
        return fallback_url
    return candidates[-1] if prefer_last else candidates[0]


def part_fee_rows(
    chamber_slug: str,
    fees: dict[int, float],
    *,
    source_url: str,
    qualifier: str = "",
    fee_max: dict[int, float] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for part, fee in sorted(fees.items()):
        row = {
            "chamber_slug": chamber_slug,
            "trade_slug": None,
            "part": part,
            "fee": float(fee),
            "qualifier": qualifier,
            "source_url": source_url,
        }
        if fee_max and part in fee_max:
            row["fee_max"] = float(fee_max[part])
        rows.append(row)
    return rows


def combo_fee_rows(
    chamber_slug: str,
    combos: dict[tuple[int, ...], float],
    *,
    source_url: str,
    qualifier: str = "",
) -> list[dict]:
    rows: list[dict] = []
    for parts, fee in combos.items():
        rows.append({
            "chamber_slug": chamber_slug,
            "trade_slug": None,
            "parts": list(parts),
            "fee": float(fee),
            "qualifier": qualifier,
            "source_url": source_url,
        })
    return rows


def fetch_pdf_and_parse(
    scraper,
    *,
    pdf_url: str,
    parse_fn: Callable[[str], dict[int, float]],
    label: str,
) -> dict[int, float]:
    text = download_pdf_text(scraper, pdf_url, label=label)
    if not text:
        return {}
    fees = parse_fn(text)
    if not fees:
        logger.warning("%s: could not parse Meister exam fees from PDF.", label)
    return fees


def merge_tariff_rows_last_good(
    previous: list[dict],
    fresh_by_chamber: dict[str, list[dict]],
) -> list[dict]:
    """
    Replace tariff rows per chamber when the weekly scrape returned rows;
    keep the previous rows when a chamber returned nothing (PDF/parse fail).
    """
    merged: dict[str, list[dict]] = {}
    for row in previous:
        merged.setdefault(row["chamber_slug"], []).append(row)
    for slug, rows in fresh_by_chamber.items():
        if rows:
            merged[slug] = rows
        elif slug not in merged:
            merged[slug] = []
    out: list[dict] = []
    for slug in sorted(merged):
        out.extend(merged[slug])
    return out


# ---------------------------------------------------------------------------
# Parsers for newly added Hesse / RLP Gebührenverzeichnisse
# ---------------------------------------------------------------------------

_KOBLENZ_PART_RE = re.compile(
    r"B\.II\.1\.[a-d]\s+Prüfungsteil\s+(I{1,3}|IV)\s*:[^\d]*bis\s*([\d.]+),(\d{2})",
    re.IGNORECASE,
)

_RH_RANGE_RE = re.compile(
    r"Teil\s+(I{1,3}|IV)\)?\s*([\d.]+)\s*[-–]\s*([\d.]+)",
    re.IGNORECASE,
)

_HESSE_PART_RE = re.compile(
    r"Teil\s+(I{1,3}|IV)\s+([\d.]+),(\d{2})",
    re.IGNORECASE,
)
_HESSE_PART_INT_RE = re.compile(
    r"Teil\s+(I{1,3}|IV)\s+(\d{2,4})(?:\s|$)",
    re.IGNORECASE,
)
_HESSE_COMBO_RE = re.compile(
    r"Teil\s+I\s+und\s+II\s+([\d.]+),(\d{2}).*?Teil\s+III\s+und\s+IV\s+([\d.]+),(\d{2})",
    re.IGNORECASE | re.DOTALL,
)
_HESSE_COMBO_INT_RE = re.compile(
    r"Teil\s+I\s+und\s+II\s+(\d{2,4}).*?Teil\s+III\s+und\s+IV\s+(\d{2,4})",
    re.IGNORECASE | re.DOTALL,
)
_HESSE_TOTAL_RE = re.compile(
    r"Höchstbetrag\s+([\d.]+),(\d{2})",
    re.IGNORECASE,
)
_HESSE_TOTAL_INT_RE = re.compile(
    r"Höchstbetrag\s+(\d{2,4})",
    re.IGNORECASE,
)


def parse_koblenz_meister_fees(text: str) -> tuple[dict[int, float], str]:
    """Return ({part: fee}, qualifier). Koblenz publishes ceiling amounts."""
    fees: dict[int, float] = {}
    for match in _KOBLENZ_PART_RE.finditer(text):
        part = ROMAN[match.group(1).upper()]
        fees[part] = german_amount(match.group(2), match.group(3))
    return fees, "bis zu"


def parse_rheinhessen_meister_fees(text: str) -> tuple[dict[int, float], dict[int, float]]:
    """Return (fee_min_by_part, fee_max_by_part) for Meisterprüfung ranges."""
    # Prefer the structured block under "Gebühren für Meisterprüfung".
    block = text
    start = text.lower().find("gebühren für meisterprüfung")
    if start >= 0:
        end = text.lower().find("gebühren für fortbildung", start)
        block = text[start:end if end > start else start + 2500]

    fees: dict[int, float] = {}
    fee_max: dict[int, float] = {}
    # PDF extracts ranges as four consecutive "min - max" lines after the four Teil bullets.
    # Fall back to searching Teil + range nearby.
    range_pairs = re.findall(r"(\d{2,4})\s*[-–]\s*(\d{2,4})", block)
    teil_labels = re.findall(r"\(Teil\s+(I{1,3}|IV)\)", block, flags=re.IGNORECASE)
    if len(teil_labels) >= 4 and len(range_pairs) >= 4:
        for roman, (lo, hi) in zip(teil_labels[:4], range_pairs[:4]):
            part = ROMAN[roman.upper()]
            fees[part] = float(lo)
            fee_max[part] = float(hi)
        return fees, fee_max

    for match in _RH_RANGE_RE.finditer(block):
        part = ROMAN[match.group(1).upper()]
        fees[part] = float(match.group(2))
        fee_max[part] = float(match.group(3))
    return fees, fee_max


def parse_hesse_schedule_fees(text: str) -> tuple[dict[int, float], dict[tuple[int, ...], float]]:
    """
    Shared Hesse schedule (Rhein-Main / Wiesbaden / Kassel):
      Teil I–IV fixed amounts + combo I+II / III+IV + Höchstbetrag all four.
    """
    fees: dict[int, float] = {}
    combos: dict[tuple[int, ...], float] = {}

    # Narrow to Meisterprüfung section when present.
    lower = text.lower()
    start = lower.find("meisterprüfung")
    if start >= 0:
        end = lower.find("fortbildungsprüfung", start + 10)
        section = text[start:end if end > start else start + 2000]
    else:
        section = text

    for match in _HESSE_PART_RE.finditer(section):
        fees[ROMAN[match.group(1).upper()]] = german_amount(match.group(2), match.group(3))
    if len(fees) < 4:
        for match in _HESSE_PART_INT_RE.finditer(section):
            fees.setdefault(ROMAN[match.group(1).upper()], float(match.group(2)))

    # Wiesbaden / Rhein-Main often put amounts on following lines after labels.
    if len(fees) < 4:
        labels = list(re.finditer(r"Teil\s+(I{1,3}|IV)\b", section, flags=re.IGNORECASE))
        amounts = [float(a) for a in re.findall(r"\b(\d{3,4})\b", section)]
        # After four Teil labels, the next four 3–4 digit ints are usually I–IV fees.
        if len(labels) >= 4 and len(amounts) >= 4:
            # Prefer amounts that appear after the first Teil label.
            after = section[labels[0].start():]
            after_amounts = [float(a) for a in re.findall(r"\b(\d{3,4})\b", after)]
            if len(after_amounts) >= 4:
                for roman_i, amount in zip(("I", "II", "III", "IV"), after_amounts[:4]):
                    fees[ROMAN[roman_i]] = amount
                if len(after_amounts) >= 6:
                    combos[(1, 2)] = after_amounts[4]
                    combos[(3, 4)] = after_amounts[5]
                if len(after_amounts) >= 7:
                    combos[(1, 2, 3, 4)] = after_amounts[6]

    combo_m = _HESSE_COMBO_RE.search(section)
    if combo_m:
        combos[(1, 2)] = german_amount(combo_m.group(1), combo_m.group(2))
        combos[(3, 4)] = german_amount(combo_m.group(3), combo_m.group(4))
    else:
        combo_i = _HESSE_COMBO_INT_RE.search(section)
        if combo_i:
            combos[(1, 2)] = float(combo_i.group(1))
            combos[(3, 4)] = float(combo_i.group(2))

    total_m = _HESSE_TOTAL_RE.search(section)
    if total_m:
        combos[(1, 2, 3, 4)] = german_amount(total_m.group(1), total_m.group(2))
    elif (1, 2, 3, 4) not in combos:
        # Integer "Höchstbetrag" often sits above a column of part fees (Wiesbaden).
        # Only accept it when the next number is larger than any single-part fee.
        total_i = _HESSE_TOTAL_INT_RE.search(section)
        if total_i:
            amount = float(total_i.group(1))
            part_vals = list(fees.values())
            if not part_vals or amount > max(part_vals):
                combos[(1, 2, 3, 4)] = amount

    # Kassel Symbol-font fallback.
    if len(fees) < 4:
        tokens = re.findall(r"[ψχφϋόύτωυ]+", section)
        decoded = [KASSEL_SYMBOL_FEES[t] for t in tokens if t in KASSEL_SYMBOL_FEES]
        # Expected order: I, II, III, IV, I+II, III+IV, all-four
        if len(decoded) >= 4:
            fees = {1: decoded[0], 2: decoded[1], 3: decoded[2], 4: decoded[3]}
            if len(decoded) >= 6:
                combos[(1, 2)] = decoded[4]
                combos[(3, 4)] = decoded[5]
            if len(decoded) >= 7:
                combos[(1, 2, 3, 4)] = decoded[6]

    return fees, combos


def find_gebuehrenverzeichnis_pdf_link(soup: BeautifulSoup, page_url: str) -> str | None:
    """Generic link picker used by chambers that only expose 'Gebührenverzeichnis'."""
    candidates: list[str] = []
    for link in soup.select("a[href]"):
        href = link.get("href") or ""
        text = " ".join(link.get_text(" ", strip=True).split()).lower()
        blob = f"{href.lower()} {text}"
        if "genehmigung" in blob:
            continue
        if "gebuehrenverzeichnis" in blob or "gebührenverzeichnis" in blob:
            if ".pdf" in href.lower() or href.lower().endswith(".pdf") or "securedl" in href.lower():
                candidates.append(urljoin(page_url, href))
    return candidates[0] if candidates else None
