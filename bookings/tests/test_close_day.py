"""Close the venue for a day (V15, US-O03, BR-16)."""

from datetime import date, timedelta

import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory
from bookings import selectors, services
from bookings.models import Booking, BookingEvent, Kind, Source, Status
from core.exceptions import NotAllowed, RuleViolation, SlotTaken
from notifications.models import SmsMessage

from .conftest import at

pytestmark = pytest.mark.django_db

TUESDAY = date(2026, 12, 8)


def phone_booking(venue, court, hour, phone="+94775550001"):
    return services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=at(2026, 12, 8, hour, 0),
        end_at=at(2026, 12, 8, hour + 1, 0),
        source=Source.PHONE,
        customer_name="Ruwan",
        customer_phone=phone,
    )


def test_closing_an_empty_day_closes_every_court(venue, court, court2, player, clock):
    cancelled = services.close_day(venue=venue, actor=venue.staff, day=TUESDAY, note="Poya day")

    assert cancelled == 0
    closure = services.day_closure(venue, TUESDAY)
    assert {b.court_id for b in closure} == {court.pk, court2.pk}
    assert all(b.start_at == at(2026, 12, 8, 3, 0) for b in closure)
    assert all(b.end_at == at(2026, 12, 9, 3, 0) for b in closure)
    assert services.closure_note(closure) == "Poya day"
    # Players see "Closed", can't find it in search and can't book it.
    assert selectors.venue_day(venue, TUESDAY).state == "closed"
    results = selectors.search(sport="futsal", area=venue.area, day=TUESDAY)
    assert venue.pk not in [r.venue.pk for r in results]
    with pytest.raises((SlotTaken, RuleViolation)):
        services.create_online_booking(
            user=player, court_id=court.pk, start_at=at(2026, 12, 8, 18, 0)
        )
    # Other days are untouched.
    assert selectors.venue_day(venue, TUESDAY + timedelta(days=1)).state == "open"


def test_a_day_with_bookings_needs_cancel_all(venue, court, court2, clock):
    first = phone_booking(venue, court, 18)
    second = phone_booking(venue, court2, 20, phone="+94775550002")
    sms_before = SmsMessage.objects.filter(purpose="booking_cancelled").count()

    with pytest.raises(services.DayHasBookings) as caught:
        services.close_day(venue=venue, actor=venue.owner, day=TUESDAY)
    assert [b.pk for b in caught.value.bookings] == [first.pk, second.pk]
    assert services.day_closure(venue, TUESDAY) == []

    cancelled = services.close_day(
        venue=venue, actor=venue.owner, day=TUESDAY, cancel_bookings=True
    )

    assert cancelled == 2
    for booking in (first, second):
        booking.refresh_from_db()
        assert booking.status == Status.CANCELLED
        assert booking.cancel_reason == "venue_closed"
        assert not booking.is_late_cancellation
    sms = SmsMessage.objects.filter(purpose="booking_cancelled")
    assert sms.count() == sms_before + 2
    assert set(sms.values_list("to_phone", flat=True)) >= {"+94775550001", "+94775550002"}
    assert len(services.day_closure(venue, TUESDAY)) == 2


def test_other_blocks_that_day_are_replaced_and_not_restored(venue, court, clock):
    (block,) = services.create_block(
        venue=venue,
        actor=venue.owner,
        court_ids=[court.pk],
        start_at=at(2026, 12, 8, 14, 0),
        end_at=at(2026, 12, 8, 16, 0),
        reason="maintenance",
    )
    services.close_day(venue=venue, actor=venue.owner, day=TUESDAY)
    block.refresh_from_db()
    assert block.status == Status.CANCELLED
    assert BookingEvent.objects.filter(booking=block, changes__replaced_by="closed_day").exists()

    services.reopen_day(venue=venue, actor=venue.owner, day=TUESDAY)

    assert services.day_closure(venue, TUESDAY) == []
    block.refresh_from_db()
    assert block.status == Status.CANCELLED  # option (a): not brought back
    assert selectors.venue_day(venue, TUESDAY).state == "open"


def test_close_day_rules(venue, court, clock):
    with pytest.raises(RuleViolation, match="passed"):
        services.close_day(venue=venue, actor=venue.owner, day=date(2026, 12, 6))
    services.close_day(venue=venue, actor=venue.owner, day=TUESDAY)
    with pytest.raises(RuleViolation, match="already closed"):
        services.close_day(venue=venue, actor=venue.owner, day=TUESDAY)
    with pytest.raises(RuleViolation, match="isn't closed"):
        services.reopen_day(venue=venue, actor=venue.owner, day=TUESDAY + timedelta(days=1))
    stranger = UserFactory()
    with pytest.raises(NotAllowed):
        services.reopen_day(venue=venue, actor=stranger, day=TUESDAY)
    with pytest.raises(NotAllowed):
        services.close_day(venue=venue, actor=stranger, day=TUESDAY + timedelta(days=1))


def test_one_court_of_a_closed_day_cannot_be_unblocked_alone(venue, court, clock):
    services.close_day(venue=venue, actor=venue.owner, day=TUESDAY)
    (block,) = services.day_closure(venue, TUESDAY)
    with pytest.raises(RuleViolation, match="Reopen this day"):
        services.cancel_block(venue=venue, actor=venue.owner, booking_id=block.pk)


def test_closing_today_keeps_games_already_played(venue, court, clock):
    # Monday 7 Dec, now 10:00. A game 8-9 am already happened; one at 6 pm is still to come.
    played = services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=at(2026, 12, 7, 8, 0),
        end_at=at(2026, 12, 7, 9, 0),
        source=Source.WALK_IN,
        customer_name="Early",
        allow_outside_hours=True,
    )
    today = date(2026, 12, 7)
    services.close_day(venue=venue, actor=venue.owner, day=today)
    played.refresh_from_db()
    assert played.status == Status.CONFIRMED
    (closure,) = services.day_closure(venue, today)
    assert closure.start_at == at(2026, 12, 7, 10, 0)


def test_a_game_in_progress_stops_the_closure(venue, court, clock):
    services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=at(2026, 12, 7, 9, 30),
        end_at=at(2026, 12, 7, 10, 30),
        source=Source.WALK_IN,
        customer_name="Now",
        allow_outside_hours=True,
    )
    with pytest.raises(RuleViolation, match="A game is on now"):
        services.close_day(
            venue=venue, actor=venue.owner, day=date(2026, 12, 7), cancel_bookings=True
        )


# ---------------------------------------------------------------- screens


def test_close_day_screen_flow(client, venue, court, clock):
    booking = phone_booking(venue, court, 18)
    client.force_login(venue.staff)  # staff may close days (BR-16)
    url = reverse("manage:close_day", args=[venue.pk])
    assert "Close this day" in client.get(url, {"date": "2026-12-08"}).content.decode()

    page = client.post(url, {"date": "2026-12-08", "note": "Repairs"})
    html = page.content.decode()
    assert "1 booking on this day" in html
    assert "Cancel all and send SMS" in html
    assert "077 555 0001" in html
    booking.refresh_from_db()
    assert booking.status == Status.CONFIRMED

    response = client.post(url, {"date": "2026-12-08", "note": "Repairs", "cancel_all": "1"})
    assert response.status_code == 302
    calendar = client.get(response.url).content.decode()
    assert "Closed for the day" in calendar
    assert "Repairs" in calendar
    assert "Reopen this day" in calendar

    response = client.post(reverse("manage:reopen_day", args=[venue.pk]), {"date": "2026-12-08"})
    assert "Closed for the day" not in client.get(response.url).content.decode()


def test_close_day_screen_errors(client, venue, court, clock):
    client.force_login(venue.owner)
    url = reverse("manage:close_day", args=[venue.pk])
    response = client.post(url, {"date": "2026-12-01"})
    assert "close a day that has passed." in response.content.decode()
    response = client.post(reverse("manage:reopen_day", args=[venue.pk]), {"date": "bad"})
    assert response.status_code == 302
    response = client.post(
        reverse("manage:reopen_day", args=[venue.pk]), {"date": "2026-12-08"}, follow=True
    )
    assert "This day isn&#x27;t closed." in response.content.decode()


def test_players_never_see_the_staff_note(client, venue, court, clock):
    services.close_day(venue=venue, actor=venue.owner, day=TUESDAY, note="Owner wedding")
    html = client.get(
        reverse("venue_page", args=[venue.slug]), {"date": "2026-12-08"}
    ).content.decode()
    assert "Owner wedding" not in html
    assert Booking.objects.filter(kind=Kind.BLOCK, notes__contains="Owner wedding").exists()
