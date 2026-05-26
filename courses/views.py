"""
courses/views.py
"""

import json
from django.views.generic import ListView
from django.db.models import Q
from .models import CourseOffer, CourseFormat, TeachingMode
from chambers.models import Chamber, Trade

PER_PAGE_OPTIONS = [10, 20, 40, 60]
PER_PAGE_DEFAULT = 30


class CourseListView(ListView):
    model = CourseOffer
    template_name = "courses/list.html"
    context_object_name = "offers"

    def get_paginate_by(self, queryset):
        per_page = self.request.GET.get("per_page", "")
        if per_page == "all":
            return None
        try:
            val = int(per_page)
            if val in PER_PAGE_OPTIONS:
                return val
        except (ValueError, TypeError):
            pass
        return PER_PAGE_DEFAULT

    def _apply_filters(self, qs):
        p = self.request.GET
        if v := p.get("chamber"):   qs = qs.filter(chamber__slug=v)
        if v := p.get("trade"):     qs = qs.filter(trade__slug=v)
        if v := p.get("format"):    qs = qs.filter(format=v)
        if v := p.get("teaching"):  qs = qs.filter(teaching_mode=v)
        if v := p.get("date_from"): qs = qs.filter(start_date__gte=v)
        if v := p.get("date_to"):   qs = qs.filter(start_date__lte=v)

        # Parts filter: multi-value list + optional "include combos" checkbox
        selected_parts = [int(x) for x in p.getlist("part") if x.isdigit()]
        include_combos = p.get("include_combos") == "1"

        if selected_parts:
            q = Q()
            for part in selected_parts:
                field = f"has_part_{part}"
                if include_combos:
                    # Any course that covers this part (including combos)
                    q |= Q(**{field: True})
                else:
                    # Only courses where EXACTLY this part is True, others False
                    exact = {f"has_part_{pp}": (pp == part) for pp in [1, 2, 3, 4]}
                    q |= Q(**exact)
            qs = qs.filter(q)

        return qs

    def get_queryset(self):
        return self._apply_filters(
            CourseOffer.objects.filter(is_active=True)
            .select_related("chamber", "trade")
            .order_by("trade__name", "start_date")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["chambers"]        = Chamber.objects.all().order_by("name")
        ctx["formats"]         = CourseFormat.choices
        ctx["teaching_modes"]  = TeachingMode.choices
        ctx["per_page_options"] = PER_PAGE_OPTIONS

        p = self.request.GET
        sel_chamber = p.get("chamber", "")

        # Dynamic trades: only show trades available in the selected chamber
        if sel_chamber:
            trades_qs = Trade.objects.filter(
                course_offers__chamber__slug=sel_chamber,
                course_offers__is_active=True,
            ).distinct().order_by("name")
        else:
            trades_qs = Trade.objects.filter(
                course_offers__is_active=True
            ).distinct().order_by("name")
        ctx["trades"] = trades_qs

        ctx["sel_chamber"]       = sel_chamber
        ctx["sel_trade"]         = p.get("trade",         "")
        ctx["sel_format"]        = p.get("format",        "")
        ctx["sel_teaching"]      = p.get("teaching",      "")
        ctx["sel_parts"]         = p.getlist("part")       # list of strings
        ctx["sel_include_combos"] = p.get("include_combos", "") == "1"
        ctx["sel_date_from"]     = p.get("date_from",     "")
        ctx["sel_date_to"]       = p.get("date_to",       "")
        ctx["sel_per_page"]      = p.get("per_page",      "")
        ctx["view_mode"]         = p.get("view",          "list")

        map_qs = self._apply_filters(
            CourseOffer.objects
            .filter(is_active=True, latitude__isnull=False, longitude__isnull=False)
            .select_related("chamber", "trade")
            .order_by("start_date")
        )
        ctx["map_data_json"] = json.dumps([
            {
                "title":    o.title,
                "trade":    o.trade.name if o.trade else "Allgemein",
                "chamber":  o.chamber.short_name,
                "city":     o.city,
                "lat":      float(o.latitude),
                "lng":      float(o.longitude),
                "fee":      float(o.course_fee) if o.course_fee else None,
                "exam_fee": float(o.exam_fee_scraped) if o.exam_fee_scraped else None,
                "format":   o.get_format_display(),
                "teaching": o.get_teaching_mode_display(),
                "parts":    o.parts_label,
                "start":    o.start_date.strftime("%d.%m.%Y") if o.start_date else "",
                "url":      o.source_url,
            }
            for o in map_qs
        ])

        filter_params = "&".join(
            f"{k}={v}" for k, v in p.items()
            if k not in ("view", "page") and v
        )
        ctx["list_url_params"] = filter_params
        return ctx