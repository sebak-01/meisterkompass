"""
courses/admin.py
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import CourseOffer, ExamFee


@admin.register(CourseOffer)
class CourseOfferAdmin(admin.ModelAdmin):
    list_display = (
        "title", "chamber", "trade", "parts_label",
        "format", "teaching_mode", "start_date",
        "duration_hours", "course_fee", "city", "availability", "is_active",
    )
    list_filter  = ("chamber", "trade", "format", "teaching_mode",
                    "availability", "is_active")
    search_fields = ("title", "chamber__name", "trade__name", "city")
    readonly_fields = ("parts_label", "last_scraped_at", "scraped_raw",
                       "created_at", "updated_at")
    date_hierarchy = "start_date"

    fieldsets = (
        ("Course Identity", {
            "fields": ("chamber", "trade", "title", "format", "teaching_mode", "is_active"),
        }),
        ("Exam Parts Covered", {
            "fields": ("has_part_1", "has_part_2", "has_part_3", "has_part_4", "parts_label"),
        }),
        ("Schedule & Duration", {
            "fields": ("start_date", "end_date", "duration_hours"),
        }),
        ("Fees", {"fields": ("course_fee",)}),
        ("Location", {
            "fields": ("city", "location_name", "street", "zip_code", "latitude", "longitude"),
        }),
        ("Status & Source", {
            "fields": ("availability", "source_url"),
        }),
        ("Scraper Metadata", {
            "fields": ("last_scraped_at", "scraped_raw", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Parts")
    def parts_label(self, obj):
        return obj.parts_label


@admin.register(ExamFee)
class ExamFeeAdmin(admin.ModelAdmin):
    list_display = (
        "chamber", "trade", "part", "fee",
        "source_type", "manually_verified", "scraper_may_overwrite", "updated_at",
    )
    list_filter  = ("chamber", "trade", "part", "source_type",
                    "manually_verified", "scraper_may_overwrite")
    search_fields = ("chamber__name", "trade__name")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Fee", {"fields": ("chamber", "trade", "part", "fee")}),
        ("Source & Verification", {
            "fields": ("source_type", "source_url", "manually_verified", "scraper_may_overwrite"),
        }),
        ("Validity", {"fields": ("valid_from", "valid_until"), "classes": ("collapse",)}),
        ("Metadata", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.manually_verified:
            return self.readonly_fields + ("fee", "part", "chamber", "trade")
        return self.readonly_fields