"""Admin sign-in: platform admins with number + password, rate limits, 8 hours (D9, D16)."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from django.conf import settings
from django.urls import reverse

from accounts.models import User
from accounts.tests.factories import UserFactory
from adminpanel.sites import SESSION_VERIFIED
from adminpanel.testing import sign_in_admin
from notifications.models import SmsMessage

pytestmark = pytest.mark.django_db

ADMIN_PHONE = "+94711234567"
PASSWORD = "a-long-admin-password"
LOGIN = reverse("admin:login")
INDEX = reverse("admin:index")
T0 = datetime(2026, 12, 7, 4, 30, tzinfo=UTC)


@pytest.fixture
def clock():
    with time_machine.travel(T0, tick=False) as traveller:
        yield traveller


@pytest.fixture
def root(db):
    return User.objects.create_superuser(phone=ADMIN_PHONE, name="Founder", password=PASSWORD)


def sign_in(client, phone="071 123 4567", password=PASSWORD, **extra):
    return client.post(LOGIN, {"phone": phone, "password": password, **extra})


def test_admin_signs_in_with_number_and_password(client, root, clock):
    assert client.get(INDEX).status_code == 302
    assert client.get(LOGIN).status_code == 200

    response = sign_in(client)

    assert response.status_code == 302
    assert response.url == INDEX
    assert client.session["_auth_user_id"] == str(root.pk)
    assert client.get(INDEX).status_code == 200
    assert not SmsMessage.objects.exists()  # no SMS step
    # Already signed in: the sign-in page goes straight to the admin home.
    assert client.get(LOGIN).url == INDEX


def test_platform_admins_with_is_staff_can_sign_in(client, clock):
    staff = UserFactory(phone=ADMIN_PHONE, is_staff=True)
    staff.set_password(PASSWORD)
    staff.save()
    assert sign_in(client).url == INDEX
    assert client.get(INDEX).status_code == 200


def test_admin_sign_in_does_not_shorten_the_site_session(client, root, clock):
    sign_in(client)
    assert client.session.get_expiry_age() == settings.SESSION_COOKIE_AGE  # 30 days


def test_next_page_is_kept_but_never_another_site(client, root, clock):
    target = reverse("admin:bookings_booking_changelist")
    assert sign_in(client, next=target).url == target
    client.logout()
    assert sign_in(client, next="https://evil.example/").url == INDEX


def test_sign_in_page_keeps_next_from_the_redirect(client, root):
    response = client.get(INDEX, follow=True)
    assert f'name="next" value="{INDEX}"' in response.content.decode()


@pytest.mark.parametrize("make", ["player", "inactive"])
def test_players_and_disabled_admins_cannot_sign_in(client, make):
    if make == "player":
        user = UserFactory(phone=ADMIN_PHONE)
    else:
        user = User.objects.create_superuser(phone=ADMIN_PHONE, name="Old", password=PASSWORD)
        user.is_active = False
    user.set_password(PASSWORD)
    user.save()

    response = sign_in(client)

    assert response.status_code == 200
    assert "Wrong mobile number or password." in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_signed_in_players_cannot_open_the_admin(client):
    player = UserFactory()
    sign_in_admin(client, player)  # even with the flag, a player is not a platform admin
    response = client.get(INDEX)
    assert response.status_code == 302
    assert response.url.startswith(LOGIN)


def test_an_admin_signed_in_by_sms_code_must_still_use_the_password(client, root):
    client.force_login(root)  # e.g. signed in to the player site with an SMS code
    response = client.get(INDEX)
    assert response.status_code == 302
    assert response.url.startswith(LOGIN)


def test_wrong_password_gives_the_same_message_as_an_unknown_number(client, root):
    for response in (sign_in(client, password="not-it"), sign_in(client, phone="077 999 9999")):
        assert response.status_code == 200
        assert "Wrong mobile number or password." in response.content.decode()


def test_bad_number_format_is_a_form_error(client, root):
    response = sign_in(client, phone="12345")
    assert "Enter a valid Sri Lankan mobile number" in response.content.decode()


def test_five_wrong_passwords_lock_that_number_for_15_minutes(client, root, clock, caplog):
    caplog.set_level(logging.INFO)
    for _ in range(5):
        sign_in(client, password="not-the-password")

    response = sign_in(client)  # right password, but locked

    assert response.status_code == 429
    assert "Try again in 15 minutes." in response.content.decode()
    assert "_auth_user_id" not in client.session
    # Failures are logged with the number masked, never in full.
    assert "admin_login.locked" in caplog.text
    assert ADMIN_PHONE not in caplog.text
    assert "711234567" not in caplog.text

    clock.shift(timedelta(minutes=15, seconds=1))
    assert sign_in(client).status_code == 302


def test_a_correct_password_resets_the_failure_count(client, root, clock):
    for _ in range(4):
        sign_in(client, password="not-the-password")
    assert sign_in(client).status_code == 302
    client.logout()
    for _ in range(4):
        sign_in(client, password="not-the-password")
    assert sign_in(client).status_code == 302


def test_at_most_20_attempts_per_ip_per_hour(client, root):
    for n in range(20):
        sign_in(client, phone=f"077 000 {n:04d}", password="guess")
    response = sign_in(client)
    assert response.status_code == 429
    assert "_auth_user_id" not in client.session


def test_admin_access_ends_after_8_hours(client, root, clock):
    sign_in(client)
    assert client.get(INDEX).status_code == 200
    clock.shift(timedelta(hours=7, minutes=59))
    assert client.get(INDEX).status_code == 200
    clock.shift(timedelta(minutes=2))
    assert client.get(INDEX).status_code == 302
    # Still signed in to the site itself; only admin access needs the password again.
    assert client.session["_auth_user_id"] == str(root.pk)


def test_verified_flag_belongs_to_one_user(client, root):
    other = User.objects.create_superuser(phone="+94719999999", name="Other", password=PASSWORD)
    sign_in_admin(client, root)
    session = client.session
    session[SESSION_VERIFIED] = {"user": other.pk, "at": session[SESSION_VERIFIED]["at"]}
    session.save()
    assert client.get(INDEX).status_code == 302


def test_logout_ends_the_admin_session(client, root):
    sign_in_admin(client, root)
    client.post(reverse("admin:logout"))
    assert client.get(INDEX).status_code == 302
