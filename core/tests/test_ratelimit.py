from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from core import ratelimit
from core.exceptions import RateLimited

T0 = datetime(2026, 12, 5, 10, 0, 30, tzinfo=UTC)


def make_request(remote="198.51.100.7", cf=None):
    meta = {"REMOTE_ADDR": remote}
    if cf is not None:
        meta["HTTP_CF_CONNECTING_IP"] = cf
    return RequestFactory().get("/", **meta)


# ---------------------------------------------------------------- client_ip


def test_client_ip_uses_remote_addr_by_default():
    assert ratelimit.client_ip(make_request(cf="203.0.113.9")) == "198.51.100.7"


@override_settings(TRUST_CF_CONNECTING_IP=True)
def test_client_ip_trusts_cloudflare_header_only_when_configured():
    assert ratelimit.client_ip(make_request(cf="203.0.113.9")) == "203.0.113.9"


@override_settings(TRUST_CF_CONNECTING_IP=True)
def test_client_ip_falls_back_when_cloudflare_header_is_garbage():
    assert ratelimit.client_ip(make_request(cf="not-an-ip")) == "198.51.100.7"


def test_client_ip_none_when_nothing_usable():
    assert ratelimit.client_ip(make_request(remote="")) is None


def test_client_ip_normalises_ipv6():
    assert ratelimit.client_ip(make_request(remote="2001:DB8:0:0::1")) == "2001:db8::1"


# ---------------------------------------------------------------- hit


def test_allows_up_to_limit_then_raises_with_wait_until_window_end():
    with time_machine.travel(T0, tick=False):
        for _ in range(3):
            ratelimit.hit("test", "1.2.3.4", limit=3, window=60)
        with pytest.raises(RateLimited) as exc:
            ratelimit.hit("test", "1.2.3.4", limit=3, window=60)
    # 30 seconds into the minute: 30 seconds left.
    assert exc.value.retry_after == 30


def test_new_window_resets_the_count():
    with time_machine.travel(T0, tick=False) as clock:
        for _ in range(2):
            ratelimit.hit("test", "1.2.3.4", limit=2, window=60)
        clock.shift(timedelta(seconds=30))
        ratelimit.hit("test", "1.2.3.4", limit=2, window=60)  # new minute: allowed


def test_idents_and_scopes_are_independent():
    ratelimit.hit("a", "1.1.1.1", limit=1, window=60)
    ratelimit.hit("a", "2.2.2.2", limit=1, window=60)
    ratelimit.hit("b", "1.1.1.1", limit=1, window=60)
    with pytest.raises(RateLimited):
        ratelimit.hit("a", "1.1.1.1", limit=1, window=60)


def test_missing_ident_still_limited():
    ratelimit.hit("test", None, limit=1, window=60)
    with pytest.raises(RateLimited):
        ratelimit.hit("test", None, limit=1, window=60)


def test_cache_keys_do_not_contain_raw_ip():
    ratelimit.hit("test", "203.0.113.77", limit=5, window=60)
    keys = list(cache._cache.keys())  # LocMemCache internals, test settings only
    assert keys
    assert not any("203.0.113.77" in key for key in keys)


def test_survives_key_expiring_between_add_and_incr(monkeypatch):
    def incr(*args, **kwargs):
        raise ValueError("Key not found")

    monkeypatch.setattr(cache, "incr", incr)
    ratelimit.hit("test", "1.2.3.4", limit=1, window=60)  # treated as the first hit


def test_rate_limited_rounds_wait_up():
    exc = RateLimited(retry_after=61.2)
    assert exc.retry_after == 62
    assert exc.retry_after_minutes == 2
    assert RateLimited(retry_after=0).retry_after == 1
