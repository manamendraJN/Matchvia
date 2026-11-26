"""Project foundation: health check, base template security, PWA manifest, btree_gist (S01, S09)."""

import json
import re

import pytest
from django.conf import settings
from django.db import DatabaseError, connection
from django.urls import reverse

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- /healthz


def test_healthz_reports_database_ok(client):
    response = client.get(reverse("healthz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert "no-cache" in response["Cache-Control"]


def test_healthz_reports_database_error_without_details(client, monkeypatch):
    def broken_cursor(*args, **kwargs):
        raise DatabaseError("connection refused to secret-host:5432")

    monkeypatch.setattr(connection, "cursor", broken_cursor)
    response = client.get(reverse("healthz"))

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "error"}
    assert b"secret-host" not in response.content


def test_healthz_rejects_post(client):
    assert client.post(reverse("healthz")).status_code == 405


# ---------------------------------------------------------------- base template


def _csp_nonce(response) -> str:
    header = response["Content-Security-Policy"]
    match = re.search(r"'nonce-([^']+)'", header)
    assert match, header
    return match.group(1)


def test_home_page_renders_with_tagline(client):
    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert b"Book your court." in response.content
    assert b"Bring your team." in response.content


def test_csp_header_has_nonce_and_no_unsafe_sources(client):
    response = client.get(reverse("home"))
    header = response["Content-Security-Policy"]

    assert "default-src 'self'" in header
    assert "'unsafe-inline'" not in header
    assert "'unsafe-eval'" not in header
    assert "frame-ancestors 'none'" in header


def test_every_script_and_stylesheet_carries_the_nonce(client):
    response = client.get(reverse("home"))
    nonce = _csp_nonce(response)
    html = response.content.decode()

    scripts = re.findall(r"<script\b[^>]*>", html)
    styles = re.findall(r"<link\b[^>]*rel=\"stylesheet\"[^>]*>", html)
    assert scripts
    assert styles
    for tag in scripts + styles:
        assert f'nonce="{nonce}"' in tag, tag


def test_no_inline_scripts_or_styles(client):
    html = client.get(reverse("home")).content.decode()

    # Every <script> loads a self-hosted file; no inline code, no CDN.
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert 'src="/static/' in tag, tag
    assert "<style" not in html
    assert " style=" not in html
    assert not re.search(r"\son[a-z]+=", html), "inline event handler found"


def test_htmx_is_vendored_with_eval_off(client):
    html = client.get(reverse("home")).content.decode()

    assert 'src="/static/vendor/htmx/htmx.min.js"' in html
    match = re.search(r"<meta name=\"htmx-config\" content='([^']+)'>", html)
    assert match
    config = json.loads(match.group(1))
    assert config["allowEval"] is False
    assert config["includeIndicatorStyles"] is False


def test_htmx_requests_carry_the_csrf_token(client):
    response = client.get(reverse("home"))
    html = response.content.decode()

    match = re.search(r"hx-headers='([^']+)'", html)
    assert match
    token = json.loads(match.group(1))["X-CSRFToken"]
    assert len(token) >= 32


def test_mobile_viewport_and_manifest_linked(client):
    html = client.get(reverse("home")).content.decode()

    assert 'name="viewport" content="width=device-width, initial-scale=1' in html
    assert 'rel="manifest" href="/static/manifest.webmanifest"' in html


def test_security_headers_on_every_response(client):
    response = client.get(reverse("home"))

    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin"


# ---------------------------------------------------------------- PWA manifest


def test_manifest_is_installable():
    path = settings.BASE_DIR / "static" / "manifest.webmanifest"
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(icon.get("purpose") == "maskable" for icon in manifest["icons"])
    for icon in manifest["icons"]:
        assert (path.parent / icon["src"]).is_file(), icon["src"]


# ---------------------------------------------------------------- database


def test_btree_gist_extension_is_installed():
    """The no-double-booking exclusion constraint needs btree_gist (CLAUDE.md rule 1)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        assert cursor.fetchone() == (1,)
