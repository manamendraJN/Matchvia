"""Cache-based rate limits for per-IP and per-user limits (CLAUDE.md rule 4, architecture 5.1).

Per-phone OTP limits are counted from the OTPChallenge table instead (data-model 3.1), so they
survive restarts. These counters use Django's cache (DatabaseCache in dev/staging/prod, D14),
shared by every web and worker process.

Fixed windows: a key counts hits during one window of ``window`` seconds. The counted value
(an IP address or a user id) is hashed so the cache table holds no raw IP addresses.
"""

import hashlib
import ipaddress
import logging
import time

from django.conf import settings
from django.core.cache import cache

from core.exceptions import RateLimited

logger = logging.getLogger(__name__)


def client_ip(request) -> str | None:
    """The client's IP address.

    ``CF-Connecting-IP`` is trusted only when TRUST_CF_CONNECTING_IP is on (staging and
    production), where the origin firewall accepts traffic from Cloudflare alone. Anywhere
    else the header could be forged to dodge limits, so REMOTE_ADDR is used.
    """
    candidates = []
    if settings.TRUST_CF_CONNECTING_IP:
        candidates.append(request.META.get("HTTP_CF_CONNECTING_IP", ""))
    candidates.append(request.META.get("REMOTE_ADDR", ""))
    for value in candidates:
        try:
            return str(ipaddress.ip_address(value.strip()))
        except ValueError:
            continue
    return None


def _key(scope: str, ident: str, window: int, now: float) -> tuple[str, float]:
    digest = hashlib.sha256(f"{scope}:{ident}".encode()).hexdigest()[:32]
    bucket = int(now // window)
    window_ends = (bucket + 1) * window
    return f"rl:{scope}:{digest}:{bucket}", window_ends


def hit(scope: str, ident: str | None, *, limit: int, window: int) -> None:
    """Count one hit for ``ident`` in ``scope``; raise RateLimited once over ``limit``.

    A missing ident (no usable IP) shares one bucket, so limits still apply.
    """
    now = time.time()
    key, window_ends = _key(scope, ident or "unknown", window, now)
    # add() is a no-op if the key exists; the timeout outlives the window slightly.
    cache.add(key, 0, timeout=window + 60)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=window + 60)
        count = 1
    if count > limit:
        logger.warning("rate_limit.hit scope=%s", scope)
        raise RateLimited(retry_after=window_ends - now)
