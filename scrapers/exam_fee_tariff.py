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
    try:
        text = extract_pdf_text(response.content)
    except Exception as exc:
        logger.warning("%s: could not read exam-fee PDF (%s): %s", label, pdf_url, exc)
        return ""
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

_TRIER_TEIL_LABEL_RE = re.compile(r"\(Teil\s+(I{1,3}|IV)\)", re.IGNORECASE)

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


def parse_trier_meister_fees(text: str) -> dict[int, float]:
    """
    HWK Trier Gebührenverzeichnis (section 3.4 Meisterprüfungen):
    four Teil labels followed by Euro amounts on separate lines.
    """
    lower = text.lower()
    start = lower.find("meisterprüfungen")
    if start < 0:
        return {}
    end = lower.find("fortbildungsprüfungen", start + 10)
    section = text[start:end if end > start else start + 2000]

    teil_order = _TRIER_TEIL_LABEL_RE.findall(section)
    if len(teil_order) < 4:
        return {}

    amounts: list[float] = []
    for match in re.finditer(r"\b([\d.]+)(?:,(\d{2}))?\s*€", section):
        amounts.append(german_amount(match.group(1), match.group(2)))
    amounts = [amount for amount in amounts if amount >= 100]
    if len(amounts) < 4:
        return {}

    fees: dict[int, float] = {}
    for roman, fee in zip(teil_order[:4], amounts[:4]):
        fees[ROMAN[roman.upper()]] = fee
    return fees


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


# ---------------------------------------------------------------------------
# City states, Bremen, BW, Bavaria B.IV, Thüringen
# ---------------------------------------------------------------------------

_BERLIN_PART_RE = re.compile(
    r"Teil\s+(I{1,3}|IV|[1-4])\s+([\d.]+),(\d{2})",
    re.IGNORECASE,
)
_BERLIN_COMBO_RE = re.compile(
    r"Meisterprüfung zu einem Prüfungstermin\s+([\d.]+),(\d{2})",
    re.IGNORECASE,
)

_HH_PART_RE = re.compile(
    r"Prüfungsteil\s+(I{1,3}|IV)\s+([\d.,-]+)",
    re.IGNORECASE,
)
_HH_COMBO_RE = re.compile(
    r"Meisterprüfung\s*\(Teile\s+I-IV\s+im\s+Zusammenhang\)\s+([\d.,-]+)",
    re.IGNORECASE,
)

_BREMEN_TRADE_FEE_RE = re.compile(
    r"([A-Za-zÄÖÜäöüß\-,/ ]+?)\s+([\d.]+),(\d{2})\s*€",
)
_BREMEN_TEIL_III_RE = re.compile(
    r"c\)\s*Teil\s+III[^€]*?([\d.]+),(\d{2})\s*€",
    re.IGNORECASE,
)
_BREMEN_TEIL_IV_RE = re.compile(
    r"AEVO.*?([\d.]+),(\d{2})\s*€",
    re.IGNORECASE | re.DOTALL,
)

_BW_PART_RE = re.compile(
    r"Teil\s+(I{1,3}|IV)\s+([\d.]+),(\d{2})",
    re.IGNORECASE,
)
_BW_SUBSECTION_PART_RE = re.compile(
    r"3\.2\.2\.(?:[1-5]\s+)?(?:Teilgebühr\s+(?:für\s+)?)?Prüfungsteil\s+(I{1,3}|IV)\s+([\d.]+),(\d{2})",
    re.IGNORECASE,
)
_BW_COMBO_RES = (
    re.compile(
        r"Meisterprüfung,?\s*Teile?\s+(?:I\s*[-–]\s*IV|1\s*[-–]\s*4)\s+zusammen\s+([\d.]+),(\d{2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"Meisterprüfung\s+Teil\s+I-IV\s+zusammen[\s\S]{0,160}?([\d.]+),(\d{2})",
        re.IGNORECASE,
    ),
    re.compile(r"Gesamtprüfung\s+([\d.]+),(\d{2})", re.IGNORECASE),
    re.compile(r"alle\s+vier\s+Prüfungsteile\s+([\d.]+),(\d{2})", re.IGNORECASE),
    re.compile(r"Teile\s+I\s+bis\s+IV\s+([\d.]+),(\d{2})", re.IGNORECASE),
)

_ULM_INFOBLATT_PARTS_RE = re.compile(
    r"Meisterprüfungsgebühr von (\d+) Euro "
    r"\(Teil I = (\d+) Euro, Teil II = (\d+) Euro, Teil III = (\d+) Euro, Teil IV =\s*"
    r"(\d+) Euro\)",
    re.IGNORECASE | re.DOTALL,
)
_ULM_NEBENKOSTEN_ROW_RE = re.compile(
    r"^(.+?)\s+([\d.]+(?:/[\d.]+)?)\s*$",
    re.MULTILINE,
)

_HTML_BW_PART_RE = re.compile(
    r"Teil\s+(I{1,3}|IV)\s*(?:\([^)]*\))?(?:\s*/[^\n:]*)?:\s*([\d.]+)(?:,(\d{2}))?\s*Euro",
    re.IGNORECASE,
)

_BAVARIA_B_IV_PART_RE = re.compile(
    r"Teil\s+(I{1,3}|IV)\s+([\d.]+),(\d{2})",
    re.IGNORECASE,
)

_THURINGIA_PART_RES = {
    1: re.compile(r"5\.1\s+Teil\s+I\s+([\d.]+),(\d{2})\s*€", re.IGNORECASE),
    2: re.compile(r"5\.2\s+Teil\s+II\s+([\d.]+),(\d{2})\s*€", re.IGNORECASE),
    3: re.compile(r"5\.3\s+Teil\s+III[\s\S]{0,160}?([\d.]+),(\d{2})\s*€", re.IGNORECASE),
    4: re.compile(r"5\.4\s+Teil\s+IV[\s\S]{0,120}?([\d.]+),(\d{2})\s*€", re.IGNORECASE),
}


def _hh_amount(raw: str) -> float:
    cleaned = raw.strip().replace(".", "").replace(",", ".")
    cleaned = cleaned.rstrip("-")
    return float(cleaned)


def parse_berlin_meister_fees(text: str) -> tuple[dict[int, float], dict[tuple[int, ...], float]]:
    fees: dict[int, float] = {}
    combos: dict[tuple[int, ...], float] = {}
    block = text
    start = text.lower().find("abnahme von teilprüfungen")
    if start >= 0:
        block = text[start:start + 400]
    for match in _BERLIN_PART_RE.finditer(block):
        token = match.group(1).upper()
        part = ROMAN[token] if token in ROMAN else int(token)
        fees[part] = german_amount(match.group(2), match.group(3))
    combo_m = _BERLIN_COMBO_RE.search(text)
    if combo_m:
        combos[(1, 2, 3, 4)] = german_amount(combo_m.group(1), combo_m.group(2))
    return fees, combos


def parse_hamburg_meister_fees(text: str) -> tuple[dict[int, float], dict[tuple[int, ...], float]]:
    fees: dict[int, float] = {}
    combos: dict[tuple[int, ...], float] = {}
    block = text
    start = text.lower().find("meisterprüfungen")
    if start >= 0:
        end = text.lower().find("schaumeister", start + 10)
        block = text[start:end if end > start else start + 1200]
    for match in _HH_PART_RE.finditer(block):
        fees[ROMAN[match.group(1).upper()]] = _hh_amount(match.group(2))
    combo_m = _HH_COMBO_RE.search(block)
    if combo_m:
        combos[(1, 2, 3, 4)] = _hh_amount(combo_m.group(1))
    return fees, combos


def parse_bremen_meister_fees(text: str) -> tuple[dict[str, dict[int, float]], dict[int, float]]:
    """Return ({trade_label: {part: fee}}, generic_part_fees)."""
    trade_fees: dict[str, dict[int, float]] = {}
    generic: dict[int, float] = {}

    start = text.find("3. Abnahme und Wiederholung der Meisterprüfung")
    end = text.find("4. Entscheidungen", start + 1) if start >= 0 else -1
    block = text[start:end if end > start else start + 5000] if start >= 0 else text

    teil_i = re.search(r"a\)\s*Teil I[\s\S]*?(?=b\)\s*Teil II)", block, re.IGNORECASE)
    teil_ii = re.search(r"b\)\s*Teil II[\s\S]*?(?=c\)\s*Teil III)", block, re.IGNORECASE)
    for part, section in ((1, teil_i), (2, teil_ii)):
        if not section:
            continue
        for match in _BREMEN_TRADE_FEE_RE.finditer(section.group(0)):
            trade = match.group(1).strip()
            if not trade or trade.lower().startswith("teil"):
                continue
            trade_fees.setdefault(trade, {})[part] = german_amount(match.group(2), match.group(3))

    teil_iii = _BREMEN_TEIL_III_RE.search(block)
    if teil_iii:
        generic[3] = german_amount(teil_iii.group(1), teil_iii.group(2))

    teil_iv = _BREMEN_TEIL_IV_RE.search(text)
    if teil_iv:
        generic[4] = german_amount(teil_iv.group(1), teil_iv.group(2))

    return trade_fees, generic


def parse_bw_322_meister_fees(text: str) -> tuple[dict[int, float], dict[tuple[int, ...], float]]:
    """Baden-Württemberg Gebührenverzeichnis section 3.2.2 (Meisterprüfung)."""
    fees: dict[int, float] = {}
    combos: dict[tuple[int, ...], float] = {}
    lower = text.lower()
    start = lower.find("3.2.2 meisterprüfung")
    if start < 0:
        start = lower.find("3.2.2")
    if start < 0:
        start = lower.find("meisterprüfung")
    end = lower.find("3.2.3", start + 5) if start >= 0 else -1
    block = text[start:end if end > start else start + 2200] if start >= 0 else text

    for match in _BW_SUBSECTION_PART_RE.finditer(block):
        fees[ROMAN[match.group(1).upper()]] = german_amount(match.group(2), match.group(3))

    column_layout = (
        len(fees) < 4
        and re.search(r"Teilgebühr\s+Prüfungsteil\s+IV", block, re.IGNORECASE)
        and re.search(r"Teilgebühr\s+Prüfungsteil\s+I\b", block, re.IGNORECASE)
    )
    if not column_layout and len(fees) < 4:
        for match in _BW_PART_RE.finditer(block):
            fees.setdefault(ROMAN[match.group(1).upper()], german_amount(match.group(2), match.group(3)))

    if len(fees) < 4 and (column_layout or "zusammen" in block.lower()):
        block_lower = block.lower()
        idx = block_lower.rfind("teilgebühr prüfungsteil iv")
        if idx < 0:
            idx = block_lower.find("zusammen")
        tail = block[idx:idx + 500]
        amounts = [
            german_amount(whole, cents)
            for whole, cents in re.findall(r"([\d.]+),(\d{2})", tail)
            if float(whole.replace(".", "") + "." + cents) >= 100
        ]
        if len(amounts) >= 5 and amounts[0] > amounts[1]:
            combos[(1, 2, 3, 4)] = amounts[0]
            fees = {1: amounts[1], 2: amounts[2], 3: amounts[3], 4: amounts[4]}

    for pattern in _BW_COMBO_RES:
        combo_m = pattern.search(block)
        if combo_m:
            combos[(1, 2, 3, 4)] = german_amount(combo_m.group(1), combo_m.group(2))
            break
    return fees, combos


def parse_ulm_infoblatt_fees(
    text: str,
) -> tuple[
    dict[int, float],
    dict[tuple[int, ...], float],
    dict[str, dict[int, float]],
    dict[str, dict[int, float]],
]:
    """
    Parse HWK Ulm Infoblatt Meisterprüfungsgebühr PDF.

    Returns generic per-part fees, the all-parts combo, trade-specific Part I totals
    (base fee + Nebenkosten), and optional Part I fee_max where Nebenkosten vary.
    """
    generic: dict[int, float] = {}
    combos: dict[tuple[int, ...], float] = {}
    trade_part1: dict[str, dict[int, float]] = {}
    trade_part1_max: dict[str, dict[int, float]] = {}

    parts_m = _ULM_INFOBLATT_PARTS_RE.search(text)
    if parts_m:
        combos[(1, 2, 3, 4)] = float(parts_m.group(1))
        generic = {
            1: float(parts_m.group(2)),
            2: float(parts_m.group(3)),
            3: float(parts_m.group(4)),
            4: float(parts_m.group(5)),
        }

    base_part1 = generic.get(1, 580.0)
    lower = text.lower()
    start = lower.find("handwerksberuf")
    end = lower.find("der aufstellung", start + 1) if start >= 0 else -1
    block = text[start:end if end > start else start + 1200] if start >= 0 else ""
    for match in _ULM_NEBENKOSTEN_ROW_RE.finditer(block):
        trade = match.group(1).strip()
        lower_trade = trade.lower()
        if (
            lower_trade.startswith("handwerksberuf")
            or lower_trade.endswith("nebenkosten in euro")
            or "handwerkskammer" in lower_trade
            or "seite" in lower_trade
        ):
            continue
        raw_amounts = match.group(2)
        if "/" in raw_amounts:
            lo_s, hi_s = raw_amounts.split("/", 1)
            lo = float(lo_s.replace(".", ""))
            hi = float(hi_s.replace(".", ""))
            if lo < 20 or hi < 20:
                continue
            trade_part1[trade] = {1: base_part1 + lo}
            trade_part1_max[trade] = {1: base_part1 + hi}
        else:
            extra = float(raw_amounts.replace(".", ""))
            if extra < 20:
                continue
            trade_part1[trade] = {1: base_part1 + extra}

    return generic, combos, trade_part1, trade_part1_max


def parse_bw_meister_fees_from_html(text: str) -> tuple[dict[int, float], dict[tuple[int, ...], float]]:
    """Parse generic Teile I–IV amounts published on a chamber HTML page."""
    fees: dict[int, float] = {}
    start = text.lower().find("prüfungsgebühr")
    block = text[start:start + 1200] if start >= 0 else text
    for match in _HTML_BW_PART_RE.finditer(block):
        fees[ROMAN[match.group(1).upper()]] = german_amount(match.group(2), match.group(3))
    return fees, {}


def parse_bavaria_b_iv_meister_fees(text: str) -> dict[int, float]:
    fees: dict[int, float] = {}
    lower = text.lower()
    start = lower.find("b. iv")
    if start < 0:
        start = lower.find("b.iv")
    if start < 0:
        start = lower.find("meisterprüfung")
    block = text[start:start + 1500] if start >= 0 else text
    for match in _BAVARIA_B_IV_PART_RE.finditer(block):
        fees[ROMAN[match.group(1).upper()]] = german_amount(match.group(2), match.group(3))
    return fees


def parse_thuringia_meister_fees(text: str) -> dict[int, float]:
    fees: dict[int, float] = {}
    for part, pattern in _THURINGIA_PART_RES.items():
        match = pattern.search(text)
        if match:
            fees[part] = german_amount(match.group(1), match.group(2))
    return fees


def trade_part_fee_rows(
    chamber_slug: str,
    trade_fees: dict[str, dict[int, float]],
    *,
    source_url: str,
    trade_slug_fn,
    qualifier: str = "",
) -> list[dict]:
    rows: list[dict] = []
    for trade_name, parts in trade_fees.items():
        trade_slug = trade_slug_fn(trade_name)
        for part, fee in parts.items():
            rows.append({
                "chamber_slug": chamber_slug,
                "trade_slug": trade_slug,
                "part": part,
                "fee": float(fee),
                "qualifier": qualifier,
                "source_url": source_url,
            })
    return rows


def published_rows_from_part_and_combo(
    chamber_slug: str,
    fees: dict[int, float],
    combos: dict[tuple[int, ...], float],
    *,
    source_url: str,
    qualifier: str = "",
) -> list[dict]:
    rows = part_fee_rows(chamber_slug, fees, source_url=source_url, qualifier=qualifier)
    rows.extend(combo_fee_rows(chamber_slug, combos, source_url=source_url, qualifier=qualifier))
    return rows


def published_bw_322_exam_fee_rows(
    scraper,
    *,
    chamber_slug: str,
    page_url: str,
    pdf_fallback: str | None,
    fallback_fees: dict[int, float],
    fallback_combos: dict[tuple[int, ...], float],
    label: str,
    parse_pdf_fn=parse_bw_322_meister_fees,
    parse_html_fn=None,
) -> list[dict]:
    """Shared weekly-tariff helper for BW chambers (PDF and/or HTML sources)."""
    fees: dict[int, float] = {}
    combos: dict[tuple[int, ...], float] = {}

    if pdf_fallback:
        text = download_pdf_text(scraper, pdf_fallback, label=label)
        if text:
            fees, combos = parse_pdf_fn(text)

    if not fees and parse_html_fn:
        soup = scraper.parse_html(page_url)
        if soup is not None:
            fees, combos = parse_html_fn(soup.get_text("\n", strip=True))

    if not fees:
        logger.warning("%s: using fallback Meister exam fees.", label)
        fees, combos = fallback_fees, fallback_combos
    return published_rows_from_part_and_combo(
        chamber_slug,
        fees,
        combos,
        source_url=page_url,
    )


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
