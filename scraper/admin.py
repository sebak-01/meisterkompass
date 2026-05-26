"""
scraper/admin.py

Admin configuration for ScraperRun.
Read-only — scraper logs should never be edited manually.
"""

from django.contrib import admin

from .models import ScraperRun


@admin.register(ScraperRun)
class ScraperRunAdmin(admin.ModelAdmin):
    list_display = (
        "chamber", "status", "started_at", "duration_display",
        "offers_created", "offers_updated",
        "bundles_created", "bundles_updated",
        "exam_fees_updated",
    )
    list_filter  = ("status", "chamber")
    readonly_fields = (
        "chamber", "status",
        "offers_created", "offers_updated",
        "bundles_created", "bundles_updated",
        "exam_fees_updated",
        "error_log",
        "started_at", "finished_at",
    )
    # Prevent manual creation of log entries
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Duration")
    def duration_display(self, obj):
        secs = obj.duration_seconds
        if secs is None:
            return "—"
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m {secs % 60}s"
