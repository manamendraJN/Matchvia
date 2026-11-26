"""Peak periods (data-model 3.3). Each court has its own normal and peak price (BR-18)."""

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.querysets import VenueOwnedQuerySet
from core.timeutils import DAY_END_MINUTE, DAY_START_MINUTE


class PeakPeriod(models.Model):
    """A slot is peak if its start falls inside a peak period for its operating day's weekday."""

    venue = models.ForeignKey("venues.Venue", on_delete=models.CASCADE, related_name="peak_periods")
    weekday = models.PositiveSmallIntegerField()  # 0 = Monday … 6 = Sunday
    starts_minute = models.PositiveSmallIntegerField()
    ends_minute = models.PositiveSmallIntegerField()

    objects = VenueOwnedQuerySet.as_manager()

    class Meta:
        ordering = ["weekday", "starts_minute"]
        verbose_name = _("peak period")
        indexes = [models.Index(fields=["venue", "weekday"], name="peak_venue_weekday_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(weekday__lte=6), name="peak_weekday_valid"),
            models.CheckConstraint(
                condition=Q(
                    starts_minute__gte=DAY_START_MINUTE,
                    starts_minute__lt=models.F("ends_minute"),
                    ends_minute__lte=DAY_END_MINUTE,
                ),
                name="peak_window_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"Weekday {self.weekday} {self.starts_minute}-{self.ends_minute}"
