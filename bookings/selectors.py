"""Read-only queries: free slots (data-model 7, US-P02, US-P03).

Slots are computed, never stored: opening hours + slot length make the grid, then booked or
blocked times, the past, the minimum notice and the horizon are removed (BR-01 to BR-05, BR-15).
Availability always comes from the database at request time, never from a cache (NFR-01).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.utils import timezone

from core.timeutils import at_operating_minute, operating_date
from pricing import services as pricing
from venues.models import OpeningHours

from .models import ACTIVE_STATUSES, Booking


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    price_lkr: int
    is_peak: bool


def booking_horizon_end(venue, now: datetime | None = None) -> date:
    """The last operating date players may book online (BR-04)."""
    now = now or timezone.now()
    return operating_date(now) + timedelta(days=venue.settings.booking_horizon_days)


def slot_grid(court, day: date) -> list[Slot]:
    """Every slot the court offers on operating date ``day``, booked or not, with prices.

    Slots start at opening time and follow the slot length (BR-03). Closed day: no slots.
    """
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
    return [
        Slot(
            start=s.start,
            end=s.start + timedelta(minutes=length),
            price_lkr=s.price_lkr,
            is_peak=s.is_peak,
        )
        for s in pricing.slot_prices(court, first, end)
    ]


def occupied_ranges(court, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Active bookings and blocks on the court that overlap ``[start, end)``."""
    return list(
        Booking.objects.filter(
            court=court, status__in=ACTIVE_STATUSES, start_at__lt=end, end_at__gt=start
        ).values_list("start_at", "end_at")
    )


def get_available_slots(
    court, day: date, *, now: datetime | None = None, for_staff: bool = False
) -> list[Slot]:
    """Free slots on operating date ``day``.

    Players: only approved courts' future slots after the minimum notice (BR-05) and within the
    horizon (BR-04). Staff: every free slot, including past ones and short notice (US-S03).
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
    free = []
    for slot in grid:
        if any(start < slot.end and end > slot.start for start, end in taken):
            continue
        if not for_staff and slot.start < earliest:
            continue
        free.append(slot)
    return free
