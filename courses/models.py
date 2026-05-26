"""
courses/models.py
"""

from django.db import models
from django.core.exceptions import ValidationError
from chambers.models import Chamber, Trade


class CourseFormat(models.TextChoices):
    FULL_TIME    = "full_time",    "Vollzeit"
    PART_TIME    = "part_time",    "Teilzeit"
    PART_OR_FULL = "part_or_full", "Teil- oder Vollzeit"


class TeachingMode(models.TextChoices):
    PRESENCE = "presence", "Präsenz"
    ONLINE   = "online",   "Online"
    HYBRID   = "hybrid",   "Hybrid"


class Availability(models.TextChoices):
    AVAILABLE = "available", "Freie Plätze"
    FEW_SPOTS = "few_spots", "Wenige Plätze"
    FULL      = "full",      "Ausgebucht"
    UNKNOWN   = "unknown",   "Unbekannt"


class ExamSourceType(models.TextChoices):
    SCRAPED      = "scraped",      "Scraped automatically"
    PDF_MANUAL   = "pdf_manual",   "Taken from PDF (manually entered)"
    ADMIN_MANUAL = "admin_manual", "Entered via admin interface"


class CourseOffer(models.Model):
    """
    One course offering exactly as listed on the chamber website.
    """

    chamber = models.ForeignKey(
        Chamber, on_delete=models.CASCADE, related_name="course_offers",
    )
    trade = models.ForeignKey(
        Trade, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="course_offers",
        help_text="Leave blank for generic Parts III+IV courses.",
    )
    title        = models.CharField(max_length=300)
    has_part_1   = models.BooleanField(default=False, verbose_name="Part I")
    has_part_2   = models.BooleanField(default=False, verbose_name="Part II")
    has_part_3   = models.BooleanField(default=False, verbose_name="Part III")
    has_part_4   = models.BooleanField(default=False, verbose_name="Part IV")
    format       = models.CharField(max_length=20, choices=CourseFormat.choices)
    teaching_mode = models.CharField(
        max_length=20, choices=TeachingMode.choices,
        default=TeachingMode.PRESENCE, verbose_name="Unterrichtsform",
    )
    start_date     = models.DateField(null=True, blank=True)
    end_date       = models.DateField(null=True, blank=True)
    duration_hours = models.PositiveIntegerField(null=True, blank=True,
                                                  verbose_name="Duration (hours)")

    # Kursgebühr
    course_fee = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True,
                                      help_text="Course fee in EUR, excluding exam fees.")

    # Prüfungsgebühr — only populated when stated directly on the course page
    # (e.g. HWK Trier). For the authoritative per-part record see ExamFee.
    exam_fee_scraped = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        verbose_name="Prüfungsgebühr (scraped)",
        help_text=(
            "Exam fee as stated on this specific course page. "
            "May cover one or multiple parts. "
            "The ExamFee model holds the per-part breakdown for the total-cost calculator."
        ),
    )

    city          = models.CharField(max_length=100, blank=True)
    location_name = models.CharField(max_length=200, blank=True)
    street        = models.CharField(max_length=200, blank=True)
    zip_code      = models.CharField(max_length=10,  blank=True)
    latitude      = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude     = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    availability = models.CharField(max_length=20, choices=Availability.choices,
                                     default=Availability.UNKNOWN)
    is_active     = models.BooleanField(default=True)
    source_url    = models.URLField(blank=True)
    last_scraped_at = models.DateTimeField(null=True, blank=True)
    scraped_raw   = models.JSONField(null=True, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chamber__name", "trade__name", "start_date"]
        verbose_name = "Course Offer"
        verbose_name_plural = "Course Offers"

    def __str__(self):
        return f"{self.chamber} · {self.title}"

    def clean(self):
        if not any([self.has_part_1, self.has_part_2, self.has_part_3, self.has_part_4]):
            raise ValidationError("A CourseOffer must include at least one exam part.")

    @property
    def parts_label(self) -> str:
        roman = {1: "I", 2: "II", 3: "III", 4: "IV"}
        included = [roman[p] for p, f in [(1, self.has_part_1), (2, self.has_part_2),
                                           (3, self.has_part_3), (4, self.has_part_4)] if f]
        if not included:
            return "—"
        return ("Part " if len(included) == 1 else "Parts ") + " + ".join(included)

    @property
    def included_parts(self) -> list[int]:
        return [p for p, f in [(1, self.has_part_1), (2, self.has_part_2),
                                (3, self.has_part_3), (4, self.has_part_4)] if f]


class ExamFee(models.Model):
    PART_CHOICES = [
        (1, "Part I   – Practical/technical"),
        (2, "Part II  – Theory/technical"),
        (3, "Part III – Business administration"),
        (4, "Part IV  – Vocational training"),
    ]
    chamber           = models.ForeignKey(Chamber, on_delete=models.CASCADE, related_name="exam_fees")
    trade             = models.ForeignKey(Trade,   on_delete=models.CASCADE, related_name="exam_fees")
    part              = models.IntegerField(choices=PART_CHOICES)
    fee               = models.DecimalField(max_digits=8, decimal_places=2)
    scraper_may_overwrite = models.BooleanField(default=True)
    manually_verified = models.BooleanField(default=False)
    source_type       = models.CharField(max_length=20, choices=ExamSourceType.choices,
                                          default=ExamSourceType.SCRAPED)
    source_url        = models.URLField(blank=True)
    valid_from        = models.DateField(null=True, blank=True)
    valid_until       = models.DateField(null=True, blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chamber__name", "trade__name", "part"]
        verbose_name = "Exam Fee"
        verbose_name_plural = "Exam Fees"
        unique_together = [("chamber", "trade", "part")]

    def __str__(self):
        roman = {1: "I", 2: "II", 3: "III", 4: "IV"}
        return f"{self.chamber} · {self.trade} · Part {roman[self.part]} · {self.fee} €"