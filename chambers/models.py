"""
chambers/models.py
"""

from django.db import models
from django.utils.text import slugify


class Chamber(models.Model):
    name     = models.CharField(max_length=200)
    slug     = models.SlugField(max_length=100, unique=True)
    region   = models.CharField(max_length=100)
    website  = models.URLField(blank=True)
    street   = models.CharField(max_length=200, blank=True)
    city     = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=10,  blank=True)
    latitude  = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Chamber"
        verbose_name_plural = "Chambers"

    def __str__(self):
        return self.name

    @property
    def short_name(self) -> str:
        """Abbreviated display name, e.g. 'HWK Koblenz' instead of 'Handwerkskammer Koblenz'."""
        return self.name.replace("Handwerkskammer", "HWK").strip()

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Trade(models.Model):
    name         = models.CharField(max_length=200)
    slug         = models.SlugField(max_length=100, unique=True)
    is_mandatory = models.BooleanField(default=True)

    # Berufenet ID — links to the Federal Employment Agency trade profile.
    # URL pattern: https://web.arbeitsagentur.de/berufenet/beruf/{id}
    # Example: Meister Elektrotechnik → id=2731
    berufenet_id = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name="Berufenet ID",
        help_text=(
            "Numeric ID from the Berufenet URL. "
            "Find it at https://web.arbeitsagentur.de/berufenet/ — "
            "e.g. Elektrotechnik Meister → 2731"
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Trade"
        verbose_name_plural = "Trades"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def berufenet_url(self) -> str | None:
        if self.berufenet_id:
            return f"https://web.arbeitsagentur.de/berufenet/beruf/{self.berufenet_id}"
        return None