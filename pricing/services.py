"""Prices for a court at a time (BR-18). Read by booking and slot code; owns no transactions.

Each slot is priced by its **start**: peak if the start falls inside a peak period for the
operating day's weekday (a Friday 00:30 slot is Friday night). A booking stores the total at
booking time, so later price changes never affect it.

This module never imports the venues app at load time (venues.services calls into it).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.timeutils import DAY_END_MINUTE, DAY_START_MINUTE, operating_date, operating_minute

from .models import PeakPeriod

# BR-18 defaults: Mon–Fri from 17:00 to close (03:00 next day), all day Sat–Sun.
DEFAULT_PEAK_PERIODS = [
    *((weekday, 1020, DAY_END_MINUTE) for weekday in range(5)),
    *((weekday, DAY_START_MINUTE, DAY_END_MINUTE) for weekday in (5, 6)),
]


@dataclass(frozen=True)
class SlotPrice:
    start: datetime
    is_peak: bool
    price_lkr: int


def create_default_peak_periods(venue) -> None:
    """Called by venues.services.create_venue() inside its transaction."""
    PeakPeriod.objects.bulk_create(
        PeakPeriod(venue=venue, weekday=w, starts_minute=s, ends_minute=e)
        for w, s, e in DEFAULT_PEAK_PERIODS
    )


def _peak_windows(venue) -> dict[int, list[tuple[int, int]]]:
    windows: dict[int, list[tuple[int, int]]] = {}
    for period in PeakPeriod.objects.for_venue(venue):
        windows.setdefault(period.weekday, []).append((period.starts_minute, period.ends_minute))
    return windows


def _is_peak(windows: dict[int, list[tuple[int, int]]], start: datetime) -> bool:
    weekday = operating_date(start).weekday()
    minute = operating_minute(start)
    return any(begin <= minute < end for begin, end in windows.get(weekday, []))


def slot_prices(court, start_at: datetime, end_at: datetime | None = None) -> list[SlotPrice]:
    """Price of each slot from ``start_at`` to ``end_at`` (one slot if ``end_at`` is None).

    The range must be a whole number of the court's slots. Raises ValueError otherwise.
    """
    slot = timedelta(minutes=court.slot_minutes)
    end_at = end_at or start_at + slot
    length = end_at - start_at
    if length <= timedelta(0):
        raise ValueError("The end must be after the start.")
    if length % slot:
        raise ValueError(f"The range must be whole {court.slot_minutes}-minute slots.")

    windows = _peak_windows(court.venue)
    result = []
    start = start_at
    while start < end_at:
        peak = _is_peak(windows, start)
        price = court.peak_price_lkr if peak else court.off_peak_price_lkr
        result.append(SlotPrice(start=start, is_peak=peak, price_lkr=price))
        start += slot
    return result


def price_for(court, start_at: datetime, end_at: datetime | None = None) -> int:
    """Total price in whole rupees for one slot, or for a range of consecutive slots."""
    return sum(slot.price_lkr for slot in slot_prices(court, start_at, end_at))


def replace_peak_periods(venue, periods: Iterable[tuple[int, int, int]]) -> None:
    """Replace all of a venue's peak periods. Called by venues.services inside its transaction."""
    PeakPeriod.objects.for_venue(venue).delete()
    PeakPeriod.objects.bulk_create(
        PeakPeriod(venue=venue, weekday=w, starts_minute=s, ends_minute=e) for w, s, e in periods
    )
