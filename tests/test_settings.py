"""Settings load per environment; production refuses to start insecurely (S01, S02)."""

import importlib
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config.settings import _env

ROOT = Path(__file__).resolve().parent.parent

# Dummy production environment. None of these values is a real secret.
PROD_ENV = {
    "SECRET_KEY": "prod-test-" + "k" * 50,
    "OTP_HMAC_KEY": "prod-test-otp-" + "h" * 40,
    "SMS_BACKEND": "notifications.backends.textlk.TextLkBackend",
    "DATABASE_URL": "postgres://matchvia:pw@db.example.com:5432/matchvia?sslmode=require",
    "ALLOWED_HOSTS": "matchvia.lk, www.matchvia.lk",
    "CSRF_TRUSTED_ORIGINS": "https://matchvia.lk,https://www.matchvia.lk",
    "ADMIN_URL_PATH": "/ops-test123/",
}
REQUIRED_IN_PROD = [
    "SECRET_KEY",
    "OTP_HMAC_KEY",
    "SMS_BACKEND",
    "DATABASE_URL",
    "ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS",
    "ADMIN_URL_PATH",
]


def load_settings(module: str, monkeypatch, **overrides):
    """Import a settings module fresh with the given environment."""
    for name, value in {**PROD_ENV, **overrides}.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    for name in [m for m in sys.modules if m.startswith(f"config.settings.{module}")]:
        del sys.modules[name]
    if module == "staging":
        sys.modules.pop("config.settings.prod", None)
    return importlib.import_module(f"config.settings.{module}")


# ---------------------------------------------------------------- shared settings


def test_time_zone_and_language():
    assert settings.TIME_ZONE == "Asia/Colombo"
    assert settings.USE_TZ is True
    assert settings.USE_I18N is True
    assert settings.LANGUAGE_CODE == "en"


def test_postgresql_only():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_all_apps_installed():
    for app in [
        "core",
        "accounts",
        "venues",
        "pricing",
        "bookings",
        "teams",
        "notifications",
        "adminpanel",
    ]:
        assert app in settings.INSTALLED_APPS
    # Created only in Phase 2.
    assert "payments" not in settings.INSTALLED_APPS
    assert "reports" not in settings.INSTALLED_APPS


def test_csp_has_no_unsafe_sources():
    from django.utils.csp import CSP

    for directive, sources in settings.SECURE_CSP.items():
        assert CSP.UNSAFE_INLINE not in sources, directive
        assert CSP.UNSAFE_EVAL not in sources, directive
    assert CSP.NONCE in settings.SECURE_CSP["script-src"]
    assert settings.SECURE_CSP["frame-ancestors"] == [CSP.NONE]
    assert settings.SECURE_CSP["object-src"] == [CSP.NONE]


# ---------------------------------------------------------------- dev and test


def test_dev_settings_load(monkeypatch):
    dev = load_settings("dev", monkeypatch)
    assert dev.DEBUG is True
    assert dev.SMS_BACKEND.endswith("ConsoleBackend")
    assert dev.ADMIN_URL_PATH.endswith("/")


def test_dev_requires_secret_key(monkeypatch, tmp_path):
    # Point BASE_DIR's .env lookup away from any real local .env file.
    monkeypatch.setattr(_env, "load_dotenv", lambda path: None)
    with pytest.raises(ImproperlyConfigured, match="SECRET_KEY"):
        load_settings("dev", monkeypatch, SECRET_KEY="")


def test_test_settings_use_fake_sms_and_local_cache():
    assert settings.SMS_BACKEND.endswith("LocmemBackend")
    assert settings.CACHES["default"]["BACKEND"].endswith("LocMemCache")
    assert settings.DEBUG is False


# ---------------------------------------------------------------- production


@pytest.mark.parametrize("name", REQUIRED_IN_PROD)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_prod_refuses_to_start_without_required_variable(monkeypatch, name, value):
    with pytest.raises(ImproperlyConfigured, match=name):
        load_settings("prod", monkeypatch, **{name: value})


def test_prod_rejects_default_admin_path(monkeypatch):
    with pytest.raises(ImproperlyConfigured, match="ADMIN_URL_PATH"):
        load_settings("prod", monkeypatch, ADMIN_URL_PATH="admin/")


def test_prod_rejects_non_postgresql_database(monkeypatch):
    with pytest.raises(ImproperlyConfigured, match="PostgreSQL"):
        load_settings("prod", monkeypatch, DATABASE_URL="sqlite:///db.sqlite3")


def test_prod_security_settings(monkeypatch):
    prod = load_settings("prod", monkeypatch)

    assert prod.DEBUG is False
    assert prod.ALLOWED_HOSTS == ["matchvia.lk", "www.matchvia.lk"]
    assert prod.CSRF_TRUSTED_ORIGINS == ["https://matchvia.lk", "https://www.matchvia.lk"]
    assert prod.ADMIN_URL_PATH == "ops-test123/"

    # HTTPS
    assert prod.SECURE_SSL_REDIRECT is True
    assert prod.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert prod.SECURE_HSTS_SECONDS >= 31_536_000
    assert prod.SECURE_HSTS_INCLUDE_SUBDOMAINS is True

    # Cookies
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SESSION_COOKIE_HTTPONLY is True
    assert prod.CSRF_COOKIE_HTTPONLY is True
    assert prod.SESSION_COOKIE_SAMESITE == "Lax"

    # Headers
    assert prod.X_FRAME_OPTIONS == "DENY"
    assert prod.SECURE_REFERRER_POLICY == "same-origin"
    assert prod.SECURE_CONTENT_TYPE_NOSNIFF is True
    assert "django.middleware.csp.ContentSecurityPolicyMiddleware" in prod.MIDDLEWARE
    assert "django.middleware.csrf.CsrfViewMiddleware" in prod.MIDDLEWARE

    # Database over TLS, persistent connections
    assert prod.DATABASES["default"]["OPTIONS"]["sslmode"] == "require"
    assert prod.DATABASES["default"]["CONN_MAX_AGE"] > 0

    # Rate limits may trust Cloudflare's client IP header only in production
    assert prod.TRUST_CF_CONNECTING_IP is True
    assert prod.CACHES["default"]["BACKEND"].endswith("DatabaseCache")


def test_prod_secret_key_fallbacks(monkeypatch):
    prod = load_settings("prod", monkeypatch, SECRET_KEY_FALLBACKS="old-one, old-two")
    assert prod.SECRET_KEY_FALLBACKS == ["old-one", "old-two"]


def test_staging_uses_prod_settings(monkeypatch):
    staging = load_settings("staging", monkeypatch)
    assert staging.DEBUG is False
    assert staging.SECURE_SSL_REDIRECT is True
    assert staging.SESSION_COOKIE_SECURE is True


def test_prod_passes_deploy_checks():
    """`manage.py check --deploy` must pass with production settings (architecture 8.2)."""
    env = {**os.environ, **PROD_ENV, "DJANGO_SETTINGS_MODULE": "config.settings.prod"}
    result = subprocess.run(  # nosec B603
        [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
