"""Business logic for notifications: SMS outbox, templates, gateway adapter and the
worker's send loop.

Services own the transaction; views stay thin. Cross-app calls go through the other
app's services.py (CLAUDE.md "Code conventions").

Other apps call ``queue_sms`` (or a purpose-specific helper such as ``queue_otp_sms``) inside
their own transaction. Nothing here talks to the gateway; only the worker does (worker.py).
"""

import base64
import functools
from datetime import datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.module_loading import import_string

from core.formatting import format_lkr, format_range
from core.phone import format_local

from .backends.base import BaseSmsBackend
from .models import SmsMessage

REDACTED_OTP_BODY = "[OTP]"
# An OTP message older than this is never sent: the code has expired (architecture 3.1).
OTP_MAX_AGE_SECONDS = 5 * 60


# ---------------------------------------------------------------- encryption of OTP text


@functools.cache
def _fernet(key_material: str) -> Fernet:
    # Derive a dedicated key from OTP_HMAC_KEY so the outbox key is never the HMAC key itself.
    raw = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"matchvia:sms-outbox:v1",
    ).derive(key_material.encode())
    return Fernet(base64.urlsafe_b64encode(raw))


def _encrypt(text: str) -> str:
    return _fernet(settings.OTP_HMAC_KEY).encrypt(text.encode()).decode()


def decrypt_otp_text(token: str) -> str | None:
    """The OTP text, or None if the token is invalid or older than 5 minutes."""
    try:
        return (
            _fernet(settings.OTP_HMAC_KEY).decrypt(token.encode(), ttl=OTP_MAX_AGE_SECONDS).decode()
        )
    except InvalidToken:
        return None


# ---------------------------------------------------------------- queueing


def queue_sms(
    *,
    to_phone: str,
    purpose: str,
    body: str,
    scheduled_for: datetime | None = None,
    venue=None,
    booking=None,
) -> SmsMessage:
    """Write one SMS to the outbox, in the caller's transaction.

    Raises RuntimeError outside ``transaction.atomic()``: an SMS must commit or roll back
    together with the change that caused it (data-model 3.6).
    OTP messages are stored redacted, with the real text encrypted for the worker.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("queue_sms() must be called inside the caller's transaction.")
    if purpose not in SmsMessage.Purpose.values:
        raise ValueError(f"Unknown SMS purpose: {purpose}")

    encrypted = ""
    if purpose == SmsMessage.Purpose.OTP:
        encrypted = _encrypt(body)
        body = REDACTED_OTP_BODY
    return SmsMessage.objects.create(
        to_phone=to_phone,
        purpose=purpose,
        body=body,
        encrypted_body=encrypted,
        scheduled_for=scheduled_for or timezone.now(),
        venue=venue,
        booking=booking,
    )


# ---------------------------------------------------------------- message texts


# The GSM 03.38 basic character set: texts using only these fit 160 characters per SMS.
# One character outside it (an en dash, a Sinhala letter) makes the whole SMS UCS-2: 70 each.
GSM7_CHARACTERS = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
SINGLE_SMS_LENGTH = 160


def is_gsm7(text: str) -> bool:
    return set(text) <= GSM7_CHARACTERS


def render_sms(template: str, **context) -> str:
    """Render ``sms/<template>.txt`` (translatable, never HTML-escaped) as one line."""
    text = render_to_string(f"sms/{template}.txt", context)
    return " ".join(text.split())


def otp_text(code: str) -> str:
    """The sign-in code SMS. Short enough for one SMS segment."""
    return render_sms("otp", code=code)


def booking_context(booking) -> dict:
    """Everything booking SMS show. Never the customer's own name or number (data-model 9)."""
    return {
        "ref": booking.display_reference,
        "venue": booking.venue.name,
        "court": booking.court.name,
        "when": format_range(booking.start_at, booking.end_at, dash="-"),
        "price": format_lkr(booking.price_lkr),
        "venue_phone": format_local(booking.venue.phone),
    }


def _booking_phone(booking) -> str | None:
    customer = booking.venue_customer if booking.venue_customer_id else None
    return customer.phone if customer else None


def queue_booking_sms(booking, purpose: str) -> SmsMessage | None:
    """Confirmation, change or cancellation SMS to the customer, if we have their number."""
    phone = _booking_phone(booking)
    if not phone:
        return None
    return queue_sms(
        to_phone=phone,
        purpose=purpose,
        body=render_sms(purpose, **booking_context(booking)),
        venue=booking.venue,
        booking=booking,
    )


# ---------------------------------------------------------------- reminders (BR-20, US-P07)

QUIET_FROM_HOUR = 22  # 10 pm
QUIET_UNTIL_HOUR = 7  # 7 am
QUIET_SEND_HOUR = 21  # 9 pm the evening before


def reminder_time(start: datetime, lead_hours: int) -> datetime:
    """When the reminder goes out: ``lead_hours`` before the start, out of quiet hours.

    A time between 22:00 and 07:00 moves to 21:00 the evening before (BR-20).
    """
    at = timezone.localtime(start - timedelta(hours=lead_hours))
    if at.hour >= QUIET_FROM_HOUR:
        at = at.replace(hour=QUIET_SEND_HOUR, minute=0, second=0, microsecond=0)
    elif at.hour < QUIET_UNTIL_HOUR:
        evening = at - timedelta(days=1)
        at = evening.replace(hour=QUIET_SEND_HOUR, minute=0, second=0, microsecond=0)
    return at


def schedule_reminder(booking, *, now: datetime | None = None) -> SmsMessage | None:
    """Queue the one reminder for a confirmed booking (US-P07).

    None for walk-ins, for customers without a phone, and when the reminder time has already
    passed (the confirmation SMS is enough).
    """
    now = now or timezone.now()
    phone = _booking_phone(booking)
    if not phone or booking.source == "walk_in" or booking.status != "confirmed":
        return None
    send_at = reminder_time(booking.start_at, booking.venue.settings.reminder_lead_hours)
    if send_at <= now:
        return None
    return queue_sms(
        to_phone=phone,
        purpose=SmsMessage.Purpose.REMINDER,
        body=render_sms("reminder", **booking_context(booking)),
        scheduled_for=send_at,
        venue=booking.venue,
        booking=booking,
    )


def cancel_reminder(booking) -> int:
    """Stop a queued reminder (cancel, no-show, move). Must run in the caller's transaction."""
    return SmsMessage.objects.filter(
        booking=booking, purpose=SmsMessage.Purpose.REMINDER, status=SmsMessage.Status.QUEUED
    ).update(status=SmsMessage.Status.CANCELLED, last_error="booking changed")


def reschedule_reminder(booking, *, now: datetime | None = None) -> SmsMessage | None:
    cancel_reminder(booking)
    return schedule_reminder(booking, now=now)


# ---------------------------------------------------------------- minimum data (PDPA)

PHONE_RETENTION = timedelta(days=90)


def forget_old_phone_numbers(*, now: datetime | None = None) -> int:
    """Blank the number on finished SMS older than 90 days (architecture 5.2)."""
    now = now or timezone.now()
    return (
        SmsMessage.objects.filter(created_at__lt=now - PHONE_RETENTION, to_phone__isnull=False)
        .exclude(status=SmsMessage.Status.QUEUED)
        .update(to_phone=None)
    )


def queue_otp_sms(*, to_phone: str, code: str) -> SmsMessage:
    return queue_sms(to_phone=to_phone, purpose=SmsMessage.Purpose.OTP, body=otp_text(code))


def forget_phone(phone: str) -> int:
    """Remove a phone number from the SMS log (account deletion, data-model 9).

    Queued messages to that number are cancelled. Returns the number of rows changed.
    """
    messages = SmsMessage.objects.filter(to_phone=phone)
    messages.filter(status=SmsMessage.Status.QUEUED).update(
        status=SmsMessage.Status.CANCELLED, encrypted_body="", last_error="account deleted"
    )
    return messages.update(to_phone=None)


# ---------------------------------------------------------------- gateway


def get_backend() -> BaseSmsBackend:
    """An instance of the configured SMS backend (settings.SMS_BACKEND)."""
    return import_string(settings.SMS_BACKEND)()
