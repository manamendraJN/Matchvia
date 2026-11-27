"""Background process heartbeats, kept in the shared cache (architecture 4.1).

The worker beats every loop; /healthz reports a stale heartbeat so the uptime monitor alerts
when the worker has stopped (architecture 4.2).
"""

import time

from django.core.cache import cache

KEY = "heartbeat:{name}"


def beat(name: str) -> None:
    cache.set(KEY.format(name=name), time.time(), timeout=24 * 3600)


def age_seconds(name: str) -> float | None:
    """Seconds since the last beat, or None if there has never been one."""
    last = cache.get(KEY.format(name=name))
    return None if last is None else max(0.0, time.time() - last)
