"""Production settings. Every secret is required from the environment; no .env file is read.

The app refuses to start (ImproperlyConfigured) if a required variable is missing.
`manage.py check --deploy --fail-level WARNING` must pass against these settings in CI.
"""

from ._env import admin_path, as_list, database, optional, phone_list, required, required_list
from .base import *

DEBUG = False

SECRET_KEY = required("SECRET_KEY")
# Old keys stay valid for signatures during rotation, so users are not logged out.
SECRET_KEY_FALLBACKS = as_list(optional("SECRET_KEY_FALLBACKS"))

# Separate from SECRET_KEY so rotating one never affects the other (architecture 5 A02).
OTP_HMAC_KEY = required("OTP_HMAC_KEY")

# Dotted path to the SMS gateway adapter (Text.lk, D4). The adapter itself refuses to start
# without SMS_API_KEY and SMS_SENDER_ID, so a misconfigured worker fails loudly.
SMS_BACKEND = required("SMS_BACKEND")
SMS_API_KEY = optional("SMS_API_KEY")
SMS_SENDER_ID = optional("SMS_SENDER_ID")
SMS_ALLOWED_NUMBERS = phone_list("SMS_ALLOWED_NUMBERS")  # set on staging only
HEALTHZ_CHECK_WORKER = True

# The origin firewall accepts traffic from Cloudflare only (architecture 5.1).
TRUST_CF_CONNECTING_IP = True

ALLOWED_HOSTS = required_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = required_list("CSRF_TRUSTED_ORIGINS")

# Use ?sslmode=require (or verify-full) in DATABASE_URL: TLS to the database (architecture 5 A02).
DATABASES = {"default": database(required("DATABASE_URL"), conn_max_age=60)}

ADMIN_URL_PATH = admin_path(required("ADMIN_URL_PATH"), allow_default=False)

# ---------------------------------------------------------------- HTTPS
SECURE_SSL_REDIRECT = True
# Caddy terminates TLS from Cloudflare and sets X-Forwarded-Proto. Only safe because the
# origin accepts traffic from Cloudflare via Caddy alone (architecture 5 A05).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# The deploy script checks /healthz on the server itself over plain HTTP.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]

SECURE_HSTS_SECONDS = 31_536_000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# Preload is switched on after the pilot (architecture 5 A02); it is hard to undo.
SECURE_HSTS_PRELOAD = False
SILENCED_SYSTEM_CHECKS = ["security.W021"]  # HSTS preload off on purpose, see above

# ---------------------------------------------------------------- cookies
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
