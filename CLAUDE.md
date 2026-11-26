# Project: Matchvia - futsal & indoor cricket court booking (Sri Lanka)

## What we are building
A multi-venue booking and management platform for futsal and indoor cricket venues.
- Players and team captains search venues, see live free slots, and book.
- Venue owners and staff manage courts, prices, opening hours, walk-in and phone bookings.
- Platform admin approves venues and handles disputes.
Tagline: "Book your court. Bring your team." Owners: two co-founders. Business documents: proposal and requirements in /docs.

## Tech stack
- Python, Django 6.1, PostgreSQL (btree_gist), Django templates + HTMX + Tailwind CSS
- Mobile-first, low-bandwidth friendly, installable PWA
- Time zone: Asia/Colombo for all times. Currency: LKR, stored as integer rupees or cents.
- Languages: English first; all user-facing text wrapped for translation (Sinhala later).

## Non-negotiable rules
1. NO DOUBLE BOOKINGS: enforced by a PostgreSQL ExclusionConstraint on bookings
   (court + time range overlap, ignoring cancelled/expired/no_show). Never rely only on app checks.
2. Multi-tenant security: a venue owner/staff can only ever read or change their own venue's data.
   Every queryset for venue data must be filtered by the user's venue. Add tests for this.
3. Security defaults on: CSRF, autoescaping, HTTPS settings, secure cookies, HSTS, CSP,
   ALLOWED_HOSTS. No csrf_exempt, no mark_safe on user input, no raw SQL without parameters.
   Only exception: the Phase 2 payment webhook may be csrf_exempt, protected by signature checks
   (docs/architecture.md 9.3).
4. Rate-limit OTP requests, login and booking endpoints (Django does not throttle logins itself).
5. Secrets only in environment variables, never in code or Git.
6. No card data stored. Payments go through the gateway's hosted checkout; verify webhooks.
7. Personal data: collect the minimum; support data deletion (Sri Lanka PDPA).

## Code conventions
- Apps: accounts, venues, pricing, bookings, teams, notifications, payments, reports, adminpanel.
  Shared helpers (phone normalisation, operating-day/time helpers, VenueOwnedQuerySet, domain
  exceptions) live in `core`. payments and reports are created only in Phase 2.
- Business logic in services.py, not in views or templates. Services own the transaction;
  cross-app calls go through the other app's services.py. No signals for business logic.
- Venue-side views get the venue only through venues.services.get_venue_for_user() (404 if not a
  member) and query with .for_venue(venue). Form querysets are scoped to the venue too.
- SMS only through the notifications outbox, written in the same transaction. Never call the SMS
  gateway inside a request.
- No inline JS/CSS and no CDNs: htmx and Leaflet are vendored; CSP with nonces; htmx allowEval off.
- Never log OTP codes, tokens, session IDs or full phone numbers.
- Tests always run on PostgreSQL, never SQLite.
- Design docs in /docs (requirements, data-model, architecture) are the source of truth; update
  them in the same change when a decision changes.
- Every feature has tests (pytest + pytest-django). Booking engine and permissions need the most.
- Small, focused commits with clear messages.

## How to work with me
- Before coding, explain your plan and list the files you will change. Wait for my OK.
- Ask when a requirement is unclear; do not guess business rules.
- After coding, run tests and show results. Summarise what changed and what I should test by hand.
