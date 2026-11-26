"""Fixtures shared by every app's tests."""

import pytest
from django.core.cache import cache

from notifications.backends import locmem


@pytest.fixture(autouse=True)
def _isolate_cache_and_sms():
    """Every test starts with empty rate-limit counters and an empty fake SMS outbox."""
    cache.clear()
    locmem.outbox.clear()
    locmem.fail_with = None
    yield
    locmem.outbox.clear()
    locmem.fail_with = None
