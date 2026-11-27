"""OTP rules (BR-27, US-P01): hashing, expiry, wrong codes, lock, and rate limits."""

import hashlib
import hmac
import threading
from datetime import timedelta

import pytest
from django.conf import settings
from django.db import connection

from accounts import services
from accounts.models import OTPChallenge
from core.exceptions import RateLimited
from notifications.models import SmsMessage

from .conftest import IP, PHONE, last_code, wrong

LOGIN = OTPChallenge.Purpose.LOGIN
pytestmark = pytest.mark.django_db


def request(phone=PHONE, ip=IP, purpose=LOGIN):
    return services.request_code(phone=phone, purpose=purpose, ip=ip)


def verify(code, phone=PHONE, ip=IP, purpose=LOGIN):
    return services.verify_code(phone=phone, code=code, purpose=purpose, ip=ip)


# ---------------------------------------------------------------- storing the code


def test_only_an_hmac_of_the_code_is_stored(clock):
    challenge = request()
    code = last_code()

    challenge.refresh_from_db()
    expected = hmac.new(
        settings.OTP_HMAC_KEY.encode(), f"{challenge.pk}:{code}".encode(), hashlib.sha256
    ).hexdigest()
    assert challenge.code_hash == expected
    stored = {str(value) for value in OTPChallenge.objects.values().get().values()}
    assert not any(code in value for value in stored)
    sms = SmsMessage.objects.get()
    assert sms.body == "[OTP]"
    assert code not in sms.encrypted_body


def test_code_is_six_digits_from_secrets(monkeypatch, clock):
    monkeypatch.setattr(services.secrets, "randbelow", lambda n: 42)
    request()
    assert last_code() == "000042"  # leading zeros kept


def test_challenge_records_purpose_expiry_and_ip(clock):
    challenge = request()
    assert challenge.purpose == LOGIN
    assert challenge.expires_at - challenge.created_at == timedelta(minutes=5)
    assert challenge.ip_address == IP
    assert challenge.attempts == 0
    assert challenge.consumed_at is None


# ---------------------------------------------------------------- expiry


def test_code_works_just_before_five_minutes(clock):
    request()
    code = last_code()
    clock.shift(timedelta(minutes=4, seconds=59))

    challenge = verify(code)

    assert challenge.consumed_at is not None


def test_code_expires_at_five_minutes(clock):
    request()
    code = last_code()
    clock.shift(timedelta(minutes=5))

    with pytest.raises(services.CodeExpired) as exc:
        verify(code)
    assert "expired" in str(exc.value.message).lower()
    # An expired code is not counted as a wrong guess.
    assert OTPChallenge.objects.get().attempts == 0


def test_new_code_can_be_requested_after_expiry(clock):
    request()
    clock.shift(timedelta(minutes=6))
    request()
    verify(last_code())


# ---------------------------------------------------------------- wrong codes and reuse


def test_wrong_code_is_counted_and_reports_attempts_left(clock):
    request()
    code = last_code()

    with pytest.raises(services.WrongCode) as exc:
        verify(wrong(code))

    assert exc.value.remaining == 4
    assert OTPChallenge.objects.get().attempts == 1
    verify(code)  # the right code still works afterwards


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "٠١٢٣٤٥"])
def test_malformed_codes_count_as_wrong(clock, bad):
    request()
    with pytest.raises(services.WrongCode):
        verify(bad)


def test_code_cannot_be_used_twice(clock):
    request()
    code = last_code()
    verify(code)

    with pytest.raises(services.NoActiveCode):
        verify(code)


def test_only_the_newest_code_is_accepted(clock):
    request()
    first = last_code()
    clock.shift(timedelta(seconds=30))
    request()
    second = last_code()
    if first == second:  # pragma: no cover - one in a million
        pytest.skip("random codes collided")

    with pytest.raises(services.WrongCode):
        verify(first)
    verify(second)


def test_verify_without_any_code_requested():
    with pytest.raises(services.NoActiveCode):
        verify("123456")


def test_code_for_one_purpose_does_not_work_for_another(clock):
    request(purpose=OTPChallenge.Purpose.DELETE_ACCOUNT)
    with pytest.raises(services.NoActiveCode):
        verify(last_code(), purpose=LOGIN)


# ---------------------------------------------------------------- 5 wrong codes lock the number


def test_five_wrong_codes_lock_the_number_for_fifteen_minutes(clock):
    request()
    code = last_code()
    for remaining in [4, 3, 2, 1]:
        with pytest.raises(services.WrongCode) as exc:
            verify(wrong(code))
        assert exc.value.remaining == remaining

    with pytest.raises(services.NumberLocked) as exc:
        verify(wrong(code))
    assert exc.value.retry_after == 15 * 60

    # Locked: even the right code is refused, and no new code can be requested.
    with pytest.raises(services.NumberLocked):
        verify(code)
    with pytest.raises(services.NumberLocked):
        request()
    assert SmsMessage.objects.count() == 1


def test_lock_reports_remaining_wait(clock):
    request()
    code = last_code()
    for _ in range(4):
        with pytest.raises(services.WrongCode):
            verify(wrong(code))
    with pytest.raises(services.NumberLocked):
        verify(wrong(code))

    clock.shift(timedelta(minutes=10))
    with pytest.raises(services.NumberLocked) as exc:
        request()
    assert exc.value.retry_after == 5 * 60
    assert services.locked_until(PHONE) is not None


def test_lock_lifts_after_fifteen_minutes(clock):
    request()
    code = last_code()
    for _ in range(4):
        with pytest.raises(services.WrongCode):
            verify(wrong(code))
    with pytest.raises(services.NumberLocked):
        verify(wrong(code))

    clock.shift(timedelta(minutes=15))
    assert services.locked_until(PHONE) is None
    request()
    verify(last_code())


def test_wrong_codes_across_several_codes_add_up(clock):
    request()
    for _ in range(3):
        with pytest.raises(services.WrongCode):
            verify(wrong(last_code()))
    clock.shift(timedelta(minutes=1))
    request()
    with pytest.raises(services.WrongCode) as exc:
        verify(wrong(last_code()))
    assert exc.value.remaining == 1
    with pytest.raises(services.NumberLocked):
        verify(wrong(last_code()))


def test_wrong_codes_older_than_fifteen_minutes_are_forgotten(clock):
    request()
    for _ in range(4):
        with pytest.raises(services.WrongCode):
            verify(wrong(last_code()))
    clock.shift(timedelta(minutes=16))
    request()
    with pytest.raises(services.WrongCode) as exc:
        verify(wrong(last_code()))
    assert exc.value.remaining == 4


def test_lock_is_per_number(clock):
    request()
    code = last_code()
    for _ in range(4):
        with pytest.raises(services.WrongCode):
            verify(wrong(code))
    with pytest.raises(services.NumberLocked):
        verify(wrong(code))

    other = "+94711234567"
    request(phone=other)
    verify(last_code(other), phone=other)


# ---------------------------------------------------------------- per-number request limit


def test_three_requests_per_number_per_fifteen_minutes(clock):
    for _ in range(3):
        request()
        clock.shift(timedelta(minutes=2))

    with pytest.raises(RateLimited) as exc:
        request()

    # The first request was 6 minutes ago, so the wait is 9 minutes.
    assert exc.value.retry_after == 9 * 60
    assert exc.value.retry_after_minutes == 9
    assert OTPChallenge.objects.count() == 3
    assert SmsMessage.objects.count() == 3


def test_request_window_slides(clock):
    request()
    clock.shift(timedelta(minutes=5))
    request()
    request()
    clock.shift(timedelta(minutes=10, seconds=1))  # first request now older than 15 min

    request()

    assert OTPChallenge.objects.count() == 4


def test_request_limit_is_per_number(clock):
    for _ in range(3):
        request()
    request(phone="+94711234567")


# ---------------------------------------------------------------- per-IP limits


def test_ten_code_requests_per_ip_per_hour(clock):
    phones = [f"+9477000{i:04d}" for i in range(11)]
    for phone in phones[:10]:
        request(phone=phone)

    with pytest.raises(RateLimited):
        request(phone=phones[10])

    assert SmsMessage.objects.count() == 10
    request(phone=phones[10], ip="203.0.113.50")  # another IP is fine


def test_ip_request_limit_resets_next_hour(clock):
    for i in range(10):
        request(phone=f"+9477000{i:04d}")
    clock.shift(timedelta(hours=1))
    request(phone="+94770009999")


def test_thirty_code_checks_per_ip_per_hour(clock):
    for i in range(30):
        with pytest.raises(services.NoActiveCode):
            verify("123456", phone=f"+9477000{i:04d}")

    with pytest.raises(RateLimited):
        verify("123456", phone="+94770009999")


# ---------------------------------------------------------------- concurrency


@pytest.mark.django_db(transaction=True)
def test_parallel_requests_cannot_exceed_the_number_limit():
    results = []
    barrier = threading.Barrier(6)

    def worker(i):
        barrier.wait()
        try:
            services.request_code(phone=PHONE, purpose=LOGIN, ip=f"203.0.113.{i}")
            results.append("ok")
        except RateLimited:
            results.append("limited")
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(results) == ["limited"] * 3 + ["ok"] * 3
    assert OTPChallenge.objects.filter(phone=PHONE).count() == 3


@pytest.mark.django_db(transaction=True)
def test_parallel_guesses_cannot_exceed_five_wrong_codes():
    services.request_code(phone=PHONE, purpose=LOGIN, ip=IP)
    code = last_code()
    barrier = threading.Barrier(8)
    errors = []

    def worker(i):
        barrier.wait()
        try:
            services.verify_code(phone=PHONE, code=wrong(code), purpose=LOGIN, ip=f"203.0.113.{i}")
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors.count("WrongCode") == 4
    assert errors.count("NumberLocked") == 4
    assert OTPChallenge.objects.get().attempts == 5


def test_old_otp_rows_are_purged(clock):
    request()
    clock.shift(timedelta(hours=24, seconds=1))
    request(phone="+94711234567")
    assert services.purge_old_otps() == 1
    assert list(OTPChallenge.objects.values_list("phone", flat=True)) == ["+94711234567"]
