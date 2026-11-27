# Matchvia MVP Requirements

Version 1.0 · 26 Nov 2026 · Source: [proposal.md](proposal.md) sections 5.1–5.5

Status of business rules: **CONFIRMED by the founders on 26 Nov 2026** (see section 5). Defaults are
to be revisited after venue demos.

---

## 1. Purpose and scope

This document turns the MVP scope of the proposal (FR-01 to FR-15, NFR-01 to NFR-10) into user
stories, acceptance criteria and business rules that the build can be tested against.

There is no venue interview data yet. The founders chose to build first and demo the working MVP to
venues. The rules below are therefore based on the proposal and on how small Sri Lankan futsal and
indoor cricket venues usually work today. Every rule is a sensible default, and wherever possible it
is a **per-venue setting**, so feedback from demos changes a setting, not the code.

### 1.1 In scope (MVP)

| Priority | Requirements | Meaning |
|---|---|---|
| Must | FR-01 to FR-12 | The MVP is not done without these |
| Should | FR-13 to FR-15 | Build if time allows in Phase 1; otherwise first thing in Phase 2 |
| NFR | NFR-01 to NFR-10 | Apply to everything built |

### 1.2 Out of scope for MVP ("later")

- Online payment, deposits, holds while paying, refunds, split payments (FR-16 to FR-18): **Phase 2**.
  MVP is **pay at venue only**.
- Reviews, subscriptions/billing, reports (FR-19 to FR-21): **Phase 2**.
- Opponent finder, open games, tournaments, WhatsApp messages (FR-22 to FR-24): **Phase 3**.
- Native apps (FR-25): **Phase 4**.
- Full list of smaller "later" items: section 7.

### 1.3 How venues work today (design context)

- Bookings come by **phone call and WhatsApp**, plus **walk-ins** at the counter. One person (owner or
  a front-desk staff member) writes them in a **notebook** or a WhatsApp note.
- **Regular teams** ("every Tuesday 8 pm") are a large share of evening bookings and are agreed
  verbally, often for months.
- **Payment is cash** (sometimes bank transfer) at the venue, after or before the game. No deposits.
- **No-shows and last-minute cancellations** cost the venue the slot. The only defence today is
  refusing to book that person again.
- **Peak time** is weekday evenings and weekends. Many venues stay open late (to midnight or later).
- Staff are busy and on their phones, so every venue-side task must be quick on a small screen.

The MVP must fit this reality: the online calendar has to hold **all** bookings (online, phone,
WhatsApp, walk-in) or it is not trusted.

---

## 2. Roles

| Role | Who | Notes |
|---|---|---|
| Player | Anyone with a verified phone number | Default role for every account |
| Team captain | A player who has created a team | Not a separate account; a player who owns a team |
| Venue owner | Owns one or more venues | Can do everything staff can, plus settings, courts, prices, staff |
| Venue staff | Front desk or manager, added by an owner | Works only on the venues the owner assigned |
| Platform admin | The founders, later support staff | Approves and suspends venues; reads data for disputes |

One person can hold several roles (for example a staff member who also plays). Roles are attached to
the account, and venue roles are attached **per venue**.

---

## 3. Key terms

| Term | Meaning |
|---|---|
| Court | One bookable physical space. A court can support futsal, indoor cricket or both, but it is booked as one space |
| Slot | One unit of time on a court's grid, for example 18:00–19:00. Slot length is set per court |
| Booking | A reservation of one court for one or more consecutive slots |
| Block | Time a court is unavailable (maintenance, private event). Stored with bookings so the same overlap rule applies |
| Source | Where a booking came from: `online`, `phone`, `whatsapp`, `walk_in` |
| Booking status | `confirmed`, `cancelled`, `no_show`. "Completed" is derived (confirmed and end time passed). `expired` is reserved for Phase 2 payment holds |
| Recurring series | A weekly repeating booking (same court, weekday and time) for a set number of weeks. Each week is a normal booking linked to the series |
| Booking reference | Short code shown to players and staff, for example `MV-7K3P` (no ambiguous characters such as 0/O, 1/I) |

---

## 4. User stories and acceptance criteria

Format: each story is "As a …, I want …, so that …", followed by Given/When/Then acceptance criteria.
`BR-xx` refers to a business rule in section 5. "Later" marks parts that are not MVP.

### 4.1 Player

#### US-P01 Register and log in with phone OTP (FR-01) · Must
As a player, I want to sign in with my mobile number and a one-time code, so that I don't need to
remember a password.

- **Given** I enter `0771234567`, `771234567` or `+94771234567`, **when** I request a code, **then** the
  number is stored in one format (`+94771234567`) and a 6-digit code is sent by SMS (BR-27).
- **Given** I enter a number that is not a valid Sri Lankan mobile number, **when** I submit, **then** I
  see "Enter a valid Sri Lankan mobile number" and no SMS is sent.
- **Given** a code was sent, **when** I enter it within 5 minutes, **then** I am signed in.
- **Given** the code is older than 5 minutes, **when** I enter it, **then** I see "Code expired" and can
  request a new one.
- **Given** I entered a wrong code 5 times, **when** I try again, **then** that number is locked for 15
  minutes (BR-27).
- **Given** I have requested 3 codes in 15 minutes, **when** I request a fourth, **then** I see how long
  to wait, and no SMS is sent (BR-27).
- **Given** this is my first sign-in, **when** I am signed in, **then** I am asked only for my name and
  to accept the privacy notice and terms (NFR-07). Nothing else is required.
- **Given** staff earlier entered a phone booking with my number, **when** I sign in for the first time,
  **then** my upcoming bookings at that venue appear in "My bookings".

#### US-P02 Search for free slots (FR-04) · Must
As a player, I want to search by sport, area, date and time, so that I can find a free court without
calling venues.

- **Given** I choose sport "Futsal", area "Malabe", date "Sat 5 Dec" and time "18:00–21:00", **when** I
  search, **then** I see only **approved, active** venues in that area with at least one futsal court
  that has a free slot starting in that window, each with the free start times and price.
- **Given** I leave time empty, **when** I search, **then** all free slots for that date are shown.
- **Given** I search for today, **when** results load, **then** slots that start in the past or inside
  the minimum notice (BR-05) are not shown.
- **Given** a date beyond the venue's booking horizon (BR-04), **when** I search, **then** that venue
  shows "Bookings open up to N days ahead" instead of slots.
- **Given** the venue is closed that day (weekly closed day or closed date, BR-15, BR-16), **when** I
  search, **then** the venue is not in the results.
- **Given** a slot is booked or blocked, **when** I search, **then** it is never shown as free.
  Availability is read from the database at request time, not from a cache (NFR-01).
- **Given** no venues match, **when** results load, **then** I see "No free courts" and a shortcut to
  the next day.
- Results load in under 2 seconds on a 4G phone (NFR-02).

#### US-P03 View a venue and its free slots (FR-04, FR-15) · Must
As a player, I want to open a venue's page, so that I can see its courts, location, photos, prices
and free slots for any day.

- **Given** I open a venue, **when** the page loads, **then** I see name, area, address, map pin,
  photos, facilities, the venue's phone number, cancellation policy, and a day picker with free slots
  per court.
- **Given** a court has peak and off-peak prices, **when** I view slots, **then** each slot shows its
  own price (BR-18).
- **Given** a time is blocked, **when** I view slots, **then** it shows as "Unavailable" without the
  reason.
- **Given** the venue is not approved or is suspended, **when** I open its link, **then** I see "This
  venue is not taking online bookings" and no slots.

#### US-P04 Book a slot with instant confirmation (FR-05, FR-06) · Must
As a player, I want to book a free slot and get a confirmation immediately, so that I know the court
is mine.

- **Given** I am signed in and choose a free slot, **when** I review, **then** I see venue, court,
  date, start and end time, total price, "Pay at venue", and the cancellation policy (BR-08).
- **Given** I choose 2 consecutive free slots (18:00 and 19:00), **when** I book, **then** one booking
  18:00–20:00 is created, priced per slot (BR-02, BR-18).
- **Given** I choose more consecutive slots than the venue allows (BR-02), **when** I try, **then** I
  cannot select beyond the limit.
- **Given** I confirm, **when** the booking is saved, **then** its status is `confirmed`, source
  `online`, the price is stored at today's rate (later price changes don't affect it), and I see a
  confirmation screen with the booking reference.
- **Given** the booking is confirmed, **when** the SMS is sent, **then** it contains the reference,
  venue, court, date, time, price and venue phone number.
- **Given** the SMS gateway fails, **when** I book, **then** the booking is still confirmed, the
  confirmation screen is shown, and the SMS is retried in the background (NFR-03).
- **Edge: overlapping booking.** **Given** another player (or staff) booked an overlapping time a moment
  before me, **when** I confirm, **then** the database rejects my booking, I see "Sorry, this slot was
  just taken" and the refreshed free slots. No double booking is ever saved (NFR-01).
- **Edge: not signed in.** **Given** I pick a slot while signed out, **when** I continue, **then** I sign
  in with OTP and return to the review screen. The slot is **not held** while I sign in (BR-07); if it
  was taken meanwhile I see the message above.
- **Edge: booking limit.** **Given** I already have the maximum number of upcoming online bookings at
  this venue (BR-12), **when** I try to book, **then** I see "You already have N upcoming bookings
  here. Call the venue to book more."
- **Edge: blocked player.** **Given** the venue has blocked my number from online booking (BR-11),
  **when** I try to book, **then** I see "Please contact the venue to book" with its phone number.
- **Edge: outside rules.** **Given** a slot is outside opening hours, inside the minimum notice, or
  beyond the horizon, **then** it is not selectable.
- **Edge: two courts at once.** **Given** I book two different courts for the same time, **then** it is
  allowed (subject to BR-12).

#### US-P05 See my bookings · Must
As a player, I want a list of my upcoming and past bookings, so that I can check times and cancel.

- **Given** I have bookings, **when** I open "My bookings", **then** I see upcoming bookings first
  (soonest first), then past ones, each with reference, venue, court, time, price, status and source.
- **Given** staff entered a booking with my phone number, **then** it appears here too.

#### US-P06 Cancel a booking (FR-09) · Must
As a player, I want to cancel a booking myself within the venue's policy, so that the court is freed
and I don't have to call.

- **Given** my booking starts more than the venue's cancellation window from now (BR-08), **when** I
  cancel and confirm, **then** status becomes `cancelled`, the slot is free again immediately, I get an
  SMS confirming the cancellation, and the venue's calendar shows it as cancelled.
- **Given** the booking starts inside the cancellation window, **when** I open it, **then** the cancel
  button is replaced by "Cancellation closed. Call the venue: 07X XXX XXXX".
- **Given** the booking has already started or ended, **then** it cannot be cancelled by me.
- **Given** the booking was made by staff (phone/walk-in) and is linked to my number, **then** I can
  cancel it under the same rule.
- Cancelling is recorded with who cancelled, when, and whether it was inside the window ("late").

#### US-P07 Get a reminder before the game (FR-10) · Must
As a player, I want an SMS reminder before my game, so that I don't forget.

- **Given** a confirmed booking with a phone number, **when** the reminder time arrives (BR-20),
  **then** one reminder SMS is sent with venue, court, time and the venue phone.
- **Given** the booking was made after the reminder time had already passed, **then** no reminder is
  sent (the confirmation SMS is enough).
- **Given** the reminder time falls in quiet hours (22:00–07:00), **then** it is sent at 21:00 the
  evening before.
- **Given** the booking is cancelled or marked no-show before the reminder time, **then** no reminder is
  sent.
- **Given** a walk-in booking, **then** no reminder is sent.

#### US-P08 Delete my account (NFR-07) · Must
As a player, I want to delete my account and personal data, so that my privacy is respected (PDPA).

- **Given** I choose "Delete my account" and confirm with an OTP, **when** deletion runs, **then** my
  name and phone number are removed from my account and from my bookings, my future bookings are
  cancelled, each affected venue is notified, and I am signed out (BR-25).
- **Given** venues need their history, **then** past bookings remain as anonymised records
  ("Deleted user", court, time, price, status) for venue counts.
- **Given** I am the owner of a venue or a captain of a team, **when** I try to delete, **then** I am
  told to transfer or close the venue/team first.

#### US-P09 Join a team (FR-13) · Should
As a player, I want to accept a captain's invite, so that I can see my team's bookings.

- **Given** I received an invite SMS with a link, **when** I open it and sign in with the invited
  number, **then** I can accept or decline.
- **Given** the invite is older than 7 days (BR-26), **then** it shows "Invite expired".
- **Given** I accepted, **then** I see the team's upcoming bookings in "My bookings" (marked with the
  team name). I do not get SMS for team bookings in MVP (only the captain does).

### 4.2 Team captain

#### US-C01 Create a team (FR-13) · Should
As a captain, I want to create a team with a name and sport, so that I can organise my regular group.

- **Given** I enter team name and sport (futsal or indoor cricket), **when** I save, **then** the team
  is created and I am its captain.
- A player can captain several teams. Team names do not need to be unique.

#### US-C02 Invite players (FR-13) · Should
As a captain, I want to invite teammates by phone number, so that they can see our bookings.

- **Given** I enter a valid mobile number, **when** I invite, **then** an SMS with a join link is sent.
- **Given** the team already has the maximum number of members (BR-26), **then** I cannot invite more.
- **Given** I invite the same number twice, **then** the existing invite is re-sent (rate-limited),
  not duplicated.
- **Given** I remove a member, **then** they no longer see the team's bookings.

#### US-C03 Book for my team · Should
As a captain, I want to tag a booking with my team, so that teammates see it.

- **Given** I am booking (US-P04) and I captain a team, **when** I choose the team, **then** the
  booking shows the team name to me, team members and venue staff. All other booking rules are the
  same as US-P04.

#### US-C04 Request a recurring weekly slot (FR-14) · Should
As a captain, I want to request the same court, day and time every week, so that my team doesn't
have to book every week.

- **Given** I choose court, weekday, start time, duration and number of weeks (BR-13), **when** I
  submit, **then** a recurring **request** is created with status `pending` and the venue is notified.
  A pending request does **not** reserve slots.
- **Given** the venue approves (US-O07), **then** one confirmed booking per week is created, linked to
  the series, each priced at the rate on the approval date, and I get one SMS summary
  ("8 weeks, Tue 20:00–21:00, starting 8 Dec; 1 week skipped: 29 Dec").
- **Edge: clashing weeks.** **Given** some weeks clash with existing bookings, blocks or closed days,
  **then** those weeks are skipped and listed to both the approver and me. The rest are booked.
- **Given** the venue rejects, **then** I get an SMS with the reason (optional text from the venue).
- **Given** the venue does not respond within 48 hours, **then** the request expires and I am
  notified.
- **Given** the first week starts inside the minimum notice, **then** the series starts the following
  week.
- Recurring series do not count towards the upcoming-booking limit (BR-12) because the venue approved
  them.

#### US-C05 Cancel one week or the whole series (FR-14, FR-09) · Should
As a captain, I want to cancel one week or the rest of the series, so that the venue can resell the
court.

- **Given** one week is outside the cancellation window, **when** I cancel that week, **then** only that
  booking is cancelled (US-P06 rules).
- **Given** I cancel the series, **then** all future weeks **outside** the cancellation window are
  cancelled; any week already inside the window stays and I am told to call the venue.
- The venue sees the series as cancelled from that date.

### 4.3 Venue owner

The owner can also do everything in section 4.4 (staff).

#### US-O01 Register a venue (FR-02) · Must
As a venue owner, I want to create my venue with its details, so that I can manage bookings and
later go live.

- **Given** I am signed in, **when** I choose "List my venue" and enter name, area (from the fixed area
  list), address, map pin, venue phone number and facilities, **then** the venue is created with status
  `pending approval` and I become its owner.
- **Given** I upload photos, **then** JPG/PNG/WebP up to 5 MB each are accepted, at most 6 per venue,
  and are resized and compressed for mobile (NFR-02).
- **Given** the venue is pending approval, **then** I and my staff **can already use the calendar**
  (walk-ins, phone bookings, blocks), but the venue is not in search and its page shows it is not
  taking online bookings (BR-22). This lets pilot venues start on day one.
- **Given** I submit for approval, **then** the admin is notified.

#### US-O02 Add and manage courts (FR-02) · Must
As an owner, I want to add my courts with their sports, so that each can be booked separately.

- **Given** I add a court with a name ("Court 1"), supported sports (futsal, indoor cricket, or both)
  and indoor/outdoor flag, **then** it appears in the calendar and on the venue page.
- **Given** a court supports both sports, **then** it is still one space: a futsal booking blocks
  cricket at that time and vice versa (BR-29).
- **Given** I deactivate a court that has future confirmed bookings, **then** I am shown the list and
  must cancel or move them first.
- Splitting one big pitch into two smaller courts is **later** (section 7).

#### US-O03 Set opening hours and closed days (FR-03, FR-08) · Must
As an owner, I want to set opening hours per weekday and add closed dates, so that players only see
times we are open.

- **Given** I set Mon–Sun open/close times (BR-15), **then** slots are only offered within them.
- **Given** I mark a weekday as closed, **then** no slots are offered on that weekday.
- **Given** I set a closing time after midnight (for example 18:00–01:00), **then** the late slots
  belong to the opening day in the calendar and in search (BR-15).
- **Edge: closed date with bookings.** **Given** I add a closed date (for example a Poya day or a
  family event) that has confirmed bookings, **when** I save, **then** I see the affected bookings and
  can choose "Cancel all and send SMS" or go back. The closure is not saved while confirmed bookings
  remain (BR-16).
- **Edge: changing hours.** **Given** I shorten opening hours and future bookings fall outside the new
  hours, **then** those bookings stay valid and I am shown a warning listing them.

#### US-O04 Set slot length and prices (FR-03) · Must
As an owner, I want to set slot length and peak/off-peak prices per court, so that prices match my
business.

- **Given** I set slot length (BR-01), off-peak price and peak price per court in rupees, **then** each
  slot shows the right price (BR-18).
- **Given** I define peak periods (weekday + time range, for example Mon–Fri 17:00–23:00 and all day
  Sat–Sun), **then** slots starting inside a peak period use the peak price.
- **Given** I change a price, **then** existing bookings keep their stored price; only new bookings use
  the new price.
- **Edge: changing slot length.** **Given** future bookings exist and I change slot length, **then**
  existing bookings stay as they are; new slots are generated on the new grid; slots overlapping
  existing bookings show as unavailable.
- Special-date prices and discounts are **later**.

#### US-O05 Choose my booking settings · Must
As an owner, I want to adjust booking rules for my venue, so that the system works the way my venue
works.

- **Given** I open venue settings, **then** I can change every per-venue setting in section 5 within
  its allowed range, each pre-filled with the default.
- **Given** I change a setting, **then** it applies to new bookings only; existing bookings are not
  changed.

#### US-O06 Add staff (role permissions) · Must
As an owner, I want to give my front-desk staff their own access, so that they can take bookings
without my login.

- **Given** I add a staff member by name and mobile number, **then** they get an SMS and can sign in
  with OTP; they see only the venues I assigned.
- **Given** a staff member is signed in, **then** they can view the calendar, add/edit/cancel bookings,
  add blocks and mark no-shows; they **cannot** change courts, prices, hours, settings or staff, and
  cannot see other venues.
- **Given** I remove a staff member, **then** they lose access immediately (their open sessions stop
  working on the next request).

#### US-O07 Approve recurring requests (FR-14) · Should
As an owner, I want to approve or reject recurring requests, so that I control which teams get a
regular slot.

- **Given** a pending request, **when** I open it, **then** I see the team, captain's name and phone,
  the requested weeks, and which weeks clash.
- **Given** I approve, **then** US-C04 approval behaviour applies. **Given** I reject, I can add a reason.
- Who may approve (owner only, or owner and staff) is a per-venue setting (BR-13).

#### US-O08 Share a branded booking page (FR-15) · Should
As an owner, I want a link and QR code for my venue page, so that I can share it on WhatsApp, Facebook
and posters.

- **Given** my venue is approved, **then** it has a short link `matchvia.lk/v/<venue-name>` showing my
  logo, cover photo and live slots (US-P03).
- **Given** I tap "Download QR", **then** I get a printable QR code image for that link.
- Custom colours and custom domains are **later**.

#### US-O09 Block a player from online booking (no-show defence) · Must
As an owner, I want to stop a repeat no-show from booking online at my venue, so that I don't lose
more slots.

- **Given** a player's booking history at my venue (including their no-show count), **when** I block
  their phone number, **then** they can no longer book my venue online (US-P04 edge case), and their
  existing bookings are unchanged.
- **Given** I unblock them, **then** they can book again.
- A block applies only to my venue, not the whole platform.

### 4.4 Venue staff

#### US-S01 See the daily and weekly calendar (FR-11) · Must
As staff, I want to see all bookings by court and time, so that I know who is playing when.

- **Given** I open the calendar, **then** I see today by default, one column per court, every booking
  and block, colour-coded by source (online, phone, WhatsApp, walk-in, block) and status.
- **Given** I switch to week view, **then** I see 7 days per court.
- **Given** I tap a booking, **then** I see customer name, phone (tap to call), team, source, price,
  status, notes and history (created/changed by whom, when).
- Cancelled bookings are hidden by default and can be shown with a filter.
- The calendar refreshes without a full page reload (HTMX) so new online bookings appear.

#### US-S02 Add a walk-in booking (FR-07) · Must
As staff, I want to add a walk-in in a few taps, so that the online calendar matches reality.

- **Given** I tap a free slot and choose "Walk-in", enter a name (phone optional) and save, **then** a
  `confirmed` booking with source `walk_in` is created immediately (no hold), in 3 taps or fewer after
  opening the calendar (NFR-04).
- **Given** the slot was just booked online, **when** I save, **then** the database rejects mine and I
  see "Just booked online by <name>" (NFR-01).
- **Given** no phone is entered, **then** no SMS is sent.

#### US-S03 Add a phone or WhatsApp booking (FR-07) · Must
As staff, I want to enter bookings that come by phone or WhatsApp, so that every booking is in one
calendar.

- **Given** I enter name and phone number, choose source `phone` or `whatsapp`, court and time,
  **then** a confirmed booking is created and an SMS confirmation is sent (BR-21).
- **Given** the phone number belongs to a registered player, **then** the booking appears in their
  account (US-P05).
- **Given** I type a phone number that has booked before at this venue, **then** the name is suggested
  and their no-show count is shown.
- **Given** I book outside opening hours, **then** I see a warning but can save (BR-23). Staff are not
  limited by the booking horizon, minimum notice or upcoming-booking limit.
- **Given** I change the price (for example a regular-customer discount), **then** I must give a short
  reason, and the change is logged (BR-19).

#### US-S04 Move or edit a booking · Must
As staff, I want to change a booking's time or court, so that I can handle "can we move to 9 pm?"
requests.

- **Given** I change time or court to a free time, **when** I save, **then** the booking is updated,
  the price is recalculated (I can keep the old price with a reason), the change is logged, and the
  customer gets an SMS with the new details.
- **Given** the new time overlaps another booking or block, **then** the save is rejected and nothing
  changes.
- Players cannot move bookings themselves in MVP (they cancel and rebook): **later**.

#### US-S05 Cancel a booking for a customer · Must
As staff, I want to cancel any booking with a reason, so that I can act on calls and WhatsApp
messages.

- **Given** any confirmed future booking, **when** I cancel with a reason (customer request, venue
  issue, other), **then** it is cancelled at any time regardless of the player window (BR-09), the
  slot is freed, and the customer gets an SMS if a phone is known.
- **Given** a cancellation inside the venue's window at the customer's request, **then** it is recorded
  as a "late cancellation" in that customer's history at this venue.

#### US-S06 Block time (FR-08) · Must
As staff, I want to block a court for maintenance or a private event, so that nobody can book it.

- **Given** I choose court(s), start and end time and a reason, **when** I save, **then** a block is
  created and those times show as "Unavailable" to players (BR-17).
- **Given** the time overlaps a confirmed booking, **then** the block is rejected and I see the
  conflicting bookings; I must move or cancel them first.
- **Given** I block a whole day for all courts, **then** it behaves like a closed date (US-O03).
- Recurring blocks (for example every Monday 06:00–08:00 cleaning) are **later**; MVP blocks are
  one-off.

#### US-S07 Mark a no-show (FR-11) · Must
As staff, I want to mark a booking as a no-show, so that we have a record and the court can be
reused.

- **Given** a confirmed booking whose start time was at least 15 minutes ago and which ended no more
  than 48 hours ago (BR-10), **when** I mark no-show, **then** status becomes `no_show` and the count
  is added to that customer's history at this venue.
- **Given** I marked no-show during the booked time, **then** the remaining time becomes free so I can
  add a walk-in (BR-10).
- **Given** I marked no-show by mistake, **then** I can undo it within 48 hours, provided the time has
  not been rebooked.
- **Given** a booking is not marked, **then** it counts as played (completed) after its end time.
- Bookings in the future cannot be marked no-show.

#### US-S08 Create a recurring booking for a regular team (FR-14) · Should
As staff, I want to enter a regular team's weekly slot directly, so that our existing "every Tuesday"
teams are in the system from day one.

- **Given** I enter customer name, phone, court, weekday, time and number of weeks, **then** the series
  is created immediately (no approval step), clashing weeks are skipped and shown to me, and the
  customer gets one SMS summary.
- I can cancel one week or the rest of the series at any time, with a reason.

### 4.5 Platform admin

Admin screens can use the Django admin panel in MVP, restricted to platform admins.

#### US-A01 Approve or reject a venue (FR-12) · Must
As admin, I want to review new venues before they go live, so that only real venues are bookable.

- **Given** a venue is pending, **when** I review name, location, photos, phone and courts, and approve,
  **then** it becomes visible in search, takes online bookings, and the owner gets an SMS.
- **Given** I reject with a reason, **then** the owner gets an SMS with the reason, can fix the venue
  and resubmit. Their calendar keeps working.
- Edits after approval do not need re-approval in MVP.

#### US-A02 Suspend a venue · Must
As admin, I want to suspend a venue (for example after complaints), so that players stop booking it.

- **Given** I suspend a venue with a reason, **then** it disappears from search and stops online
  bookings; existing bookings stay; the owner is notified. Unsuspending reverses this.

#### US-A03 Manage the area list · Must
As admin, I want to manage the list of areas, so that search by area works consistently.

- **Given** I add an area (for example "Kotte"), **then** owners can choose it and players can search
  by it. Launch list: Malabe, Battaramulla, Athurugiriya, Kaduwela, Kotte, Maharagama, Nugegoda.

#### US-A04 Look up bookings for a dispute · Must
As admin, I want to look up a booking by reference or phone number, so that I can resolve a
complaint.

- **Given** I search by reference or phone, **then** I see the booking with its full change history
  (read-only by default). Every admin view of personal data is logged.

---

## 5. Business rules

**Status: CONFIRMED (26 Nov 2026).** Each rule has a default. "Per venue" means the owner can change it
in venue settings (US-O05) within the allowed range.

### 5.1 Slots and booking

| ID | Rule | Default | Per venue? | Allowed range |
|---|---|---|---|---|
| BR-01 | Slot length | 60 minutes | Per **court** | 30, 60, 90, 120 min |
| BR-02 | Longest booking a player can make online | 3 consecutive slots | Yes | 1–6 slots |
| BR-03 | Slot grid alignment | Slots start at opening time and follow the slot length (06:00, 07:00, …) | No | – |
| BR-04 | Booking horizon (how far ahead players can book) | 14 days | Yes | 1–60 days |
| BR-05 | Minimum notice for online bookings | 60 minutes before start | Yes | 0–24 hours |
| BR-06 | Online confirmation mode | Instant confirmation (no owner approval) | No in MVP | "Owner approves each booking" is later |
| BR-07 | Hold while booking | **No hold in MVP.** The booking is created as confirmed when the player taps Confirm; the database constraint decides any race | No | Phase 2: 10-minute hold while paying online |
| BR-12 | Maximum upcoming online bookings per player at one venue | 2 | Yes | 1–10. Staff bookings and approved recurring series don't count |
| BR-29 | Multi-sport court | One court = one space, one price regardless of sport | No | Different price per sport is later |

### 5.2 Cancellations and no-shows

| ID | Rule | Default | Per venue? | Allowed range |
|---|---|---|---|---|
| BR-08 | Player self-cancellation window | Up to **6 hours** before start | Yes | 0–72 hours |
| BR-09 | Staff cancellation | Any time, reason required, SMS to customer | No | – |
| BR-10 | No-show marking | From start + 15 min until 48 h after end. **A no-show frees the rest of the booked time** for walk-ins | No | – |
| BR-11 | No-show consequence | Staff see each customer's no-show count. Owner can manually block a phone number from online booking at their venue | No | Automatic blocking after N no-shows is later |

### 5.3 Recurring weekly bookings

| ID | Rule | Default | Per venue? | Allowed range |
|---|---|---|---|---|
| BR-13 | Recurring requests from captains | Need approval. **Owner or staff** may approve. Series length 8 weeks by default. Requests expire after 48 h without an answer | Who approves: yes. Max weeks: yes | Approver: owner only / owner or staff. Weeks: 2–12 |
| BR-14 | Recurring cancellation | One week: normal player window. Whole series: cancels all future weeks outside the window | No | – |
| – | Staff-created series | No approval needed; clashing weeks skipped | No | – |

### 5.4 Opening hours, closures and blocks

| ID | Rule | Default | Per venue? | Allowed range |
|---|---|---|---|---|
| BR-15 | Opening hours | Per weekday, default 06:00–24:00 every day. Closing **after midnight allowed up to 03:00**; late slots belong to the opening day | Yes | Any weekday can be closed |
| BR-16 | Closed dates | Owner/staff add closed dates. A closure can't be saved over confirmed bookings: staff choose "Cancel all and send SMS" or go back | Yes | – |
| BR-17 | Blocks | One-off blocks by owner/staff with reason (maintenance, private event, coaching, other). Can't overlap confirmed bookings. Players see "Unavailable" only | No | Recurring blocks later |
| BR-23 | Staff bookings outside opening hours | Allowed with a warning | No | – |

### 5.5 Prices and messages

| ID | Rule | Default | Per venue? | Allowed range |
|---|---|---|---|---|
| BR-18 | Pricing | Per court: off-peak and peak price per slot, whole rupees. Peak by default Mon–Fri 17:00–close and all day Sat–Sun. Each slot is priced by its start time; booking stores the price at booking time | Prices and peak periods: yes | Rs. 0–100,000 per slot |
| BR-19 | Staff price change on a booking | Allowed with a reason; logged with who and when | Yes (owner can restrict to owner only) | – |
| BR-20 | Reminder SMS | 3 hours before start; quiet hours 22:00–07:00 move it to 21:00 the evening before | Lead time: yes | 1–24 hours |
| BR-21 | SMS for staff-entered bookings | Confirmation SMS for phone/WhatsApp bookings; none for walk-ins | Yes | On/off each |
| BR-22 | Going live | Not in search or bookable online until admin approval; calendar usable before approval | No | – |

### 5.6 Accounts, teams and privacy

| ID | Rule | Default | Per venue? | Allowed range |
|---|---|---|---|---|
| BR-24 | Player data collected | Phone number (verified) and name only. No email, no date of birth | No | – |
| BR-25 | Account deletion | Self-service with OTP; immediate anonymisation; future bookings cancelled and venues notified; past bookings kept anonymised | No | – |
| BR-26 | Teams | Max 15 members; invites expire after 7 days | No | – |
| BR-27 | OTP and rate limits | 6-digit code valid 5 min. Max 3 code requests per number per 15 min and 10 per IP per hour. 5 wrong codes lock the number for 15 min. Booking: max 10 booking attempts per user per hour | No (platform security) | – |
| BR-28 | Staff-entered customer data | Venue's own customers' name/phone kept while the venue is active. Retention period and deletion of walk-in data | No | **Later**: decide with legal advice before public launch |

---

## 6. Non-functional requirements as acceptance criteria

#### NFR-01 Data integrity: zero double bookings · Must
- A PostgreSQL exclusion constraint on bookings (court + time range overlap) rejects any overlap among
  bookings and blocks that are not `cancelled`, `expired` or `no_show` (BR-10). The app checks first
  for a friendly message, but correctness never depends on the app check.
- **Given** 20 simultaneous requests for the same slot, **when** they run, **then** exactly one
  succeeds and 19 get "slot just taken" (automated concurrency test).
- Adjacent bookings (18:00–19:00 and 19:00–20:00) are allowed: ranges are start-inclusive and
  end-exclusive.

#### NFR-02 Performance · Must
- Search and venue pages respond in under 2 seconds on a 4G phone.
- First page load under 300 KB excluding photos; photos are resized, compressed and lazy-loaded.
- Pages remain usable on a slow 3G connection (no large JavaScript bundles; HTMX + server HTML).

#### NFR-03 Availability · Must
- Target 99.5% monthly uptime.
- SMS failure never blocks a booking, cancellation or login fallback; failed SMS are retried and
  logged.

#### NFR-04 Usability · Must
- Mobile-first: every screen works on a 360 px wide phone.
- A first-time player can find and book a slot in under 60 seconds (excluding OTP delivery time).
- Owner/staff tasks (add walk-in, mark no-show, cancel) take 3 taps or fewer from the calendar.
- Installable as a PWA on Android and iPhone home screens.

#### NFR-05 Language · Must
- MVP screens in English. Every user-facing string, including SMS text, is wrapped for translation.
- Sinhala translation before public launch (Phase 3, per roadmap); Tamil later.
  Note: the proposal's NFR-05 says Sinhala "at launch"; this document reads that as public launch,
  matching CLAUDE.md ("Sinhala later") and roadmap phase 3.

#### NFR-06 Security · Must
- HTTPS only, HSTS, secure cookies, CSRF, CSP and ALLOWED_HOSTS on in production.
- Role-based access, and every venue-data query filtered by the user's venues.
- **Given** an owner or staff member of venue A requests any page, form or action for venue B (by URL
  or ID), **then** they get "not found" (404), and nothing is changed. Automated tests cover every
  venue-side view.
- No card data stored (no online payment in MVP).
- Rate limits per BR-27.
- An audit log records booking creation, changes, cancellations, no-shows, price changes and blocks:
  who, when, what changed.

#### NFR-07 Privacy (PDPA) · Must
- Privacy notice and terms accepted at first sign-in; consent recorded with date and version.
- Only the minimum data collected (BR-24). Self-service deletion (BR-25).
- Phone numbers are shown only to the venue a booking belongs to, to the player themselves and to
  platform admins.
- Cross-border hosting decision and legal check before public launch (proposal 6.3).

#### NFR-08 Scalability · Must
- Data model supports 200 venues and 50,000 players without redesign: every venue record is tied to a
  venue, and all calendar and search queries are indexed by court/venue and time.

#### NFR-09 Maintainability · Must
- Automated tests (pytest + pytest-django) for the booking engine, business rules in section 5 and
  venue isolation; tests run before every deploy.
- Daily database backups; error monitoring with alerts.

#### NFR-10 Time zone and currency · Must
- All times stored as timezone-aware values and shown in Asia/Colombo.
- All prices in LKR as whole rupees (integers), displayed as "Rs. 3,500".

---

## 7. Later (not MVP)

| Item | Phase |
|---|---|
| Online payment, deposits, 10-minute payment hold, `expired` status, refunds | 2 |
| Split payment among team members | 2 |
| Reviews and ratings | 2 |
| Subscription plans and billing | 2 |
| Occupancy, revenue and no-show reports; daily cash summary | 2 |
| Owner approves each online booking (approval mode) | 2 |
| Automatic blocking after N no-shows | 2 |
| Player self-reschedule (move instead of cancel and rebook) | 2 |
| Recurring blocks (weekly cleaning, coaching) | 2 |
| Special-date prices, discounts, different price per sport on a shared court | 2 |
| Buffer time between bookings | 2 |
| Splitting/combining courts (one big pitch as two small courts) | 2 |
| Team members receive SMS for team bookings | 2 |
| Public holiday calendar for peak pricing | 2 |
| Walk-in customer data retention rule (BR-28) | Before public launch |
| Sinhala screens and SMS | 3 |
| Opponent finder, open games, tournaments, leagues | 3 |
| WhatsApp notifications | 3 |
| Tamil | 3 |
| "Near me" distance search | 3 |
| Custom colours / custom domain for venue pages | 3 |
| Native apps | 4 |

---

## 8. Traceability

| Requirement | Stories |
|---|---|
| FR-01 | US-P01 |
| FR-02 | US-O01, US-O02 |
| FR-03 | US-O03, US-O04 |
| FR-04 | US-P02, US-P03 |
| FR-05 | US-P04 |
| FR-06 | US-P04, US-S02, US-S04, NFR-01 |
| FR-07 | US-S02, US-S03 |
| FR-08 | US-S06, US-O03 |
| FR-09 | US-P06, US-C05, US-S05 |
| FR-10 | US-P07 |
| FR-11 | US-S01, US-S07 |
| FR-12 | US-A01, US-A02 |
| FR-13 | US-C01, US-C02, US-C03, US-P09 |
| FR-14 | US-C04, US-C05, US-O07, US-S08 |
| FR-15 | US-O08 |
| Supporting | US-P05, US-P08, US-O05, US-O06, US-O09, US-S04, US-S05, US-A03, US-A04 |

---

## 9. Decision log

| Date | Decision | By |
|---|---|---|
| 26 Nov 2026 | Business rules in section 5 proposed | Claude (BA draft) |
| 26 Nov 2026 | All section 5 defaults confirmed as proposed, including: no-show frees the rest of the booked time (BR-10); owner can manually block a phone number (BR-11); 6-hour player cancellation window (BR-08); closing after midnight up to 03:00 (BR-15) | Founders |
| 26 Nov 2026 | MVP is pay-at-venue only with instant confirmation; no hold until online payment (Phase 2) | Founders |
| 26 Nov 2026 | Proposal NFR-05 "Sinhala at launch" means before public launch (Phase 3); MVP in English with all text wrapped for translation | Founders |
| 26 Nov 2026 | CLAUDE.md rule 1 updated: the overlap constraint also ignores `no_show` bookings | Founders |
| 26 Nov 2026 | Build prompt C3 differed from this document; the documented rules were kept: blocks live in the bookings table (not a separate BlockedTime table), prices are normal + peak per slot per court with venue peak periods (BR-18, not hourly price rules), opening hours are per venue (BR-15), a court can support both sports (BR-29) and floodlights are a venue facility, venue approval is a status workflow (draft, pending, approved, rejected, suspended) | Founders |
| 26 Nov 2026 | Build prompt C4 differed from this document; the documented rules were kept: no 10-minute hold in MVP (BR-07, online bookings are confirmed on Confirm; the `held` status and expiry column stay in the schema for Phase 2), no-show frees the court (CLAUDE.md rule 1), "completed" is derived rather than stored, start and end are separate columns. Staff booking services (walk-in, phone, move, no-show, blocks) were built in C4 with the engine; C6 adds their screens | Founders |
| 26 Nov 2026 | Build prompt C5: no 10-minute hold or countdown (BR-07 stands). Players pick a start time on the venue page and the length (1-3 slots) on the review page, instead of tapping chips to extend (screens P3, P7 updated) | Founders |
| 26 Nov 2026 | Build prompt C6: an "Arrived" tick for the front desk (records who and when, changes no rule; a booking still counts as played unless marked no-show); a one-line daily summary on the calendar (bookings, expected revenue, free peak slots; full reports stay Phase 2); new booking, cancel and block as full pages instead of bottom sheets | Founders |
| 27 Nov 2026 | Build prompt C7 asked for reminders 2 hours before; BR-20 kept (3 hours by default, each venue chooses 1-24). Reminders go to every confirmed booking with a phone except walk-ins; the BR-21 setting controls only the confirmation SMS for staff-entered bookings | Founders |
| 27 Nov 2026 | Build prompt C8 said "the venue owner approves"; BR-13 kept (owner or staff by default, a venue setting). Weekly series bookings and team bookings built together with staff-created series (PM1). Invite links use a SITE_URL setting | Founders |
| 27 Nov 2026 | Build prompt C9: the admin site is for superusers only (no limited admin roles yet). Admin sign-in is mobile number + password, then a code sent by SMS to the admin's own number. 20 password attempts per IP per hour; 5 wrong passwords lock that number's admin sign-in for 15 minutes; admin sessions last 8 hours (D9) | Founders |
| 27 Nov 2026 | Account deletion completed (C9, US-P08, BR-25): owners and captains hand over first; captains get "Make captain" and "Close team" (a closed team disappears for its players, open invites stop, booked games stay); each affected venue's owners get one SMS with the number of cancelled bookings; admins can carry out a request received by phone or email (logged with how it came in, never for their own account). Only venues that are pending, approved or suspended block an owner's deletion; drafts and rejected venues don't (to confirm) | Founders (draft/rejected rule proposed by Claude) |
