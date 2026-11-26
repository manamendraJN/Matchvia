"""Account deletion with OTP and immediate anonymisation (US-P08, BR-25, data-model 9)."""

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts import services
from accounts.models import DELETED_USER_NAME, ConsentRecord, OTPChallenge, User
from core.exceptions import NotAllowed
from notifications import services as notifications
from notifications.models import SmsMessage

from .conftest import IP, PHONE, last_code, wrong

pytestmark = pytest.mark.django_db

DELETE_URL = reverse("me:delete")
CONFIRM_URL = reverse("me:delete_confirm")


def test_delete_page_explains_and_needs_sign_in(client, user):
    assert client.get(DELETE_URL).status_code == 302
    client.force_login(user)
    response = client.get(DELETE_URL)
    assert response.status_code == 200
    assert "This can't be undone." in response.content.decode()
    assert b"077 123 4567" in response.content


def test_full_deletion_flow(client, user):
    client.force_login(user)
    other_device = Client()
    other_device.force_login(user)
    notifications_sent_before = SmsMessage.objects.count()

    response = client.post(DELETE_URL)
    assert response.status_code == 302
    assert response.url == CONFIRM_URL
    assert SmsMessage.objects.count() == notifications_sent_before + 1
    code = last_code()

    response = client.post(CONFIRM_URL, {"code": code})

    assert response.status_code == 302
    assert response.url == reverse("accounts:deleted")
    user.refresh_from_db()
    assert user.phone is None
    assert user.name == DELETED_USER_NAME
    assert not user.is_active
    assert user.deleted_at is not None
    assert not user.has_usable_password()
    # Signed out here and on every other device.
    assert "_auth_user_id" not in client.session
    assert other_device.get(reverse("me:account")).status_code == 302
    # Minimum data: no OTP rows, number removed from the SMS log; consent proof kept.
    assert not OTPChallenge.objects.filter(phone=PHONE).exists()
    assert not SmsMessage.objects.filter(to_phone=PHONE).exists()
    assert ConsentRecord.objects.filter(user=user).count() == 2
    assert b"Your account has been deleted" in client.get(response.url).content


def test_wrong_code_does_not_delete(client, user):
    client.force_login(user)
    client.post(DELETE_URL)

    response = client.post(CONFIRM_URL, {"code": wrong(last_code())})

    assert b"Wrong code. 4 attempts left." in response.content
    user.refresh_from_db()
    assert user.phone == PHONE
    assert user.is_active


def test_login_code_cannot_confirm_deletion(user):
    services.request_code(phone=PHONE, purpose=OTPChallenge.Purpose.LOGIN, ip=IP)
    with pytest.raises(services.NoActiveCode):
        services.delete_account(user, code=last_code(), ip=IP)
    user.refresh_from_db()
    assert not user.is_deleted


def test_deletion_cancels_queued_messages_to_the_number(user):
    with_reminder = notifications.queue_sms(
        to_phone=PHONE,
        purpose="reminder",
        body="7 pm",
        scheduled_for=timezone.now() + timedelta(hours=3),
    )
    services.request_deletion_code(user, ip=IP)
    services.delete_account(user, code=last_code(), ip=IP)

    with_reminder.refresh_from_db()
    assert with_reminder.to_phone is None
    assert with_reminder.status == SmsMessage.Status.CANCELLED


def test_admin_rights_removed_on_deletion(user):
    User.objects.filter(pk=user.pk).update(is_staff=True, is_superuser=True)
    user.refresh_from_db()
    services.request_deletion_code(user, ip=IP)
    services.delete_account(user, code=last_code(), ip=IP)
    user.refresh_from_db()
    assert not user.is_staff
    assert not user.is_superuser


def test_same_number_can_sign_up_again_as_a_new_account(user):
    services.request_deletion_code(user, ip=IP)
    services.delete_account(user, code=last_code(), ip=IP)

    services.request_code(phone=PHONE, purpose=OTPChallenge.Purpose.LOGIN, ip=IP)
    new_user, created = services.sign_in_with_code(phone=PHONE, code=last_code(), ip=IP)

    assert created
    assert new_user.pk != user.pk


def test_deleted_account_cannot_delete_again(user):
    services.request_deletion_code(user, ip=IP)
    services.delete_account(user, code=last_code(), ip=IP)
    user.refresh_from_db()
    with pytest.raises(NotAllowed):
        services.request_deletion_code(user, ip=IP)
    with pytest.raises(NotAllowed):
        services.delete_account(user, code="123456", ip=IP)


def test_deletion_code_requests_are_rate_limited(client, user):
    client.force_login(user)
    for _ in range(3):
        client.post(DELETE_URL)
    response = client.post(DELETE_URL)
    assert response.status_code == 429
    assert b"Please wait" in response.content


def test_locked_number_on_confirm_returns_429(client, user):
    client.force_login(user)
    client.post(DELETE_URL)
    code = last_code()
    for _ in range(4):
        client.post(CONFIRM_URL, {"code": wrong(code)})
    response = client.post(CONFIRM_URL, {"code": wrong(code)})
    assert response.status_code == 429


def test_confirm_page_renders(client, user):
    client.force_login(user)
    response = client.get(CONFIRM_URL)
    assert response.status_code == 200
    assert b'autocomplete="one-time-code"' in response.content


def test_deletion_view_handles_refusal(client, user, monkeypatch):
    def refuse(*args, **kwargs):
        raise NotAllowed("Transfer your venue first.")

    monkeypatch.setattr(services, "delete_account", refuse)
    client.force_login(user)
    response = client.post(CONFIRM_URL, {"code": "123456"})
    assert response.status_code == 403
    assert b"Transfer your venue first." in response.content
