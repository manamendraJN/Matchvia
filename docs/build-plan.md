# Matchvia MVP Build Plan

Version 1.0 · 26 Nov 2026 · Based on [requirements.md](requirements.md), [data-model.md](data-model.md),
[architecture.md](architecture.md), [screens.md](screens.md) and [CLAUDE.md](../CLAUDE.md)

The MVP broken into 34 steps of 1–3 days each for one developer. The order puts the riskiest work
first (permissions, the no-double-booking constraint, the slot engine, OTP), then builds a **demo
slice** so the co-founder can start venue demos, then completes the Must requirements, then pilot
readiness, then the Should requirements if time allows.

> **About prompts C1–C10:** they are not in the repository, so this plan follows risk and dependency
> order. Share them and a "Prompt" column will be added mapping each step to C1–C10.

---

## 1. How to use this plan

1. Work on **one step at a time**, in order (later steps depend on earlier ones).
2. At the start of a step, Claude explains the plan and lists the files it will change, and waits for
   your OK (CLAUDE.md "How to work with me").
3. Build with tests. A step is finished only when its **Done when** list **and** the Definition of
   Done (section 2) are met.
4. Tick the box in section 4, commit (`Build S06: booking constraint`), and note anything learned in
   the step's row of the progress log (section 9).
5. If a step takes more than 1.5× its estimate, stop and re-plan with the cut list (section 8).

---

## 2. Definition of Done (every step)

- [ ] Tests written for the step and **passing in CI on PostgreSQL** (never SQLite).
- [ ] Coverage thresholds hold (`bookings`, venue access code and `accounts` ≥ 95%; project ≥ 85%).
- [ ] Every new venue-side URL has an **isolation test** (another venue's staff gets 404, nothing
      changes). The meta-test from S05 enforces this.
- [ ] Business logic is in `services.py`; views stay thin.
- [ ] All user-facing text (including SMS) wrapped for translation.
- [ ] New screens checked at **360 px wide** with throttled "Slow 4G" in Chrome DevTools, and with the
      pseudo-locale (long labels) from S09.
- [ ] No secrets in code; new settings added to `.env.example`.
- [ ] `ruff`, `makemigrations --check`, `check --deploy`, `pip-audit`, `bandit`, `gitleaks` green.
- [ ] Docs in `/docs` updated if a decision changed.
- [ ] Summary written: what changed and what to test by hand.

---

## 3. Decisions needed before certain steps

These were proposed in earlier documents with recommended defaults. Each must be confirmed (or
changed) before the step that needs it.

| Decision | Default | Needed before |
|---|---|---|
| UX1 Time format | 12-hour ("7:00 pm") | S09 |
| D4 SMS gateway account (and sender ID) | Text.lk | S08 (real sending only needed by S12) |
| D5 Bot check on OTP | Cloudflare Turnstile | S10 |
| D10 Domain registered | `matchvia.lk` + `.com` | S12 |
| D1 Hosting | DigitalOcean Bangalore: VPS + managed PostgreSQL | S12 (staging), S30 (production) |
| D7 Photo storage | Cloudflare R2 | S21 |
| D9 Session lifetimes | Players 30 d, venue 7 d, admin 8 h | S10 |
| D6 Production deploy | One-click approval | S30 |
| D2 Legal advice on hosting player data abroad (PDPA) | Before the pilot | S30 |
| UX2–UX5 | See screens.md section 6 | S13–S16 |
| PM1 Staff weekly bookings in pilot scope (section 6) | Yes | S27 |

---

## 4. Checklist

### Milestone 0: Foundation (about 4 days)

- [x] **S01** Project skeleton and local development · 1.5 d
- [x] **S02** CI pipeline and production security settings · 1 d
- [x] **S03** Custom user model and `core` helpers · 1.5 d

### Milestone 1: Riskiest core (about 21 days)

- [x] **S04** Venue, court, hours and settings models · 2 d
- [x] **S05** Venue permissions and isolation test framework · 2 d
- [x] **S06** Booking table and the no-double-booking constraint · 2.5 d
- [x] **S07** Free-slot engine and pricing · 2.5 d
- [ ] **S08** SMS outbox, worker and gateway adapter · 2 d
- [ ] **S09** Front-end foundation (layout, Tailwind, HTMX, CSP, components, i18n) · 2 d
- [ ] **S10** Phone OTP sign-in · 3 d
- [x] **S11** Booking services (online, staff, cancel, move, no-show) · 3 d
- [ ] **S12** Staging environment and deploy pipeline · 2 d

### Milestone 2: Demo slice (about 13 days)

- [ ] **S13** Venue page and slot picker (P3) · 2.5 d
- [ ] **S14** Booking review and confirmation (P4–P8) · 2 d
- [x] **S15** Venue calendar, day and week (V7–V9) · 3 d
- [x] **S16** New booking sheet and booking actions (V10–V13) · 3 d
- [ ] **S17** Booking SMS and reminders · 1.5 d
- [ ] **S18** Demo-ready milestone (seed data, demo on staging) · 1 d

### Milestone 3: Complete the Must requirements (about 17.5 days)

- [ ] **S19** Search and results (P1, P2) · 2 d
- [ ] **S20** My bookings, details and cancel (P9–P11) · 1.5 d
- [ ] **S21** Venue setup wizard and photos (V1–V6) · 3 d
- [ ] **S22** Blocks and closed days (V14, V15) · 2.5 d
- [ ] **S23** Customer book and online blocking (V18, V19) · 1.5 d
- [ ] **S24** Venue settings, courts, hours, prices, staff, profile (V20–V25) · 3 d
- [ ] **S25** Platform admin (A1–A5) · 2 d
- [ ] **S26** Account, deletion and privacy pages (P18–P20) · 2 d

### Milestone 4: Recommended for the pilot (Should) (about 3 days)

- [ ] **S27** Recurring engine and staff weekly bookings (V16) · 3 d

### Milestone 5: Pilot readiness (about 7.5 days)

- [ ] **S28** Security review and hardening · 2 d
- [ ] **S29** Performance and load test · 1 d
- [ ] **S30** Production environment, backups and smoke tests · 2.5 d
- [ ] **S31** Pilot onboarding and acceptance-test buffer · 2 d

### Milestone 6: Should requirements, if time allows (about 5.5 days)

- [ ] **S32** Teams and invites (P14–P17) · 2.5 d
- [ ] **S33** Captain weekly requests and approvals (P12, P13, V17) · 2 d
- [ ] **S34** Share page and QR poster (V26) · 1 d

---

## 5. Step details

### Milestone 0: Foundation

#### S01 Project skeleton and local development · 1.5 days
- **Goal:** a Django 6.1 project that runs locally on PostgreSQL, with the agreed layout and tooling.
- **Touches:** `pyproject.toml`, `uv.lock`, `config/settings/{base,dev,test,staging,prod}.py`,
  `config/urls.py`, empty apps `core accounts venues pricing bookings teams notifications adminpanel`
  (no `payments`/`reports` yet), `compose.yaml` (PostgreSQL 17 for local dev), `.env.example`,
  `pytest.ini`/`pyproject` pytest config, `ruff` config, `.pre-commit-config.yaml` (ruff, gitleaks),
  `README.md` (setup in 5 commands), `/healthz` view.
- **Tests:** settings load for dev/test; `/healthz` returns 200 and reports database OK; settings
  refuse to start in prod mode without required env vars.
- **Done when:** `docker compose up -d db && uv run pytest` passes on a fresh clone; `TIME_ZONE =
  "Asia/Colombo"`, `USE_TZ = True`; secrets only read from the environment.

#### S02 CI pipeline and production security settings · 1 day
- **Goal:** every push is checked automatically; production settings are secure from day one.
- **Touches:** `.github/workflows/ci.yml` (test job only for now; actions pinned to SHAs),
  `config/settings/prod.py` (HTTPS redirect, HSTS, secure/HttpOnly/SameSite cookies, CSP via Django's
  built-in support, `X-Frame-Options`, `Referrer-Policy`, exact `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`),
  Dependabot config, GitHub branch protection on `main`.
- **Tests:** `check --deploy --settings=config.settings.prod` passes with dummy env values; a test
  asserts key security settings are on in prod settings.
- **Done when:** a pull request shows the CI job green; direct pushes to `main` are blocked.

#### S03 Custom user model and `core` helpers · 1.5 days
- **Goal:** the phone-based user model (must exist before the first real migration) and the shared
  helpers everything else depends on.
- **Touches:** `accounts/models.py` (`User`, manager), `core/phone.py`, `core/timeutils.py`
  (operating day, operating minutes, local ↔ UTC), `core/exceptions.py`, `core/querysets.py`
  (`VenueOwnedQuerySet`), `accounts/admin.py`, first migrations, factories.
- **Tests:**
  - Phone normalisation table: `0771234567`, `771234567`, `+94771234567`, spaces/dashes → `+94771234567`;
    landlines, foreign numbers, too short/long → rejected.
  - Operating day: 00:30 Saturday belongs to Friday; 03:00 starts a new day; operating minute 1500 on
    Friday = Saturday 01:00 local; conversions round-trip through UTC.
  - User: created with phone and name, unusable password, phone unique, deleted user has no phone
    (check constraint).
- **Done when:** `AUTH_USER_MODEL = "accounts.User"` migrated; helpers 100% covered.

### Milestone 1: Riskiest core

#### S04 Venue, court, hours and settings models · 2 days
- **Goal:** all venue-owned configuration tables with their database constraints.
- **Touches:** `venues/models.py` (`Area`, `Venue`, `VenueSettings`, `VenueMembership`, `VenuePhoto`,
  `Court`, `OpeningHours`, `VenueCustomer`), `pricing/models.py` (`PeakPeriod`),
  `venues/services.py` (`create_venue()` creating defaults: settings, 7 opening-hour rows, peak
  periods, owner membership), migrations, factories, basic admin registration.
- **Tests:**
  - Every check constraint rejects bad values (slot length 45, opening 02:00, closing 03:30, horizon
    0 or 61, weekday 7, empty sports array, unknown sport code, price over 100,000).
  - `create_venue()` creates the defaults from BR-01–BR-27 exactly.
  - `VenueCustomer` unique per venue and phone; null phones allowed.
- **Done when:** data-model sections 3.2–3.3 implemented field for field; `UQ (id, venue)` exists on
  `Court` and `VenueCustomer`.

#### S05 Venue permissions and isolation test framework · 2 days · CLAUDE.md rule 2
- **Goal:** one enforced way into venue data, and tests that make skipping it impossible.
- **Touches:** `venues/services.py` (`get_venue_for_user(user, venue_id, roles)`),
  `core/views.py` (`VenueViewMixin` / decorator that resolves the venue and role once per request),
  `venues/urls.py` (`/manage/<venue_id>/` namespace with one placeholder "dashboard" view),
  `tests/test_isolation.py` (shared helper + **meta-test**).
- **Tests:**
  - Owner and staff of venue A get in; a user with no membership, a member of venue B, and an
    anonymous user get 404 (anonymous → login redirect).
  - Owner-only view rejects staff with 404.
  - Removing a membership blocks the next request.
  - **Meta-test:** lists every URL pattern under `manage:` and fails if any is missing from the
    isolation test registry.
- **Done when:** the meta-test fails when a new unregistered venue URL is added (proved once by a
  temporary test URL), then passes.

#### S06 Booking table and the no-double-booking constraint · 2.5 days · FR-06, NFR-01
- **Goal:** the database makes double bookings impossible, including under concurrency.
- **Touches:** `bookings/models.py` (`Booking`, `BookingEvent`, `RecurringSeries` table only),
  migration with `BtreeGistExtension()`, the exclusion constraint, all check constraints, partial
  unique "one hold per user", indexes, **composite foreign keys via `RunSQL`**, `bookings/reference.py`
  (6-character codes with collision retry), factories.
- **Tests:**
  - Overlap on the same court rejected for `confirmed` and `held`; different courts fine; adjacent
    ranges (18–19, 19–20) allowed.
  - `cancelled`, `expired`, `no_show` rows don't block; changing a `no_show` back to `confirmed` fails
    if the time was rebooked.
  - Block vs booking collide both ways.
  - Check constraints: end ≤ start, block with price/customer/source, held without expiry, cancelled
    without `cancelled_at`.
  - Composite FKs: booking with venue A and court of venue B rejected; same for customer and series.
  - **Concurrency:** 20 threads insert the same slot → exactly 1 succeeds, 19 raise the exclusion
    violation (`transaction=True` test).
  - Reference format and uniqueness.
- **Done when:** all tests pass in CI; the constraint name and violation code match data-model 4.1.

#### S07 Free-slot engine and pricing · 2.5 days · FR-03, FR-04
- **Goal:** correct free slots and prices for any court and operating date.
- **Touches:** `pricing/services.py` (`price_for(court, start_at)`), `bookings/selectors.py`
  (`free_slots(court, operating_date, now, for_staff=False)` and a batch version for many courts),
  `core/timeutils.py` additions.
- **Tests (with frozen time):**
  - Grid from opening hours and slot length (30/60/90/120); closing after midnight (18:00–01:00 gives
    a 00:00 slot on the same operating day); closed weekday gives nothing.
  - Removes booked, blocked and held slots; ignores cancelled/no-show/expired.
  - Past slots and slots inside minimum notice (BR-05) hidden for players, shown for staff.
  - Horizon (BR-04) respected.
  - Peak vs off-peak by slot start time and weekday (BR-18), including all-day weekend and late-night
    slots.
  - Batch query count stays constant as courts increase (`django_assert_num_queries`).
- **Done when:** every BR-01–BR-05, BR-15 and BR-18 example from requirements is a passing test.

#### S08 SMS outbox, worker and gateway adapter · 2 days · NFR-03
- **Goal:** reliable SMS sending that never blocks a request.
- **Touches:** `notifications/models.py` (`SmsMessage`), `notifications/services.py` (`queue_sms`,
  reminder helpers), `notifications/backends/` (console, fake for tests, Text.lk adapter),
  `notifications/management/commands/run_worker.py` (job loop: send SMS, heartbeat, placeholders for
  expiry jobs), `/healthz` worker heartbeat.
- **Tests:**
  - `queue_sms` inside a rolled-back transaction leaves no row.
  - Worker sends due messages, skips future ones, uses `SKIP LOCKED` (two workers don't double-send).
  - Retry with backoff; `failed` after 5 attempts; OTP older than 5 min dropped; reminder for a booking
    that already started cancelled.
  - OTP message body stored redacted.
  - Gateway timeout doesn't crash the loop.
- **Done when:** a message queued locally is printed by the console backend within 5 seconds of the
  worker running; Text.lk adapter tested with mocked HTTP (real account optional until S12).

#### S09 Front-end foundation · 2 days · NFR-02, NFR-04, NFR-05
- **Goal:** the shared look, components and security headers every screen uses.
- **Touches:** `templates/base.html` (CSP nonces, `hx-headers` CSRF, bottom nav slots), Tailwind
  standalone CLI build, vendored `htmx` (configured `allowEval=false`, `includeIndicatorStyles=false`),
  `static/js/app.js`, component partials (button with loading state, form field with error, time
  chip, day strip, bottom sheet, toast, status chip, empty state), `core/formatting.py` (time per UX1,
  date, "Rs. 3,500"), i18n setup with `LocaleMiddleware` and a **pseudo-locale**, 404/500/429 pages,
  PWA manifest, icons, minimal service worker (static files + offline page only).
- **Tests:** CSP header present with nonce and no `unsafe-inline`/`unsafe-eval`; CSRF token reaches
  HTMX requests; formatters (12-hour times, late-night "(next day)", rupees); error pages render;
  service worker doesn't cache HTML (test the file's cache list).
- **Done when:** a demo page with all components renders at 360 px under the pseudo-locale without
  overflow; first load under 300 KB.

#### S10 Phone OTP sign-in · 3 days · FR-01, US-P01, BR-27
- **Goal:** secure phone sign-in with all rate limits.
- **Touches:** `accounts/models.py` (`OTPChallenge`, `ConsentRecord`), `accounts/services.py`
  (request code, verify code, sign in, link `VenueCustomer` rows by phone, record consent),
  `accounts/views.py` + templates (P4, P5, P6), Turnstile verification, `core/ratelimit.py`
  (`DatabaseCache`-backed IP limits, Cloudflare client IP), session settings per role (D9),
  `next` redirect validation.
- **Tests:**
  - Code generation uses `secrets`; only an HMAC is stored; constant-time compare.
  - Expiry at 5 minutes; 5 wrong codes → 15-minute lock; 3 requests per 15 minutes per number;
    10 per hour per IP; consumed code can't be reused.
  - Same response for known and unknown numbers.
  - Non-Sri-Lankan and landline numbers rejected without sending SMS.
  - Session ID rotates at login; open-redirect attempts (`next=https://evil.com`) ignored.
  - First sign-in requires name and consent; consent recorded with version; earlier phone bookings
    linked.
  - Turnstile failure blocks the request (mocked).
- **Done when:** sign-in works end to end locally with the console SMS backend; all BR-27 limits
  proven by tests.

#### S11 Booking services · 3 days · FR-05, FR-07, FR-09, FR-11
- **Goal:** all booking business rules in one tested service layer, used later by every screen.
- **Touches:** `bookings/services.py`: `create_online_booking`, `create_staff_booking`,
  `cancel_booking` (player and staff), `move_booking`, `mark_no_show`, `undo_no_show`; each writes a
  `BookingEvent` (no personal data in `changes`) and queues SMS through `notifications.services`;
  domain exceptions; `VenueCustomer` get-or-create.
- **Tests:**
  - Online: approved venue only; blocked customer refused (BR-11); max slots (BR-02); notice (BR-05);
    horizon (BR-04); upcoming limit (BR-12); price snapshot; overlap → `SlotTaken`.
  - Staff: bypasses notice/horizon/limit; warns outside hours (BR-23); price change needs reason and
    permission (BR-19); walk-in without phone allowed.
  - Cancel: player inside window refused, outside allowed (BR-08); staff any time with reason (BR-09);
    late-cancellation flag; queued reminder cancelled.
  - Move: into free time OK with SMS; into taken time fails with no change.
  - No-show: only from start + 15 min to end + 48 h (BR-10); frees the court; undo fails if rebooked.
  - Audit events written with the right action and no names or phones.
- **Done when:** every acceptance criterion in US-P04, US-P06, US-S02–S05 and US-S07 that isn't about
  screens has a passing service test.

#### S12 Staging environment and deploy pipeline · 2 days · needs D1, D10
- **Goal:** the app running on staging, deployed automatically from `main`.
- **Touches:** `Dockerfile` (web and worker from one image), `compose.prod.yaml` (Caddy, web,
  worker, PostgreSQL for staging), `Caddyfile`, CI jobs `build` and `deploy-staging`, staging VPS
  setup notes in `docs/runbook.md` (new), Cloudflare DNS + proxy + Access on staging, firewall
  allowing Cloudflare IPs only, real SMS gateway with a **number allowlist**.
- **Tests:** CI deploy job checks `/healthz` (database and worker heartbeat) after deploy; a test that
  the staging SMS allowlist blocks other numbers.
- **Done when:** merging to `main` updates `staging.matchvia.lk` within minutes; sign-in works on
  staging with a founder's phone; staging is not reachable without Cloudflare Access.

### Milestone 2: Demo slice

The goal of this milestone is something the co-founder can demo: a venue page where a player books,
and a calendar where staff see it and add walk-ins. Venue setup is done by seed data or the Django
admin until S21.

#### S13 Venue page and slot picker (P3) · 2.5 days · FR-04, FR-15, US-P03
- **Goal:** the public, shareable venue page with live free slots.
- **Touches:** `venues/views.py` (public `/v/<slug>/`), `bookings` slot partial (HTMX day switch),
  templates for P3 (header, Call, Directions, day strip, court rows with chips, sticky selection
  bar, collapsible sections, tap-to-load map with Leaflet vendored).
- **Tests:** only approved venues show slots (pending/suspended show the notice); blocked times show
  "Unavailable" without reason; consecutive selection limited by BR-02 (server re-checks); day switch
  returns a partial; correct prices on chips; page works without JavaScript for viewing.
- **Done when:** the page meets screens.md P3 including all empty/error states, and loads under 2 s on
  throttled Slow 4G from staging.

#### S14 Booking review and confirmation (P4–P8) · 2 days · FR-05, US-P04
- **Goal:** a player goes from a chosen slot to a confirmed booking, signing in on the way.
- **Touches:** `bookings/views.py` (review, confirm, confirmation), templates P7, P8, sign-in
  hand-off that remembers the selection, share-sheet link, booking rate limit (10/hour).
- **Tests:** signed-out user is sent to sign-in and returns to review with the selection; confirm
  creates the booking and queues SMS; "slot just taken" returns to P3 with the message; booking limit
  and blocked-player messages; double submit doesn't create two bookings; price recalculated on the
  server (tampered form price ignored).
- **Done when:** flow 5.1 in screens.md works on staging on a real phone, including the error rows.

#### S15 Venue calendar, day and week (V7–V9) · 3 days · FR-11, US-S01
- **Goal:** the staff dashboard home.
- **Touches:** `bookings/views_manage.py` (calendar day/week, HTMX polling partial), templates for
  V7 (venue switcher), V8, V9, bottom nav for the dashboard, venue status banner.
- **Tests:** isolation tests for every new URL; day view shows bookings, blocks, sources, series icon;
  cancelled hidden unless filtered; late-night bookings under the right operating day; polling partial
  returns only changes for that venue; query count bounded.
- **Done when:** V8/V9 match screens.md at 360 px with 4 courts (swipe), and a booking made on P3
  appears within 30 seconds without reload.

#### S16 New booking sheet and booking actions (V10–V13) · 3 days · FR-07, US-S02–S05, US-S07
- **Goal:** staff add walk-in/phone/WhatsApp bookings in 3 taps and manage them.
- **Touches:** views and templates for V10 (bottom sheet, source switch with UX4 default, customer
  suggestions, duration chips, price change), V11 (details, history, actions), V12 (move), V13
  (cancel); all call S11 services.
- **Tests:** isolation tests; form querysets scoped to the venue (tampered court ID of another venue
  rejected); walk-in without phone; phone required for phone/WhatsApp; overlap message; outside-hours
  warning and "Save anyway"; no-show button timing; undo no-show; staff without price permission can't
  change price.
- **Done when:** flow 5.3 in screens.md works on staging in under 15 seconds on a real budget phone.

#### S17 Booking SMS and reminders · 1.5 days · FR-05, FR-10, US-P07, BR-20, BR-21
- **Goal:** the right SMS at the right time with the right text.
- **Touches:** `notifications/templates/sms/*.txt` (confirmation, cancellation, change, reminder,
  OTP with WebOTP line), reminder scheduling (lead time per venue, quiet hours → 21:00 the evening
  before, none if booked after reminder time, none for walk-ins), SMS settings for staff bookings.
- **Tests:** each template renders within one SMS segment where possible (length check); reminder time
  calculation table (normal, quiet hours, late booking, walk-in); cancelling/moving updates the queued
  reminder; unique reminder per booking.
- **Done when:** on staging, a booking made at 2 pm for 7 pm sends a confirmation now and a reminder at
  4 pm to an allowlisted phone.

#### S18 Demo-ready milestone · 1 day
- **Goal:** the co-founder can demo the working system to venues (proposal phase 1, from about week 9).
- **Touches:** `bookings/management/commands/seed_demo.py` (2–3 realistic venues in Malabe with
  courts, prices, a week of bookings, regular teams, blocks), staging reset script, a one-page demo
  script in `docs/demo-script.md` (what to show, in what order, matching proposal 7.4).
- **Tests:** seed command runs twice without errors (idempotent) and passes model validation.
- **Done when:** the co-founder runs the demo script on staging from their own phone without help.

### Milestone 3: Complete the Must requirements

#### S19 Search and results (P1, P2) · 2 days · FR-04, US-P02
- **Goal:** players find free courts across venues.
- **Touches:** `bookings/views.py` (search form, results, HTMX filter updates), batch free-slot
  selector use, cache for venue/court/hours data with invalidation on owner edits, search rate limit.
- **Tests:** filters by sport, area, date, time-of-day; only approved venues; closed venues excluded;
  beyond-horizon message; empty state with "Try Sunday"; constant number of queries for many venues;
  availability never served from cache (book a slot, search again, it's gone); invalid filters
  handled.
- **Done when:** search returns in under 2 s on staging with seeded data for 30 venues.

#### S20 My bookings, details and cancel (P9–P11) · 1.5 days · US-P05, US-P06
- **Goal:** players see and cancel their bookings.
- **Touches:** `/me/bookings` views and templates P9, P10, P11.
- **Tests:** player sees only their own bookings (another player's booking ID → 404); staff-entered
  bookings with their phone appear; cancel inside/outside window; window closing while the sheet is
  open; past bookings not cancellable.
- **Done when:** screens.md P9–P11 states all work.

#### S21 Venue setup wizard and photos (V1–V6) · 3 days · FR-02, FR-03, US-O01–O04 · needs D7
- **Goal:** a non-technical owner sets up a venue in about 10 minutes.
- **Touches:** wizard views/templates V1–V6 (resume at first unfinished step), photo upload to object
  storage (Pillow re-encode, EXIF stripped, size and dimension limits, random names), Leaflet pin with
  "Use my current location", "same hours every day" and "same prices for all courts" shortcuts,
  submit for approval.
- **Tests:** each step validates and saves; resume works; photo rules (type, 5 MB, 6 max, EXIF removed,
  decompression-bomb guard); only the owner can edit; pin outside Sri Lanka rejected; submit changes
  status to pending and notifies admin; calendar usable while pending.
- **Done when:** flow 5.2 in screens.md is completed by someone non-technical (for example a family
  member) on a budget phone in under 15 minutes.

#### S22 Blocks and closed days (V14, V15) · 2.5 days · FR-08, US-S06, US-O03, BR-16, BR-17
- **Goal:** staff block times and close whole days safely.
- **Touches:** `bookings/services.py` (`create_block`, `remove_block`, `close_day` using a
  `block_group` across all courts for the operating day 03:00–03:00, `cancel_all_and_close`), views
  and templates V14, V15, closed-day display in V8 and P3.
- **Tests:** block over bookings rejected with the conflicting list; multi-court block; close day with
  no bookings; close day with bookings requires "cancel all and send SMS" and queues SMS for each;
  reopening removes the group; players see "Unavailable"/"Closed" without reasons; isolation tests.
- **Done when:** US-S06 and the BR-16 criteria pass.

#### S23 Customer book and online blocking (V18, V19) · 1.5 days · US-O09, BR-11
- **Goal:** the venue's customer list and the no-show defence.
- **Touches:** views/templates V18, V19; `venues/services.py` (`block_customer_online`, `unblock`);
  counts computed from bookings.
- **Tests:** isolation (venue A never sees venue B's customers, even with the same phone); no-show and
  late-cancellation counts; only owners block/unblock; blocked customer can't book online but staff can
  book them; deleted user shows as "Deleted user".
- **Done when:** US-O09 criteria pass.

#### S24 Venue settings, courts, hours, prices, staff and profile (V20–V25) · 3 days · US-O02–O06
- **Goal:** owners manage their venue after setup.
- **Touches:** views/templates V20 (booking rules as plain questions), V21, V22, V23, V24 (add staff by
  phone with SMS, remove, last-owner protection), V25 (profile and status, resubmit); cache
  invalidation for search data.
- **Tests:** settings only accept allowed values (and the database rejects others); changes apply to
  new bookings only; deactivating a court with future bookings blocked; shortening hours warns; staff
  can't reach any of these screens (404); removing staff ends access on the next request; can't remove
  the last owner; isolation tests.
- **Done when:** US-O02–US-O06 criteria pass.

#### S25 Platform admin (A1–A5) · 2 days · FR-12, US-A01–A04
- **Goal:** founders approve, reject and suspend venues and look up bookings.
- **Touches:** `adminpanel/admin.py` (venue approval queue, approve/reject/suspend actions with
  required reason and owner SMS, area admin, booking lookup by reference/phone with history,
  read-only `AdminAccessLog`), admin at a private path, admin session lifetime, access logging.
- **Tests:** only `is_staff` users reach the admin; approve makes a venue searchable and bookable;
  reject/suspend need a reason and send SMS; suspended venue hidden from search with existing bookings
  kept; viewing a booking or customer writes an access log entry.
- **Done when:** a venue goes from pending to live through the admin on staging (behind Cloudflare
  Access).

#### S26 Account, deletion and privacy pages (P18–P20) · 2 days · US-P08, NFR-07, BR-25
- **Goal:** PDPA basics: privacy notice, terms and self-service deletion.
- **Touches:** P18 account page, P19 deletion with OTP, `accounts/services.py` (`delete_account`
  anonymising per data-model section 9), privacy and terms pages (draft text, marked for legal
  review), worker `purge_personal_data` job.
- **Tests:** deletion anonymises user, venue customer rows and booking names; future bookings cancelled
  with venues notified; OTP rows deleted; audit log untouched; owner/captain blocked from deleting until
  they transfer; purge job removes OTP rows after 24 h and SMS phone numbers after 90 days.
- **Done when:** after deleting a test account on staging, a database search for its phone number
  finds nothing outside consent records.

### Milestone 4: Recommended for the pilot

#### S27 Recurring engine and staff weekly bookings (V16) · 3 days · FR-14 (part), US-S08 · needs PM1
- **Goal:** pilot venues can enter their existing "every Tuesday" teams on day one (screens flow 5.2
  step 9).
- **Touches:** `bookings/services.py` (`preview_series`, `create_staff_series`, `expand_series` with
  one savepoint per week, `cancel_series`), V16 view/template, "Repeat weekly" link from V10, series
  display in V8/V11/P9, single summary SMS.
- **Tests:** expansion dates and times including late-night start times; clashing weeks skipped and
  recorded with reasons; prices fixed at creation; cancel one week vs the rest; series bookings count
  as normal bookings for the constraint; max weeks respected; isolation tests.
- **Done when:** US-S08 criteria pass and a 12-week series with 2 clashes creates 10 bookings.

### Milestone 5: Pilot readiness

#### S28 Security review and hardening · 2 days · proposal 8.2
- **Goal:** find and fix security gaps before real venues and players.
- **Touches:** fixes only; `docs/security-review.md` (new) with findings and status.
- **Checks:** OWASP ZAP baseline scan against staging; manual tests of OTP abuse (SMS bombing, brute
  force), access control (every venue URL with another venue's IDs), price tampering, CSP violations
  in the browser console, file upload abuse; review all `RunSQL`/raw queries; confirm no `csrf_exempt`,
  no `|safe` on user data, no personal data in logs or Sentry events; secrets rotated from development
  values.
- **Done when:** no open high or medium findings; every fix has a regression test.

#### S29 Performance and load test · 1 day · NFR-02
- **Goal:** prove the speed targets on budget phones.
- **Touches:** `loadtests/locustfile.py`, fixes (indexes, query counts, image sizes).
- **Checks:** Lighthouse mobile on P1, P3, V8 with Slow 4G throttling; first load under 300 KB; search
  under 2 s at 20 concurrent users on staging; booking burst (50 bookings in a minute) with zero
  double bookings and no errors.
- **Done when:** targets met and results recorded in `docs/runbook.md`.

#### S30 Production environment, backups and smoke tests · 2.5 days · needs D1, D2, D6
- **Goal:** a production environment ready for the pilot.
- **Touches:** production VPS + managed PostgreSQL (`btree_gist` enabled), production secrets
  (different from staging), Cloudflare (DNS, WAF rules, `/auth/` rate rule, Access on the admin path),
  CI `smoke-staging` (Playwright: sign in → search → book → cancel; staff walk-in) and
  `deploy-production` with manual approval and pre-migration snapshot, nightly encrypted `pg_dump` to
  a different provider, Sentry, uptime + heartbeat alerts to both founders' phones, `docs/runbook.md`
  (deploy, rollback, restore, incident and data-breach steps).
- **Tests:** Playwright smoke suite green against staging; **restore drill**: restore last night's
  backup into a throwaway database and run the constraint/row-count check script.
- **Done when:** production serves `matchvia.lk`; a deploy and a rollback have been practised; alerts
  reach both phones when the worker is stopped.

#### S31 Pilot onboarding and acceptance-test buffer · 2 days
- **Goal:** pilot venues are set up and confident; last fixes done.
- **Touches:** fixes from acceptance testing; `docs/pilot-checklist.md` (per-venue onboarding: setup,
  load notebook bookings and regular teams, add staff, print QR poster, train staff, agree success
  measures).
- **Checks:** each pilot owner and one staff member complete real tasks on their own phones (proposal
  8.2 user acceptance testing): add a walk-in, take a phone booking, mark a no-show, close a day; one
  player per venue books online.
- **Done when:** the phase 1 gate is met: all Must requirements pass tests, and 3+ venues commit to the
  pilot.

### Milestone 6: Should requirements, if time allows

#### S32 Teams and invites (P14–P17) · 2.5 days · FR-13, US-C01–C03, US-P09
- **Goal:** captains create teams, invite players, and tag bookings with a team.
- **Touches:** `teams/models.py`, `teams/services.py` (create, invite with hashed token, accept with
  row lock and 15-member limit, remove), views/templates P14–P17, team picker in P7, team bookings in
  P9.
- **Tests:** invite token stored hashed; expired/declined/revoked invites; wrong number signed in;
  15-member limit under concurrent accepts; invite rate limit; removed member loses access to team
  bookings.
- **Done when:** US-C01–C03 and US-P09 criteria pass.

#### S33 Captain weekly requests and approvals (P12, P13, V17) · 2 days · FR-14, US-C04, US-C05, US-O07
- **Goal:** captains request weekly slots; venues approve or reject.
- **Touches:** `bookings/services.py` (`request_series`, `approve_series`, `reject_series`, expiry job in
  the worker), views/templates P12, P13, V17, Requests badge, approver setting (BR-13).
- **Tests:** pending request reserves nothing; approval preview recalculated; approve expands like
  S27; approver rule (owner only vs owner or staff); expiry after 48 h with SMS; captain cancels one
  week vs the rest within the window; isolation tests.
- **Done when:** US-C04, US-C05 and US-O07 criteria pass.

#### S34 Share page and QR poster (V26) · 1 day · FR-15, US-O08
- **Goal:** owners share their page and print a poster.
- **Touches:** V26 view/template, QR code generation (pure Python library, no external API), A4
  poster PNG/PDF with venue name, tagline and QR.
- **Tests:** QR encodes the venue's public link; poster renders; not-yet-approved state; isolation
  test.
- **Done when:** a printed poster scanned with a phone opens the venue page.

---

## 6. Scope decision PM1: staff weekly bookings in the pilot

FR-14 is a Should requirement, but the venue setup flow (screens.md 5.2, step 9) and the sales
approach rely on loading a venue's existing regular teams. Without it, staff must re-enter those
teams every week, which undermines the "one calendar" promise.

**Recommendation:** build S27 (staff-created weekly bookings) before pilot readiness. Captain
requests (S33) stay "if time allows".

---

## 7. Timeline

Estimates include writing tests. They assume close to full-time work; at part-time pace, roughly
double them (proposal section 8).

| Weeks of build | Steps | Outcome |
|---|---|---|
| 1 | S01–S03 | Project, CI, user model |
| 2–5 | S04–S12 | Riskiest parts proven by tests; staging live |
| 6–8 | S13–S18 | **Demo slice on staging; co-founder starts venue demos** |
| 8–11 | S19–S26 | All Must requirements |
| 12 | S27 | Staff weekly bookings |
| 12–13 | S28–S31 | Pilot readiness; phase 1 gate |
| 14 | S32–S34 | Should requirements, if time allows |

| Group | Working days |
|---|---|
| Foundation + riskiest core (S01–S12) | 25 |
| Demo slice (S13–S18) | 13 |
| Rest of Must (S19–S26) | 17.5 |
| Staff weekly bookings (S27) | 3 |
| Pilot readiness (S28–S31) | 7.5 |
| **Must + pilot readiness + S27** | **66 days ≈ 13 weeks** |
| Should, if time (S32–S34) | 5.5 |

**Gap against the proposal.** The proposal plans phase 1 as weeks 3–12 (10 weeks of build) with venue
demos from about week 9, and estimates the MVP at about 8 weeks of full-time work. These estimates
come to about **13 weeks** for Must + pilot readiness, with the demo slice ready after about **8 weeks
of build (project week 10–11)**. Options:

1. **Accept a later pilot** (recommended): demos start around project week 10 as planned in spirit;
   the pilot starts around week 16 instead of 13. Honest, and protects quality on the booking engine.
2. **Cut scope** using section 8 to save about 6–7 days.
3. **Work faster than estimated**: AI-assisted development may beat these numbers; re-check the
   timeline after Milestone 1 using actual days spent.

---

## 8. Cut list (if behind schedule)

In order of what to cut first. None of these affect the no-double-booking guarantee, permissions or
security.

| Cut | Saves | Impact |
|---|---|---|
| V9 week view (keep day view with ◀ ▶) | 0.5 d | Staff check other days one at a time |
| V12 move booking (staff cancel and rebook instead) | 1 d | One more step for "can we move to 9 pm?" |
| V18 customer list screen (customer details reachable from a booking) | 1 d | No browsable customer book |
| Photo gallery beyond the cover photo | 0.5 d | Venue page shows one photo |
| "Same prices for all courts" / per-court price variations in the wizard (always same prices; edit per court later) | 0.5 d | Slightly less flexible setup |
| PWA install and offline page | 0.5 d | Players use it as a normal website |
| S34 QR poster (share link only) | 1 d | Posters made by hand |
| S32/S33 teams and captain requests | 4.5 d | Move to phase 2 |

---

## 9. Progress log

| Step | Started | Finished | Actual days | Notes |
|---|---|---|---|---|
| S01 | 26 Nov 2026 | 26 Nov 2026 | 0.5 | Prompt C1. Local PostgreSQL 17 instead of Docker Compose for now (Docker not installed); `compose.yaml` comes with the Dockerfile in S12 |
| S02 | 26 Nov 2026 | 26 Nov 2026 | (with S01) | Prompt C1. Branch protection on `main` must be switched on by hand in GitHub settings |
| S09 (part) | 26 Nov 2026 | | | Prompt C1: base template, vendored htmx 2.0.11 (eval off), Tailwind standalone CLI, PWA manifest and icons, CSP nonces. Components, formatters, pseudo-locale, error pages and service worker still to do |
| S03 (part) | 26 Nov 2026 | | | Prompt C2: `User` model and first migration, `core/phone.py`, `core/exceptions.py`, `core/db.py`, factories. `core/timeutils.py` and `VenueOwnedQuerySet` still to do |
| S08 (part) | 26 Nov 2026 | | | Prompt C2: `SmsMessage` outbox, console/locmem backends, Text.lk placeholder, `run_worker` with retries and OTP drop. Worker heartbeat, purge job and real Text.lk adapter still to do (C7) |
| S10 (part) | 26 Nov 2026 | | | Prompt C2: OTP request/verify with all BR-27 limits, P4–P6, consent, sign-out, P18 account and P19 deletion (accounts part). OTP text encrypted in the outbox (data-model 3.6). Still to do: Turnstile (D5), per-role session lifetimes (D9), linking VenueCustomer rows at first sign-in (needs S04), deletion steps for venues/bookings/teams (S26) |
| S03 (rest) | 26 Nov 2026 | 26 Nov 2026 | | Prompt C3: `core/timeutils.py` (operating day and minute) and `VenueOwnedQuerySet` |
| S04 | 26 Nov 2026 | 26 Nov 2026 | | Prompt C3: all venue models and constraints, `create_venue()` defaults, launch areas. `VenueCustomer` moved to C4 (only useful with bookings) |
| S05 | 26 Nov 2026 | 26 Nov 2026 | | Prompt C3: `get_venue_for_user()`, venue decorators, isolation tests for every `/manage/` URL plus the meta-test (proved by a test that adds an unregistered URL) |
| S07 (part) | 26 Nov 2026 | | | Prompt C3: `pricing.services.price_for()` and `slot_prices()`. Free-slot engine comes with C4 |
| S21/S24 (part) | 26 Nov 2026 | | | Prompt C3: create venue, profile, photos (Pillow re-encode, 5 MB, 6 max), courts, hours, prices and peak times, submit for approval; staff see them read-only. Wizard flow, Leaflet map pin, object storage (D7), booking-rules screen (V20) and staff screen (V24) still to do |
| S06 | 26 Nov 2026 | 26 Nov 2026 | | Prompt C4: `Booking` (bookings and blocks), `BookingEvent`, exclusion constraint, all check constraints, composite foreign keys (RunSQL), references, 20-thread concurrency test. `RecurringSeries` and the team/series foreign keys move to C8 |
| S07 | 26 Nov 2026 | 26 Nov 2026 | | Prompt C4: `bookings.selectors.get_available_slots()` (grid, late-night days, booked/blocked removed, notice, horizon, prices). The multi-court batch version for search comes with C5 |
| S11 | 26 Nov 2026 | 26 Nov 2026 | | Prompt C4: online and staff bookings, player and staff cancel, blocks, move, no-show and undo, audit events, confirmation/cancellation/change SMS. Reminders come with C7; booking rate limit (10/hour) with the C5 views |
| S13/S14 | 26 Nov 2026 | 26 Nov 2026 | | Prompt C5: venue page with HTMX day strip, Unavailable chips, closed/horizon/fully-booked messages; review with length choice and cancellation deadline; confirm with "just taken" and double-tap handling; 10-per-hour booking rate limit; confirmation page with WhatsApp share. Map (Leaflet) and the 'share sheet' JS still to do |
| S19 | 26 Nov 2026 | 26 Nov 2026 | | Prompt C5: search form (home) and results with HTMX filters, fixed query count for any number of venues, empty states. Search cache and the 60/min IP limit still to do |
| S20 | 26 Nov 2026 | 26 Nov 2026 | | Prompt C5: My bookings (upcoming/past, staff-entered bookings linked by phone), details, cancel with confirmation |
| S15 | 26 Nov 2026 | 26 Nov 2026 | | Prompt C6: day calendar (one column per court, source colours, blocks, free cells, now line, show cancelled, 30 s HTMX refresh, daily summary) and week view for one court. Venue switcher kept as the My venues list |
| S16 | 26 Nov 2026 | 26 Nov 2026 | | Prompt C6: new booking (walk-in/phone/WhatsApp, UX4 default, durations, price change with reason, Save anyway, customer suggestions), booking details with history, move, cancel with late warning, no-show and undo, Arrived. Pages instead of bottom sheets |
| S22 (part) | 26 Nov 2026 | | | Prompt C6: block time on one or more courts with the conflict list; remove a block. Closing a whole day with "cancel all and SMS" (V15) still to do |
| S24 (part) | 26 Nov 2026 | | | Prompt C6: staff screen (V24): add by name and phone with SMS, remove, last-owner protection. Booking rules screen (V20) still to do |
| S25 (part) | 26 Nov 2026 | | | Prompt C3: area admin, venue review page with approve/reject/suspend/unsuspend and owner SMS. Booking lookup and access log still to do (C9) |
