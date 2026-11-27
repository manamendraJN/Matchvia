"""Read-only queries: free slots, the venue day view and search (data-model 7, US-P02, US-P03).

Slots are computed, never stored: opening hours + slot length make the grid, then booked or
blocked times, the past, the minimum notice and the horizon are removed (BR-01 to BR-05, BR-15).
Availability always comes from the database at request time, never from a cache (NFR-01).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from core.timeutils import (
    DAY_END_MINUTE,
    DAY_START_MINUTE,
    MINUTES_PER_DAY,
    at_operating_minute,
    operating_date,
    operating_minute,
)
from pricing import services as pricing
from venues.models import Court, OpeningHours, Venue

from .models import ACTIVE_STATUSES, Booking, Kind, Status

# Time-of-day filters for search, in operating minutes (screens P1).
TIME_WINDOWS = {
    "any": (DAY_START_MINUTE, DAY_END_MINUTE),
    "morning": (360, 720),  # 6 am - 12 pm
    "afternoon": (720, 1020),  # 12 pm - 5 pm
    "evening": (1020, 1260),  # 5 pm - 9 pm
    "night": (1260, DAY_END_MINUTE),  # 9 pm - close
}


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    price_lkr: int
    is_peak: bool

    @property
    def is_next_day(self) -> bool:
        """After midnight but part of the previous day: shown '(next day)' (screens 1.5)."""
        return operating_minute(self.start) >= MINUTES_PER_DAY


@dataclass(frozen=True)
class Chip:
    """A slot as a player sees it on the venue page: free, or 'Unavailable' (no reason)."""

    slot: Slot
    available: bool


def booking_horizon_end(venue, now: datetime | None = None) -> date:
    """The last operating date players may book online (BR-04)."""
    now = now or timezone.now()
    return operating_date(now) + timedelta(days=venue.settings.booking_horizon_days)


def slot_grid(court, day: date, *, hours=None, windows=None) -> list[Slot]:
    """Every slot the court offers on operating date ``day``, booked or not, with prices.

    Slots start at opening time and follow the slot length (BR-03). Closed day: no slots.
    ``hours`` and ``windows`` may be passed in to avoid queries when many courts are listed.
    """
    if hours is None:
        hours = OpeningHours.objects.for_venue(court.venue).filter(weekday=day.weekday()).first()
    if hours is None or hours.is_closed:
        return []
    length = court.slot_minutes
    # Whole slots only: a 06:00-23:30 day with 60-minute slots ends with the 22:00 slot.
    count = (hours.closes_minute - hours.opens_minute) // length
    if count < 1:
        return []
    first = at_operating_minute(day, hours.opens_minute)
    end = at_operating_minute(day, hours.opens_minute + count * length)
    step = timedelta(minutes=length)
    return [
        Slot(start=s.start, end=s.start + step, price_lkr=s.price_lkr, is_peak=s.is_peak)
        for s in pricing.slot_prices(court, first, end, windows=windows)
    ]


def _taken_by_court(courts, start: datetime, end: datetime) -> dict[int, list[tuple]]:
    """Active bookings and blocks overlapping ``[start, end)``, grouped by court (one query)."""
    taken = defaultdict(list)
    rows = Booking.objects.filter(
        court__in=list(courts), status__in=ACTIVE_STATUSES, start_at__lt=end, end_at__gt=start
    ).values_list("court_id", "start_at", "end_at")
    for court_id, s, e in rows:
        taken[court_id].append((s, e))
    return taken


def _overlaps(slot: Slot, ranges) -> bool:
    return any(s < slot.end and e > slot.start for s, e in ranges)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    return at_operating_minute(day, DAY_START_MINUTE), at_operating_minute(day, DAY_END_MINUTE)


def occupied_ranges(court, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Active bookings and blocks on the court that overlap ``[start, end)``."""
    return _taken_by_court([court], start, end)[court.pk]


def get_available_slots(
    court, day: date, *, now: datetime | None = None, for_staff: bool = False
) -> list[Slot]:
    """Free slots on operating date ``day``.

    Players: future slots after the minimum notice (BR-05) and within the horizon (BR-04).
    Staff: every free slot, including past ones and short notice (US-S03).
    """
    now = now or timezone.now()
    if not court.is_active:
        return []
    settings = court.venue.settings
    if not for_staff and day > booking_horizon_end(court.venue, now):
        return []
    grid = slot_grid(court, day)
    if not grid:
        return []
    taken = occupied_ranges(court, grid[0].start, grid[-1].end)
    earliest = now + timedelta(minutes=settings.min_notice_minutes)
    return [
        slot
        for slot in grid
        if not _overlaps(slot, taken) and (for_staff or slot.start >= earliest)
    ]


# ---------------------------------------------------------------- venue page (P3)


@dataclass
class VenueDay:
    """What the venue page shows for one operating day."""

    day: date
    state: str  # "open", "closed", "beyond_horizon", "past", "not_public"
    courts: list[tuple[Court, list[Chip]]] = field(default_factory=list)

    @property
    def has_free(self) -> bool:
        return any(chip.available for _court, chips in self.courts for chip in chips)


def venue_day(venue: Venue, day: date, *, now: datetime | None = None) -> VenueDay:
    """Free and unavailable times per court for players (US-P03). Blocks show as 'Unavailable'."""
    now = now or timezone.now()
    if not venue.is_public:
        return VenueDay(day, "not_public")
    if day < operating_date(now):
        return VenueDay(day, "past")
    if day > booking_horizon_end(venue, now):
        return VenueDay(day, "beyond_horizon")
    hours = OpeningHours.objects.for_venue(venue).filter(weekday=day.weekday()).first()
    if hours is None or hours.is_closed:
        return VenueDay(day, "closed")
    courts = list(Court.objects.for_venue(venue).filter(is_active=True))
    windows = pricing.peak_windows(venue)
    taken = _taken_by_court(courts, *_day_bounds(day))
    earliest = now + timedelta(minutes=venue.settings.min_notice_minutes)
    result = VenueDay(day, "open")
    for court in courts:
        court.venue = venue
        chips = [
            Chip(slot, available=not _overlaps(slot, taken[court.pk]))
            for slot in slot_grid(court, day, hours=hours, windows=windows)
            if slot.start >= earliest
        ]
        result.courts.append((court, chips))
    return result


def next_free_day(venue: Venue, after: date, *, now: datetime | None = None) -> date | None:
    """The next day with a free slot, for 'Fully booked on Saturday' (P3)."""
    now = now or timezone.now()
    day = after + timedelta(days=1)
    while day <= booking_horizon_end(venue, now):
        if venue_day(venue, day, now=now).has_free:
            return day
        day += timedelta(days=1)
    return None


def consecutive_free(court, start: datetime, *, now: datetime | None = None) -> int:
    """How many slots in a row are free from ``start``, up to the venue's online limit (BR-02).

    0 if ``start`` itself isn't a free, bookable slot for players.
    """
    now = now or timezone.now()
    limit = court.venue.settings.max_slots_per_booking
    free = {slot.start for slot in get_available_slots(court, operating_date(start), now=now)}
    count = 0
    step = timedelta(minutes=court.slot_minutes)
    while count < limit and start + count * step in free:
        count += 1
    return count


# ---------------------------------------------------------------- search (P2)


@dataclass(frozen=True)
class CourtSlot:
    court: Court
    slot: Slot


@dataclass
class VenueResult:
    venue: Venue
    slots: list[CourtSlot] = field(default_factory=list)
    beyond_horizon: bool = False

    @property
    def earliest(self) -> datetime | None:
        return min((cs.slot.start for cs in self.slots), default=None)

    @property
    def min_price(self) -> int | None:
        return min((cs.slot.price_lkr for cs in self.slots), default=None)


def search(
    *, sport: str, area, day: date, time_window: str = "any", now: datetime | None = None
) -> list[VenueResult]:
    """Approved venues in ``area`` with a free ``sport`` court starting in the time window.

    A fixed number of queries whatever the number of venues (NFR-02): venues, courts, hours,
    peak periods, bookings. Closed venues are left out; venues whose horizon ends before
    ``day`` are listed with ``beyond_horizon`` (US-P02).
    """
    now = now or timezone.now()
    first_minute, last_minute = TIME_WINDOWS[time_window]
    venues = {
        v.pk: v for v in Venue.objects.public().filter(area=area).select_related("settings", "area")
    }
    if not venues:
        return []
    courts = list(
        Court.objects.filter(venue_id__in=list(venues), is_active=True, sports__contains=[sport])
    )
    hours = {
        h.venue_id: h
        for h in OpeningHours.objects.filter(venue_id__in=list(venues), weekday=day.weekday())
    }
    windows = pricing.peak_windows_for(venues.values())
    taken = _taken_by_court(courts, *_day_bounds(day))
    window_start = at_operating_minute(day, first_minute)
    window_end = at_operating_minute(day, last_minute)

    results: dict[int, VenueResult] = {}
    for court in courts:
        venue = venues[court.venue_id]
        court.venue = venue
        day_hours = hours.get(venue.pk)
        if day_hours is None or day_hours.is_closed:
            continue
        if day > booking_horizon_end(venue, now):
            results.setdefault(venue.pk, VenueResult(venue, beyond_horizon=True))
            continue
        earliest = max(now + timedelta(minutes=venue.settings.min_notice_minutes), window_start)
        grid = slot_grid(court, day, hours=day_hours, windows=windows.get(venue.pk, {}))
        for slot in grid:
            if earliest <= slot.start < window_end and not _overlaps(slot, taken[court.pk]):
                results.setdefault(venue.pk, VenueResult(venue)).slots.append(
                    CourtSlot(court, slot)
                )

    ordered = sorted(
        results.values(),
        key=lambda r: (r.beyond_horizon, r.earliest or window_end, r.venue.name),
    )
    for result in ordered:
        result.slots.sort(key=lambda cs: (cs.slot.start, cs.court.position))
    return ordered


# ---------------------------------------------------------------- my bookings (P9)


def player_bookings(user, *, now: datetime | None = None):
    """(upcoming, past) bookings for 'My bookings' (US-P05), staff-entered ones included."""
    now = now or timezone.now()
    mine = Q(venue_customer__user=user) | Q(team__memberships__user=user, team__is_active=True)
    base = (
        Booking.objects.filter(mine, kind=Kind.BOOKING)
        .select_related("venue", "court", "team")
        .distinct()
    )
    upcoming = list(base.filter(status=Status.CONFIRMED, end_at__gt=now).order_by("start_at"))
    past = list(base.exclude(pk__in=[b.pk for b in upcoming]).order_by("-start_at")[:50])
    return upcoming, past


def team_bookings(team, *, now: datetime | None = None):
    """Upcoming bookings tagged with a team (P16, US-C03)."""
    now = now or timezone.now()
    return list(
        Booking.objects.filter(team=team, status=Status.CONFIRMED, end_at__gt=now)
        .select_related("venue", "court")
        .order_by("start_at")[:20]
    )
