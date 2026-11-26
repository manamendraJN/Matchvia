import re
from datetime import UTC, datetime

import pytest
import time_machine

from notifications.backends import locmem
from notifications.backends.locmem import LocmemBackend
from notifications.worker import send_due_messages

from .factories import UserFactory

PHONE = "+94771234567"
IP = "198.51.100.7"
# Saturday 5 Dec 2026, 10:00 in Colombo.
T0 = datetime(2026, 12, 5, 4, 30, tzinfo=UTC)


@pytest.fixture
def clock():
    """Frozen time that tests move forward with ``clock.shift(timedelta(...))``."""
    with time_machine.travel(T0, tick=False) as traveller:
        yield traveller


def deliver_sms() -> list:
    """Run the worker once with the fake gateway; return everything sent so far."""
    send_due_messages(backend=LocmemBackend())
    return locmem.outbox


def last_code(phone: str = PHONE) -> str:
    """The code from the newest SMS to ``phone``, as the player would read it."""
    messages = [sms for sms in deliver_sms() if sms.to_phone == phone]
    assert messages, f"no SMS sent to {phone}"
    match = re.search(r"\b(\d{6})\b", messages[-1].text)
    assert match, messages[-1].text
    return match.group(1)


def wrong(code: str) -> str:
    """A different 6-digit code."""
    return f"{(int(code) + 1) % 1_000_000:06d}"


@pytest.fixture
def user(db):
    return UserFactory(phone=PHONE, name="Kasun Perera")
