"""Cloudflare Turnstile on the sign-in form (D5)."""

import io
import json
import urllib.error

import pytest
from django.urls import reverse

from core import turnstile
from notifications.models import SmsMessage

pytestmark = pytest.mark.django_db

URL = reverse("accounts:phone")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def keys(settings):
    settings.TURNSTILE_SITE_KEY = "1x00000000000000000000AA"
    settings.TURNSTILE_SECRET_KEY = "1x0000000000000000000000000000000AA"


@pytest.fixture
def cloudflare(monkeypatch):
    """Fake siteverify endpoint; records what was sent."""
    calls = []

    def answer(success=True, error=None):
        def urlopen(request, timeout):
            calls.append((request.full_url, request.data.decode(), timeout))
            if error:
                raise error
            return FakeResponse(json.dumps({"success": success, "error-codes": []}).encode())

        monkeypatch.setattr(turnstile.urllib.request, "urlopen", urlopen)
        return calls

    return answer


def test_off_without_keys(client):
    page = client.get(URL).content.decode()
    assert "challenges.cloudflare.com" not in page
    response = client.post(URL, {"phone": "0771234567"})
    assert response.status_code == 302
    assert SmsMessage.objects.filter(purpose="otp").count() == 1


def test_widget_shown_and_csp_allows_it(client, keys):
    response = client.get(URL)
    html = response.content.decode()
    assert 'class="cf-turnstile" data-sitekey="1x00000000000000000000AA"' in html
    assert "https://challenges.cloudflare.com/turnstile/v0/api.js" in html
    csp = response["Content-Security-Policy"]
    assert "https://challenges.cloudflare.com" in csp
    assert "frame-src https://challenges.cloudflare.com" in csp


def test_passing_the_check_sends_the_code(client, keys, cloudflare):
    calls = cloudflare(success=True)
    response = client.post(
        URL, {"phone": "0771234567", turnstile.FIELD: "token-123"}, REMOTE_ADDR="198.51.100.7"
    )
    assert response.status_code == 302
    assert SmsMessage.objects.filter(purpose="otp").count() == 1
    url, data, timeout = calls[0]
    assert url == turnstile.VERIFY_URL
    assert "response=token-123" in data
    assert "remoteip=198.51.100.7" in data
    assert timeout == turnstile.TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "setup",
    ["missing token", "failed", "unreachable"],
)
def test_no_code_without_a_passed_check(client, keys, cloudflare, setup):
    data = {"phone": "0771234567", turnstile.FIELD: "token-123"}
    if setup == "missing token":
        cloudflare(success=True)
        data.pop(turnstile.FIELD)
    elif setup == "failed":
        cloudflare(success=False)
    else:
        cloudflare(error=urllib.error.URLError("down"))  # fails closed

    response = client.post(URL, data)

    assert response.status_code == 400
    assert "confirm you&#x27;re not a robot" in response.content.decode()
    assert not SmsMessage.objects.filter(purpose="otp").exists()
