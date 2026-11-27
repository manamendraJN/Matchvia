# Matchvia

**Book your court. Bring your team.**

Booking and management for futsal and indoor cricket venues in Sri Lanka. Players find free
slots and book; venue owners and staff run their courts, walk-ins and phone bookings from one
calendar.

Django 6.1 · PostgreSQL · Django templates + HTMX + Tailwind CSS · installable PWA.
Design documents (the source of truth) are in [docs/](docs/); rules for contributors are in
[CLAUDE.md](CLAUDE.md).

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.13 and all packages)
- PostgreSQL 17 running locally (tests never use SQLite)

## Setup

```sh
uv sync                                   # Python 3.13 + dependencies from uv.lock
cp .env.example .env                      # then fill in SECRET_KEY and OTP_HMAC_KEY (see the file)
createdb matchvia                         # or point DATABASE_URL in .env at your own database
uv run python manage.py migrate
uv run python manage.py createcachetable  # database cache, used by rate limits
uv run python scripts/tailwind.py build   # builds static/css/app.css
uv run python manage.py runserver
```

Open http://localhost:8000. The health check is at http://localhost:8000/healthz.

To sign in locally, start the worker in a second terminal (`uv run python manage.py run_worker`).
SMS are never sent in development: the worker prints them, so the 6-digit code appears there.
Reminders are printed at their scheduled time (by default 3 hours before the game).

To try real SMS through Text.lk from your laptop, add to `.env` (never commit it):
`SMS_BACKEND=notifications.backends.textlk.TextLkBackend`, `SMS_API_KEY=...`, `SMS_SENDER_ID=...`
and `SMS_ALLOWED_NUMBERS=+9477...` (only these numbers will receive SMS).

To use the admin site, create a platform admin:
`uv run python manage.py createsuperuser` (asks for a mobile number like `+94771234567`, a name and a
password).

Generate each secret with:

```sh
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"
```

## Everyday commands

| Task | Command |
|---|---|
| Run the site | `uv run python manage.py runserver` |
| Run the background worker (prints SMS, including sign-in codes, in development) | `uv run python manage.py run_worker` |
| Rebuild CSS while editing templates | `uv run python scripts/tailwind.py watch` |
| Run all tests | `uv run pytest` |
| Tests with coverage | `uv run pytest --cov` |
| Lint and format | `uv run ruff check . --fix` and `uv run ruff format .` |
| Security checks | `uv run bandit -c pyproject.toml -r . -q` |
| Install the Git hooks (once) | `uv run pre-commit install` |

The Tailwind CLI is the standalone binary (no Node.js). `scripts/tailwind.py` downloads the pinned
version into `.tools/` and checks its SHA-256 before running it.

## Settings

| Module | Used for |
|---|---|
| `config.settings.dev` | Local development (default for `manage.py`). Reads `.env` |
| `config.settings.test` | pytest, locally and in CI. Reads `.env` |
| `config.settings.staging` / `prod` | Servers. Every secret comes from real environment variables; the app refuses to start if one is missing |

All required variables are listed in [.env.example](.env.example). Never commit `.env`.

## Continuous integration

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push and pull request:
secret scan, lint, missing-migration check, `check --deploy` against production settings,
dependency audit, bandit, Tailwind build, and the test suite on PostgreSQL 17.
