"""SMS outbox (data-model 3.6).

Messages are written in the same transaction as the change that causes them and sent later by
the worker (``manage.py run_worker``), so a slow or failing gateway never blocks a request
(NFR-03, CLAUDE.md "SMS only through the notifications outbox").

The ``venue`` and ``booking`` foreign keys and the one-reminder-per-booking constraint are added
by the migrations that create those tables (S04, S06).
"""

from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class SmsPurpose(models.TextChoices):
    OTP = "otp", _("Sign-in code")
    BOOKING_CONFIRMATION = "booking_confirmation", _("Booking confirmation")
    BOOKING_CHANGED = "booking_changed", _("Booking changed")
    BOOKING_CANCELLED = "booking_cancelled", _("Booking cancelled")
    REMINDER = "reminder", _("Reminder")
    SERIES_SUMMARY = "series_summary", _("Weekly booking summary")
    SERIES_DECISION = "series_decision", _("Weekly request decision")
    TEAM_INVITE = "team_invite", _("Team invite")
    STAFF_ADDED = "staff_added", _("Staff added")
    VENUE_STATUS = "venue_status", _("Venue status")
    VENUE_NOTICE = "venue_notice", _("Venue notice")


class SmsStatus(models.TextChoices):
    QUEUED = "queued", _("Queued")
    SENT = "sent", _("Sent")
    FAILED = "failed", _("Failed")
    CANCELLED = "cancelled", _("Cancelled")


class SmsMessage(models.Model):
    Purpose = SmsPurpose
    Status = SmsStatus

    # Wiped after sending + 90 days, or on account deletion (data-model 9).
    # NULL means "number removed", distinct from never having one.
    to_phone = models.CharField(max_length=16, null=True, blank=True)  # noqa: DJ001
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    # For OTP messages this is the redacted text "[OTP]"; the real text is in encrypted_body.
    body = models.TextField()
    # OTP text encrypted with a key from the environment, readable only by the worker and only
    # for 5 minutes. Emptied once the message is sent, dropped or failed.
    encrypted_body = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    scheduled_for = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    provider_message_id = models.CharField(max_length=100, blank=True, default="")
    last_error = models.CharField(max_length=255, blank=True, default="")
    # Which venue and booking a message is about (cleared, never cascaded, if those go away).
    venue = models.ForeignKey(
        "venues.Venue", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_messages",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("SMS message")
        verbose_name_plural = _("SMS messages")
        indexes = [
            # The send job's queue.
            models.Index(
                fields=["scheduled_for"],
                condition=Q(status="queued"),
                name="sms_queued_due_idx",
            ),
            models.Index(fields=["to_phone"], name="sms_to_phone_idx"),
        ]
        constraints = [
            # One live reminder per booking (US-P07, data-model 3.6).
            models.UniqueConstraint(
                fields=["booking", "purpose"],
                condition=Q(purpose="reminder") & ~Q(status="cancelled"),
                name="sms_one_reminder_per_booking",
            ),
            models.CheckConstraint(
                condition=Q(purpose__in=SmsPurpose.values),
                name="sms_purpose_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=SmsStatus.values),
                name="sms_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(status="queued") | Q(encrypted_body=""),
                name="sms_encrypted_body_only_while_queued",
            ),
        ]

    def __str__(self) -> str:
        return f"SMS #{self.pk} {self.purpose} ({self.status})"
