"""System pages (P20) and the offline service worker (screens 1.3)."""

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory

from core.exceptions import RateLimited
from core.middleware import RateLimitedMiddleware

pytestmark = pytest.mark.django_db


def test_not_found_page(client):
    response = client.get("/no-such-page/")
    assert response.status_code == 404
    html = response.content.decode()
    assert "find that page." in html
    assert 'href="/"' in html


def test_server_error_page_renders_without_a_request():
    html = render_to_string("500.html")
    assert "Something went wrong on our side. Please try again." in html
    assert "<script" not in html


def test_uncaught_rate_limit_shows_the_429_page():
    request = RequestFactory().get("/")
    from django.contrib.auth.models import AnonymousUser

    request.user = AnonymousUser()
    middleware = RateLimitedMiddleware(lambda r: None)
    response = middleware.process_exception(request, RateLimited(retry_after=90))
    assert response.status_code == 429
    assert response["Retry-After"] == "90"
    assert "Please wait a moment and try again." in response.content.decode()
    assert middleware.process_exception(request, ValueError()) is None
    assert middleware(request) is None  # passes requests straight through


def test_service_worker_is_served_from_the_root(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/javascript")
    assert response["Cache-Control"] == "no-cache"
    body = response.content.decode()
    assert 'const OFFLINE_URL = "/offline/"' in body
    assert "css/app.css" in body
    assert 'event.request.mode !== "navigate"' in body


def test_offline_page(client):
    response = client.get("/offline/")
    assert response.status_code == 200
    assert "Bookings need a connection." in response.content.decode()
