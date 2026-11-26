"""Pricing (BR-18): peak by slot start and operating weekday; totals for ranges."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from pricing import services
from pricing.models import PeakPeriod
from venues.tests.factories import make_court, make_venue

COLOMBO = ZoneInfo("Asia/Colombo")
pytestmark = pytest.mark.django_db


def at(*args):
    return datetime(*args, tzinfo=COLOMBO)


@pytest.fixture
def court():
    venue = make_venue()
    return make_court(venue, off_peak_price_lkr=3000, peak_price_lkr=4000)


def test_new_venue_gets_default_peak_periods(court):
    periods = list(
        PeakPeriod.objects.for_venue(court.venue).values_list(
            "weekday", "starts_minute", "ends_minute"
        )
    )
    assert periods == [
        (0, 1020, 1620),
        (1, 1020, 1620),
        (2, 1020, 1620),
        (3, 1020, 1620),
        (4, 1020, 1620),
        (5, 180, 1620),
        (6, 180, 1620),
    ]


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (at(2026, 12, 7, 10, 0), 3000),  # Monday morning: normal
        (at(2026, 12, 7, 16, 0), 3000),  # Monday 16:00: normal
        (at(2026, 12, 7, 17, 0), 4000),  # Monday 17:00: peak starts
        (at(2026, 12, 7, 23, 0), 4000),
        (at(2026, 12, 8, 0, 30), 4000),  # Tue 00:30 is Monday night: peak
        (at(2026, 12, 5, 6, 0), 4000),  # Saturday morning: all-day peak
        (at(2026, 12, 6, 23, 0), 4000),  # Sunday night
        (at(2026, 12, 7, 1, 0), 4000),  # Mon 01:00 is Sunday night: peak
        (at(2026, 12, 7, 3, 0), 3000),  # Mon 03:00 starts Monday: normal
    ],
)
def test_each_slot_priced_by_its_start(court, start, expected):
    assert services.price_for(court, start) == expected


def test_range_sums_each_slot(court):
    # Monday 16:00–19:00: one normal slot then two peak slots.
    start = at(2026, 12, 7, 16, 0)
    slots = services.slot_prices(court, start, start + timedelta(hours=3))
    assert [s.price_lkr for s in slots] == [3000, 4000, 4000]
    assert [s.is_peak for s in slots] == [False, True, True]
    assert services.price_for(court, start, start + timedelta(hours=3)) == 11000


def test_ninety_minute_slots(court):
    court.slot_minutes = 90
    court.save()
    start = at(2026, 12, 7, 15, 30)  # 15:30 normal, 17:00 peak
    assert services.price_for(court, start, start + timedelta(minutes=180)) == 7000


@pytest.mark.parametrize("minutes", [0, -60, 30, 90])
def test_range_must_be_whole_slots(court, minutes):
    start = at(2026, 12, 7, 10, 0)
    with pytest.raises(ValueError, match=r"end must be after|whole"):
        services.price_for(court, start, start + timedelta(minutes=minutes))


def test_peak_periods_are_per_venue(court):
    other = make_court(make_venue(name="Other"), off_peak_price_lkr=1000, peak_price_lkr=9000)
    services.replace_peak_periods(other.venue, [(0, 600, 720)])  # Monday 10:00–12:00 only

    monday_10 = at(2026, 12, 7, 10, 0)
    monday_18 = at(2026, 12, 7, 18, 0)
    assert services.price_for(other, monday_10) == 9000
    assert services.price_for(other, monday_18) == 1000
    assert services.price_for(court, monday_18) == 4000  # first venue unchanged


def test_no_peak_periods_means_always_normal(court):
    services.replace_peak_periods(court.venue, [])
    assert services.price_for(court, at(2026, 12, 5, 20, 0)) == 3000


def test_free_court(court):
    court.off_peak_price_lkr = court.peak_price_lkr = 0
    court.save()
    assert services.price_for(court, at(2026, 12, 5, 20, 0)) == 0
