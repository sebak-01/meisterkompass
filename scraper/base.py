"""
scraper/base.py
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup
from django.utils import timezone as django_timezone

from chambers.models import Chamber, Trade
from courses.models import CourseOffer, ExamFee, ExamSourceType, TeachingMode
from scraper.models import ScraperRun

logger = logging.getLogger(__name__)

GENERIC_TRADE_SLUG = "allgemein-teil-iii-iv"
GENERIC_TRADE_NAME = "Allgemein (Teil III + IV)"


@dataclass
class RawCourseOffer:
    title:            str
    trade_name:       str | None
    parts:            list[int]
    format_key:       str
    teaching_mode:    str
    start_date:       str | None
    end_date:         str | None
    duration_hours:   int | None
    course_fee:       float | None
    city:             str
    # Fields with defaults (must come after all non-default fields)
    exam_fee_scraped: float | None = None   # stated on course page (e.g. HWK Trier)
    street:           str = ""
    zip_code:         str = ""
    availability:     str = "unknown"
    source_url:       str = ""
    scraped_raw:      dict = field(default_factory=dict)


@dataclass
class RawExamFee:
    trade_name: str
    part:       int
    fee:        float
    source_url: str = ""


class BaseScraper(ABC):
    chamber_slug:    str = ""
    chamber_name:    str = ""
    chamber_region:  str = ""
    chamber_website: str = ""
    source_url:      str = ""
    request_delay:   float = 1.0

    def __init__(self):
        if not self.chamber_slug:
            raise ValueError(f"{self.__class__.__name__} must define chamber_slug")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; MeistervergleichBot/1.0; "
                "+https://meistervergleich.de/bot)"
            ),
            "Accept-Language": "de-DE,de;q=0.9",
        })

    @abstractmethod
    def fetch_raw_courses(self) -> list[RawCourseOffer]: ...

    def fetch_raw_exam_fees(self) -> list[RawExamFee]:
        return []

    def get(self, url: str, **kwargs) -> requests.Response | None:
        import time
        try:
            time.sleep(self.request_delay)
            r = self.session.get(url, timeout=20, **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            logger.warning("GET %s failed: %s", url, exc)
            return None

    def parse_html(self, url: str, **kwargs) -> BeautifulSoup | None:
        r = self.get(url, **kwargs)
        return BeautifulSoup(r.text, "html.parser") if r else None

    def run(self) -> ScraperRun:
        logger.info("Starting scraper: %s", self.__class__.__name__)
        chamber, created = Chamber.objects.get_or_create(
            slug=self.chamber_slug,
            defaults={
                "name":    self.chamber_name or self.chamber_slug,
                "region":  self.chamber_region,
                "website": self.chamber_website,
            },
        )
        if created:
            logger.info("Chamber '%s' auto-created.", self.chamber_slug)

        run = ScraperRun.objects.create(chamber=chamber)
        errors: list[str] = []

        try:
            raw_offers = self.fetch_raw_courses()
            stats = self._save_courses(chamber, raw_offers, errors)
        except Exception as exc:
            logger.exception("fetch_raw_courses failed for %s", self.chamber_slug)
            stats = {"created": 0, "updated": 0}
            errors.append(f"fetch_raw_courses raised: {exc}")

        try:
            raw_fees = self.fetch_raw_exam_fees()
            fees_updated = self._save_exam_fees(chamber, raw_fees, errors)
        except Exception as exc:
            logger.exception("fetch_raw_exam_fees failed for %s", self.chamber_slug)
            fees_updated = 0
            errors.append(f"fetch_raw_exam_fees raised: {exc}")

        run.offers_created    = stats["created"]
        run.offers_updated    = stats["updated"]
        run.exam_fees_updated = fees_updated
        run.error_log         = "\n".join(errors)
        run.status = (
            ScraperRun.Status.SUCCESS if not errors
            else ScraperRun.Status.PARTIAL if stats["created"] + stats["updated"] > 0
            else ScraperRun.Status.FAILED
        )
        run.finished_at = django_timezone.now()
        run.save()
        return run

    def _resolve_trade(self, trade_name: str | None) -> Trade | None:
        if trade_name is None:
            trade, _ = Trade.objects.get_or_create(
                slug=GENERIC_TRADE_SLUG,
                defaults={"name": GENERIC_TRADE_NAME, "is_mandatory": False},
            )
            return trade
        trade = Trade.objects.filter(name__iexact=trade_name).first()
        if trade is None:
            from django.utils.text import slugify
            trade = Trade.objects.filter(slug=slugify(trade_name)).first()
        if trade is None:
            from django.utils.text import slugify
            trade, created = Trade.objects.get_or_create(
                slug=slugify(trade_name),
                defaults={"name": trade_name, "is_mandatory": True},
            )
            if created:
                logger.info("Trade '%s' auto-created.", trade_name)
        return trade

    def _save_courses(
        self, chamber: Chamber, raw_offers: list[RawCourseOffer], errors: list[str]
    ) -> dict:
        created = updated = 0
        for raw in raw_offers:
            trade = self._resolve_trade(raw.trade_name)
            if trade is None:
                errors.append(f"Skipped: could not resolve trade '{raw.trade_name}'.")
                continue
            lookup = {
                "chamber":    chamber,
                "trade":      trade,
                "has_part_1": 1 in raw.parts,
                "has_part_2": 2 in raw.parts,
                "has_part_3": 3 in raw.parts,
                "has_part_4": 4 in raw.parts,
                "format":     raw.format_key,
                "start_date": raw.start_date,
            }
            defaults = {
                "title":            raw.title,
                "teaching_mode":    raw.teaching_mode,
                "end_date":         raw.end_date,
                "duration_hours":   raw.duration_hours,
                "course_fee":       raw.course_fee,
                "exam_fee_scraped": raw.exam_fee_scraped,
                "city":             raw.city,
                "street":           raw.street,
                "zip_code":         raw.zip_code,
                "availability":     raw.availability,
                "source_url":       raw.source_url,
                "is_active":        True,
                "last_scraped_at":  django_timezone.now(),
                "scraped_raw":      raw.scraped_raw,
            }
            _, was_created = CourseOffer.objects.update_or_create(
                **lookup, defaults=defaults
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return {"created": created, "updated": updated}

    def _save_exam_fees(
        self, chamber: Chamber, raw_fees: list[RawExamFee], errors: list[str]
    ) -> int:
        updated = 0
        for raw in raw_fees:
            trade = self._resolve_trade(raw.trade_name)
            if trade is None:
                errors.append(f"Skipped exam fee: trade '{raw.trade_name}' not resolvable.")
                continue
            existing = ExamFee.objects.filter(
                chamber=chamber, trade=trade, part=raw.part
            ).first()
            if existing and not existing.scraper_may_overwrite:
                continue
            ExamFee.objects.update_or_create(
                chamber=chamber, trade=trade, part=raw.part,
                defaults={
                    "fee":         raw.fee,
                    "source_type": ExamSourceType.SCRAPED,
                    "source_url":  raw.source_url,
                },
            )
            updated += 1
        return updated