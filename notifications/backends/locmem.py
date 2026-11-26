from dataclasses import dataclass

from .base import BaseSmsBackend, SmsSendError

# Messages "sent" during tests. Cleared by the autouse fixture in conftest.py.
outbox: list["SentSms"] = []
# Set to an exception instance to make the next sends fail (worker retry tests).
fail_with: SmsSendError | None = None


@dataclass(frozen=True)
class SentSms:
    to_phone: str
    text: str
    message_id: str


class LocmemBackend(BaseSmsBackend):
    """Tests only: records messages in ``outbox`` instead of sending them."""

    def send(self, to_phone: str, text: str) -> str:
        if fail_with is not None:
            raise fail_with
        message_id = f"locmem-{len(outbox) + 1}"
        outbox.append(SentSms(to_phone=to_phone, text=text, message_id=message_id))
        return message_id
