"""Bookings, blocks and the audit trail (data-model 3.4 and 4).

THE NO-DOUBLE-BOOKING RULE (CLAUDE.md rule 1, NFR-01) is the exclusion constraint
``booking_no_overlap`` below: PostgreSQL refuses any two active rows on the same court whose
``[start_at, end_at)`` ranges overlap. Bookings and blocks share this table so the one constraint
covers both. Cancelled, expired and no-show rows free the court. Services check availability
first only to give a friendly message; correctness never depends on that check.

Composite foreign keys (court, venue) and (venue_customer, venue) are added in migration 0002
with RunSQL, so a booking can never point at another venue's court or customer (data-model 6.3).
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Func, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.querysets import VenueOwnedQuerySet


class TsTzRange(Func):
    """``tstzrange(start_at, end_at, '[)')`` for the exclusion constraint."""

    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class Kind(models.TextChoices):
    BOOKING = "booking", _("Booking")
    BLOCK = "block", _("Block")


class Status(models.TextChoices):
    HELD = "held", _("Held")  # Phase 2 (online payment); never created in MVP (BR-07)
    CONFIRMED = "confirmed", _("Confirmed")
    CANCELLED = "cancelled", _("Cancelled")
    EXPIRED = "expired", _("Expired")  # Phase 2
    NO_SHOW = "no_show", _("No-show")


# Rows in these statuses occupy the court. Everything else frees it (CLAUDE.md rule 1).
ACTIVE_STATUSES = [Status.HELD, Status.CONFIRMED]


class Source(models.TextChoices):
    ONLINE = "online", _("Online")
    PHONE = "phone", _("Phone")
    WHATSAPP = "whatsapp", _("WhatsApp")
    WALK_IN = "walk_in", _("Walk-in")


class BlockReason(models.TextChoices):
    MAINTENANCE = "maintenance", _("Maintenance")
    PRIVATE_EVENT = "private_event", _("Private event")
    COACHING = "coaching", _("Coaching")
    CLOSED = "closed", _("Closed")
    OTHER = "other", _("Other")


class CancelReason(models.TextChoices):
    CUSTOMER_REQUEST = "customer_request", _("Customer asked")
    VENUE_ISSUE = "venue_issue", _("Venue issue")
    VENUE_CLOSED = "venue_closed", _("Venue closed")
    OTHER = "other", _("Other")


class Booking(models.Model):
    """One booking or one block of one court for ``[start_at, end_at)``."""

    reference = models.CharField(max_length=6)
    venue = models.ForeignKey("venues.Venue", on_delete=models.PROTECT, related_name="bookings")
    court = models.ForeignKey("venues.Court", on_delete=models.PROTECT, related_name="bookings")
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.BOOKING)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    # NULL for blocks (data-model 3.4): a block has no source, and the checks rely on NULL.
    source = models.CharField(  # noqa: DJ001
        max_length=10, choices=Source.choices, null=True, blank=True
    )
    start_at = models.DateTimeField()  # inclusive
    end_at = models.DateTimeField()  # exclusive
    # Local operating day of start_at (03:00 to 03:00). Set by the services on insert and move.
    operating_date = models.DateField()
    venue_customer = models.ForeignKey(
        "venues.VenueCustomer",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bookings",
    )
    # Snapshot shown on the calendar; walk-ins without a phone have only this.
    customer_name = models.CharField(max_length=80, blank=True)
    price_lkr = models.PositiveIntegerField(default=0)  # stored at booking time
    price_change_reason = models.CharField(max_length=255, blank=True)
    block_reason = models.CharField(max_length=16, choices=BlockReason.choices, blank=True)
    block_group = models.UUIDField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    hold_expires_at = models.DateTimeField(null=True, blank=True)  # Phase 2
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cancel_reason = models.CharField(max_length=20, choices=CancelReason.choices, blank=True)
    is_late_cancellation = models.BooleanField(default=False)
    no_show_marked_at = models.DateTimeField(null=True, blank=True)
    no_show_marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # "Arrived" tick for the front desk (C6). Records who and when; changes no rule.
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = VenueOwnedQuerySet.as_manager()

    class Meta:
        verbose_name = _("booking")
        indexes = [
            models.Index(fields=["venue", "operating_date"], name="booking_venue_day_idx"),
            models.Index(fields=["court", "operating_date"], name="booking_court_day_idx"),
            models.Index(fields=["venue_customer", "start_at"], name="booking_customer_idx"),
            models.Index(
                fields=["hold_expires_at"],
                condition=Q(status="held"),
                name="booking_hold_expiry_idx",
            ),
        ]
        constraints = [
            ExclusionConstraint(
                name="booking_no_overlap",
                expressions=[
                    ("court", RangeOperators.EQUAL),
                    (TsTzRange("start_at", "end_at", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
                condition=Q(status__in=ACTIVE_STATUSES),
                violation_error_code="slot_taken",
            ),
            models.CheckConstraint(
                condition=Q(end_at__gt=F("start_at")), name="booking_end_after_start"
            ),
            models.CheckConstraint(
                condition=Q(end_at__lte=F("start_at") + timedelta(hours=24)),
                name="booking_max_length",
            ),
            models.CheckConstraint(condition=Q(kind__in=Kind.values), name="booking_kind_valid"),
            models.CheckConstraint(
                condition=Q(status__in=Status.values), name="booking_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(source__isnull=True) | Q(source__in=Source.values),
                name="booking_source_valid",
            ),
            models.CheckConstraint(
                condition=Q(block_reason="") | Q(block_reason__in=BlockReason.values),
                name="booking_block_reason_valid",
            ),
            models.CheckConstraint(
                condition=Q(cancel_reason="") | Q(cancel_reason__in=CancelReason.values),
                name="booking_cancel_reason_valid",
            ),
            # A block is never sold, held, priced or marked no-show.
            models.CheckConstraint(
                condition=~Q(kind="block")
                | Q(
                    source__isnull=True,
                    venue_customer__isnull=True,
                    price_lkr=0,
                    status__in=["confirmed", "cancelled"],
                )
                & ~Q(block_reason=""),
                name="booking_block_shape",
            ),
            models.CheckConstraint(
                condition=~Q(kind="booking") | Q(source__isnull=False, block_reason=""),
                name="booking_shape",
            ),
            models.CheckConstraint(
                condition=Q(status="held", hold_expires_at__isnull=False)
                | (~Q(status="held") & Q(hold_expires_at__isnull=True)),
                name="booking_hold_has_expiry",
            ),
            models.CheckConstraint(
                condition=~Q(status="cancelled") | Q(cancelled_at__isnull=False),
                name="booking_cancel_has_time",
            ),
            models.CheckConstraint(
                condition=~Q(status="no_show") | Q(no_show_marked_at__isnull=False),
                name="booking_no_show_has_time",
            ),
            models.UniqueConstraint(fields=["reference"], name="booking_reference_unique"),
            models.UniqueConstraint(
                fields=["created_by"],
                condition=Q(status="held"),
                name="booking_one_hold_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"MV-{self.reference}"

    @property
    def display_reference(self) -> str:
        return f"MV-{self.reference}"

    @property
    def is_completed(self) -> bool:
        """'Completed' is derived, not stored: confirmed and already over (requirements 3)."""
        return self.status == Status.CONFIRMED and self.end_at <= timezone.now()


class EventAction(models.TextChoices):
    CREATED = "created", _("Created")
    MOVED = "moved", _("Moved")
    PRICE_CHANGED = "price_changed", _("Price changed")
    CANCELLED = "cancelled", _("Cancelled")
    NO_SHOW = "no_show", _("No-show")
    NO_SHOW_UNDONE = "no_show_undone", _("No-show undone")
    CONFIRMED = "confirmed", _("Confirmed")
    EXPIRED = "expired", _("Expired")
    CUSTOMER_CHANGED = "customer_changed", _("Customer changed")
    NOTES_CHANGED = "notes_changed", _("Notes changed")
    ARRIVED = "arrived", _("Arrived")


class BookingEvent(models.Model):
    """Append-only audit log (NFR-06). Never stores names or phone numbers (BR-25)."""

    venue = models.ForeignKey("venues.Venue", on_delete=models.PROTECT, related_name="+")
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    action = models.CharField(max_length=20, choices=EventAction.choices)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = VenueOwnedQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = _("booking event")
        indexes = [
            models.Index(fields=["booking", "created_at"], name="event_booking_idx"),
            models.Index(fields=["venue", "created_at"], name="event_venue_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=EventAction.values), name="event_action_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action} #{self.booking_id}"
