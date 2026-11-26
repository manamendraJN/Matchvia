"""Business logic for accounts: users, phone OTP sign-in, consent and account deletion.

Services own the transaction; views stay thin. Cross-app calls go through the other
app's services.py (CLAUDE.md "Code conventions").

OTP rules (BR-27, architecture 3.1):
- 6-digit code from ``secrets``; only ``HMAC-SHA256(OTP_HMAC_KEY, "<challenge id>:<code>")`` is
  stored, compared in constant time; valid for 5 minutes; usable once.
- Max 3 code requests per number per 15 minutes (counted from OTPChallenge) and 10 per IP per
  hour (cache). Max 30 code checks per IP per hour.
- 5 wrong codes for a number within 15 minutes lock that number for 15 minutes.
- Requesting a code never reveals whether the number has an account.
"""

import hashlib
import hmac
import logging
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core import ratelimit
from core.db import advisory_xact_lock
from core.exceptions import DomainError, NotAllowed, RateLimited, RuleViolation
from core.phone import mask_phone
from notifications import services as notifications

from .models import DELETED_USER_NAME, ConsentRecord, OTPChallenge, Role, User

logger = logging.getLogger(__name__)

OTP_TTL = timedelta(minutes=5)
OTP_LENGTH = 6
MAX_WRONG_CODES = 5
LOCK_DURATION = timedelta(minutes=15)
REQUESTS_PER_PHONE = 3
REQUEST_WINDOW = timedelta(minutes=15)
REQUESTS_PER_IP_PER_HOUR = 10
VERIFIES_PER_IP_PER_HOUR = 30

# Bump when the text of the privacy notice or terms changes; users accept again (NFR-07).
PRIVACY_VERSION = "2026-11-26"
TERMS_VERSION = "2026-11-26"
CURRENT_DOCUMENTS = {
    ConsentRecord.Document.PRIVACY: PRIVACY_VERSION,
    ConsentRecord.Document.TERMS: TERMS_VERSION,
}

NAME_MAX_LENGTH = 80
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


# ---------------------------------------------------------------- errors


class OTPError(DomainError):
    """A code could not be accepted. The message is safe to show."""


class NoActiveCode(OTPError):
    def __init__(self):
        super().__init__(_("Request a new code."))


class CodeExpired(OTPError):
    def __init__(self):
        super().__init__(_("Code expired. Request a new one."))


class WrongCode(OTPError):
    def __init__(self, remaining: int):
        super().__init__(_("Wrong code."))
        self.remaining = remaining


class NumberLocked(RateLimited):
    """Too many wrong codes: the number is locked (BR-27)."""


class AccountDisabled(NotAllowed):
    def __init__(self):
        super().__init__(_("This account is disabled. Please contact Matchvia support."))


# ---------------------------------------------------------------- OTP helpers


def _generate_code() -> str:
    return f"{secrets.randbelow(10**OTP_LENGTH):0{OTP_LENGTH}d}"


def _hash_code(challenge_id: int, code: str) -> str:
    message = f"{challenge_id}:{code}".encode()
    return hmac.new(settings.OTP_HMAC_KEY.encode(), message, hashlib.sha256).hexdigest()


def _code_matches(challenge: OTPChallenge, code: str) -> bool:
    code = (code or "").strip()
    if len(code) != OTP_LENGTH or not code.isascii() or not code.isdigit():
        return False
    return hmac.compare_digest(_hash_code(challenge.pk, code), challenge.code_hash)


def _locked_until(phone: str, now):
    challenge = (
        OTPChallenge.objects.filter(phone=phone, locked_until__gt=now)
        .order_by("-locked_until")
        .first()
    )
    return challenge.locked_until if challenge else None


def locked_until(phone: str):
    """When the lock on this number ends, or None if it is not locked."""
    return _locked_until(phone, timezone.now())


# ---------------------------------------------------------------- request and verify


def request_code(*, phone: str, purpose: str, ip: str | None) -> OTPChallenge:
    """Create a challenge and queue the code SMS. ``phone`` must already be normalised.

    Raises RateLimited (IP or number limit) or NumberLocked. Nothing is queued in that case.
    """
    ratelimit.hit("otp-request-ip", ip, limit=REQUESTS_PER_IP_PER_HOUR, window=3600)
    now = timezone.now()
    with transaction.atomic():
        # Serialise requests for this number so parallel requests can't all pass the count.
        advisory_xact_lock(f"otp:{phone}")

        lock_ends = _locked_until(phone, now)
        if lock_ends:
            raise NumberLocked(retry_after=(lock_ends - now).total_seconds())

        recent = list(
            OTPChallenge.objects.filter(phone=phone, created_at__gt=now - REQUEST_WINDOW)
            .order_by("created_at")
            .values_list("created_at", flat=True)
        )
        if len(recent) >= REQUESTS_PER_PHONE:
            logger.warning("otp.request_limited phone=%s", mask_phone(phone))
            raise RateLimited(retry_after=(recent[0] + REQUEST_WINDOW - now).total_seconds())

        code = _generate_code()
        challenge = OTPChallenge.objects.create(
            phone=phone,
            purpose=purpose,
            code_hash="!",  # replaced below: the hash includes the challenge id
            expires_at=now + OTP_TTL,
            ip_address=ip,
            created_at=now,
        )
        challenge.code_hash = _hash_code(challenge.pk, code)
        challenge.save(update_fields=["code_hash"])
        notifications.queue_otp_sms(to_phone=phone, code=code)

    logger.info("otp.requested purpose=%s phone=%s", purpose, mask_phone(phone))
    return challenge


def verify_code(*, phone: str, code: str, purpose: str, ip: str | None) -> OTPChallenge:
    """Check a code against the newest open challenge for this number and purpose.

    On success the challenge is consumed and returned. Otherwise raises NoActiveCode,
    CodeExpired, WrongCode (with attempts left), NumberLocked or RateLimited. Wrong guesses
    are committed before the error is raised.
    """
    ratelimit.hit("otp-verify-ip", ip, limit=VERIFIES_PER_IP_PER_HOUR, window=3600)
    now = timezone.now()
    with transaction.atomic():
        advisory_xact_lock(f"otp:{phone}")

        lock_ends = _locked_until(phone, now)
        if lock_ends:
            error = NumberLocked(retry_after=(lock_ends - now).total_seconds())
        else:
            challenge = (
                OTPChallenge.objects.select_for_update()
                .filter(phone=phone, purpose=purpose, consumed_at__isnull=True)
                .order_by("-created_at", "-id")
                .first()
            )
            if challenge is None or challenge.attempts >= MAX_WRONG_CODES:
                error = NoActiveCode()
            elif now >= challenge.expires_at:
                error = CodeExpired()
            elif _code_matches(challenge, code):
                challenge.consumed_at = now
                challenge.save(update_fields=["consumed_at"])
                return challenge
            else:
                error = _record_wrong_code(challenge, phone, now)
    # Raised outside the atomic block so the attempt count above is committed.
    raise error


def _record_wrong_code(challenge: OTPChallenge, phone: str, now) -> OTPError | NumberLocked:
    challenge.attempts += 1
    earlier = (
        OTPChallenge.objects.filter(
            phone=phone, consumed_at__isnull=True, created_at__gt=now - LOCK_DURATION
        )
        .exclude(pk=challenge.pk)
        .aggregate(total=Sum("attempts"))["total"]
        or 0
    )
    wrong_codes = earlier + challenge.attempts
    if wrong_codes >= MAX_WRONG_CODES:
        challenge.locked_until = now + LOCK_DURATION
        challenge.save(update_fields=["attempts", "locked_until"])
        logger.warning("otp.locked phone=%s", mask_phone(phone))
        return NumberLocked(retry_after=LOCK_DURATION.total_seconds())
    challenge.save(update_fields=["attempts"])
    logger.info("otp.wrong_code phone=%s attempts=%s", mask_phone(phone), wrong_codes)
    return WrongCode(remaining=MAX_WRONG_CODES - wrong_codes)


# ---------------------------------------------------------------- sign-in


def sign_in_with_code(*, phone: str, code: str, ip: str | None) -> tuple[User, bool]:
    """Verify a login code and return ``(user, created)``. The view then calls login().

    A new number gets a new player account with no name yet (asked on the next screen).
    Linking the venues' earlier phone bookings to the new account is added with
    VenueCustomer in S04 (US-P01).
    """
    verify_code(phone=phone, code=code, purpose=OTPChallenge.Purpose.LOGIN, ip=ip)
    created = False
    try:
        user = User.objects.get(phone=phone)
    except User.DoesNotExist:
        try:
            with transaction.atomic():
                user = User.objects.create_user(phone=phone)
                created = True
        except IntegrityError:  # created by a parallel request a moment ago
            user = User.objects.get(phone=phone)
    if not user.is_active:
        logger.warning("login.refused_inactive user_id=%s", user.pk)
        raise AccountDisabled()
    logger.info("login.success user_id=%s new=%s", user.pk, created)
    return user, created


# ---------------------------------------------------------------- profile and consent


def clean_name(value: str) -> str:
    """Trim and collapse spaces; refuse empty, too long or control characters."""
    name = " ".join((value or "").split())
    if not name:
        raise RuleViolation(_("Enter your name."))
    if len(name) > NAME_MAX_LENGTH:
        raise RuleViolation(_("Use at most 80 characters."))
    if _CONTROL_CHARS.search(name):
        raise RuleViolation(_("Use letters, numbers and spaces only."))
    return name


def has_current_consent(user: User) -> bool:
    accepted = set(ConsentRecord.objects.filter(user=user).values_list("document", "version"))
    return all((doc, version) in accepted for doc, version in CURRENT_DOCUMENTS.items())


def needs_profile(user: User) -> bool:
    """First sign-in (or new terms): name and consent are still missing (US-P01, NFR-07)."""
    return not user.name or not has_current_consent(user)


def complete_profile(user: User, *, name: str, accepted: bool) -> User:
    """Save the name and record acceptance of the current privacy notice and terms."""
    if not accepted:
        raise RuleViolation(_("Please accept the privacy notice and terms to continue."))
    name = clean_name(name)
    now = timezone.now()
    with transaction.atomic():
        user.name = name
        user.save(update_fields=["name"])
        for document, version in CURRENT_DOCUMENTS.items():
            ConsentRecord.objects.get_or_create(
                user=user, document=document, version=version, defaults={"accepted_at": now}
            )
    return user


def update_name(user: User, name: str) -> User:
    user.name = clean_name(name)
    user.save(update_fields=["name"])
    return user


# ---------------------------------------------------------------- roles


def platform_roles(user) -> frozenset[str]:
    """Roles that come from the account itself (data-model 3.1).

    Every active account is a player; platform admins have ``is_staff``. Venue owner and
    staff roles are per venue and come from VenueMembership (venues app, S04), never from here.
    """
    if not getattr(user, "is_authenticated", False) or not user.is_active or user.is_deleted:
        return frozenset()
    roles = {Role.PLAYER}
    if user.is_staff:
        roles.add(Role.ADMIN)
    return frozenset(roles)


def set_platform_admin(user: User, *, is_admin: bool, actor: User) -> User:
    """Grant or remove platform admin. Only superusers may do this."""
    if not (actor.is_active and actor.is_superuser):
        raise NotAllowed(_("Only a superuser can change platform admins."))
    if user.is_deleted:
        raise RuleViolation(_("This account has been deleted."))
    user.is_staff = is_admin
    user.save(update_fields=["is_staff"])
    logger.info(
        "account.platform_admin_changed user_id=%s is_admin=%s actor_id=%s",
        user.pk,
        is_admin,
        actor.pk,
    )
    return user


# ---------------------------------------------------------------- account deletion


def request_deletion_code(user: User, *, ip: str | None) -> OTPChallenge:
    """Send a code to the user's own phone to confirm deletion (BR-25)."""
    if user.is_deleted or not user.phone:
        raise NotAllowed(_("This account has been deleted."))
    return request_code(phone=user.phone, purpose=OTPChallenge.Purpose.DELETE_ACCOUNT, ip=ip)


def delete_account(user: User, *, code: str, ip: str | None) -> None:
    """Confirm with the code, then anonymise the account immediately (BR-25, data-model 9).

    Removes name and phone, signs the user out everywhere (inactive + unusable password),
    deletes their OTP rows and removes their number from the SMS log. Consent records stay as
    proof of consent. The user row itself is kept so history stays valid.

    S26 adds the steps that need other apps: refuse while the user owns a venue or captains
    a team, cancel future bookings and notify venues, anonymise VenueCustomer rows and
    booking names.
    """
    if user.is_deleted or not user.phone:
        raise NotAllowed(_("This account has been deleted."))
    verify_code(phone=user.phone, code=code, purpose=OTPChallenge.Purpose.DELETE_ACCOUNT, ip=ip)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        phone = user.phone
        user.phone = None
        user.name = DELETED_USER_NAME
        user.is_active = False
        user.is_staff = False
        user.is_superuser = False
        user.deleted_at = timezone.now()
        user.set_unusable_password()  # also ends every other session (session auth hash)
        user.save()
        user.groups.clear()
        user.user_permissions.clear()
        OTPChallenge.objects.filter(phone=phone).delete()
        notifications.forget_phone(phone)
    logger.info("account.deleted user_id=%s", user.pk)
