"""Text.lk adapter with a fake HTTP layer: nothing is really sent (C7, D4)."""

import io
import json
import urllib.error

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from notifications.backends import textlk
from notifications.backends.base import SmsSendError

CONFIGURED = {
    "SMS_API_KEY": "test-token-not-real",
    "SMS_SENDER_ID": "Matchvia",
    "SMS_API_URL": "https://app.text.lk/api/v3/sms/send",
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self, limit=-1):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    """Capture requests and answer like Text.lk does on success."""
    calls = []

    def fake_urlopen(request, timeout):
        calls.append({"request": request, "timeout": timeout})
        return FakeResponse({"status": "success", "data": {"uid": "abc123", "status": "Delivered"}})

    monkeypatch.setattr(textlk.urllib.request, "urlopen", fake_urlopen)
    return calls


@override_settings(**CONFIGURED)
def test_sends_json_with_bearer_token(sent):
    message_id = textlk.TextLkBackend().send("+94771234567", "Your Matchvia code is 482913.")

    assert message_id == "abc123"
    request = sent[0]["request"]
    assert request.full_url == "https://app.text.lk/api/v3/sms/send"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer test-token-not-real"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {
        "recipient": "94771234567",
        "sender_id": "Matchvia",
        "type": "plain",
        "message": "Your Matchvia code is 482913.",
    }
    assert sent[0]["timeout"] == 10


@pytest.mark.parametrize(
    "settings_change",
    [{"SMS_API_KEY": ""}, {"SMS_SENDER_ID": ""}, {"SMS_API_URL": "http://app.text.lk/api"}],
)
def test_refuses_to_start_misconfigured(settings_change):
    with (
        override_settings(**{**CONFIGURED, **settings_change}),
        pytest.raises(ImproperlyConfigured),
    ):
        textlk.TextLkBackend()


def _failing(monkeypatch, exc):
    def fake_urlopen(request, timeout):
        raise exc

    monkeypatch.setattr(textlk.urllib.request, "urlopen", fake_urlopen)


@override_settings(**CONFIGURED)
def test_error_reply_becomes_send_error_without_our_text_or_key(monkeypatch):
    monkeypatch.setattr(
        textlk.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(
            {"status": "error", "message": "Insufficient balance"}
        ),
    )
    with pytest.raises(SmsSendError) as exc:
        textlk.TextLkBackend().send("+94771234567", "Secret code 482913")
    assert "Insufficient balance" in str(exc.value)
    assert "482913" not in str(exc.value)
    assert "test-token-not-real" not in str(exc.value)


@override_settings(**CONFIGURED)
def test_http_error(monkeypatch):
    body = io.BytesIO(json.dumps({"status": "error", "message": "Unauthenticated."}).encode())
    _failing(monkeypatch, urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, body))
    with pytest.raises(SmsSendError, match=r"HTTP 401: Unauthenticated."):
        textlk.TextLkBackend().send("+94771234567", "hi")


@override_settings(**CONFIGURED)
@pytest.mark.parametrize("exc", [urllib.error.URLError("dns failure"), TimeoutError(), OSError()])
def test_network_failures(monkeypatch, exc):
    _failing(monkeypatch, exc)
    with pytest.raises(SmsSendError, match="unreachable"):
        textlk.TextLkBackend().send("+94771234567", "hi")


@override_settings(**CONFIGURED)
@pytest.mark.parametrize("payload", [b"<html>502</html>", b"[]", b'{"status": "queued"}'])
def test_unexpected_replies(monkeypatch, payload):
    monkeypatch.setattr(
        textlk.urllib.request, "urlopen", lambda request, timeout: FakeResponse(payload)
    )
    with pytest.raises(SmsSendError):
        textlk.TextLkBackend().send("+94771234567", "hi")


@override_settings(**CONFIGURED)
def test_failed_send_is_retried_by_the_worker(monkeypatch, db):
    from notifications import services
    from notifications.models import SmsMessage
    from notifications.worker import send_due_messages

    _failing(monkeypatch, TimeoutError())
    message = services.queue_sms(to_phone="+94771234567", purpose="venue_notice", body="Hello")
    send_due_messages(backend=textlk.TextLkBackend())
    message.refresh_from_db()
    assert message.status == SmsMessage.Status.QUEUED
    assert message.attempts == 1
    assert "unreachable" in message.last_error
