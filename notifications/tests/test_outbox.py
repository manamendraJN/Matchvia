from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from django.db import IntegrityError, transaction

from notifications import services
from notifications.models import SmsMessage

PHONE = "+94771234567"
T0 = datetime(2026, 12, 5, 4, 30, tzinfo=UTC)


@pytest.mark.django_db(transaction=True)
def test_queue_sms_refuses_to_run_outside_a_transaction():
    with pytest.raises(RuntimeError, match="transaction"):
        services.queue_sms(to_phone=PHONE, purpose="reminder", body="See you at 7 pm")
    assert SmsMessage.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_rolled_back_transaction_leaves_no_message():
    def change_that_fails_after_queueing():
        with transaction.atomic():
            services.queue_sms(to_phone=PHONE, purpose="reminder", body="See you at 7 pm")
            raise RuntimeError("the caller's change failed")

    with pytest.raises(RuntimeError):
        change_that_fails_after_queueing()
    assert SmsMessage.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_committed_transaction_keeps_the_message():
    with transaction.atomic():
        services.queue_sms(to_phone=PHONE, purpose="reminder", body="See you at 7 pm")
    message = SmsMessage.objects.get()
    assert message.status == SmsMessage.Status.QUEUED
    assert message.body == "See you at 7 pm"
    assert message.encrypted_body == ""


@pytest.mark.django_db
def test_unknown_purpose_rejected():
    with pytest.raises(ValueError, match="purpose"):
        services.queue_sms(to_phone=PHONE, purpose="marketing", body="Sale!")


@pytest.mark.django_db
def test_otp_message_is_stored_redacted_and_encrypted():
    message = services.queue_otp_sms(to_phone=PHONE, code="482913")

    message.refresh_from_db()
    assert message.body == "[OTP]"
    assert "482913" not in message.encrypted_body
    assert "482913" in services.decrypt_otp_text(message.encrypted_body)


@pytest.mark.django_db
def test_otp_ciphertext_unreadable_after_five_minutes():
    with time_machine.travel(T0, tick=False) as clock:
        message = services.queue_otp_sms(to_phone=PHONE, code="482913")
        clock.shift(timedelta(minutes=5, seconds=1))
        assert services.decrypt_otp_text(message.encrypted_body) is None


def test_decrypt_rejects_garbage():
    assert services.decrypt_otp_text("not-a-token") is None


def test_otp_text_fits_one_sms_segment():
    text = services.otp_text("123456")
    assert "123456" in text
    assert len(text) <= 160
    assert text.isascii()  # GSM-7 friendly, so 160 characters per segment


@pytest.mark.django_db
def test_forget_phone_removes_number_and_cancels_queued_messages():
    queued = services.queue_sms(to_phone=PHONE, purpose="reminder", body="Reminder")
    otp = services.queue_otp_sms(to_phone=PHONE, code="111111")
    sent = services.queue_sms(to_phone=PHONE, purpose="booking_confirmation", body="Booked")
    SmsMessage.objects.filter(pk=sent.pk).update(status=SmsMessage.Status.SENT)
    other = services.queue_sms(to_phone="+94711111111", purpose="reminder", body="Other")

    assert services.forget_phone(PHONE) == 3

    for message in (queued, otp, sent):
        message.refresh_from_db()
        assert message.to_phone is None
        assert message.encrypted_body == ""
    assert queued.status == otp.status == SmsMessage.Status.CANCELLED
    assert sent.status == SmsMessage.Status.SENT
    other.refresh_from_db()
    assert other.to_phone == "+94711111111"


@pytest.mark.django_db
def test_database_rejects_ciphertext_on_a_finished_message():
    message = services.queue_otp_sms(to_phone=PHONE, code="111111")
    with pytest.raises(IntegrityError), transaction.atomic():
        SmsMessage.objects.filter(pk=message.pk).update(status=SmsMessage.Status.SENT)


@pytest.mark.django_db
def test_database_rejects_unknown_status():
    message = services.queue_sms(to_phone=PHONE, purpose="reminder", body="x")
    with pytest.raises(IntegrityError), transaction.atomic():
        SmsMessage.objects.filter(pk=message.pk).update(status="lost")
