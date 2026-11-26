"""The SMS send job run by ``manage.py run_worker`` (architecture 4.1, 4.2).

Claims due messages with ``SELECT ... FOR UPDATE SKIP LOCKED`` so two workers never send the
same message from one claim. If the worker crashes mid-batch, the claim rolls back and the
messages are retried: a rare duplicate SMS is better than a lost one.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.phone import mask_phone

from .backends.base import BaseSmsBackend
from .models import SmsMessage
from .services import OTP_MAX_AGE_SECONDS, decrypt_otp_text, get_backend

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
MAX_ATTEMPTS = 5
# Wait before attempt 2, 3, 4 and 5 (architecture 4.2).
RETRY_DELAYS = [
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
]


def send_due_messages(
    *, backend: BaseSmsBackend | None = None, batch_size: int = BATCH_SIZE
) -> int:
    """Send queued messages that are due. Returns how many were processed."""
    backend = backend or get_backend()
    now = timezone.now()
    with transaction.atomic():
        due = list(
            SmsMessage.objects.select_for_update(skip_locked=True)
            .filter(status=SmsMessage.Status.QUEUED, scheduled_for__lte=now)
            .order_by("scheduled_for", "id")[:batch_size]
        )
        for message in due:
            _process(message, backend, now)
    return len(due)


def _process(message: SmsMessage, backend: BaseSmsBackend, now) -> None:
    text = message.body
    if message.purpose == SmsMessage.Purpose.OTP:
        too_old = message.created_at < now - timedelta(seconds=OTP_MAX_AGE_SECONDS)
        text = None if too_old else decrypt_otp_text(message.encrypted_body)
        if text is None:
            # The code has expired; sending it now would only confuse (architecture 4.2).
            _finish(message, SmsMessage.Status.CANCELLED, error="expired before sending")
            logger.info("sms.dropped id=%s purpose=otp reason=expired", message.pk)
            return
    if not message.to_phone:
        _finish(message, SmsMessage.Status.CANCELLED, error="no phone number")
        return

    message.attempts += 1
    try:
        provider_id = backend.send(message.to_phone, text)
    except Exception as exc:  # any gateway failure must not stop the loop (architecture 4.2)
        error = f"{type(exc).__name__}: {exc}"[:255]
        if message.attempts >= MAX_ATTEMPTS:
            _finish(message, SmsMessage.Status.FAILED, error=error)
            logger.error(
                "sms.failed id=%s purpose=%s to=%s attempts=%s",
                message.pk,
                message.purpose,
                mask_phone(message.to_phone),
                message.attempts,
            )
        else:
            message.last_error = error
            message.scheduled_for = now + RETRY_DELAYS[message.attempts - 1]
            message.save(update_fields=["attempts", "last_error", "scheduled_for", "updated_at"])
            logger.warning(
                "sms.retry id=%s purpose=%s attempt=%s",
                message.pk,
                message.purpose,
                message.attempts,
            )
        return

    message.provider_message_id = (provider_id or "")[:100]
    message.sent_at = now
    _finish(message, SmsMessage.Status.SENT)
    logger.info(
        "sms.sent id=%s purpose=%s to=%s",
        message.pk,
        message.purpose,
        mask_phone(message.to_phone),
    )


def _finish(message: SmsMessage, status: str, *, error: str = "") -> None:
    message.status = status
    message.encrypted_body = ""  # the OTP text is never kept once the message is done
    if error:
        message.last_error = error
    message.save()
