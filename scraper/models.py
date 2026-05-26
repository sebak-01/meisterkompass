"""
scraper/models.py

Tracks the history of scraper runs for monitoring and debugging.
Each time the weekly scraper pipeline runs, one ScraperRun record is created
per chamber, recording outcome, stats, and any errors encountered.
"""

from django.db import models

from chambers.models import Chamber


class ScraperRun(models.Model):
    """
    Log entry for a single scraper execution against one chamber.

    Created automatically by the scraper runner — do not create manually.
    Read-only in the admin interface.
    """

    class Status(models.TextChoices):
        SUCCESS  = "success",  "Success"
        PARTIAL  = "partial",  "Partial (some errors)"
        FAILED   = "failed",   "Failed"
        SKIPPED  = "skipped",  "Skipped (site unreachable)"

    chamber = models.ForeignKey(
        Chamber,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="scraper_runs",
        help_text="The chamber this run targeted (null = full pipeline run)",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUCCESS,
    )

    # --- Stats ---
    offers_created = models.PositiveIntegerField(
        default=0,
        help_text="Number of new TradeOffer records created",
    )
    offers_updated = models.PositiveIntegerField(
        default=0,
        help_text="Number of existing TradeOffer records updated",
    )
    bundles_created = models.PositiveIntegerField(
        default=0,
        help_text="Number of new CourseBundle records created",
    )
    bundles_updated = models.PositiveIntegerField(
        default=0,
        help_text="Number of existing CourseBundle records updated",
    )
    exam_fees_updated = models.PositiveIntegerField(
        default=0,
        help_text="Number of ExamFee records updated (scraper_may_overwrite=True only)",
    )

    # --- Error details ---
    error_log = models.TextField(
        blank=True,
        help_text="Full error output or traceback if the run failed or was partial",
    )

    started_at  = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Scraper Run"
        verbose_name_plural = "Scraper Runs"

    def __str__(self):
        chamber_name = self.chamber.name if self.chamber else "All chambers"
        return f"{chamber_name} — {self.started_at:%Y-%m-%d %H:%M} — {self.get_status_display()}"

    @property
    def duration_seconds(self) -> int | None:
        """Returns the run duration in seconds, or None if not yet finished."""
        if self.finished_at and self.started_at:
            return int((self.finished_at - self.started_at).total_seconds())
        return None
