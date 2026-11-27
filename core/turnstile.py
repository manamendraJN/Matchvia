"""Cloudflare Turnstile bot check on the sign-in form (D5, architecture 5 A07).

Each code SMS costs money, and SMS pumping is the most likely abuse, so the form proves a person
sent it before a code is requested. Without keys (laptop, tests) the check is off; production
refuses to start without them (config/settings/prod.py).
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_SECONDS = 5
FIELD = "cf-turnstile-response"


def enabled() -> bool:
    return bool(settings.TURNSTILE_SECRET_KEY)


def verify(token: str, ip: str | None) -> bool:
    """True if Cloudflare confirms the token. Fails closed: no answer means no code is sent."""
    if not enabled():
        return True
    if not token:
        return False
    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token[:2048]}
    if ip:
        data["remoteip"] = ip
    request = urllib.request.Request(
        VERIFY_URL, data=urllib.parse.urlencode(data).encode(), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310  # nosec B310
            result = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError):
        logger.warning("turnstile.unreachable")
        return False
    if not result.get("success"):
        logger.info("turnstile.failed codes=%s", ",".join(result.get("error-codes", [])))
        return False
    return True
