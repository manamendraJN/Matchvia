"""Text.lk HTTP API adapter (decision D4). Docs: https://text.lk/docs/send-sms/

POST https://app.text.lk/api/v3/sms/send with ``Authorization: Bearer <API token>`` and JSON
``{"recipient": "94771234567", "sender_id": "...", "type": "plain", "message": "..."}``.
Success: ``{"status": "success", "data": {"uid": "..."}}``; failure: ``{"status": "error",
"message": "..."}``.

Only the worker calls this, never a web request (CLAUDE.md). Errors never include the message
text or the API key, because they end up in the outbox and the logs.
"""

import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import BaseSmsBackend, SmsSendError

TIMEOUT_SECONDS = 10  # architecture 4.2: a send never hangs a worker claim
MAX_RESPONSE_BYTES = 65536


class TextLkBackend(BaseSmsBackend):
    def __init__(self):
        self.url = settings.SMS_API_URL
        self.api_key = settings.SMS_API_KEY
        self.sender_id = settings.SMS_SENDER_ID
        if not self.api_key or not self.sender_id:
            raise ImproperlyConfigured("Set SMS_API_KEY and SMS_SENDER_ID for the Text.lk backend.")
        if not self.url.startswith("https://"):
            raise ImproperlyConfigured("SMS_API_URL must use https.")

    def send(self, to_phone: str, text: str) -> str:
        payload = json.dumps(
            {
                "recipient": to_phone.removeprefix("+"),  # Text.lk wants 94771234567
                "sender_id": self.sender_id,
                "type": "plain",
                "message": text,
            }
        ).encode()
        request = urllib.request.Request(  # noqa: S310  fixed https URL from settings
            self.url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310  # nosec B310
                raw = response.read(MAX_RESPONSE_BYTES)
        except urllib.error.HTTPError as exc:
            raise SmsSendError(
                f"Text.lk HTTP {exc.code}: {_error_message(exc.read(4096))}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SmsSendError(f"Text.lk unreachable ({type(exc).__name__})") from None

        try:
            data = json.loads(raw)
        except ValueError:
            raise SmsSendError("Text.lk sent a response that isn't JSON") from None
        if not isinstance(data, dict) or data.get("status") != "success":
            raise SmsSendError(f"Text.lk refused the message: {_error_message(raw)}")
        details = data.get("data") if isinstance(data.get("data"), dict) else {}
        return str(details.get("uid", ""))[:100]


def _error_message(raw: bytes) -> str:
    """Text.lk's own error text, short; never our request (which holds the message)."""
    try:
        message = json.loads(raw).get("message", "")
    except (ValueError, AttributeError):
        message = ""
    return str(message)[:200] or "no details"
