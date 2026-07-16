"""
scrapers/fees.py

Pure (Django-free) port of ``CourseOffer.resolved_exam_fee_info``.

Builds the per-part exam-fee lookup from scraped rows overlaid with the
hand-curated ``data/manual/exam_fees_manual.json`` (manual always wins, which
subsumes the old ``scraper_may_overwrite`` / ``manually_verified`` flags), then
resolves a single display object per course offer.
"""

from decimal import Decimal

# lookup key: (chamber_slug, trade_slug_or_None, part_or_partset) -> fee dict
#   part_or_partset is either a single int (per-part fee) or a frozenset[int]
#   (an exact combo-bundle override for that exact set of parts together).
#   fee dict: {"fee": float, "fee_max": float|None, "qualifier": str}
ExamFeeLookup = dict[tuple[str, str | None, int | frozenset[int]], dict]


def _fmt(amount: Decimal) -> str:
    """German number without decimals, e.g. '1.130 €'."""
    return f"{amount:,.0f}".replace(",", ".") + " €"


_INLINE_DISPLAY_QUALIFIERS = frozenset({"bis zu", "ca."})


def _fee_display(fee_str: str, qualifier: str) -> str:
    """Show short fee markers inline; keep longer notes for tooltips only."""
    q = qualifier.strip()
    if q in _INLINE_DISPLAY_QUALIFIERS:
        return f"{q} {fee_str}"
    return fee_str


def build_exam_fee_lookup(scraped_rows: list[dict], manual_rows: list[dict]) -> ExamFeeLookup:
    """
    Merge scraped per-part exam fees with manual entries. Manual wins on
    collision. Each row carries chamber_slug, part, fee and optionally
    trade_slug (None/"" => all-trades), fee_max, qualifier.

    A row may carry a ``parts`` list instead of a single ``part`` to register
    an exact combo-bundle fee (e.g. Teile I+II at a flat price).
    """
    lookup: ExamFeeLookup = {}

    def add(row: dict):
        trade = row.get("trade_slug") or None
        if "parts" in row:
            # Combo-bundle row: an exact total for a SET of parts booked/
            # examined together (e.g. Teile I+II at a flat discounted price
            # rather than the sum of each part's individual fee).
            key = (row["chamber_slug"], trade, frozenset(int(p) for p in row["parts"]))
        else:
            key = (row["chamber_slug"], trade, int(row["part"]))
        lookup[key] = {
            "fee":       float(row["fee"]),
            "fee_max":   float(row["fee_max"]) if row.get("fee_max") else None,
            "qualifier": row.get("qualifier") or "",
        }

    for row in scraped_rows:
        add(row)
    for row in manual_rows:   # manual overlay wins
        add(row)
    return lookup


def resolve_exam_fee(
    chamber_slug: str,
    trade_slug: str | None,
    included_parts: list[int],
    exam_fee_scraped: float | None,
    lookup: ExamFeeLookup,
    exam_fee_qualifier: str = "",
) -> dict:
    """
    Returns the best exam-fee display info for a course offer.

    Priority:
      1. ``exam_fee_scraped`` stated on the course page (Trier/Pfalz/Saarland)
      2a. Exact combo-bundle override for the offer's full set of parts
          (e.g. Teile I+II at a flat discounted price — see HWK Frankfurt-
          Rhein-Main, which charges 730 € for I+II rather than 420+420=840 €)
      2b. ExamFee lookup — summed across the offer's parts; trade-specific
          first, then all-trades (trade=None) fallback.

    Returns {fee, fee_max, qualifier, display, from_tariff}.
    ``from_tariff`` is True when the fee comes from the Gebührenverzeichnis
    lookup (scraped PDF rows or manual exam_fees_manual.json), False when
    stated on the course page.
    """
    # Priority 1: scraped fee on the course page
    if exam_fee_scraped is not None:
        fee = Decimal(str(exam_fee_scraped))
        qualifier = exam_fee_qualifier.strip()
        fee_str = _fmt(fee)
        display = _fee_display(fee_str, qualifier)
        return {
            "fee": float(fee), "fee_max": None, "qualifier": qualifier,
            "display": display, "from_tariff": False,
        }

    # Priority 2a: exact combo-bundle override for this exact set of parts.
    # Checked trade-specific first, then the all-trades (trade=None) fallback
    # — same precedence as the per-part lookup below.
    parts_key = frozenset(included_parts)
    combo = lookup.get((chamber_slug, trade_slug, parts_key)) or lookup.get((chamber_slug, None, parts_key))
    if combo:
        fee = Decimal(str(combo["fee"]))
        fee_max = Decimal(str(combo["fee_max"])) if combo["fee_max"] is not None else None
        if fee_max is not None:
            display = f"{_fmt(fee)} bis {_fmt(fee_max)}"
            return {
                "fee": float(fee), "fee_max": float(fee_max), "qualifier": "",
                "display": display, "from_tariff": True,
            }
        qualifier = combo["qualifier"]
        fee_str = _fmt(fee)
        display = _fee_display(fee_str, qualifier)
        return {
            "fee": float(fee), "fee_max": None, "qualifier": qualifier,
            "display": display, "from_tariff": True,
        }

    # Priority 2b: per-part ExamFee lookup
    total_min = Decimal("0")
    total_max = Decimal("0")
    qualifier = ""
    found = False
    has_range = False

    for part in included_parts:
        ef = lookup.get((chamber_slug, trade_slug, part)) or lookup.get((chamber_slug, None, part))
        if not ef:
            continue
        fee = Decimal(str(ef["fee"]))
        fee_max = Decimal(str(ef["fee_max"])) if ef["fee_max"] is not None else None
        total_min += fee
        total_max += fee_max if fee_max is not None else fee
        if fee_max is not None:
            has_range = True
        if ef["qualifier"] and not qualifier:
            qualifier = ef["qualifier"]
        found = True

    if not found:
        return {"fee": None, "fee_max": None, "qualifier": "", "display": "", "from_tariff": False}

    if has_range:
        display = f"{_fmt(total_min)} bis {_fmt(total_max)}"
        return {
            "fee": float(total_min), "fee_max": float(total_max), "qualifier": "",
            "display": display, "from_tariff": True,
        }

    fee_str = _fmt(total_min)
    display = _fee_display(fee_str, qualifier)
    return {
        "fee": float(total_min), "fee_max": None, "qualifier": qualifier,
        "display": display, "from_tariff": True,
    }