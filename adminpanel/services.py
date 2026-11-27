"""Platform admin logic: admin sign-in, access log, admin home, PDPA deletion (C9).

Admin sign-in (architecture 5, D9, D16): the Django admin with mobile number + password, for
active platform admins (``is_staff``). Django does not throttle logins, so (CLAUDE.md rule 4):
- at most 20 password attempts per IP per hour;
- 5 wrong passwords for one number lock that number's admin sign-in for 15 minutes;
- failures are logged with the number masked.
Admin access lasts 8 hours after signing in.

Services own the transaction; cross-app calls go through the other app's services.py.
"""

import hashlib
import logging
from datetime import timedelta

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts import services as accounts
from bookings import selectors as booking_selectors
from core import ratelimit
from core.exceptions import DomainError, RateLimited, RuleViolation
from core.phone import InvalidPhone, mask_phone, normalise_phone
from core.timeutils import operating_date
from venues import services as venues

from .models import AccessAction, AdminAccessLog

logger = logging.getLogger(__name__)

ATTEMPTS_PER_IP_PER_HOUR = 20
WRONG_PASSWORDS_BEFORE_LOCK = 5
LOCK_SECONDS = 15 * 60
ADMIN_SESSION = timedelta(hours=8)


class BadCredentials(DomainError):
    def __init__(self):
        super().__init__(_("Wrong mobile number or password."))


class AdminLocked(RateLimited):
    """Too many wrong passwords for this number."""


# ---------------------------------------------------------------- sign-in


def _failure_key(phone: str) -> str:
    # Hashed so the cache table holds no phone numbers.
    return "admin-login-fail:" + hashlib.sha256(phone.encode()).hexdigest()[:32]


def _record_failure(phone: str) -> None:
    key = _failure_key(phone)
    cache.add(key, 0, timeout=LOCK_SECONDS)
    try:
        failures = cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=LOCK_SECONDS)
        failures = 1
    if failures >= WRONG_PASSWORDS_BEFORE_LOCK:
        cache.set(key, failures, timeout=LOCK_SECONDS)  # the 15 minutes start now
        logger.warning("admin_login.locked phone=%s", mask_phone(phone))
    else:
        logger.warning("admin_login.failed phone=%s failures=%s", mask_phone(phone), failures)


def check_password(*, phone: str, password: str, ip: str | None):
    """Return the admin user for a correct number + password; the view then calls login().

    ``phone`` must be normalised. Wrong number, wrong password, a non-admin account or a
    disabled account all give the same BadCredentials error. Raises AdminLocked or
    RateLimited when over a limit.
    """
    ratelimit.hit("admin-login-ip", ip, limit=ATTEMPTS_PER_IP_PER_HOUR, window=3600)
    if (cache.get(_failure_key(phone)) or 0) >= WRONG_PASSWORDS_BEFORE_LOCK:
        raise AdminLocked(retry_after=LOCK_SECONDS)
    user = authenticate(None, phone=phone, password=password)
    if user is None or not (user.is_active and user.is_staff):
        _record_failure(phone)
        raise BadCredentials()
    cache.delete(_failure_key(phone))
    logger.info("admin_login.success user_id=%s", user.pk)
    return user


# ---------------------------------------------------------------- access log (A5)


def masked_term(term: str) -> str:
    """A search term fit for the log: phone numbers masked, at most 100 characters."""
    term = " ".join((term or "").split())[:100]
    try:
        return mask_phone(normalise_phone(term))
    except InvalidPhone:
        return term


def log_access(admin, action: str, object_type: str, object_id=None, detail: str = ""):
    """Record that an admin viewed, searched or changed personal data (US-A04)."""
    if object_id is not None:
        try:
            object_id = int(object_id)
        except (TypeError, ValueError):
            object_id = None
    return AdminAccessLog.objects.create(
        admin=admin,
        action=action,
        object_type=object_type,
        object_id=object_id,
        detail=detail[:255],
    )


# ---------------------------------------------------------------- admin home (A1)


def home(*, now=None) -> dict:
    now = now or timezone.now()
    counts = venues.status_counts()
    return {
        "pending_count": counts["pending"],
        "live_count": counts["approved"],
        "suspended_count": counts["suspended"],
        "bookings_today": booking_selectors.bookings_on_day(operating_date(now)),
        "waiting": venues.waiting_for_review(),
    }


# ---------------------------------------------------------------- PDPA deletion


def delete_account_on_request(*, admin, user, reason: str) -> int:
    """Carry out a deletion request received by phone or email, and log who did it.

    Same steps as self-service deletion (accounts.services). Returns bookings cancelled.
    """
    reason = " ".join((reason or "").split())
    if not reason:
        raise RuleViolation(_("Say how the request came in (for example: email, 27 Nov)."))
    with transaction.atomic():
        cancelled = accounts.delete_account_on_request(user, admin=admin)
        log_access(admin, AccessAction.DELETE_ACCOUNT, "user", user.pk, detail=reason)
    return cancelled
