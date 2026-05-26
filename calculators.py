"""
courses/calculators.py

Calculates total and partial costs for a Meister qualification
at a given chamber and trade, based on CourseOffer + ExamFee records.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from courses.models import CourseOffer, ExamFee


@dataclass
class PartCost:
    """Cost breakdown for one exam part."""
    part: int
    course_fee: Decimal | None
    exam_fee: Decimal | None
    offer_title: str = ""


@dataclass
class TotalCostResult:
    chamber_name: str
    trade_name: str

    parts: list[PartCost] = field(default_factory=list)
    total_course_fees: Decimal = Decimal("0.00")
    total_exam_fees:   Decimal = Decimal("0.00")
    grand_total:       Decimal = Decimal("0.00")

    all_parts_available: bool = False
    missing_course_parts: list[int] = field(default_factory=list)
    missing_exam_fees:    list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def calculate_total_cost(
    chamber_slug: str,
    trade_slug: str,
) -> TotalCostResult | None:
    """
    Calculates the full cost breakdown for a Meister qualification.

    Looks for CourseOffer records that together cover all four parts.
    Where a single offer covers multiple parts (e.g. I+II together),
    the fee is attributed proportionally per part for the breakdown,
    but displayed as a bundle in the frontend.

    Returns None if no CourseOffer exists for this chamber + trade.
    """
    from chambers.models import Chamber, Trade

    try:
        chamber = Chamber.objects.get(slug=chamber_slug)
        trade   = Trade.objects.get(slug=trade_slug)
    except (Chamber.DoesNotExist, Trade.DoesNotExist):
        return None

    offers = CourseOffer.objects.filter(
        chamber=chamber, trade=trade, is_active=True,
    )
    if not offers.exists():
        return None

    # Map each part to the offer that covers it (first active offer found)
    part_to_offer: dict[int, CourseOffer] = {}
    for offer in offers:
        for part in offer.included_parts:
            if part not in part_to_offer:
                part_to_offer[part] = offer

    missing_course = [p for p in [1, 2, 3, 4] if p not in part_to_offer]

    # Exam fees
    exam_fee_map = {
        ef.part: ef.fee
        for ef in ExamFee.objects.filter(chamber=chamber, trade=trade)
    }
    missing_exam = [p for p in [1, 2, 3, 4] if p not in exam_fee_map]

    # Build per-part breakdown
    parts_list = []
    for part in [1, 2, 3, 4]:
        offer = part_to_offer.get(part)
        if offer:
            # Distribute fee evenly across all parts the offer covers
            n = len(offer.included_parts)
            per_part_fee = (offer.course_fee / n) if offer.course_fee else None
        else:
            per_part_fee = None

        parts_list.append(PartCost(
            part=part,
            course_fee=per_part_fee,
            exam_fee=exam_fee_map.get(part),
            offer_title=offer.title if offer else "",
        ))

    total_course = sum((p.course_fee for p in parts_list if p.course_fee), Decimal("0.00"))
    total_exam   = sum((p.exam_fee   for p in parts_list if p.exam_fee),   Decimal("0.00"))

    warnings = []
    if missing_course:
        roman = {1: "I", 2: "II", 3: "III", 4: "IV"}
        warnings.append(
            f"No course offer found for part(s): {', '.join(roman[p] for p in missing_course)}. "
            "Grand total cannot be calculated."
        )
    if missing_exam:
        roman = {1: "I", 2: "II", 3: "III", 4: "IV"}
        warnings.append(
            f"No exam fee on record for part(s): {', '.join(roman[p] for p in missing_exam)}."
        )

    return TotalCostResult(
        chamber_name=chamber.name,
        trade_name=trade.name,
        parts=parts_list,
        total_course_fees=total_course,
        total_exam_fees=total_exam,
        grand_total=total_course + total_exam,
        all_parts_available=not missing_course and not missing_exam,
        missing_course_parts=missing_course,
        missing_exam_fees=missing_exam,
        warnings=warnings,
    )