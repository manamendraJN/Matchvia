"""Online booking by a player (US-P04, BR-02, BR-04, BR-05, BR-07, BR-11, BR-12, BR-18)."""

from datetime import UTC, timedelta

import pytest

from bookings import services
from bookings.models import Booking, BookingEvent, Source, Status
from core.exceptions import NotAllowed, RuleViolation, SlotTaken
from notifications.models import SmsMessage
from venues.models import Venue, VenueCustomer, VenueSettings

from .conftest import NOW, at

pytestmark = pytest.mark.django_db

TUE_18 = at(2026, 12, 8, 18, 0)


def book(player, court, start=TUE_18, slots=1):
    return services.create_online_booking(
        user=player, court_id=court.pk, start_at=start, slots=slots
    )


def test_booking_is_confirmed_at_once_with_price_and_reference(player, court, clock):
    booking = book(player, court)

    assert booking.status == Status.CONFIRMED  # no hold in MVP (BR-07)
    assert booking.source == Source.ONLINE
    assert booking.hold_expires_at is None
    assert (booking.start_at, booking.end_at) == (TUE_18, TUE_18 + timedelta(hours=1))
    assert booking.price_lkr == 4000  # Tuesday 18:00 is peak
    assert len(booking.reference) == 6
    assert str(booking) == booking.display_reference == f"MV-{booking.reference}"
    assert booking.created_by == player
    assert booking.operating_date.isoformat() == "2026-12-08"


def test_times_are_stored_in_utc_and_mean_colombo_time(player, court, clock):
    booking = book(player, court)
    booking.refresh_from_db()
    assert booking.start_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M") == "2026-12-08 12:30"


def test_player_becomes_a_venue_customer(player, court, clock):
    booking = book(player, court)
    customer = booking.venue_customer
    assert (customer.phone, customer.name, customer.user) == (player.phone, player.name, player)
    assert booking.customer_name == player.name


def test_confirmation_sms_and_audit_event(player, court, clock):
    booking = book(player, court)

    sms = SmsMessage.objects.get(purpose="booking_confirmation")
    assert sms.to_phone == player.phone
    assert booking.display_reference in sms.body
    assert "Tue 8 Dec, 6:00 pm–7:00 pm" in sms.body
    assert "Rs. 4,000" in sms.body
    event = BookingEvent.objects.get(booking=booking)
    assert event.action == "created"
    assert event.actor == player
    assert event.changes["price_lkr"] == 4000
    assert player.name not in str(event.changes)
    assert player.phone not in str(event.changes)


def test_consecutive_slots_make_one_booking_priced_per_slot(player, court, clock):
    booking = book(
        player, court, at(2026, 12, 8, 16, 0), slots=3
    )  # 16:00 normal, 17:00, 18:00 peak
    assert booking.end_at == at(2026, 12, 8, 19, 0)
    assert booking.price_lkr == 3000 + 4000 + 4000
    assert Booking.objects.count() == 1


def test_more_slots_than_allowed_refused(player, court, clock):
    with pytest.raises(RuleViolation, match="up to 3 slots"):
        book(player, court, slots=4)
    with pytest.raises(RuleViolation):
        book(player, court, slots=0)


def test_taken_slot_raises_slot_taken(player, court, clock, venue):
    from accounts.tests.factories import UserFactory

    book(UserFactory(), court)
    with pytest.raises(SlotTaken, match="just taken"):
        book(player, court)
    with pytest.raises(SlotTaken):
        book(player, court, at(2026, 12, 8, 17, 0), slots=2)  # second slot is taken
    assert Booking.objects.count() == 1


def test_off_grid_and_closed_times_refused(player, court, clock):
    with pytest.raises(RuleViolation, match="can't be booked"):
        book(player, court, at(2026, 12, 8, 18, 30))
    with pytest.raises(RuleViolation, match="can't be booked"):
        book(player, court, at(2026, 12, 8, 4, 0))


def test_minimum_notice(player, court, clock):
    with pytest.raises(RuleViolation, match="60 minutes before"):
        book(player, court, NOW)  # the 10:00 slot starts now
    with pytest.raises(RuleViolation):
        book(player, court, NOW - timedelta(hours=2))
    book(player, court, NOW + timedelta(hours=1))  # exactly the notice is fine


def test_booking_horizon(player, court, clock):
    with pytest.raises(RuleViolation, match="up to 14 days ahead"):
        book(player, court, at(2026, 12, 22, 18, 0))
    book(player, court, at(2026, 12, 21, 18, 0))


def test_venue_must_be_approved(player, court, venue, clock):
    for status in ["draft", "pending", "rejected", "suspended"]:
        Venue.objects.filter(pk=venue.pk).update(status=status)
        with pytest.raises(RuleViolation, match="not taking online bookings"):
            book(player, court)


def test_inactive_court_is_not_found(player, court, clock):
    court.is_active = False
    court.save()
    from venues.models import Court

    with pytest.raises(Court.DoesNotExist):
        book(player, court)


def test_player_needs_a_completed_profile(court, clock):
    from accounts.tests.factories import UserFactory

    with pytest.raises(NotAllowed):
        book(UserFactory(name=""), court)


def test_upcoming_online_booking_limit(player, court, court2, venue, clock):
    book(player, court, at(2026, 12, 8, 18, 0))
    book(player, court2, at(2026, 12, 8, 18, 0))  # two courts at once is fine (US-P04)
    with pytest.raises(RuleViolation, match="already have 2 upcoming bookings here"):
        book(player, court, at(2026, 12, 9, 18, 0))


def test_limit_ignores_past_cancelled_and_staff_bookings(player, court, venue, clock):
    first = book(player, court, at(2026, 12, 8, 18, 0))
    services.cancel_by_player(user=player, booking_id=first.pk)
    services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=at(2026, 12, 9, 18, 0),
        end_at=at(2026, 12, 9, 19, 0),
        source=Source.PHONE,
        customer_name="Nimal",
        customer_phone=player.phone,
    )
    book(player, court, at(2026, 12, 10, 18, 0))
    book(player, court, at(2026, 12, 11, 18, 0))


def test_limit_is_a_venue_setting(player, court, venue, clock):
    VenueSettings.objects.for_venue(venue).update(max_upcoming_online_bookings=1)
    book(player, court)
    with pytest.raises(RuleViolation, match="1 upcoming"):
        book(player, court, at(2026, 12, 9, 18, 0))


def test_limit_is_per_venue(player, court, other_venue, clock):
    book(player, court, at(2026, 12, 8, 18, 0))
    book(player, court, at(2026, 12, 9, 18, 0))
    book(player, other_venue.court, at(2026, 12, 8, 18, 0))


def test_blocked_player_told_to_call_the_venue(player, court, venue, clock):
    VenueCustomer.objects.create(
        venue=venue, phone=player.phone, name="Nimal", is_blocked_online=True
    )
    with pytest.raises(NotAllowed, match="contact the venue to book"):
        book(player, court)
    assert not Booking.objects.exists()


def test_block_at_one_venue_does_not_apply_elsewhere(player, court, venue, other_venue, clock):
    VenueCustomer.objects.create(
        venue=venue, phone=player.phone, name="Nimal", is_blocked_online=True
    )
    book(player, other_venue.court)


def test_price_is_stored_at_booking_time(player, court, clock):
    booking = book(player, court)
    court.peak_price_lkr = 9999
    court.save()
    booking.refresh_from_db()
    assert booking.price_lkr == 4000


def test_late_night_slot_belongs_to_the_opening_day(player, court, venue, clock):
    from venues.models import OpeningHours

    OpeningHours.objects.for_venue(venue).filter(weekday=1).update(closes_minute=1500)
    booking = book(player, court, at(2026, 12, 9, 0, 0))  # Wednesday 00:00 = Tuesday night
    assert booking.operating_date.isoformat() == "2026-12-08"
    assert booking.price_lkr == 4000  # Tuesday-night peak


def test_existing_customer_row_is_reused_and_linked(player, court, venue, clock):
    walk_in = VenueCustomer.objects.create(venue=venue, phone=player.phone, name="Old name")
    booking = book(player, court)
    assert booking.venue_customer == walk_in
    walk_in.refresh_from_db()
    assert (walk_in.user, walk_in.name) == (player, player.name)
