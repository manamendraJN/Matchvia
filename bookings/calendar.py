"""The venue calendar: day grid per court and week grid for one court (V8, V9, US-S01).

Read-only. Builds rows of cells the template renders as a table: a booking or block starts in
one row and spans the rows it covers; free cells link to New booking. Everything is scoped to
one venue (data-model 6.2).
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import reduce
from urllib.parse import urlencode

from django.utils import timezone

from core.timeutils import at_operating_minute, minute_label, operating_date, operating_minute
from pricing import services as pricing
from venues.models import Court, OpeningHours

from .models import ACTIVE_STATUSES, Booking, Kind, Status
from .selectors import slot_grid

DEFAULT_OPEN, DEFAULT_CLOSE = 360, 1440  # rows shown on a closed day that still has bookings


@dataclass
class Cell:
    kind: str  # "booking", "covered", "free", "closed"
    booking: Booking | None = None
    rowspan: int = 1
    start: datetime | None = None
    court: Court | None = None

    @property
    def query(self) -> str:
        """URL query that pre-fills New booking with this free cell's court and time (V10)."""
        if self.court is None or self.start is None:
            return ""
        start = timezone.localtime(self.start).strftime("%Y-%m-%dT%H:%M")
        return urlencode({"court": self.court.pk, "start": start})


@dataclass
class Row:
    minute: int
    label: str
    is_now: bool = False
    cells: list[Cell] = field(default_factory=list)


@dataclass
class DaySummary:
    bookings: int
    expected_lkr: int
    free_peak_slots: int


@dataclass
class DayCalendar:
    day: date
    courts: list[Court]
    rows: list[Row]
    closed: bool
    summary: DaySummary


@dataclass
class WeekCalendar:
    court: Court
    days: list[date]
    rows: list[Row]


def _visible(bookings, show_cancelled: bool):
    """Active rows first so they win a cell over a no-show or cancelled row at the same time."""
    shown = [
        b
        for b in bookings
        if b.status in ACTIVE_STATUSES
        or b.status == Status.NO_SHOW
        or (show_cancelled and b.status == Status.CANCELLED)
    ]
    return sorted(shown, key=lambda b: (b.status not in ACTIVE_STATUSES, b.start_at))


def _column(court, day, minutes, step, hours, items, now) -> list[Cell]:
    """One court's cells for one operating day, one per row minute."""
    cells: list[Cell | None] = [None] * len(minutes)
    active_ranges = [(b.start_at, b.end_at) for b in items if b.status in ACTIVE_STATUSES]
    for booking in items:
        start_min = operating_minute(booking.start_at)
        end_min = start_min + int((booking.end_at - booking.start_at).total_seconds() // 60)
        covered = [i for i, m in enumerate(minutes) if m < end_min and m + step > start_min]
        if not covered or any(cells[i] is not None for i in covered):
            continue  # a no-show or cancelled row hidden under the booking that replaced it
        cells[covered[0]] = Cell("booking", booking=booking, rowspan=len(covered))
        for i in covered[1:]:
            cells[i] = Cell("covered")

    open_day = hours is not None and not hours.is_closed
    for i, minute in enumerate(minutes):
        if cells[i] is not None:
            continue
        start = at_operating_minute(day, minute)
        on_grid = (
            open_day
            and (minute - hours.opens_minute) % court.slot_minutes == 0
            and hours.opens_minute <= minute
            and minute + court.slot_minutes <= hours.closes_minute
        )
        end = start + timedelta(minutes=court.slot_minutes)
        if on_grid and not any(s < end and e > start for s, e in active_ranges):
            cells[i] = Cell("free", start=start, court=court)
        else:
            cells[i] = Cell("closed")
    return cells


def _row_minutes(hours_list, bookings, step) -> list[int]:
    opens = [h.opens_minute for h in hours_list if h is not None and not h.is_closed]
    closes = [h.closes_minute for h in hours_list if h is not None and not h.is_closed]
    starts = [operating_minute(b.start_at) for b in bookings]
    ends = [
        operating_minute(b.start_at) + int((b.end_at - b.start_at).total_seconds() // 60)
        for b in bookings
    ]
    first = min(opens + starts, default=DEFAULT_OPEN)
    last = max(closes + ends, default=DEFAULT_CLOSE)
    first -= (first - 180) % step  # align to the step, counted from 03:00
    return list(range(first, last, step))


def _now_row(rows: list[Row], day: date, step: int, now: datetime) -> None:
    if operating_date(now) != day:
        return
    minute = operating_minute(now)
    for row in rows:
        if row.minute <= minute < row.minute + step:
            row.is_now = True


def day_calendar(
    venue, day: date, *, show_cancelled: bool = False, now: datetime | None = None
) -> DayCalendar:
    now = now or timezone.now()
    courts = list(Court.objects.for_venue(venue).filter(is_active=True))
    hours = OpeningHours.objects.for_venue(venue).filter(weekday=day.weekday()).first()
    closed = hours is None or hours.is_closed
    bookings = list(
        Booking.objects.for_venue(venue)
        .filter(operating_date=day, court__in=courts)
        .select_related("venue_customer", "court")
        .order_by("start_at")
    )
    visible = _visible(bookings, show_cancelled)
    summary = _summary(venue, courts, day, hours, bookings, now)
    if not courts:
        return DayCalendar(day, courts, [], closed, summary)

    step = reduce(math.gcd, (c.slot_minutes for c in courts))
    minutes = _row_minutes([hours], visible, step)
    rows = [Row(m, minute_label(m)) for m in minutes]
    for court in courts:
        items = [b for b in visible if b.court_id == court.pk]
        for row, cell in zip(
            rows, _column(court, day, minutes, step, hours, items, now), strict=True
        ):
            row.cells.append(cell)
    _now_row(rows, day, step, now)
    return DayCalendar(day, courts, rows, closed, summary)


def _summary(venue, courts, day, hours, bookings, now) -> DaySummary:
    """'12 bookings · Rs. 42,000 expected · 3 peak slots free' (C6; full reports are Phase 2)."""
    confirmed = [b for b in bookings if b.kind == Kind.BOOKING and b.status == Status.CONFIRMED]
    free_peak = 0
    if hours is not None and not hours.is_closed:
        windows = pricing.peak_windows(venue)
        active = [
            (b.court_id, b.start_at, b.end_at) for b in bookings if b.status in ACTIVE_STATUSES
        ]
        for court in courts:
            court.venue = venue
            for slot in slot_grid(court, day, hours=hours, windows=windows):
                taken = any(
                    cid == court.pk and s < slot.end and e > slot.start for cid, s, e in active
                )
                if slot.is_peak and not taken and slot.start >= now:
                    free_peak += 1
    return DaySummary(
        bookings=len(confirmed),
        expected_lkr=sum(b.price_lkr for b in confirmed),
        free_peak_slots=free_peak,
    )


def week_calendar(venue, court, first_day: date, *, now: datetime | None = None) -> WeekCalendar:
    """Seven days for one court (V9): phones show one court at a time."""
    now = now or timezone.now()
    days = [first_day + timedelta(days=i) for i in range(7)]
    hours = {h.weekday: h for h in OpeningHours.objects.for_venue(venue)}
    bookings = list(
        Booking.objects.for_venue(venue)
        .filter(court=court, operating_date__in=days)
        .select_related("venue_customer")
        .order_by("start_at")
    )
    visible = _visible(bookings, show_cancelled=False)
    step = court.slot_minutes
    minutes = _row_minutes([hours.get(d.weekday()) for d in days], visible, step)
    rows = [Row(m, minute_label(m)) for m in minutes]
    for day in days:
        items = [b for b in visible if b.operating_date == day]
        column = _column(court, day, minutes, step, hours.get(day.weekday()), items, now)
        for row, cell in zip(rows, column, strict=True):
            row.cells.append(cell)
    return WeekCalendar(court, days, rows)


def customer_stats(customer) -> dict:
    """Bookings, no-shows and late cancellations at this venue (V10 suggestions, V11, BR-11)."""
    bookings = Booking.objects.filter(venue_customer=customer, kind=Kind.BOOKING)
    return {
        "bookings": bookings.count(),
        "no_shows": bookings.filter(status=Status.NO_SHOW).count(),
        "late_cancellations": bookings.filter(is_late_cancellation=True).count(),
    }


def free_starts(court, day: date, minutes: int, *, exclude=None) -> list[datetime]:
    """Start times on ``day`` where a ``minutes``-long booking fits on ``court`` (V12 Move).

    ``exclude`` is the booking being moved: its own current time doesn't count as taken.
    """
    grid = slot_grid(court, day)
    starts = {slot.start for slot in grid}
    length = timedelta(minutes=minutes)
    step = timedelta(minutes=court.slot_minutes)
    if not grid or length % step:
        return []
    taken = Booking.objects.filter(
        court=court, status__in=ACTIVE_STATUSES, start_at__lt=grid[-1].end, end_at__gt=grid[0].start
    )
    if exclude is not None:
        taken = taken.exclude(pk=exclude.pk)
    ranges = list(taken.values_list("start_at", "end_at"))
    needed = length // step
    result = []
    for slot in grid:
        if not all(slot.start + k * step in starts for k in range(needed)):
            continue
        end = slot.start + length
        if not any(s < end and e > slot.start for s, e in ranges):
            result.append(slot.start)
    return result
