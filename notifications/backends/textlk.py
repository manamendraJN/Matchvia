from .base import BaseSmsBackend, SmsSendError


class TextLkBackend(BaseSmsBackend):
    """Text.lk HTTP API adapter (decision D4). Implemented in C7/S08.

    Until then every send fails, so the worker keeps messages queued and retries them; it
    never pretends a message was delivered. Configuration will come from SMS_API_KEY and
    SMS_SENDER_ID environment variables.
    """

    def send(self, to_phone: str, text: str) -> str:
        raise SmsSendError("Text.lk backend is not implemented yet (C7/S08).")
