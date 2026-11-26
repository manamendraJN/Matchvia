import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import DELETED_USER_NAME, ConsentRecord, OTPChallenge, User

pytestmark = pytest.mark.django_db


def test_custom_user_model_is_active():
    assert get_user_model() is User
    assert User.USERNAME_FIELD == "phone"


def test_create_user_normalises_phone_and_has_no_password():
    user = User.objects.create_user(phone="077 123 4567", name="Kasun")

    assert user.phone == "+94771234567"
    assert user.name == "Kasun"
    assert not user.has_usable_password()
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser
    assert user.date_joined is not None


def test_create_user_rejects_invalid_phone():
    with pytest.raises(ValueError, match="Sri Lankan"):
        User.objects.create_user(phone="0112345678")


def test_phone_is_unique():
    User.objects.create_user(phone="+94771234567")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(phone="0771234567")


def test_create_superuser_needs_password_and_gets_admin_flags():
    with pytest.raises(ValueError, match="password"):
        User.objects.create_superuser(phone="+94771234567", name="Admin", password="")

    admin = User.objects.create_superuser(
        phone="+94771234567", name="Admin", password="a-long-admin-password"
    )
    assert admin.is_staff
    assert admin.is_superuser
    assert admin.check_password("a-long-admin-password")


def test_natural_key_lookup_accepts_local_format():
    user = User.objects.create_user(phone="+94771234567")
    assert User.objects.get_by_natural_key("077 123 4567") == user
    with pytest.raises(User.DoesNotExist):
        User.objects.get_by_natural_key("not-a-phone")


def test_database_rejects_deleted_user_with_phone():
    user = User.objects.create_user(phone="+94771234567")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user.pk).update(deleted_at=timezone.now())


def test_database_rejects_unnormalised_phone_written_outside_django():
    user = User.objects.create_user(phone="+94771234567")
    for bad in ["0771234567", "+94112345678", "+447911123456"]:
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=user.pk).update(phone=bad)


def test_several_deleted_users_can_exist():
    now = timezone.now()
    for _ in range(2):
        User.objects.create(phone=None, name=DELETED_USER_NAME, deleted_at=now, is_active=False)
    assert User.objects.filter(phone__isnull=True).count() == 2


def test_str():
    user = User.objects.create_user(phone="+94771234567", name="Kasun")
    assert str(user) == "Kasun"
    assert str(User.objects.create_user(phone="+94711234567")).startswith("User #")
    deleted = User(phone=None, name=DELETED_USER_NAME, deleted_at=timezone.now())
    assert str(deleted) == DELETED_USER_NAME
    assert user.get_full_name() == user.get_short_name() == "Kasun"
    assert not user.is_deleted


def test_consent_unique_per_document_and_version():
    user = User.objects.create_user(phone="+94771234567")
    ConsentRecord.objects.create(user=user, document="privacy", version="2026-11-26")
    ConsentRecord.objects.create(user=user, document="privacy", version="2027-01-01")
    with pytest.raises(IntegrityError), transaction.atomic():
        ConsentRecord.objects.create(user=user, document="privacy", version="2026-11-26")
    assert str(ConsentRecord.objects.first()).startswith("privacy")


def test_database_rejects_unknown_consent_document():
    user = User.objects.create_user(phone="+94771234567")
    with pytest.raises(IntegrityError), transaction.atomic():
        ConsentRecord.objects.create(user=user, document="marketing", version="1")


def _challenge(**kwargs):
    defaults = {
        "phone": "+94771234567",
        "purpose": "login",
        "code_hash": "x",
        "expires_at": timezone.now(),
    }
    return OTPChallenge.objects.create(**{**defaults, **kwargs})


def test_database_caps_attempts_at_five():
    challenge = _challenge(attempts=5)
    assert str(challenge).startswith("OTP #")
    with pytest.raises(IntegrityError), transaction.atomic():
        OTPChallenge.objects.filter(pk=challenge.pk).update(attempts=6)


def test_database_rejects_unknown_otp_purpose():
    with pytest.raises(IntegrityError), transaction.atomic():
        _challenge(purpose="reset_password")
