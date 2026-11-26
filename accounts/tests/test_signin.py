"""Sign-in service and screens P4-P6 (US-P01, NFR-07)."""

import logging
import re
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse

from accounts import services
from accounts.models import ConsentRecord, OTPChallenge, User
from notifications.models import SmsMessage

from .conftest import IP, PHONE, last_code, wrong
from .factories import UserFactory

pytestmark = pytest.mark.django_db

PHONE_URL = reverse("accounts:phone")
CODE_URL = reverse("accounts:code")
WELCOME_URL = reverse("accounts:welcome")


def request_code_via_page(client, phone="0771234567", **extra):
    return client.post(PHONE_URL, {"phone": phone, **extra})


def sign_in(client, phone="0771234567", next_url=None):
    data = {"next": next_url} if next_url else {}
    request_code_via_page(client, phone, **data)
    return client.post(CODE_URL, {"code": last_code()})


# ---------------------------------------------------------------- service


def test_new_number_creates_a_player_account_without_password(clock):
    services.request_code(phone=PHONE, purpose=OTPChallenge.Purpose.LOGIN, ip=IP)

    user, created = services.sign_in_with_code(phone=PHONE, code=last_code(), ip=IP)

    assert created
    assert user.phone == PHONE
    assert user.name == ""
    assert not user.has_usable_password()
    assert services.needs_profile(user)


def test_existing_number_signs_into_the_same_account(clock, user):
    services.request_code(phone=PHONE, purpose=OTPChallenge.Purpose.LOGIN, ip=IP)

    signed_in, created = services.sign_in_with_code(phone=PHONE, code=last_code(), ip=IP)

    assert signed_in == user
    assert not created
    assert User.objects.count() == 1


def test_disabled_account_cannot_sign_in(clock, user):
    User.objects.filter(pk=user.pk).update(is_active=False)
    services.request_code(phone=PHONE, purpose=OTPChallenge.Purpose.LOGIN, ip=IP)

    with pytest.raises(services.AccountDisabled):
        services.sign_in_with_code(phone=PHONE, code=last_code(), ip=IP)


def test_parallel_first_sign_in_reuses_the_account(clock, monkeypatch):
    services.request_code(phone=PHONE, purpose=OTPChallenge.Purpose.LOGIN, ip=IP)
    code = last_code()
    real_get = User.objects.get
    calls = []

    def get(**kwargs):
        # First lookup misses, as if a parallel request created the user right after it.
        if not calls:
            calls.append(1)
            User.objects.create_user(phone=PHONE)
            raise User.DoesNotExist
        return real_get(**kwargs)

    monkeypatch.setattr(User.objects, "get", get)
    user, created = services.sign_in_with_code(phone=PHONE, code=code, ip=IP)
    assert not created
    assert User.objects.filter(phone=PHONE).count() == 1
    assert user.phone == PHONE


# ---------------------------------------------------------------- P4 phone number


def test_phone_page_renders(client):
    response = client.get(PHONE_URL)
    assert response.status_code == 200
    assert b"Send code" in response.content
    assert b'autocomplete="tel"' in response.content


def test_invalid_number_shows_message_and_sends_nothing(client):
    response = request_code_via_page(client, "0112345678")

    assert response.status_code == 200
    assert b"Enter a valid Sri Lankan mobile number" in response.content
    assert SmsMessage.objects.count() == 0
    assert OTPChallenge.objects.count() == 0


@pytest.mark.parametrize("typed", ["0771234567", "771234567", "+94771234567", "077 123 4567"])
def test_number_is_stored_in_one_format(client, typed):
    response = request_code_via_page(client, typed)

    assert response.status_code == 302
    assert response.url == CODE_URL
    assert OTPChallenge.objects.get().phone == "+94771234567"
    assert client.session["auth_phone"] == "+94771234567"


def _comparable(html: bytes, local_number: bytes) -> bytes:
    # CSRF tokens and CSP nonces differ on every response; the number is the one typed.
    html = re.sub(rb'(value=|nonce=|"X-CSRFToken": )"[^"]*"', rb'"*"', html)
    return html.replace(local_number, b"NUMBER")


def test_same_reply_for_known_and_unknown_numbers(client, user):
    other = Client()
    known = request_code_via_page(client, PHONE)
    unknown = request_code_via_page(other, "0711234567")

    assert known.status_code == unknown.status_code == 302
    assert known.url == unknown.url
    known_page = _comparable(client.get(CODE_URL).content, b"077 123 4567")
    unknown_page = _comparable(other.get(CODE_URL).content, b"071 123 4567")
    assert known_page == unknown_page


def test_rate_limited_request_shows_wait_and_returns_429(client, clock):
    for _ in range(3):
        request_code_via_page(client)
    clock.shift(timedelta(minutes=1))

    response = request_code_via_page(client)

    assert response.status_code == 429
    assert b"Please wait 14 minutes and try again." in response.content
    assert SmsMessage.objects.count() == 3


def test_signed_in_user_skips_the_phone_page(client, user):
    client.force_login(user)
    response = client.get(PHONE_URL + "?next=/me/account/")
    assert response.status_code == 302
    assert response.url == "/me/account/"


def test_csrf_is_enforced():
    client = Client(enforce_csrf_checks=True)
    response = request_code_via_page(client)
    assert response.status_code == 403
    assert SmsMessage.objects.count() == 0


# ---------------------------------------------------------------- P5 code


def test_code_page_needs_a_requested_number(client):
    response = client.get(CODE_URL)
    assert response.status_code == 302
    assert response.url == PHONE_URL


def test_code_page_shows_the_number_locally_formatted(client):
    request_code_via_page(client)
    response = client.get(CODE_URL)
    assert b"077 123 4567" in response.content
    assert b'autocomplete="one-time-code"' in response.content


def test_full_first_sign_in_flow(client):
    request_code_via_page(client, next="/me/account/")
    session_before = client.session.session_key

    response = client.post(CODE_URL, {"code": last_code()})

    assert response.status_code == 302
    assert response.url == WELCOME_URL + "?next=%2Fme%2Faccount%2F"
    assert client.session.session_key != session_before  # rotated at login
    assert "auth_phone" not in client.session
    user = User.objects.get(phone=PHONE)
    assert int(client.session["_auth_user_id"]) == user.pk

    response = client.post(
        WELCOME_URL, {"name": "  Kasun   Perera ", "accept": "on", "next": "/me/account/"}
    )

    assert response.status_code == 302
    assert response.url == "/me/account/"
    user.refresh_from_db()
    assert user.name == "Kasun Perera"
    consents = set(ConsentRecord.objects.filter(user=user).values_list("document", "version"))
    assert consents == set(services.CURRENT_DOCUMENTS.items())


def test_returning_user_goes_straight_to_next(client, user):
    response = sign_in(client, PHONE, next_url="/me/account/")
    assert response.status_code == 302
    assert response.url == "/me/account/"


def test_returning_user_without_next_goes_home(client, user):
    response = sign_in(client, PHONE)
    assert response.url == reverse("home")


@pytest.mark.parametrize(
    "evil",
    ["https://evil.example/", "//evil.example/", "/\\evil.example", "javascript:alert(1)"],
)
def test_next_cannot_redirect_off_site(client, user, evil):
    response = sign_in(client, PHONE, next_url=evil)
    assert response.url == reverse("home")


def test_wrong_code_shows_attempts_left(client):
    request_code_via_page(client)
    response = client.post(CODE_URL, {"code": wrong(last_code())})

    assert response.status_code == 200
    assert b"Wrong code. 4 attempts left." in response.content
    assert "_auth_user_id" not in client.session


def test_badly_formatted_code_is_not_counted(client):
    request_code_via_page(client)
    response = client.post(CODE_URL, {"code": "12a"})
    assert b"Enter the 6-digit code from the SMS." in response.content
    assert OTPChallenge.objects.get().attempts == 0


def test_expired_code_offers_a_new_one(client, clock):
    request_code_via_page(client)
    code = last_code()
    clock.shift(timedelta(minutes=5))

    response = client.post(CODE_URL, {"code": code})

    assert b"Code expired. Request a new one." in response.content
    assert response.context["offer_new_code"] is True


def test_locked_number_returns_429_with_wait(client):
    request_code_via_page(client)
    code = last_code()
    for _ in range(4):
        client.post(CODE_URL, {"code": wrong(code)})

    response = client.post(CODE_URL, {"code": wrong(code)})

    assert response.status_code == 429
    assert b"Too many wrong codes. Try again in 15 minutes." in response.content


def test_disabled_account_sees_message(client, user):
    User.objects.filter(pk=user.pk).update(is_active=False)
    response = sign_in(client, PHONE)
    assert response.status_code == 403
    assert b"This account is disabled" in response.content


def test_resend_sends_a_new_code(client, clock):
    request_code_via_page(client)
    first = last_code()
    clock.shift(timedelta(seconds=40))

    response = client.post(reverse("accounts:resend"), follow=True)

    assert b"We sent you a new code." in response.content
    assert OTPChallenge.objects.count() == 2
    second = last_code()
    if second != first:
        assert client.post(CODE_URL, {"code": first}).status_code == 200  # old code refused


def test_resend_is_rate_limited(client):
    for _ in range(3):
        request_code_via_page(client)
    response = client.post(reverse("accounts:resend"), follow=True)
    assert b"Please wait" in response.content
    assert OTPChallenge.objects.count() == 3


def test_resend_without_session_goes_to_phone_page(client):
    response = client.post(reverse("accounts:resend"))
    assert response.url == PHONE_URL


def test_resend_refuses_get(client):
    assert client.get(reverse("accounts:resend")).status_code == 405


def test_sign_in_flow_never_logs_code_or_full_number(client, caplog):
    caplog.set_level(logging.DEBUG)
    request_code_via_page(client)
    code = last_code()
    client.post(CODE_URL, {"code": wrong(code)})
    client.post(CODE_URL, {"code": code})

    assert code not in caplog.text
    assert PHONE not in caplog.text
    assert "0771234567" not in caplog.text


# ---------------------------------------------------------------- P6 first-time profile


def test_welcome_requires_sign_in(client):
    response = client.get(WELCOME_URL)
    assert response.status_code == 302
    assert response.url.startswith(PHONE_URL)


def test_welcome_requires_consent(client):
    client.force_login(UserFactory(name="", consented=False))
    response = client.post(WELCOME_URL, {"name": "Kasun"})

    assert response.status_code == 200
    assert b"Please accept the privacy notice and terms to continue." in response.content
    assert ConsentRecord.objects.count() == 0


@pytest.mark.parametrize("name", ["", "   ", "x" * 81, "Kasun\x00"])
def test_welcome_rejects_bad_names(client, name):
    user = UserFactory(name="", consented=False)
    client.force_login(user)
    response = client.post(WELCOME_URL, {"name": name, "accept": "on"})
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.name == ""


def test_welcome_skipped_when_profile_is_complete(client, user):
    client.force_login(user)
    response = client.get(WELCOME_URL + "?next=/me/account/")
    assert response.url == "/me/account/"


def test_new_terms_version_asks_again(client, user, monkeypatch):
    monkeypatch.setitem(services.CURRENT_DOCUMENTS, ConsentRecord.Document.TERMS, "2027-06-01")
    assert services.needs_profile(user)
    client.force_login(user)
    assert client.get(WELCOME_URL).status_code == 200


def test_complete_profile_service_requires_acceptance(user):
    with pytest.raises(services.RuleViolation):
        services.complete_profile(user, name="Kasun", accepted=False)


# ---------------------------------------------------------------- sign out


def test_logout_requires_post(client, user):
    client.force_login(user)
    assert client.get(reverse("accounts:logout")).status_code == 405
    assert "_auth_user_id" in client.session


def test_logout_signs_out_and_goes_home(client, user):
    client.force_login(user)
    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert response.url == reverse("home")
    assert "_auth_user_id" not in client.session
