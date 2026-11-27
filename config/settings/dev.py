"""Local development settings. Secrets come from .env (copy .env.example)."""

from ._env import admin_path, database, load_dotenv, optional, phone_list, required
from .base import *

load_dotenv(BASE_DIR / ".env")

DEBUG = True

SECRET_KEY = required("SECRET_KEY")
OTP_HMAC_KEY = required("OTP_HMAC_KEY")
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# SMS are printed to the console, never sent (architecture 6.4). To try real Text.lk sending
# from your laptop, set SMS_BACKEND, SMS_API_KEY, SMS_SENDER_ID and SMS_ALLOWED_NUMBERS in .env.
SMS_BACKEND = optional("SMS_BACKEND", "notifications.backends.console.ConsoleBackend")
SMS_API_KEY = optional("SMS_API_KEY")
SMS_SENDER_ID = optional("SMS_SENDER_ID")
SMS_ALLOWED_NUMBERS = phone_list("SMS_ALLOWED_NUMBERS")

DATABASES = {"default": database(required("DATABASE_URL"))}

ADMIN_URL_PATH = admin_path(optional("ADMIN_URL_PATH", "admin/"))

# Serve unhashed static files so Tailwind's watch mode shows changes immediately.
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
