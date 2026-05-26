"""
chambers/admin.py
"""

from django.contrib import admin
from .models import Chamber, Trade


@admin.register(Chamber)
class ChamberAdmin(admin.ModelAdmin):
    list_display  = ("name", "region", "city", "website", "updated_at")
    list_filter   = ("region",)
    search_fields = ("name", "city", "region")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Identity",  {"fields": ("name", "slug", "region", "website")}),
        ("Address",   {"fields": ("street", "city", "zip_code")}),
        ("Map",       {"fields": ("latitude", "longitude")}),
        ("Metadata",  {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display  = ("name", "is_mandatory", "berufenet_id", "berufenet_url", "updated_at")
    list_filter   = ("is_mandatory",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at", "berufenet_url")

    fieldsets = (
        ("Identity", {"fields": ("name", "slug", "is_mandatory")}),
        ("Berufenet", {
            "fields": ("berufenet_id", "berufenet_url"),
            "description": (
                "Optional: enter the numeric ID from the Berufenet URL to link "
                "this trade to its profile at web.arbeitsagentur.de/berufenet/"
            ),
        }),
        ("Metadata", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Berufenet URL")
    def berufenet_url(self, obj):
        from django.utils.html import format_html
        url = obj.berufenet_url
        if url:
            return format_html('<a href="{}" target="_blank">🔗 Berufenet</a>', url)
        return "—"