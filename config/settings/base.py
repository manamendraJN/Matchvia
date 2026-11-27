"""Settings shared by every environment. Reads no secrets; see dev/test/prod."""

from pathlib import Path

from django.utils.csp import CSP
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEBUG = False

# Set by each environment module.
SECRET_KEY: str
ALLOWED_HOSTS: list[str] = []

# ---------------------------------------------------------------- applications
DJANGO_APPS = [
    "adminpanel.admin_site_config.MatchviaAdminConfig",  # replaces django.contrib.admin
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django.contrib.humanize",
]

# payments and reports are created only in Phase 2 (CLAUDE.md).
LOCAL_APPS = [
    "core",
    "accounts",
    "venues",
    "pricing",
    "bookings",
    "teams",
    "notifications",
    "adminpanel",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.RateLimitedMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csp",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------- database
# Each environment sets DATABASES from DATABASE_URL. PostgreSQL only (btree_gist).
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------- users and sign-in
# Phone-number user model from the first migration (data-model 3.1).
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:phone"
LOGIN_REDIRECT_URL = "/"
# Players stay signed in for 30 days (D9); per-role lifetimes for venue users and admins follow.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30

# ---------------------------------------------------------------- cache and rate limits
# Database cache works across web and worker processes without Redis (D14).
# Create the table once per database: `manage.py createcachetable`.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}
# Read the client IP from CF-Connecting-IP only where the origin accepts Cloudflare traffic
# alone (staging and production); otherwise the header could be forged (architecture 5.1).
TRUST_CF_CONNECTING_IP = False

# ---------------------------------------------------------------- passwords
# Players and venue users sign in with phone OTP; passwords exist only for platform admins.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------- language and time
LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", _("English")),
    # ("si", _("Sinhala")),  # before public launch (NFR-05)
]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True

TIME_ZONE = "Asia/Colombo"
USE_TZ = True

# ---------------------------------------------------------------- static files
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Uploaded venue photos. Local disk for now; object storage (Cloudflare R2, D7) replaces this
# before staging (S21), so web servers stay stateless.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# ---------------------------------------------------------------- security (all environments)
# Content Security Policy: everything self-hosted, scripts and styles need a nonce,
# no 'unsafe-inline' or 'unsafe-eval' (CLAUDE.md rule 3, architecture 5 A03).
# img-src gains the photo storage domain (S21) and OpenStreetMap tiles (S13) later.
SECURE_CSP = {
    "default-src": [CSP.SELF],
    # Cloudflare Turnstile (D5) is the one outside script, on the sign-in page.
    "script-src": [CSP.SELF, CSP.NONCE, "https://challenges.cloudflare.com"],
    "frame-src": ["https://challenges.cloudflare.com"],
    "style-src": [CSP.SELF, CSP.NONCE],
    # OpenStreetMap tiles for the venue map pin (architecture 5 A03, 10).
    "img-src": [CSP.SELF, "https://tile.openstreetmap.org"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF],
    "manifest-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
# HTMX reads the CSRF token from the template (hx-headers on <body>), not from the cookie.
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"

# Public address used in SMS links (team invites). No trailing slash.
SITE_URL = "http://localhost:8000"

# ---------------------------------------------------------------- SMS and worker
# Text.lk (D4). Key and sender ID come from the environment only (CLAUDE.md rule 5).
SMS_API_URL = "https://app.text.lk/api/v3/sms/send"
SMS_API_KEY = ""
# Cloudflare Turnstile on the sign-in form (D5). Empty secret = check off (laptop and tests only).
TURNSTILE_SITE_KEY = ""
# Empty means the check is off; it is not a password.
TURNSTILE_SECRET_KEY = ""  # nosec B105
SMS_SENDER_ID = ""
# When not empty, SMS go only to these numbers (+94...). Staging sets it (architecture 6.4).
SMS_ALLOWED_NUMBERS: list[str] = []
# /healthz fails when the worker's heartbeat is older than this (staging and production).
HEALTHZ_CHECK_WORKER = False
WORKER_HEARTBEAT_MAX_AGE = 120  # seconds

# Admin URL prefix; production requires a private value from the environment.
ADMIN_URL_PATH = "admin/"
