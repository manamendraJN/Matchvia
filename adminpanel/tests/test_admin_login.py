"""Admin sign-in: superusers only, password then SMS code, limits, 8-hour sessions (C9, D9)."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from django.urls import reverse

from accounts.models import OTPChallenge, User
from accounts.tests.conftest import last_code, wrong
from accounts.tests.factories import UserFactory
from adminpanel import services
from adminpanel.sites import SESSION_VERIFIED
from adminpanel.testing import sign_in_admin
from notifications.models import SmsMessage

pytestmark = pytest.mark.django_db

ADMIN_PHONE = "+94711234567"
PASSWORD = "a-long-admin-password"
LOGIN = reverse("admin:login")
CODE = reverse("admin:login_code")
INDEX = reverse("admin:index")
T0 = datetime(2026, 12, 7, 4, 30, tzinfo=UTC)


@pytest.fixture
def clock():
    with time_machine.travel(T0, tick=False) as traveller:
        yield traveller


@pytest.fixture
def root(db):
    return User.objects.create_superuser(phone=ADMIN_PHONE, name="Founder", password=PASSWORD)


def password_step(client, phone="071 123 4567", password=PASSWORD, **extra):
    return client.post(LOGIN, {"phone": phone, "password": password, **extra})


def test_full_two_step_sign_in(client, root, clock):
    assert client.get(INDEX).status_code == 302
    assert client.get(LOGIN).status_code == 200

    response = password_step(client)

    assert response.status_code == 302
    assert response.url == CODE
    assert "_auth_user_id" not in client.session  # not signed in after the password alone
    assert client.get(INDEX).status_code == 302
    challenge = OTPChallenge.objects.get(phone=ADMIN_PHONE)
    assert challenge.purpose == OTPChallenge.Purpose.ADMIN_LOGIN
    assert client.get(CODE).status_code == 200

    response = client.post(CODE, {"code": last_code(ADMIN_PHONE)})

    assert response.status_code == 302
    assert response.url == INDEX
    assert client.session["_auth_user_id"] == str(root.pk)
    assert client.session.get_expiry_age() == 8 * 3600
    assert client.get(INDEX).status_code == 200
    # Already signed in: the sign-in page goes straight to the admin home.
    assert client.get(LOGIN).url == INDEX


def test_next_page_is_kept_but_never_another_site(client, root, clock):
    target = reverse("admin:bookings_booking_changelist")
    password_step(client, next=target)
    response = client.post(CODE, {"code": last_code(ADMIN_PHONE)})
    assert response.url == target

    client.logout()
    password_step(client, next="https://evil.example/")
    response = client.post(CODE, {"code": last_code(ADMIN_PHONE)})
    assert response.url == INDEX


def test_sign_in_page_keeps_next_from_the_redirect(client, root):
    response = client.get(INDEX, follow=True)
    assert f'name="next" value="{INDEX}"' in response.content.decode()


@pytest.mark.parametrize("make", ["player", "staff", "inactive"])
def test_only_active_superusers_get_a_code(client, make):
    if make == "player":
        UserFactory(phone=ADMIN_PHONE)
        user = User.objects.get(phone=ADMIN_PHONE)
        user.set_password(PASSWORD)
        user.save()
    elif make == "staff":
        user = UserFactory(phone=ADMIN_PHONE, is_staff=True)
        user.set_password(PASSWORD)
        user.save()
    else:
        user = User.objects.create_superuser(phone=ADMIN_PHONE, name="Old", password=PASSWORD)
        user.is_active = False
        user.save()

    response = password_step(client)

    assert response.status_code == 200
    assert "Wrong mobile number or password." in response.content.decode()
    assert not SmsMessage.objects.exists()


def test_signed_in_players_and_staff_cannot_open_the_admin(client):
    for user in (UserFactory(), UserFactory(is_staff=True)):
        sign_in_admin(client, user)  # even with the flag, they are not superusers
        response = client.get(INDEX)
        assert response.status_code == 302
        assert response.url.startswith(LOGIN)


def test_a_superuser_session_without_the_code_step_is_refused(client, root):
    client.force_login(root)  # e.g. signed in to the player site with an SMS code
    response = client.get(INDEX)
    assert response.status_code == 302
    assert response.url.startswith(LOGIN)


def test_wrong_password_gives_the_same_message_as_an_unknown_number(client, root):
    wrong_password = password_step(client, password="not-the-password")
    unknown = password_step(client, phone="077 999 9999")
    for response in (wrong_password, unknown):
        assert response.status_code == 200
        assert "Wrong mobile number or password." in response.content.decode()
    assert not SmsMessage.objects.exists()


def test_bad_number_format_is_a_form_error(client, root):
    response = password_step(client, phone="12345")
    assert "Enter a valid Sri Lankan mobile number" in response.content.decode()


def test_five_wrong_passwords_lock_that_number_for_15_minutes(client, root, clock, caplog):
    caplog.set_level(logging.INFO)
    for _ in range(5):
        password_step(client, password="not-the-password")

    response = password_step(client)  # right password, but locked

    assert response.status_code == 429
    assert "Try again in 15 minutes." in response.content.decode()
    assert not SmsMessage.objects.exists()
    # Failures are logged with the number masked, never in full.
    assert "admin_login.locked" in caplog.text
    assert ADMIN_PHONE not in caplog.text
    assert "711234567" not in caplog.text

    clock.shift(timedelta(minutes=15, seconds=1))
    assert password_step(client).status_code == 302


def test_a_correct_password_resets_the_failure_count(client, root, clock):
    for _ in range(4):
        password_step(client, password="not-the-password")
    assert password_step(client).status_code == 302
    for _ in range(4):
        password_step(client, password="not-the-password")
    clock.shift(timedelta(minutes=6))  # new code requests are limited per number, not this
    response = password_step(client)
    assert response.status_code == 302


def test_at_most_20_attempts_per_ip_per_hour(client, root):
    for n in range(20):
        password_step(client, phone=f"077 000 {n:04d}", password="guess")
    response = password_step(client)
    assert response.status_code == 429
    assert not SmsMessage.objects.exists()


def test_wrong_code_counts_down_and_locks(client, root, clock):
    password_step(client)
    code = last_code(ADMIN_PHONE)
    response = client.post(CODE, {"code": wrong(code)})
    assert "Wrong code. 4 attempts left." in response.content.decode()
    for _ in range(3):
        client.post(CODE, {"code": wrong(code)})
    response = client.post(CODE, {"code": wrong(code)})
    assert response.status_code == 429
    response = client.post(CODE, {"code": code})
    assert response.status_code == 429
    assert "_auth_user_id" not in client.session


def test_expired_code_is_refused(client, root, clock):
    password_step(client)
    code = last_code(ADMIN_PHONE)
    clock.shift(timedelta(minutes=5, seconds=1))
    response = client.post(CODE, {"code": code})
    assert "Code expired" in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_code_step_needs_the_password_step_first(client, root, clock):
    assert client.get(CODE).url == LOGIN
    password_step(client)
    clock.shift(timedelta(minutes=10, seconds=1))
    assert client.get(CODE).url == LOGIN
    assert client.post(CODE, {"code": "123456"}).url == LOGIN


def test_a_player_sign_in_code_cannot_finish_admin_sign_in(client, root, clock):
    from accounts import services as accounts

    password_step(client)
    admin_code = last_code(ADMIN_PHONE)
    accounts.request_code(phone=ADMIN_PHONE, purpose=OTPChallenge.Purpose.LOGIN, ip="10.0.0.1")
    player_code = last_code(ADMIN_PHONE)
    if player_code == admin_code:  # one in a million
        pytest.skip("random codes happened to match")

    response = client.post(CODE, {"code": player_code})

    assert "Wrong code." in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_admin_session_ends_after_8_hours(client, root, clock):
    sign_in_admin(client, root)
    assert client.get(INDEX).status_code == 200
    clock.shift(timedelta(hours=7, minutes=59))
    assert client.get(INDEX).status_code == 200
    clock.shift(timedelta(minutes=2))
    assert client.get(INDEX).status_code == 302


def test_verified_flag_belongs_to_one_user(client, root):
    other = User.objects.create_superuser(phone="+94719999999", name="Other", password=PASSWORD)
    sign_in_admin(client, root)
    session = client.session
    session[SESSION_VERIFIED] = {"user": other.pk, "at": session[SESSION_VERIFIED]["at"]}
    session.save()
    assert client.get(INDEX).status_code == 302


def test_pending_admin_rules(root, clock):
    now = T0
    assert services.pending_admin(None, None) is None
    assert services.pending_admin(root.pk, now.timestamp()) == root
    assert services.pending_admin(root.pk, (now - timedelta(minutes=11)).timestamp()) is None
    root.is_superuser = False
    root.save()
    assert services.pending_admin(root.pk, now.timestamp()) is None


def test_logout_ends_the_admin_session(client, root):
    sign_in_admin(client, root)
    client.post(reverse("admin:logout"))
    assert client.get(INDEX).status_code == 302
