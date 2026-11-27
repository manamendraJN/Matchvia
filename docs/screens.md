# Matchvia MVP Screens

Version 1.0 · 26 Nov 2026 · Based on [requirements.md](requirements.md) v1.0 and
[architecture.md](architecture.md) v1.0

Every MVP screen, grouped by who uses it, followed by the three most important flows step by step.
Story IDs (`US-xx`) and rule IDs (`BR-xx`) refer to [requirements.md](requirements.md).

---

## 1. Design principles

### 1.1 Who we design for

| User | Device and context | What that means |
|---|---|---|
| Player / captain | Budget Android phone (2–3 GB RAM, 360 dp wide screen, Chrome), slow or patchy 4G, often booking from WhatsApp links | Light pages, big tap targets, few steps, works one-handed |
| Venue staff | Same kind of phone, at a busy front desk, often interrupted, sometimes a shared phone | One task per screen, fast entry, nothing lost if interrupted |
| Venue owner | Not technical; runs the venue from a notebook today | Plain words, sensible defaults already filled in, no setting they must understand before starting |
| Platform admin | The founders, on a laptop or phone | Django admin is fine; usable on a phone for urgent approvals |

### 1.2 Layout and touch

- **Designed at 360 × 640 dp first.** Larger screens get the same single column, centred, max 480 px
  wide for player screens; the venue calendar uses extra width for more courts.
- **Main action at the bottom**, inside thumb reach: a full-width sticky button or bottom sheet.
  One primary button per screen.
- **Tap targets at least 48 × 48 dp**, with 8 dp between them. Time chips are at least 48 dp tall.
- **Bottom navigation** with icon **and** text label (never icon only):
  - Player: **Search · My bookings · Teams · Account**
  - Venue dashboard: **Calendar · + New · Requests · More**
- **Bottom sheets** for short tasks (new booking, cancel, block) so the calendar stays visible behind
  them and the person keeps their place.
- **Forms:** one column, label above the field, hint text below, error text in red **under the field
  in words** (not colour alone). Native inputs: `type="tel"` with `inputmode="numeric"` for phones,
  `autocomplete="one-time-code"` for OTP.

### 1.3 Slow networks and cheap phones

- Server-rendered pages; HTMX swaps only the part that changes. Target under 300 KB for the first
  load excluding photos (NFR-02).
- **System fonts only** (Roboto on Android; Android's built-in Noto Sans Sinhala later). No web fonts
  to download.
- Photos: one cover image at mobile size, others lazy-loaded; no auto-playing carousels.
- **The map is "tap to load"** on the venue page, because map tiles are heavy. A "Directions" button
  opens the phone's maps app with the venue's coordinates instead.
- Every button that sends a request shows a spinner and is **disabled until the reply arrives**, so a
  slow network can't cause double taps.
- If a request fails: an inline banner "No connection. Your details are kept. **Try again**" (form
  values are never cleared).
- Offline page from the PWA cache: "You're offline. Bookings need a connection." with the venue
  phone numbers of the player's upcoming bookings if already on the page.

### 1.4 Room for Sinhala (and Tamil later)

- Assume labels grow **up to 50% longer** and Sinhala script needs **more line height** (body line
  height 1.6; never fixed-height text boxes).
- **No fixed-width buttons or tabs.** Buttons are full width on mobile; side-by-side buttons stack
  when the text doesn't fit. Labels may wrap to two lines; nothing is truncated with "…" except
  customer names in calendar cells.
- **No text inside images** or icons. No ALL CAPS (no meaning in Sinhala, harder to read in English).
- Plain, short English now makes translation easier: "Cancel booking", not "Revoke reservation".
- Dates, times and prices are formatted by one helper so the format can change per language.
- **Pseudo-localisation in development:** a test language that makes every string about 40% longer
  with non-Latin characters, so overflowing layouts show up before real Sinhala arrives.

### 1.5 Formats and words

| Item | Format | Example |
|---|---|---|
| Time | 12-hour with am/pm (common in Sri Lanka; confirm in section 6) | 6:00 pm, 12:30 am |
| Date | Short weekday, day, month | Sat 5 Dec |
| Price | "Rs." + thousands separator, whole rupees | Rs. 3,500 |
| Phone | Shown as typed locally; stored in E.164 | 077 123 4567 |
| Booking reference | Prefix + 6 characters | MV-7K3P9Q |
| Late slots | Shown under the operating day with a "next day" hint | Fri 5 Dec · 12:00 am–1:00 am (Sat) |

Words: "court" (not "pitch" or "resource"), "booking" (not "reservation"), "walk-in", "closed",
"blocked" shown to players as "Unavailable".

### 1.6 Colours and status (always colour **plus** text or icon)

| Meaning | Colour | Label/icon |
|---|---|---|
| Free slot | White with green border | Time + price |
| Online booking | Blue | 🌐 "Online" |
| Phone / WhatsApp booking | Purple | ☎ "Phone" / "WhatsApp" |
| Walk-in | Amber | 🚶 "Walk-in" |
| Block | Grey, striped | ⛔ reason ("Maintenance") |
| Weekly series | Any of the above + repeat icon | 🔁 |
| No-show | Red outline | "No-show" |
| Cancelled | Hidden by default; grey with strike-through when shown | "Cancelled" |

Colours meet WCAG AA contrast. (Emoji above stand for icons in this document; the app uses a small
inline SVG icon set.)

---

## 2. Players and captains

Navigation: bottom bar **Search · My bookings · Teams · Account**. Screens P1–P3 work without signing
in. Signing in is asked for only when it's needed (booking, teams, account).

#### P1 Search (home) · US-P02

```
┌──────────────────────────────┐
│ Matchvia                     │
│ Book your court.             │
│ Bring your team.             │
│                              │
│ Sport                        │
│ [ Futsal ] [ Indoor cricket ]│
│ Area                         │
│ [ Malabe                  ▾ ]│
│ Day                          │
│ [Today][Tomorrow][Sat 5][Sun…│  ← horizontal strip, 14 days
│ Time                         │
│ [Any][Morning][Afternoon]    │
│ [Evening][Night]             │
│                              │
│ ┌──────────────────────────┐ │
│ │      Find a court        │ │
│ └──────────────────────────┘ │
├──────────────────────────────┤
│ Search  Bookings  Teams  Me  │
└──────────────────────────────┘
```

- **Purpose:** find free courts by sport, area, day and time.
- **Main elements:** tagline; sport toggle (two large buttons); area picker (admin's area list);
  day strip for the next 14 days; time-of-day chips (Any, Morning 6–12, Afternoon 12–5, Evening
  5–9, Night 9–close); "Find a court" button. Signed-in users with upcoming bookings see a small
  "Next game: Tue 8:00 pm, Arena X" card above the form.
- **Actions:** choose filters → Find a court (goes to P2). The last used sport and area are
  remembered on the device.
- **Empty / error:** no areas configured → "Coming soon to your area" (only possible before launch).

#### P2 Search results · US-P02

- **Purpose:** compare venues with free slots for the chosen filters.
- **Main elements:** filter summary bar ("Futsal · Malabe · Sat 5 Dec · Evening", tap to change);
  one card per venue: cover photo (small), name, area, "from Rs. 3,000", up to 6 free time chips with
  price, "More times" link. Venues are sorted by the earliest free slot.
- **Actions:** tap a time chip → P3 with that slot pre-selected; tap the card → P3; change filters
  (HTMX updates the list without a full reload).
- **Empty / error:** "No free courts for Saturday evening." + buttons **"Try Sunday"** and **"Any
  time on Saturday"**. Search error → "Couldn't load courts. Try again."

#### P3 Venue page (public, shareable) · US-P03, US-O08

```
┌──────────────────────────────┐
│ [ cover photo              ] │
│ Arena X Futsal               │
│ Malabe · Futsal, Indoor crick│
│ [☎ Call]  [➤ Directions]     │
│                              │
│ [Today][Tomorrow][Sat 5][Sun…│
│                              │
│ Court 1 · Futsal             │
│ [6:00 pm ][7:00 pm ][8:00 pm]│
│ [Rs.3,500][Rs.3,500][Rs.4,000│
│ Court 2 · Futsal, Cricket    │
│ [5:00 pm ][Unavail.][9:00 pm]│
│                              │
│ Facilities · Cancellation ▸  │
│ Photos · Map (tap to load) ▸ │
├──────────────────────────────┤
│ Court 1 · 7–9 pm · Rs. 7,000 │
│ [        Continue          ] │  ← appears after choosing
└──────────────────────────────┘
```

- **Purpose:** see a venue's courts and free times, and choose a slot. This is also the venue's
  branded page shared on WhatsApp/Facebook and via QR posters.
- **Main elements:** logo/cover photo; name, area, sports; **Call** (tap-to-call) and **Directions**;
  day strip; per court: name, sports, time chips with price (peak price shown on the chip),
  "Unavailable" chips for booked/blocked times; collapsible sections for facilities, cancellation
  policy ("Free cancellation up to 6 hours before"), photos, map (tap to load).
- **Actions:** tap a free chip → P7 (or P4 first if signed out), where the player chooses how long
  (1, 2 or 3 slots, only lengths that are free and within the venue's limit, BR-02; "Up to 3 slots
  online. Call the venue for longer."). *Changed in C5: choosing the length on P7 replaces
  tap-to-extend on P3, so the flow works without JavaScript on budget phones.*
- **Empty / error:** no free slots that day → "Fully booked on Saturday" + next day with free slots;
  date beyond horizon → "Online booking opens 14 days ahead"; venue closed → "Closed on this day";
  venue not approved or suspended → "This venue isn't
  taking online bookings yet" with the Call button only.

#### P4 Sign in: phone number · US-P01

- **Purpose:** start sign-in with a mobile number.
- **Main elements:** short reason line ("Sign in to book. We'll text you a code."); phone field with
  "+94" shown in front and example "077 123 4567"; invisible bot check (Turnstile); "Send code"
  button; link to privacy notice.
- **Actions:** Send code → P5. The chosen slot is remembered and the player returns to it after
  sign-in.
- **Empty / error:** invalid number → "Enter a Sri Lankan mobile number, like 077 123 4567"; too many
  requests → "Too many codes. Try again in 12 minutes."; bot check failed → "Please try again."

#### P5 Sign in: enter code · US-P01

- **Purpose:** confirm the phone number with the 6-digit code.
- **Main elements:** "We sent a code to 077 123 4567" + **Change number**; one numeric code field
  (large digits, `autocomplete="one-time-code"` so Android can offer the code from the SMS; the SMS
  text ends with the site's WebOTP line so Chrome can fill it automatically); **Resend code** with
  countdown ("Resend in 0:45"); "Continue" button (also submits automatically when 6 digits are
  entered).
- **Actions:** enter code → signed in → P6 (first time) or back to where they were.
- **Empty / error:** wrong code → "Wrong code. 3 tries left."; expired → "This code has expired.
  Send a new one."; locked → "Too many wrong codes. Try again in 15 minutes."; SMS slow → after 45 s
  show "Didn't get it? Check the number or resend."

#### P6 First-time profile and consent · US-P01, NFR-07

- **Purpose:** collect the minimum (name) and record consent.
- **Main elements:** "What's your name?" (shown to the venue on your bookings); one checkbox "I agree
  to the **Terms** and **Privacy notice**" with links; "Continue".
- **Actions:** Continue → back to the booking (P7) or to P9.
- **Empty / error:** missing name → "Enter your name"; box not ticked → "Please agree to continue".
  If staff earlier booked with this number, a note: "We found 1 upcoming booking for you." (US-P01)

#### P7 Review booking · US-P04, US-C03

```
┌──────────────────────────────┐
│ ← Review booking             │
│ Arena X Futsal · Court 1     │
│ Sat 5 Dec · 7:00 – 9:00 pm   │
│ 2 hours                      │
│ Rs. 3,500 + Rs. 3,500        │
│ Total            Rs. 7,000   │
│ Pay at the venue             │
│                              │
│ Team (optional)              │
│ [ No team               ▾ ]  │
│                              │
│ Free cancellation until      │
│ Sat 5 Dec, 1:00 pm.          │
│ After that, call the venue.  │
├──────────────────────────────┤
│ [     Confirm booking      ] │
└──────────────────────────────┘
```

- **Purpose:** check details and confirm.
- **Main elements:** venue, court, date, start–end, duration; price per slot and total; "Pay at the
  venue"; team picker (only for captains/members of a team); cancellation deadline as an exact
  time; **Confirm booking**.
- **Actions:** Confirm → P8; back arrow → P3 with the selection kept.
- **Empty / error:** slot just taken → returns to P3 with banner "Sorry, 7:00 pm was just taken. Here
  are the times still free."; booking limit → "You already have 2 upcoming bookings here. Call the
  venue to book more." + Call; blocked player → "Please contact the venue to book." + Call; slot now
  inside minimum notice → "This time is too soon to book online. Call the venue."

#### P8 Booking confirmed · US-P04

- **Purpose:** reassure: the court is booked.
- **Main elements:** large tick, "You're booked!"; reference **MV-7K3P9Q**; venue, court, date,
  time, total, "Pay at the venue"; "We've sent the details by SMS"; buttons **Share with team**
  (opens the phone's share sheet with a short text and the venue link), **Directions**, **My
  bookings**.
- **Actions:** share, directions, go to bookings.
- **Empty / error:** none. If the SMS fails, this page still shows (the SMS is retried quietly,
  NFR-03).

#### P9 My bookings · US-P05, US-P09

- **Purpose:** see upcoming and past bookings.
- **Main elements:** tabs **Upcoming** / **Past**; cards with day and time (large), venue, court,
  status chip (Confirmed, Cancelled, No-show), team name if any, 🔁 for weekly series, source note
  for staff-entered bookings ("Booked by phone"). A "Weekly slots" section lists the player's series.
- **Actions:** tap a card → P10; tap a series → P13; **Book again** on past bookings (opens P3 for that
  venue).
- **Empty / error:** "No upcoming games. **Find a court**" (→ P1). Past tab empty: "Your past games
  will show here."

#### P10 Booking details · US-P05, US-P06, US-C05

- **Purpose:** all details of one booking; cancel.
- **Main elements:** reference, venue (with Call and Directions), court, date, time, price, status,
  team, "Part of weekly slot" link if in a series; cancellation deadline; **Cancel booking**
  (secondary, red text button).
- **Actions:** Cancel → P11; Call venue; Directions.
- **Empty / error:** inside the cancellation window → the cancel button is replaced by "Free
  cancellation closed at 1:00 pm. To cancel, call the venue." + Call; past booking → no cancel.

#### P11 Cancel booking (bottom sheet) · US-P06

- **Purpose:** confirm a cancellation so it can't happen by accident.
- **Main elements:** "Cancel Sat 5 Dec, 7:00–9:00 pm at Arena X?"; "The court will be offered to
  others."; buttons **Yes, cancel booking** (red) and **Keep booking**.
- **Actions:** Yes → booking cancelled, toast "Booking cancelled. We've sent an SMS.", back to P9.
- **Empty / error:** the window closed while the sheet was open → "Too late to cancel online. Call
  the venue."

#### P12 Request a weekly slot · US-C04

- **Purpose:** a captain asks a venue for the same court every week.
- **Main elements:** venue and court (from P3 or a past booking); weekday + start time + duration
  (pre-filled from the chosen slot); number of weeks (stepper, default 8, max per venue); team
  picker; summary "Every Tuesday, 8:00–9:00 pm, 8 weeks from 8 Dec"; note "The venue will approve or
  reject your request within 48 hours."; **Send request**.
- **Actions:** Send → toast "Request sent" → P13 (status Pending).
- **Empty / error:** not a captain → "Create a team first" + link to P15 (a weekly slot is a team
  feature); weeks above the venue's maximum → stepper stops with "This venue allows up to 12 weeks".

#### P13 Weekly slot details · US-C04, US-C05

- **Purpose:** status of a request or an approved series; cancel weeks.
- **Main elements:** status banner (Pending / Approved / Rejected with reason / Expired); rule
  summary; list of weeks with status (Booked, Skipped: "already booked", Cancelled); **Cancel this
  week** per row; **Cancel all remaining weeks**.
- **Actions:** cancel one week (same rules as P11); cancel series (sheet listing which weeks will be
  cancelled and which are too late to cancel online).
- **Empty / error:** expired → "The venue didn't reply in time. **Send again**".

#### P14 My teams · US-C01, US-P09

- **Purpose:** list teams the user captains or belongs to; see pending invites.
- **Main elements:** "Invites" section at top (Accept / Decline); team cards (name, sport, members
  count, "Captain" chip); **Create team** button.
- **Actions:** open team → P16; accept/decline invite; create → P15.
- **Empty / error:** "No teams yet. Create one to book weekly slots and share games with your team."

#### P15 Create team · US-C01

- **Purpose:** create a team.
- **Main elements:** team name; sport (Futsal / Indoor cricket); **Create team**.
- **Actions:** Create → P16 with an "Invite players" prompt.
- **Empty / error:** missing name → "Enter a team name".

#### P16 Team details · US-C02, US-C03

- **Purpose:** members, invites and team bookings.
- **Main elements:** name, sport; member list (name, "Captain" chip); pending invites (phone, "Sent 2
  days ago", Resend / Remove); **Invite a player** (phone field + Send invite); upcoming team
  bookings; captain-only: Make captain, Remove member, Edit name, **Close team** (confirmation page:
  the team disappears for every player, open invites stop, booked games stay).
- **Actions:** invite, resend, make another member captain, remove member, close team, open a
  booking (P10).
- **Empty / error:** team full → "Teams can have up to 15 players"; invalid phone → same message as
  P4; invite rate limit → "You've sent a lot of invites today. Try again tomorrow."

#### P17 Team invite (from SMS link) · US-P09

- **Purpose:** accept or decline an invite.
- **Main elements:** "Kasun invited you to join **Malabe Strikers** (Futsal)"; **Join team** /
  **Decline**. Signed-out users sign in first (P4–P6) with the invited number.
- **Actions:** Join → P16; Decline → P1.
- **Empty / error:** expired → "This invite has expired. Ask the captain to send a new one."; signed
  in with a different number → "This invite was sent to 077 *** 4567. Sign in with that number."

#### P18 Account · US-P08

- **Purpose:** personal settings.
- **Main elements:** name (editable), phone (read-only, "To change number, contact support");
  language (hidden until Sinhala is added); links: Privacy notice, Terms, Help (WhatsApp/phone of
  Matchvia support); **List my venue** (entry to V1, for owners); **My venues** (if member of any
  venue → venue dashboard); **Sign out**; **Delete my account** (at the bottom, red text).
- **Actions:** edit name, sign out, open venue dashboard, start deletion → P19.
- **Empty / error:** name empty → "Enter your name".

#### P19 Delete account · US-P08

- **Purpose:** PDPA self-service deletion.
- **Main elements:** plain list of what happens ("Your name and number are removed. Your 2 upcoming
  bookings will be cancelled and the venues told. This can't be undone."); **Send code to confirm**
  → code field → **Delete my account**.
- **Actions:** confirm with OTP → signed out → "Your account has been deleted" page.
- **Empty / error:** user is a venue owner → "You own Arena X. Transfer or close it first."; captain →
  "You captain 1 team. Transfer or delete it first." (links).

#### P20 System pages

| Page | Content |
|---|---|
| Privacy notice / Terms | Plain-language text, version date, printable |
| Not found (404) | "We couldn't find that page." + Search button. Also shown for another venue's data (no hint that it exists) |
| Server error (500) | "Something went wrong on our side. Please try again." + Search button; error sent to Sentry |
| Offline (PWA) | See 1.3 |
| Too many requests (429) | "Please wait a moment and try again." |

---

## 3. Venue owners and staff

Navigation: bottom bar **Calendar · + New · Requests · More**. "Requests" shows a badge with pending
recurring requests. "More" opens: Customers, Courts, Opening hours, Prices, Booking rules, Staff,
Venue profile, Share venue page, Switch venue, Back to player view. Owner-only items are hidden from
staff (not shown greyed out).

A **venue status banner** shows on every dashboard screen until approved: "Waiting for approval.
You can already add walk-ins and phone bookings. Players can't book online yet." Rejected: reason +
**Fix and resubmit**. Suspended: reason + support contact.

### 3.1 Venue setup (owner)

Setup is a 6-step wizard. Each step saves as soon as it's completed, so an owner who is interrupted
continues where they stopped. Every step has defaults already filled in. The co-founder can do the
whole setup with the owner on the owner's phone during a sales visit (proposal 7.4).

Progress shown as "Step 2 of 6 · Location" (text, not just dots).

#### V1 List my venue: details · US-O01

- **Purpose:** start a venue.
- **Main elements:** intro "Set up your venue in about 10 minutes. You can change everything later.";
  venue name; area (picker); venue phone number (pre-filled with the owner's number); sports offered
  (Futsal / Indoor cricket, both allowed); **Next**.
- **Actions:** Next → V2 (venue created as draft).
- **Empty / error:** missing fields → message under each field; area not listed → "Don't see your
  area? Contact us" (WhatsApp link).

#### V2 Location and photos · US-O01

- **Purpose:** help players find the venue.
- **Main elements:** address (text); map with draggable pin (loads on this screen only) + **Use my
  current location** (when the owner is at the venue); facilities checklist (parking, changing
  rooms, floodlights, drinking water, cafe, toilets); photos: up to 6, **Add photo** opens camera or
  gallery, upload progress per photo; logo (optional).
- **Actions:** Next → V3; photos can be skipped ("Add later").
- **Empty / error:** photo too big → "This photo is over 5 MB. Choose a smaller one."; upload failed
  on slow network → per-photo "Retry"; location permission denied → drag the pin manually; pin
  outside Sri Lanka → "The pin is outside Sri Lanka."

#### V3 Courts · US-O02

- **Purpose:** add the courts that can be booked.
- **Main elements:** "How many courts do you have?" stepper (creates Court 1…N); each court card:
  name (editable), sports (Futsal / Indoor cricket / both, with hint "A court used for both is
  booked as one space"), indoor/outdoor, booking length (60 min default; 30/60/90/120, explained as
  "How long is one booking slot?"); **Next**.
- **Actions:** add/remove courts, rename, set sports and slot length.
- **Empty / error:** zero courts → "Add at least one court"; duplicate names → "Two courts can't have
  the same name".

#### V4 Opening hours · US-O03

- **Purpose:** set when the venue is open.
- **Main elements:** "Same hours every day" toggle (on by default, 6:00 am–12:00 am); when off, a row
  per weekday: Open/Closed switch, opening time, closing time (closing list includes 1:00 am, 2:00 am,
  3:00 am labelled "(next day)"); **Next**.
- **Actions:** set times; mark days closed.
- **Empty / error:** closing before opening (not past midnight) → "Closing time must be after opening
  time"; all days closed → "Your venue needs at least one open day".

#### V5 Prices and peak times · US-O04

- **Purpose:** set prices.
- **Main elements:** "Same prices for all courts" toggle (on by default); **Normal price** and **Peak
  price** per booking slot (Rs.); peak times summary with defaults "Mon–Fri from 5:00 pm, all day
  Sat–Sun" and **Change peak times** (per weekday: time from–to, add another period); live example
  "Sat 7:00 pm on Court 1 = Rs. 4,000"; **Next**.
- **Actions:** enter prices; edit peak periods; turn off the toggle to price courts separately.
- **Empty / error:** empty price → "Enter a price (Rs. 0 if free)"; peak lower than normal → warning
  only ("Peak price is lower than normal price. Is that right?").

#### V6 Review and submit · US-O01, BR-22

- **Purpose:** check and send for approval.
- **Main elements:** summary cards for each step with **Edit**; "What happens next": "We'll check your
  venue within 1–2 days. Meanwhile you can start using the calendar."; **Submit for approval**;
  secondary **Go to calendar without submitting**.
- **Actions:** submit → status Pending → V8 with banner and a 3-tip intro ("Tap a free time to add a
  booking", "Add your regular teams as weekly bookings", "Share your page when approved").
- **Empty / error:** missing required items listed with links ("Add at least one photo" is a
  recommendation, not required).

#### V7 Switch venue · US-O06

- **Purpose:** choose a venue when a person works at more than one.
- **Main elements:** list of venues with role chip (Owner / Staff) and status.
- **Actions:** tap → V8 for that venue. Shown automatically after sign-in only if the person has 2+
  venues; otherwise the dashboard opens directly.
- **Empty / error:** no venues → not shown (link hidden in P18).

### 3.2 Daily work (owner and staff)

#### V8 Calendar: day view (dashboard home) · US-S01

```
┌──────────────────────────────┐
│ Arena X            [Today]   │
│ ◀  Sat 5 Dec  ▶              │
│ 3 courts · 12 bookings       │
├──────┬────────────┬──────────┤
│      │ Court 1    │ Court 2  │ ← sticky header, swipe → more courts
├──────┼────────────┼──────────┤
│ 5 pm │ + free     │🚶 Nimal  │
│      │            │ Walk-in  │
│ 6 pm │🌐 Kasun    │ + free   │
│      │ Online     │          │
│ 7 pm │☎ Strikers🔁│⛔ Maint. │
│ 8 pm │ (2 hours)  │ + free   │
│ 9 pm │ + free     │🌐 Ruwan  │
├──────┴────────────┴──────────┤
│ Calendar  + New  Requests• More│
└──────────────────────────────┘
```

- **Purpose:** see the day at a glance and act on it. This is the screen staff keep open all day.
- **Main elements:** venue name; date with ◀ ▶ and **Today**; one-line summary (courts, bookings
  today); grid with a sticky time column and one column per court (2 courts fit at 360 dp; swipe
  sideways for more, with a "Court 3 ▸" hint); booking cards showing name (truncated), source icon and
  label, 🔁 for series, team name; blocks striped grey with reason; "+ free" cells; a red "now" line.
  Cancelled bookings hidden (filter toggle "Show cancelled"). Toggle **Day / Week**.
- **Actions:** tap free cell → V10 pre-filled with court and time; tap booking → V11; tap block →
  block details (remove block); ◀ ▶ change day; refreshes itself every 30 s while open.
- **Empty / error:** no courts → "Add your courts first" (owner) / "Ask the owner to add courts"
  (staff); day closed → full-width grey "Closed today (Poya day)" with **Open for this day** (owner;
  removes the closure); no bookings → grid of free cells plus hint "Tap a free time to add a
  booking"; refresh failed → small "Not updated · Retry" label at top, the grid stays.

#### V9 Calendar: week view · US-S01

- **Purpose:** see how full the week is and find free times for phone callers.
- **Main elements:** court picker (one court at a time on phones); 7 day columns × time rows with
  compact coloured blocks (no names, just colour + icon); free cells clearly white.
- **Actions:** tap a free cell → V10; tap a booking → V11; tap a day header → V8 for that day.
- **Empty / error:** same as V8.

*C6 note: V10, V13 and V14 are built as full pages rather than bottom sheets (more reliable on budget
phones and slow networks); each action still takes 3 taps or fewer from the calendar (NFR-04).
V11 also has an **Arrived ✓** button that records who and when, and V8 shows a one-line day
summary (bookings, expected rupees, free peak slots).*

#### V10 New booking (bottom sheet) · US-S02, US-S03

```
┌──────────────────────────────┐
│ New booking                  │
│ Court 1 · Sat 5 Dec · 7:00 pm│
│ [Walk-in] [ Phone ] [WhatsApp]│
│ Name                         │
│ [ Nimal                    ] │
│ Phone (optional for walk-in) │
│ [ 077 123 4567             ] │
│  ↳ Nimal P. · 4 bookings ·   │
│    1 no-show                 │
│ How long?                    │
│ [1 hour][1½ hours][2 hours]  │
│ Price  Rs. 3,500  Change ▸   │
│ More options ▸ (team, notes, │
│               repeat weekly) │
│ [          Save            ] │
└──────────────────────────────┘
```

- **Purpose:** enter a walk-in, phone or WhatsApp booking in seconds.
- **Main elements:** court, date and time (pre-filled from the tapped cell; editable); source
  switch **Walk-in / Phone / WhatsApp** (default: Walk-in if the slot starts within the next hour,
  otherwise Phone); name; phone (required for Phone/WhatsApp, optional for Walk-in) with suggestions
  from the venue's customer book showing booking and no-show counts; duration chips limited by the
  next booking on that court; calculated price with **Change** (opens price + required reason, only
  if allowed, BR-19); "More options" (collapsed): team name, notes, **Repeat weekly** (→ V16);
  **Save**.
- **Actions:** Save → sheet closes, the new booking appears in the grid, toast "Booking saved" (+ "SMS
  sent to customer" for phone/WhatsApp, BR-21).
- **Empty / error:** missing name → "Enter a name"; phone required → "Add a phone number for phone
  bookings"; slot just taken online → "This time was just booked online by Kasun." and the grid
  behind updates; outside opening hours → yellow warning "This is outside your opening hours" with
  **Save anyway** (BR-23); customer blocked online → info only "Blocked from online booking" (staff can
  still book them).

#### V11 Booking details (staff) · US-S01, US-S04, US-S05, US-S07

- **Purpose:** everything about one booking and every action on it.
- **Main elements:** customer name, phone (**Call** and **WhatsApp** buttons), team, source, status,
  court, date and time, price (and price-change reason if any), reference, notes, series link,
  customer's history summary ("6 bookings · 1 no-show · 0 late cancellations" → V19); collapsible
  **History** (created by, changes, with times). Action buttons: **Move**, **Mark no-show** (only
  from 15 min after start), **Cancel booking**; **Undo no-show** when applicable.
- **Actions:** move → V12; no-show → confirm sheet ("Mark Kasun as no-show? The rest of this time
  becomes free for walk-ins.") → toast; cancel → V13; edit name/phone/notes inline.
- **Empty / error:** no-show too early → button disabled with "Available from 7:15 pm"; undo not
  possible because rebooked → "This time has been booked again, so the no-show can't be undone."

#### V12 Move booking · US-S04

- **Purpose:** change time or court ("can we move to 9 pm?").
- **Main elements:** current booking summary; court picker; day strip; free start times for that
  court (chips, same style as P3); new price shown with "Keep old price" checkbox (requires reason);
  "Send SMS to customer" checkbox (on by default if phone known); **Move booking**.
- **Actions:** pick court + time → Move → back to V8 with the booking highlighted.
- **Empty / error:** chosen time taken meanwhile → "That time was just booked. Choose another."; no
  free times that day → "No free times on Court 1 that day" + other courts' times.

#### V13 Cancel booking (staff, bottom sheet) · US-S05

- **Purpose:** cancel for a customer who called or messaged.
- **Main elements:** booking summary; reason (Customer asked / Venue problem / Other + optional text);
  "Send SMS to customer" (on by default if phone known); for series bookings: **This week only** /
  **This and all later weeks**; **Cancel booking**.
- **Actions:** cancel → grid updates, toast.
- **Empty / error:** inside the player's cancellation window and reason "Customer asked" → info line
  "This will be recorded as a late cancellation."

#### V14 Block time (bottom sheet) · US-S06

- **Purpose:** close a court for maintenance, a private event or coaching.
- **Main elements:** courts (checkboxes, "All courts" shortcut); date; from–to time; reason
  (Maintenance / Private event / Coaching / Other); note (staff only, never shown to players);
  **Block time**.
- **Actions:** save → grey striped block on the grid.
- **Empty / error:** overlaps bookings → "3 bookings are in this time:" list with **Open** links; the
  block isn't saved until they're moved or cancelled. End before start → "End time must be after
  start time".

#### V15 Close the venue for a day · US-O03, BR-16

- **Purpose:** mark a whole day closed (Poya day, holiday, repairs). Reached from More → Opening hours
  → **Close a day**, or the ◀ ▶ day menu.
- **Main elements:** date picker; optional note for staff ("Poya day", "Repairs"); players always
  see just "Closed"; **Close this day**.
- **Actions:** close → day shows as closed in V8 and to players.
- **Empty / error:** bookings exist → "5 bookings on this day" list (name, time, phone) with **Cancel all
  and send SMS** (confirm sheet) or **Go back**. The day is closed only after the bookings are
  cancelled.

#### V16 Weekly booking for a regular team · US-S08

- **Purpose:** enter an existing "every Tuesday" team in one go.
- **Main elements:** customer name + phone (with suggestions); team name (optional); court; weekday;
  start time; duration; number of weeks (default 8, max per venue); starting from (date); live
  preview list of weeks marked **Free** or **Clash: already booked / closed**; **Create weekly
  booking**.
- **Actions:** create → one booking per free week; toast "8 weeks booked, 1 skipped (29 Dec)"; SMS
  summary to customer.
- **Empty / error:** every week clashes → "All weeks clash. Choose another time."; missing phone →
  "Add a phone number so we can send the schedule".

#### V17 Requests (recurring) · US-O07

- **Purpose:** approve or reject captains' weekly-slot requests.
- **Main elements:** list of pending requests (team, captain name, "Tue 8:00 pm · 8 weeks", "Expires
  in 30 h"); detail view: captain name and phone (Call/WhatsApp), team, court, weekday, time,
  weeks with **Free / Clash** per week, captain's history at this venue; **Approve** (shows "7 weeks
  will be booked, 1 skipped") and **Reject** (optional reason).
- **Actions:** approve → bookings created, captain notified; reject → captain notified.
- **Empty / error:** no requests → "No requests right now. Captains can ask for weekly slots from
  your venue page."; staff not allowed to approve (BR-13 set to owner only) → buttons hidden, note
  "Only the owner can approve requests"; request expired while open → "This request has expired."

#### V18 Customers · US-S03, US-O09

- **Purpose:** the venue's customer book (replaces the notebook's phone list).
- **Main elements:** search by name or phone; list sorted by most recent booking: name, phone,
  bookings count, no-show count (red if > 0), "Blocked online" chip.
- **Actions:** tap → V19; **Call** directly from the row.
- **Empty / error:** "Customers appear here after their first booking."; no search match → "No
  customer found. Add them with a new booking."

#### V19 Customer details · US-O09

- **Purpose:** history and the no-show defence.
- **Main elements:** name, phone (Call/WhatsApp), notes ("Regular Tuesday team"); counts: bookings,
  no-shows, late cancellations; upcoming and past bookings; weekly slots; owner only: **Block from
  online booking** (sheet with optional reason; explains "They can still book through you") /
  **Unblock**.
- **Actions:** edit name/notes; block/unblock (owner); open a booking (V11).
- **Empty / error:** customer deleted their account → name shows "Deleted user", phone hidden, no
  actions.

### 3.3 Venue settings (owner only)

#### V20 Booking rules · US-O05

- **Purpose:** adjust per-venue rules without understanding "settings".
- **Main elements:** each rule as a plain question with the current answer and a short example:
  - "How far ahead can players book online?" → 14 days (BR-04)
  - "How late can players book online?" → up to 1 hour before (BR-05)
  - "Longest online booking" → 3 hours (BR-02)
  - "Bookings per player at a time" → 2 (BR-12)
  - "Free cancellation until" → 6 hours before (BR-08)
  - "Reminder SMS" → 3 hours before (BR-20)
  - "SMS for phone bookings" on / "SMS for walk-ins" off (BR-21)
  - "Who can approve weekly slots?" → Owner or staff (BR-13); "Weekly slots: up to" → 12 weeks
  - "Staff can change prices" → on (BR-19)
  Each opens a picker with allowed values only (no free typing). **Save** per item.
- **Actions:** change a rule → toast "Saved. Applies to new bookings."
- **Empty / error:** not applicable (all have defaults).

#### V21 Courts · US-O02

- **Purpose:** manage courts after setup. Same form as V3 per court; plus **Deactivate court**.
- **Empty / error:** deactivating a court with future bookings → "Court 2 has 4 upcoming bookings.
  Move or cancel them first." with the list.

#### V22 Opening hours and closed days · US-O03

- **Purpose:** same as V4, plus the list of upcoming closed days (from V15) with **Reopen**.
- **Empty / error:** shortening hours with bookings outside them → warning listing those bookings
  ("They stay booked. Contact the customers if needed.").

#### V23 Prices and peak times · US-O04

- **Purpose:** same as V5 after setup.
- **Empty / error:** after a change → "New prices apply to new bookings only."

#### V24 Staff · US-O06

- **Purpose:** give staff their own sign-in.
- **Main elements:** list of owners and staff (name, phone, role); **Add staff** (name + phone +
  role Staff/Owner; explains "They'll get an SMS and sign in with their number"); **Remove** per
  person (confirm sheet).
- **Actions:** add → SMS sent; remove → access ends immediately.
- **Empty / error:** "Only you so far. Add front-desk staff so they can take bookings."; removing the
  last owner → "A venue needs at least one owner."; invalid phone → same message as P4.

#### V25 Venue profile and status · US-O01, US-A01

- **Purpose:** edit details and photos after setup; see approval status.
- **Main elements:** status card (Draft / Waiting for approval / Approved / Rejected with reason /
  Suspended); same fields as V1–V2; **Submit for approval** (if draft or rejected).
- **Empty / error:** as V1–V2.

#### V26 Share your venue page · US-O08

- **Purpose:** get players booking online.
- **Main elements:** link `matchvia.lk/v/arena-x` with **Copy** and **Share** (phone share sheet:
  WhatsApp, Facebook); **QR code** preview with **Download poster** (A4 PDF/PNG: venue name, tagline
  "Book your court. Bring your team.", QR, link); short tips ("Put the poster at the counter").
- **Empty / error:** not approved yet → "Your page goes live after approval" (link visible but
  marked not live).

---

## 4. Platform admin

Admin uses the Django admin (architecture D16), at a private path behind Cloudflare Access.
Customisations below make the key tasks one-screen jobs and keep them usable on a phone.

#### A0 Admin sign-in

- **Purpose:** keep the admin site for platform admins only.
- **Main elements:** mobile number + password (Django admin login, at the private admin path).
- **Empty / error:** "Wrong mobile number or password." for any wrong pair or a non-admin account;
  "Too many attempts. Try again in 15 minutes." after 5 wrong passwords.

#### A1 Admin home: pending venues · US-A01

- **Purpose:** see what needs action.
- **Main elements:** counts (venues pending, suspended, live; bookings today); list of pending venues
  oldest first (name, area, submitted date, owner phone).
- **Actions:** open a venue → A2.
- **Empty / error:** "No venues waiting."

#### A2 Venue review · US-A01, US-A02

- **Purpose:** approve, reject, suspend.
- **Main elements:** all venue details, photos, map pin, courts and prices, owner name and phone
  (Call), status history; actions **Approve**, **Reject** (reason required), **Suspend** (reason
  required) / **Unsuspend**.
- **Actions:** each action → owner gets an SMS; status history updated; access logged.
- **Empty / error:** reason missing → "A reason is required (the owner will see it)."

#### A3 Areas · US-A03

- **Purpose:** manage the area list.
- **Main elements:** list (name, active, order, number of venues); add/edit form.
- **Empty / error:** deactivating an area with venues → warning with the count.

#### A4 Booking lookup · US-A04

- **Purpose:** resolve disputes.
- **Main elements:** one search box (reference `MV-…` or phone number); results with venue, court,
  time, status; detail with full change history (read-only).
- **Actions:** open venue (A2); view customer record (logged). The user page has
  **Delete account (PDPA request)** for requests received by phone or email: shows what will happen
  and any hand-over blockers, asks how the request came in, then runs the P19 steps (logged).
- **Empty / error:** "No booking found for MV-7K3P9Q."

#### A5 Access log · US-A04

- **Purpose:** prove who looked at personal data.
- **Main elements:** read-only list (admin, action, object, time), filters by admin and date.
- **Empty / error:** "No entries for these filters."

---

## 5. Key flows

### 5.1 First booking by a new player

**Goal:** from a shared link to a confirmed booking in under 60 seconds, excluding SMS delivery time
(NFR-04). **Starting point:** a captain shared Arena X's link in a WhatsApp group (or the player
scanned the QR poster).

| # | Screen | Player does | System does |
|---|---|---|---|
| 1 | P3 Venue page | Opens the link. Sees today's free times | Page loads with the cover photo and today's slots; map not loaded (saves data) |
| 2 | P3 | Taps **Sat 5** in the day strip | HTMX swaps in Saturday's slots |
| 3 | P3 | Taps **7:00 pm** on Court 1 | Not signed in → P4, remembering the selection |
| 4 | P7 (after sign-in) | Taps **120 min** | Review shows "7:00 pm–9:00 pm · Rs. 7,000" |
| 5 | P4 Phone | Types 0771234567, taps **Send code** | Normalises the number, bot check (invisible), queues the OTP SMS |
| 6 | P5 Code | Android offers the code from the SMS, or the player types it | Auto-submits at 6 digits, signs in |
| 7 | P6 Profile | Types name, ticks the agreement box, taps **Continue** | Records consent; returns to the remembered slot |
| 8 | P7 Review | Checks the details and the cancellation deadline, taps **Confirm booking** | Inserts the booking; the database guarantees no overlap; queues confirmation and reminder SMS |
| 9 | P8 Confirmed | Taps **Share with team** | Share sheet with "Futsal Sat 5 Dec 7–9 pm at Arena X, Malabe" + link |

**Taps:** about 8, plus typing the number, code and name. **Second booking:** steps 4–7 disappear
(already signed in), so it's 4 taps.

**What can go wrong:**

| Where | Problem | What the player sees |
|---|---|---|
| 4 | Wants 4 hours | Only 60/120/180 min offered: "Up to 3 slots online. Call the venue for longer." |
| 5 | Typed a landline or a foreign number | "Enter a Sri Lankan mobile number, like 077 123 4567" |
| 6 | SMS is slow | Countdown, then "Didn't get it? Check the number or resend." |
| 6 | Wrong code | "Wrong code. 4 tries left." |
| 8 | Someone else booked 7 pm meanwhile (the slot isn't held during sign-in, BR-07) | Back to P3: "Sorry, 7:00 pm was just taken. Here are the times still free." Selection cleared, other times shown |
| 8 | Network drops on Confirm | Button stays disabled with spinner, then "No connection. Your details are kept. **Try again**." Retrying is safe: a duplicate attempt is rejected by the overlap rule and shown as "You already booked this time" |
| 8 | SMS gateway down | Confirmation page shows normally; SMS sent later |

### 5.2 Owner sets up a venue with courts and prices

**Goal:** a non-technical owner gets a working calendar in about 10 minutes, ideally during the
co-founder's visit. **Starting point:** the owner has signed in (P4–P6) on their own phone.

| # | Screen | Owner does | System does |
|---|---|---|---|
| 1 | P18 Account | Taps **List my venue** | Opens the wizard |
| 2 | V1 Details | Enters "Arena X", picks area **Malabe**, keeps their phone as the venue phone, ticks **Futsal** and **Indoor cricket**, taps **Next** | Creates the venue as Draft, makes them Owner, creates default settings, opening hours and peak times |
| 3 | V2 Location | Taps **Use my current location** (standing at the venue), types the address, ticks Parking and Floodlights, adds 2 photos from the camera, taps **Next** | Uploads and compresses photos with per-photo progress; continues even if photos are still uploading |
| 4 | V3 Courts | Sets "How many courts?" to **2**. Court 2: ticks both sports. Keeps 60-minute slots. Taps **Next** | Creates Court 1 and Court 2 |
| 5 | V4 Hours | Keeps "Same hours every day", changes closing to **1:00 am (next day)**, taps **Next** | Saves hours; late slots belong to the same day (BR-15) |
| 6 | V5 Prices | Keeps "Same prices for all courts". Normal **Rs. 3,000**, Peak **Rs. 4,000**. Keeps default peak times. Sees the example "Sat 7:00 pm = Rs. 4,000". Taps **Next** | Saves prices |
| 7 | V6 Review | Checks summary, taps **Submit for approval** | Status Pending; admin notified |
| 8 | V8 Calendar | Sees the 3-tip intro and the banner "Waiting for approval. You can already add walk-ins and phone bookings." | Calendar is live for staff use (BR-22) |
| 9 | V16 / V10 | With the co-founder, enters this week's notebook bookings and the regular teams as weekly bookings | The online calendar now matches the notebook, which is what makes owners trust it |
| 10 | V24 Staff | Adds the front-desk staff member's phone | Staff gets an SMS and signs in with OTP |
| 11 | (later) V26 Share | After approval (SMS from admin), shares the link in WhatsApp groups and prints the QR poster | Venue appears in search |

**Design choices that make this work for non-technical owners:**

- Only **three questions need real answers**: name/area, number of courts, two prices. Everything
  else has a working default, and the booking rules (V20) aren't part of setup at all.
- Plain questions instead of field names ("How long is one booking slot?", not "Slot duration").
- Leaving halfway is safe; returning to "List my venue" resumes at the first unfinished step.
- The venue is usable before approval, so the visit ends with a working calendar, not "wait for us".

**What can go wrong:** photo upload fails on slow 4G → per-photo **Retry**, rest of setup continues;
location permission denied → drag the pin; closing time set before opening → "Closing time must be
after opening time" (the list shows "(next day)" options to make late closing obvious); owner exits at
step 4 → steps 1–3 are saved, venue stays Draft and isn't visible to anyone.

### 5.3 Staff adds a walk-in at the desk

**Goal:** 3 taps from the calendar (NFR-04), in under 15 seconds, while a customer waits at the
counter. **Starting point:** V8 Calendar is open on the desk phone (it's the dashboard home and
refreshes itself).

| # | Screen | Staff does | System does |
|---|---|---|---|
| 1 | V8 Calendar | Sees Court 2 free at 7:00 pm (the red "now" line is at 6:52 pm). Taps the **+ free** cell | Opens V10 as a bottom sheet with Court 2, today, 7:00 pm; source defaults to **Walk-in** because the slot starts within the hour |
| 2 | V10 New booking | Types "Nimal" (phone optional; if typed, the customer book suggests "Nimal P. · 4 bookings · 1 no-show"). Keeps **1 hour** | Shows price Rs. 4,000 (peak) |
| 3 | V10 | Taps **Save** | Inserts the booking (confirmed, walk-in); the database rejects it if Court 2 was just booked online; no SMS for walk-ins (BR-21) |
| 4 | V8 | Sees the amber "🚶 Nimal · Walk-in" card on Court 2 and the toast "Booking saved" | Audit event recorded with the staff member's name |

**Variations:**

| Situation | What happens |
|---|---|
| Group wants 2 hours | Taps **2 hours** in step 2. If the next hour is taken, only possible durations are shown |
| Customer wants to come every week | "More options" → **Repeat weekly** → V16 pre-filled |
| Phone call instead of walk-in | Same flow; source **Phone**, phone number required; SMS confirmation sent |
| A player booked the same slot online seconds earlier | Step 3 shows "This time was just booked online by Kasun." The grid behind updates; staff taps another free cell |
| The booked team didn't come (7:15 pm) | Tap their booking → **Mark no-show** → the rest of the time becomes free → tap the free cell → walk-in as above (BR-10) |
| After closing time | Warning "This is outside your opening hours" + **Save anyway** (BR-23) |
| Network drops on Save | Spinner, then "No connection. Your details are kept. **Try again**." The sheet stays open with the name filled in |

---

## 6. Design decisions to confirm

| # | Decision | Default in this document | Alternative |
|---|---|---|---|
| UX1 | Time format | 12-hour with am/pm ("7:00 pm"), as most Sri Lankans write times | 24-hour ("19:00"), clearer for late-night slots but less familiar |
| UX2 | Search time filter | Time-of-day chips (Morning, Afternoon, Evening, Night) | Exact "from–to" time pickers (more precise, slower to use) |
| UX3 | Search results layout | List of venue cards only; maps only on the venue page (tap to load) | Map view of results (heavier on data; better after "near me" in Phase 3) |
| UX4 | Default source in New booking | Walk-in if the slot starts within an hour, otherwise Phone | Always ask (one more tap) |
| UX5 | Calendar on phones | 2 courts visible, swipe sideways for more | One court at a time with tabs (simpler, but hides the overview) |

---

## 7. Screen to story coverage

| Story | Screens |
|---|---|
| US-P01 | P4, P5, P6 |
| US-P02 | P1, P2 |
| US-P03 | P3 |
| US-P04 | P3, P7, P8 |
| US-P05 | P9, P10 |
| US-P06 | P10, P11 |
| US-P07 | (SMS only; reminder time shown on P10) |
| US-P08 | P18, P19 |
| US-P09 | P14, P17 |
| US-C01 | P14, P15 |
| US-C02 | P16 |
| US-C03 | P7, P16 |
| US-C04 | P12, P13 |
| US-C05 | P13 |
| US-O01 | V1, V2, V6, V25 |
| US-O02 | V3, V21 |
| US-O03 | V4, V15, V22 |
| US-O04 | V5, V23 |
| US-O05 | V20 |
| US-O06 | V7, V24 |
| US-O07 | V17 |
| US-O08 | P3, V26 |
| US-O09 | V18, V19 |
| US-S01 | V8, V9, V11 |
| US-S02 | V10 |
| US-S03 | V10, V18 |
| US-S04 | V11, V12 |
| US-S05 | V11, V13 |
| US-S06 | V14 |
| US-S07 | V11 |
| US-S08 | V10, V16 |
| US-A01 | A1, A2 |
| US-A02 | A2 |
| US-A03 | A3 |
| US-A04 | A4, A5 |

Total: 20 player/captain screens (including system pages), 26 venue screens, 5 admin screens.
