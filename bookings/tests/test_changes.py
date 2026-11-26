"""Cancelling (US-P06, US-S05, BR-08, BR-09), moving (US-S04) and no-shows (US-S07, BR-10)."""

from datetime import timedelta

import pytest

from accounts.tests.factories import UserFactory
from bookings import services
from bookings.models import Booking, BookingEvent, Source, Status
from core.exceptions import NotAllowed, RuleViolation, SlotTaken
from notifications.models import SmsMessage

from .conftest import NOW, at

pytestmark = pytest.mark.django_db

TUE_18 = at(2026, 12, 8, 18, 0)


def online(player, court, start=TUE_18):
    return services.create_online_booking(user=player, court_id=court.pk, start_at=start)


def walk_in(venue, court, start=TUE_18, hours=1, **kw):
    params = {"source": Source.WALK_IN, "customer_name": "Kasun"}
    params.update(kw)
    return services.create_staff_booking(
        venue=venue,
        actor=venue.staff,
        court_id=court.pk,
        start_at=start,
        end_at=start + timedelta(hours=hours),
        **params,
    )


# ---------------------------------------------------------------- player cancels (BR-08)


def test_player_cancels_outside_the_window(player, court, clock):
    booking = online(player, court)
    SmsMessage.objects.all().delete()

    services.cancel_by_player(user=player, booking_id=booking.pk)

    booking.refresh_from_db()
    assert booking.status == Status.CANCELLED
    assert (booking.cancelled_by, booking.cancel_reason, booking.is_late_cancellation) == (
        player,
        "customer_request",
        False,
    )
    assert booking.cancelled_at == NOW
    assert "is cancelled" in SmsMessage.objects.get(purpose="booking_cancelled").body
    assert BookingEvent.objects.filter(booking=booking, action="cancelled").exists()
    online(UserFactory(), court)  # the slot is free again immediately


def test_cancellation_closes_six_hours_before(player, court, clock):
    booking = online(player, court, at(2026, 12, 7, 18, 0))  # 8 hours from now
    clock.shift(timedelta(hours=2))  # exactly 6 hours before
    with pytest.raises(RuleViolation, match=r"Cancellation closed\. Call the venue: 077"):
        services.cancel_by_player(user=player, booking_id=booking.pk)
    clock.shift(-timedelta(seconds=1))
    services.cancel_by_player(user=player, booking_id=booking.pk)


def test_started_or_finished_bookings_cannot_be_cancelled(player, court, clock):
    booking = online(player, court, at(2026, 12, 7, 18, 0))
    clock.shift(timedelta(hours=8, minutes=30))
    with pytest.raises(RuleViolation, match="already started"):
        services.cancel_by_player(user=player, booking_id=booking.pk)


def test_window_is_a_venue_setting(player, court, venue, clock):
    from venues.models import VenueSettings

    VenueSettings.objects.for_venue(venue).update(cancellation_window_hours=48)
    booking = online(player, court)  # 32 hours away
    with pytest.raises(RuleViolation, match="Cancellation closed"):
        services.cancel_by_player(user=player, booking_id=booking.pk)
    assert not services.player_can_cancel(booking)


def test_player_cannot_cancel_someone_elses_booking(player, court, clock):
    booking = online(UserFactory(), court)
    with pytest.raises(Booking.DoesNotExist):
        services.cancel_by_player(user=player, booking_id=booking.pk)
    booking.refresh_from_db()
    assert booking.status == Status.CONFIRMED


def test_player_can_cancel_a_phone_booking_made_with_their_number(player, venue, court, clock):
    booking = walk_in(
        venue, court, source=Source.PHONE, customer_phone=player.phone, customer_name="Nimal"
    )
    services.cancel_by_player(user=player, booking_id=booking.pk)
    booking.refresh_from_db()
    assert booking.status == Status.CANCELLED


def test_already_cancelled_booking(player, court, clock):
    booking = online(player, court)
    services.cancel_by_player(user=player, booking_id=booking.pk)
    with pytest.raises(RuleViolation, match="not active"):
        services.cancel_by_player(user=player, booking_id=booking.pk)


# ---------------------------------------------------------------- staff cancel (BR-09)


def test_staff_cancel_any_time_with_reason(player, venue, court, clock):
    booking = online(player, court, at(2026, 12, 7, 12, 0))  # 2 hours away: inside the window
    with pytest.raises(RuleViolation, match="reason"):
        services.cancel_by_staff(venue=venue, actor=venue.staff, booking_id=booking.pk, reason="")
    services.cancel_by_staff(
        venue=venue, actor=venue.staff, booking_id=booking.pk, reason="customer_request"
    )
    booking.refresh_from_db()
    assert booking.status == Status.CANCELLED
    assert booking.is_late_cancellation  # customer asked, inside the window (US-S05)
    assert SmsMessage.objects.filter(purpose="booking_cancelled", to_phone=player.phone).exists()


def test_venue_reasons_are_never_late(player, venue, court, clock):
    booking = online(player, court, at(2026, 12, 7, 12, 0))
    services.cancel_by_staff(
        venue=venue, actor=venue.owner, booking_id=booking.pk, reason="venue_issue"
    )
    booking.refresh_from_db()
    assert not booking.is_late_cancellation


def test_staff_cannot_cancel_started_bookings_or_other_venues(venue, other_venue, court, clock):
    started = walk_in(venue, court, start=NOW - timedelta(minutes=30))
    with pytest.raises(RuleViolation, match="no-show instead"):
        services.cancel_by_staff(
            venue=venue, actor=venue.owner, booking_id=started.pk, reason="other"
        )
    theirs = services.create_staff_booking(
        venue=other_venue,
        actor=other_venue.owner,
        court_id=other_venue.court.pk,
        start_at=TUE_18,
        end_at=TUE_18 + timedelta(hours=1),
        source=Source.WALK_IN,
        customer_name="B",
    )
    with pytest.raises(Booking.DoesNotExist):
        services.cancel_by_staff(
            venue=venue, actor=venue.owner, booking_id=theirs.pk, reason="other"
        )
    with pytest.raises(NotAllowed):
        services.cancel_by_staff(
            venue=other_venue, actor=venue.owner, booking_id=theirs.pk, reason="other"
        )


# ---------------------------------------------------------------- moving (US-S04)


def test_move_to_a_free_time_recalculates_price_and_sends_sms(player, venue, court, court2, clock):
    booking = online(player, court)  # Tue 18:00 Court 1, Rs. 4,000
    SmsMessage.objects.all().delete()

    services.move_booking(
        venue=venue,
        actor=venue.staff,
        booking_id=booking.pk,
        court_id=court2.pk,
        start_at=at(2026, 12, 8, 10, 0),
    )

    booking.refresh_from_db()
    assert (booking.court, booking.start_at, booking.end_at) == (
        court2,
        at(2026, 12, 8, 10, 0),
        at(2026, 12, 8, 11, 0),
    )
    assert booking.price_lkr == 2000
    assert "changed" in SmsMessage.objects.get(purpose="booking_changed").body
    actions = list(BookingEvent.objects.filter(booking=booking).values_list("action", flat=True))
    assert actions == ["created", "moved", "price_changed"]


def test_move_into_a_taken_time_changes_nothing(venue, court, clock):
    first = walk_in(venue, court)
    second = walk_in(venue, court, start=at(2026, 12, 8, 20, 0))
    with pytest.raises(SlotTaken):
        services.move_booking(
            venue=venue, actor=venue.owner, booking_id=second.pk, court_id=court.pk, start_at=TUE_18
        )
    second.refresh_from_db()
    assert second.start_at == at(2026, 12, 8, 20, 0)
    assert BookingEvent.objects.filter(booking=second, action="moved").count() == 0
    assert first.status == Status.CONFIRMED


def test_move_keeping_the_old_price_needs_a_reason(venue, court, clock):
    booking = walk_in(venue, court)  # Rs. 4,000 peak
    with pytest.raises(RuleViolation, match="reason"):
        services.move_booking(
            venue=venue,
            actor=venue.staff,
            booking_id=booking.pk,
            court_id=court.pk,
            start_at=at(2026, 12, 8, 10, 0),
            keep_price=True,
        )
    services.move_booking(
        venue=venue,
        actor=venue.staff,
        booking_id=booking.pk,
        court_id=court.pk,
        start_at=at(2026, 12, 8, 10, 0),
        keep_price=True,
        price_change_reason="Our fault",
    )
    booking.refresh_from_db()
    assert booking.price_lkr == 4000
    assert booking.operating_date.isoformat() == "2026-12-08"


def test_move_rules(venue, court, court2, other_venue, clock):
    booking = walk_in(venue, court)
    with pytest.raises(services.OutsideOpeningHours):
        services.move_booking(
            venue=venue,
            actor=venue.owner,
            booking_id=booking.pk,
            court_id=court.pk,
            start_at=at(2026, 12, 8, 4, 0),
        )
    with pytest.raises(Exception, match="matching query"):
        services.move_booking(
            venue=venue,
            actor=venue.owner,
            booking_id=booking.pk,
            court_id=other_venue.court.pk,
            start_at=TUE_18,
        )
    court2.slot_minutes = 90
    court2.save()
    with pytest.raises(RuleViolation, match="90-minute slots"):
        services.move_booking(
            venue=venue,
            actor=venue.owner,
            booking_id=booking.pk,
            court_id=court2.pk,
            start_at=TUE_18,
        )
    past = walk_in(venue, court, start=NOW - timedelta(hours=2))
    with pytest.raises(RuleViolation, match="future"):
        services.move_booking(
            venue=venue,
            actor=venue.owner,
            booking_id=past.pk,
            court_id=court.pk,
            start_at=TUE_18 + timedelta(hours=3),
        )


# ---------------------------------------------------------------- no-shows (BR-10)


def test_no_show_window(venue, court, clock):
    booking = walk_in(venue, court, start=NOW)  # 10:00-11:00 today
    clock.shift(timedelta(minutes=14))
    with pytest.raises(RuleViolation, match="15 minutes after the start"):
        services.mark_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)
    clock.shift(timedelta(minutes=1))
    services.mark_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)
    booking.refresh_from_db()
    assert booking.status == Status.NO_SHOW
    assert booking.no_show_marked_by == venue.staff


def test_no_show_too_late(venue, court, clock):
    booking = walk_in(venue, court, start=NOW)
    clock.shift(timedelta(hours=49, minutes=1))  # 48 h after the 11:00 end
    with pytest.raises(RuleViolation, match="too late"):
        services.mark_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)


def test_future_bookings_cannot_be_no_shows(venue, court, clock):
    booking = walk_in(venue, court)
    with pytest.raises(RuleViolation):
        services.mark_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)


def test_no_show_frees_the_rest_of_the_time_for_a_walk_in(venue, court, clock):
    booking = walk_in(venue, court, start=NOW, hours=2)  # 10:00-12:00
    clock.shift(timedelta(minutes=20))
    services.mark_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)
    walk_in(venue, court, start=at(2026, 12, 7, 11, 0))  # rest of the time is free (BR-10)


def test_undo_no_show(venue, court, clock):
    booking = walk_in(venue, court, start=NOW)
    clock.shift(timedelta(minutes=20))
    services.mark_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)
    services.undo_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)
    booking.refresh_from_db()
    assert booking.status == Status.CONFIRMED
    assert booking.no_show_marked_at is None
    actions = list(BookingEvent.objects.filter(booking=booking).values_list("action", flat=True))
    assert actions == ["created", "no_show", "no_show_undone"]
    with pytest.raises(RuleViolation, match="not marked"):
        services.undo_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)


def test_undo_fails_if_the_time_was_rebooked(venue, court, clock):
    booking = walk_in(venue, court, start=NOW, hours=2)
    clock.shift(timedelta(minutes=20))
    services.mark_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)
    walk_in(venue, court, start=at(2026, 12, 7, 11, 0))
    with pytest.raises(SlotTaken, match="booked again"):
        services.undo_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)
    booking.refresh_from_db()
    assert booking.status == Status.NO_SHOW


def test_undo_after_48_hours_refused(venue, court, clock):
    booking = walk_in(venue, court, start=NOW)
    clock.shift(timedelta(minutes=20))
    services.mark_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)
    clock.shift(timedelta(hours=49))
    with pytest.raises(RuleViolation, match="too late"):
        services.undo_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)


def test_completed_is_derived_not_stored(venue, court, clock):
    booking = walk_in(venue, court, start=NOW)
    assert not booking.is_completed
    clock.shift(timedelta(hours=1))
    assert booking.is_completed
    assert booking.status == Status.CONFIRMED
