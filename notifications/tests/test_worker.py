import logging
import threading
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from django.db import connection, transaction
from django.utils import timezone

from notifications import services
from notifications.backends import locmem
from notifications.backends.base import SmsSendError
from notifications.backends.locmem import LocmemBackend
from notifications.backends.textlk import TextLkBackend
from notifications.models import SmsMessage
from notifications.worker import MAX_ATTEMPTS, RETRY_DELAYS, send_due_messages

PHONE = "+94771234567"
T0 = datetime(2026, 12, 5, 4, 30, tzinfo=UTC)

pytestmark = pytest.mark.django_db


def queue(body="Booking confirmed", purpose="booking_confirmation", **kwargs):
    return services.queue_sms(to_phone=PHONE, purpose=purpose, body=body, **kwargs)


def test_sends_due_messages_and_records_result():
    message = queue()

    assert send_due_messages(backend=LocmemBackend()) == 1

    message.refresh_from_db()
    assert message.status == SmsMessage.Status.SENT
    assert message.sent_at is not None
    assert message.attempts == 1
    assert message.provider_message_id == "locmem-1"
    assert locmem.outbox[0].to_phone == PHONE
    assert locmem.outbox[0].text == "Booking confirmed"


def test_skips_messages_scheduled_for_later():
    later = queue(purpose="reminder", scheduled_for=timezone.now() + timedelta(hours=3))

    assert send_due_messages(backend=LocmemBackend()) == 0
    later.refresh_from_db()
    assert later.status == SmsMessage.Status.QUEUED
    assert locmem.outbox == []


def test_sends_oldest_first_in_batches():
    with time_machine.travel(T0, tick=False) as clock:
        for i in range(3):
            queue(body=f"msg {i}")
            clock.shift(timedelta(seconds=1))
        assert send_due_messages(backend=LocmemBackend(), batch_size=2) == 2
        assert [sms.text for sms in locmem.outbox] == ["msg 0", "msg 1"]
        assert send_due_messages(backend=LocmemBackend(), batch_size=2) == 1


def test_otp_is_decrypted_for_the_gateway_and_never_kept():
    message = services.queue_otp_sms(to_phone=PHONE, code="482913")

    send_due_messages(backend=LocmemBackend())

    assert "482913" in locmem.outbox[0].text
    message.refresh_from_db()
    assert message.status == SmsMessage.Status.SENT
    assert message.body == "[OTP]"
    assert message.encrypted_body == ""


def test_otp_older_than_five_minutes_is_dropped_not_sent():
    with time_machine.travel(T0, tick=False) as clock:
        message = services.queue_otp_sms(to_phone=PHONE, code="482913")
        clock.shift(timedelta(minutes=5, seconds=1))
        send_due_messages(backend=LocmemBackend())

    assert locmem.outbox == []
    message.refresh_from_db()
    assert message.status == SmsMessage.Status.CANCELLED
    assert message.encrypted_body == ""
    assert "expired" in message.last_error


def test_message_without_phone_is_cancelled():
    message = queue()
    SmsMessage.objects.filter(pk=message.pk).update(to_phone=None)

    send_due_messages(backend=LocmemBackend())

    message.refresh_from_db()
    assert message.status == SmsMessage.Status.CANCELLED
    assert locmem.outbox == []


def test_failures_retry_with_backoff_then_fail_after_five_attempts():
    locmem.fail_with = SmsSendError("gateway timeout")
    with time_machine.travel(T0, tick=False) as clock:
        message = queue()
        for attempt in range(1, MAX_ATTEMPTS):
            send_due_messages(backend=LocmemBackend())
            message.refresh_from_db()
            assert message.status == SmsMessage.Status.QUEUED
            assert message.attempts == attempt
            assert message.scheduled_for == timezone.now() + RETRY_DELAYS[attempt - 1]
            assert "gateway timeout" in message.last_error
            # Not due again until the delay has passed.
            assert send_due_messages(backend=LocmemBackend()) == 0
            clock.shift(RETRY_DELAYS[attempt - 1])

        send_due_messages(backend=LocmemBackend())

    message.refresh_from_db()
    assert message.status == SmsMessage.Status.FAILED
    assert message.attempts == MAX_ATTEMPTS
    assert [d.total_seconds() / 60 for d in RETRY_DELAYS] == [1, 5, 15, 30]


def test_unexpected_gateway_exception_does_not_stop_other_messages():
    class Flaky(LocmemBackend):
        def send(self, to_phone, text):
            if text == "first":
                raise RuntimeError("boom")
            return super().send(to_phone, text)

    with time_machine.travel(T0, tick=False) as clock:
        first = queue(body="first")
        clock.shift(timedelta(seconds=1))
        second = queue(body="second")
        send_due_messages(backend=Flaky())

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == SmsMessage.Status.QUEUED
    assert first.attempts == 1
    assert second.status == SmsMessage.Status.SENT


def test_textlk_placeholder_never_pretends_to_send():
    message = queue()
    send_due_messages(backend=TextLkBackend())
    message.refresh_from_db()
    assert message.status == SmsMessage.Status.QUEUED
    assert "not implemented" in message.last_error


def test_logs_never_contain_code_or_full_phone(caplog):
    caplog.set_level(logging.DEBUG)
    services.queue_otp_sms(to_phone=PHONE, code="482913")
    locmem.fail_with = SmsSendError("timeout")
    send_due_messages(backend=LocmemBackend())
    locmem.fail_with = None
    SmsMessage.objects.update(scheduled_for=timezone.now())
    send_due_messages(backend=LocmemBackend())

    assert "482913" not in caplog.text
    assert PHONE not in caplog.text
    assert "+9477****567" in caplog.text


@pytest.mark.django_db(transaction=True)
def test_message_locked_by_another_worker_is_skipped():
    with transaction.atomic():
        message = queue()
    claimed = threading.Event()
    release = threading.Event()

    def other_worker():
        with transaction.atomic():
            list(SmsMessage.objects.select_for_update().filter(pk=message.pk))
            claimed.set()
            release.wait(timeout=5)
        connection.close()

    thread = threading.Thread(target=other_worker)
    thread.start()
    assert claimed.wait(timeout=5)
    try:
        assert send_due_messages(backend=LocmemBackend()) == 0
    finally:
        release.set()
        thread.join(timeout=5)
    assert locmem.outbox == []
    assert send_due_messages(backend=LocmemBackend()) == 1
