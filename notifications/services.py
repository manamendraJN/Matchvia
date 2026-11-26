"""Business logic for notifications: SMS outbox, templates, gateway adapter and the
worker's send loop.

Services own the transaction; views stay thin. Cross-app calls go through the other
app's services.py (CLAUDE.md "Code conventions").

Other apps call ``queue_sms`` (or a purpose-specific helper such as ``queue_otp_sms``) inside
their own transaction. Nothing here talks to the gateway; only the worker does (worker.py).
"""

import base64
import functools
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

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
    )


def otp_text(code: str) -> str:
    """The sign-in code SMS. Short enough for one SMS segment."""
    return _("Your Matchvia code is %(code)s. It expires in 5 minutes. Never share it.") % {
        "code": code
    }


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
