"""Helpers for reading settings from environment variables (CLAUDE.md rule 5)."""

import os
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured


def load_dotenv(path: Path) -> None:
    """Load a local .env file into os.environ without overriding real variables.

    Only dev and test call this. Staging and production get their environment from the
    server (a root-owned env file passed to the container), never from the repository.
    """
    if path.is_file():
        environ.Env.read_env(path, overwrite=False)


def required(name: str) -> str:
    """Return a non-empty environment variable or refuse to start."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"Required environment variable {name} is not set.")
    return value


def optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def as_list(value: str) -> list[str]:
    """Split a comma-separated value, dropping blanks."""
    return [item.strip() for item in value.split(",") if item.strip()]


def required_list(name: str) -> list[str]:
    items = as_list(required(name))
    if not items:
        raise ImproperlyConfigured(f"Required environment variable {name} is empty.")
    return items


def phone_list(name: str) -> list[str]:
    """A comma-separated list of mobile numbers, normalised; refuses anything invalid."""
    from core.phone import InvalidPhone, normalise_phone

    numbers = []
    for item in as_list(optional(name)):
        try:
            numbers.append(normalise_phone(item))
        except InvalidPhone as exc:
            raise ImproperlyConfigured(f"{name} contains an invalid mobile number.") from exc
    return numbers


def database(url: str, *, conn_max_age: int = 0) -> dict:
    config = environ.Env.db_url_config(url)
    if config.get("ENGINE") != "django.db.backends.postgresql":
        raise ImproperlyConfigured("DATABASE_URL must point to PostgreSQL (postgres://...).")
    config["CONN_MAX_AGE"] = conn_max_age
    config["CONN_HEALTH_CHECKS"] = conn_max_age > 0
    return config


def admin_path(value: str, *, allow_default: bool = True) -> str:
    """Normalise the admin URL prefix to 'some-path/'.

    Production passes allow_default=False: the admin must not sit at the guessable 'admin/'.
    """
    path = value.strip().strip("/")
    if not path:
        raise ImproperlyConfigured("ADMIN_URL_PATH must not be empty.")
    if not allow_default and path.lower() == "admin":
        raise ImproperlyConfigured("ADMIN_URL_PATH must not be the default 'admin/'.")
    return f"{path}/"
