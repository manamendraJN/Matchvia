"""Free slots (US-P02, US-P03, BR-01 to BR-05, BR-15, BR-18). 'Now' is Mon 7 Dec 2026 10:00."""

from datetime import UTC, date, timedelta

import pytest

from bookings import selectors, services
from bookings.models import Source
from venues.models import OpeningHours, VenueSettings

from .conftest import NOW, at

pytestmark = pytest.mark.django_db

TUESDAY = date(2026, 12, 8)


def starts(slots):
    return [(s.start.hour, s.start.minute) for s in slots]


def hours(venue, weekday, opens, closes, closed=False):
    OpeningHours.objects.for_venue(venue).filter(weekday=weekday).update(
        opens_minute=opens, closes_minute=closes, is_closed=closed
    )


def staff_booking(venue, court, start, end):
    return services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=start,
        end_at=end,
        source=Source.WALK_IN,
        customer_name="Walk-in",
    )


def test_hourly_grid_from_opening_to_closing(court, clock):
    slots = selectors.get_available_slots(court, TUESDAY)
    assert starts(slots)[0] == (6, 0)
    assert starts(slots)[-1] == (23, 0)
    assert len(slots) == 18


@pytest.mark.parametrize(("minutes", "count"), [(30, 36), (60, 18), (90, 12), (120, 9)])
def test_slot_lengths(court, clock, minutes, count):
    court.slot_minutes = minutes
    court.save()
    slots = selectors.get_available_slots(court, TUESDAY)
    assert len(slots) == count
    assert all(s.end - s.start == timedelta(minutes=minutes) for s in slots)


def test_partial_last_slot_is_dropped(venue, court, clock):
    hours(venue, 1, 360, 1410)  # 06:00-23:30 with 60-minute slots
    assert starts(selectors.get_available_slots(court, TUESDAY))[-1] == (22, 0)


def test_closing_after_midnight_belongs_to_the_opening_day(venue, court, clock):
    hours(venue, 4, 1080, 1500)  # Friday 18:00 to 01:00
    slots = selectors.get_available_slots(court, date(2026, 12, 11))
    assert [s.start for s in slots][-2:] == [at(2026, 12, 11, 23, 0), at(2026, 12, 12, 0, 0)]
    assert slots[-1].end == at(2026, 12, 12, 1, 0)
    # Saturday's own day starts at 06:00; the 00:00 slot isn't repeated there.
    assert starts(selectors.get_available_slots(court, date(2026, 12, 12)))[0] == (6, 0)


def test_closed_weekday_has_no_slots(venue, court, clock):
    hours(venue, 1, 360, 1440, closed=True)
    assert selectors.get_available_slots(court, TUESDAY) == []


def test_inactive_court_has_no_slots(court, clock):
    court.is_active = False
    court.save()
    assert selectors.get_available_slots(court, TUESDAY) == []


def test_slots_are_priced_by_start_time(court, clock):
    slots = {s.start.hour: s for s in selectors.get_available_slots(court, TUESDAY)}
    assert (slots[16].price_lkr, slots[16].is_peak) == (3000, False)
    assert (slots[17].price_lkr, slots[17].is_peak) == (4000, True)


def test_booked_and_blocked_times_are_not_free(venue, court, court2, clock):
    staff_booking(venue, court, at(2026, 12, 8, 18, 0), at(2026, 12, 8, 20, 0))
    services.create_block(
        venue=venue,
        actor=venue.owner,
        court_ids=[court.pk],
        start_at=at(2026, 12, 8, 7, 0),
        end_at=at(2026, 12, 8, 8, 0),
        reason="maintenance",
    )
    free = starts(selectors.get_available_slots(court, TUESDAY))
    assert (18, 0) not in free
    assert (19, 0) not in free
    assert (7, 0) not in free
    assert (20, 0) in free
    # Other courts are unaffected.
    assert (18, 0) in starts(selectors.get_available_slots(court2, TUESDAY))


def test_off_grid_booking_hides_every_slot_it_touches(venue, court, clock):
    court.slot_minutes = 30
    court.save()
    staff_booking(venue, court, at(2026, 12, 8, 18, 30), at(2026, 12, 8, 19, 30))
    free = starts(selectors.get_available_slots(court, TUESDAY))
    assert (18, 0) in free
    assert (18, 30) not in free
    assert (19, 0) not in free
    assert (19, 30) in free


def test_cancelled_booking_frees_the_slot(venue, court, clock):
    booking = staff_booking(venue, court, at(2026, 12, 8, 18, 0), at(2026, 12, 8, 19, 0))
    services.cancel_by_staff(venue=venue, actor=venue.owner, booking_id=booking.pk, reason="other")
    assert (18, 0) in starts(selectors.get_available_slots(court, TUESDAY))


def test_today_hides_past_and_short_notice_for_players(court, clock):
    today = NOW.date()
    player_slots = starts(selectors.get_available_slots(court, today))
    assert player_slots[0] == (11, 0)  # 10:00 is now; 11:00 is exactly the 60-minute notice
    staff_slots = starts(selectors.get_available_slots(court, today, for_staff=True))
    assert staff_slots[0] == (6, 0)


def test_minimum_notice_is_per_venue(venue, court, clock):
    VenueSettings.objects.for_venue(venue).update(min_notice_minutes=0)
    venue.settings.refresh_from_db()
    assert starts(selectors.get_available_slots(court, NOW.date()))[0] == (10, 0)


def test_booking_horizon(venue, court, clock):
    last = NOW.date() + timedelta(days=14)
    assert selectors.get_available_slots(court, last)
    assert selectors.get_available_slots(court, last + timedelta(days=1)) == []
    assert selectors.get_available_slots(court, last + timedelta(days=1), for_staff=True)
    assert selectors.booking_horizon_end(venue) == last


def test_slot_times_are_colombo_wall_clock(court, clock):
    first = selectors.get_available_slots(court, TUESDAY)[0]
    assert first.start == at(2026, 12, 8, 6, 0)
    # 06:00 in Colombo (UTC+05:30) is 00:30 UTC.
    assert first.start.astimezone(UTC).strftime("%H:%M") == "00:30"
