"""Settings for pytest, locally and in CI. Always PostgreSQL, never SQLite (CLAUDE.md)."""

from ._env import database, load_dotenv, required
from .base import *

load_dotenv(BASE_DIR / ".env")

DEBUG = False

SECRET_KEY = required("SECRET_KEY")
OTP_HMAC_KEY = required("OTP_HMAC_KEY")
ALLOWED_HOSTS = ["testserver", "localhost"]

DATABASES = {"default": database(required("DATABASE_URL"))}

# Records messages in memory for assertions (architecture 6.4).
SMS_BACKEND = "notifications.backends.locmem.LocmemBackend"

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Fast hashing; test passwords protect nothing.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# Serve static files from the app folders, as in dev; tests never run collectstatic.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
