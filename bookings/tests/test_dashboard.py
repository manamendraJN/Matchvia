"""Venue dashboard (C6): calendar, new booking, details, move, cancel, no-show, arrived, blocks,
staff. 'Now' is Mon 7 Dec 2026 10:00 in Colombo."""

from datetime import timedelta

import pytest
from django.urls import reverse

from accounts.models import User
from bookings import calendar as cal
from bookings import services
from bookings.models import Booking, BookingEvent, Kind, Source, Status
from core.exceptions import NotAllowed, RuleViolation
from notifications.models import SmsMessage
from venues import services as venue_services
from venues.models import MemberRole, OpeningHours, VenueMembership

from .conftest import NOW, at

pytestmark = pytest.mark.django_db

TUE = "2026-12-08"


def url(name, venue, **kwargs):
    return reverse(f"manage:{name}", kwargs={"venue_id": venue.pk, **kwargs})


def walk_in(venue, court, start, hours=1, **kw):
    params = {"source": Source.WALK_IN, "customer_name": "Nimal"}
    params.update(kw)
    return services.create_staff_booking(
        venue=venue,
        actor=venue.staff,
        court_id=court.pk,
        start_at=start,
        end_at=start + timedelta(hours=hours),
        **params,
    )


@pytest.fixture
def staff_client(client, venue):
    client.force_login(venue.staff)
    return client


@pytest.fixture
def owner_client(client, venue):
    client.force_login(venue.owner)
    return client


# ---------------------------------------------------------------- calendar data


def test_day_calendar_places_bookings_blocks_and_free_cells(venue, court, court2, clock):
    booking = walk_in(venue, court, at(2026, 12, 8, 18, 0), hours=2)
    services.create_block(
        venue=venue,
        actor=venue.owner,
        court_ids=[court2.pk],
        start_at=at(2026, 12, 8, 7, 0),
        end_at=at(2026, 12, 8, 8, 0),
        reason="maintenance",
    )
    day = cal.day_calendar(venue, at(2026, 12, 8, 12, 0).date())
    rows = {row.label: row for row in day.rows}

    assert [c.name for c in day.courts] == ["Court 1", "Court 2"]
    assert rows["6:00 pm"].cells[0].kind == "booking"
    assert rows["6:00 pm"].cells[0].booking == booking
    assert rows["6:00 pm"].cells[0].rowspan == 2
    assert rows["7:00 pm"].cells[0].kind == "covered"
    assert rows["7:00 am"].cells[1].booking.kind == Kind.BLOCK
    assert rows["6:00 pm"].cells[1].kind == "free"
    assert "court=" in rows["6:00 pm"].cells[1].query
    assert "start=2026-12-08T18%3A00" in rows["6:00 pm"].cells[1].query


def test_summary_counts_bookings_revenue_and_free_peak_slots(venue, court, clock):
    walk_in(venue, court, at(2026, 12, 8, 18, 0), hours=2)  # 2 peak slots, Rs. 8,000
    cancelled = walk_in(venue, court, at(2026, 12, 8, 10, 0))
    services.cancel_by_staff(
        venue=venue, actor=venue.owner, booking_id=cancelled.pk, reason="other"
    )
    summary = cal.day_calendar(venue, at(2026, 12, 8, 12, 0).date()).summary
    assert summary.bookings == 1
    assert summary.expected_lkr == 8000
    assert summary.free_peak_slots == 7 - 2  # 17:00-24:00 is 7 peak slots


def test_cancelled_hidden_unless_asked(venue, court, clock):
    booking = walk_in(venue, court, at(2026, 12, 8, 18, 0))
    services.cancel_by_staff(venue=venue, actor=venue.owner, booking_id=booking.pk, reason="other")
    day = at(2026, 12, 8, 12, 0).date()
    assert not any(
        c.kind == "booking" for row in cal.day_calendar(venue, day).rows for c in row.cells
    )
    shown = cal.day_calendar(venue, day, show_cancelled=True)
    assert any(c.booking == booking for row in shown.rows for c in row.cells)


def test_no_show_and_the_walk_in_that_replaced_it(venue, court, clock):
    booking = walk_in(venue, court, NOW, hours=2)
    clock.shift(timedelta(minutes=20))
    services.mark_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)
    replacement = walk_in(venue, court, at(2026, 12, 7, 11, 0))
    rows = {row.label: row for row in cal.day_calendar(venue, NOW.date()).rows}
    assert rows["11:00 am"].cells[0].booking == replacement


def test_bookings_outside_opening_hours_still_show(venue, court, clock):
    early = at(2026, 12, 8, 4, 0)
    walk_in(venue, court, early, allow_outside_hours=True)
    labels = [row.label for row in cal.day_calendar(venue, early.date()).rows]
    assert labels[0] == "4:00 am"


def test_now_line_only_today(venue, court, clock):
    today = cal.day_calendar(venue, NOW.date())
    assert [row.label for row in today.rows if row.is_now] == ["10:00 am"]
    assert not any(
        row.is_now for row in cal.day_calendar(venue, NOW.date() + timedelta(days=1)).rows
    )


def test_week_calendar_for_one_court(venue, court, clock):
    walk_in(venue, court, at(2026, 12, 9, 18, 0))
    OpeningHours.objects.for_venue(venue).filter(weekday=6).update(is_closed=True)
    week = cal.week_calendar(venue, court, NOW.date())
    rows = {row.label: row for row in week.rows}
    assert len(week.days) == 7
    assert rows["6:00 pm"].cells[2].kind == "booking"  # Wednesday
    assert rows["6:00 pm"].cells[6].kind == "closed"  # Sunday closed
    assert rows["6:00 pm"].cells[1].kind == "free"


# ---------------------------------------------------------------- calendar pages


def test_calendar_page(staff_client, venue, court, clock):
    walk_in(venue, court, at(2026, 12, 8, 18, 0), customer_name="Kasun")
    html = staff_client.get(url("dashboard", venue), {"date": TUE}).content.decode()
    assert "Tue 8 Dec" in html
    assert "Kasun" in html
    assert "Walk-in" in html
    assert "+ free" in html
    assert "1 booking" in html
    assert "Rs. 4,000 expected" in html
    assert 'hx-trigger="every 30s"' in html
    assert "Only the owner can change" not in html


def test_calendar_refresh_returns_only_the_grid(staff_client, venue, court, clock):
    response = staff_client.get(url("dashboard", venue), {"date": TUE}, HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert "<html" not in html
    assert 'id="day-grid"' in html


def test_calendar_with_no_courts(staff_client, owner_client, venue, clock):
    assert "Add your courts first" in owner_client.get(url("dashboard", venue)).content.decode()


def test_closed_day(staff_client, venue, court, clock):
    OpeningHours.objects.for_venue(venue).filter(weekday=1).update(is_closed=True)
    assert (
        "Closed on this day."
        in staff_client.get(url("dashboard", venue), {"date": TUE}).content.decode()
    )


def test_week_page(staff_client, venue, court, court2, clock):
    html = staff_client.get(url("week", venue), {"court": court2.pk, "date": TUE}).content.decode()
    assert "Court 2" in html
    assert "Tue 8 Dec" in html
    assert staff_client.get(url("week", venue), {"court": "999999"}).status_code == 200


# ---------------------------------------------------------------- V10 new booking


def new_booking_data(court, **overrides):
    data = {
        "court": court.pk,
        "date": TUE,
        "start_minute": "1080",
        "slots": "1",
        "source": "walk_in",
        "customer_name": "Nimal",
        "customer_phone": "",
    }
    data.update(overrides)
    return data


def test_new_booking_from_a_free_cell_is_prefilled(staff_client, venue, court, clock):
    response = staff_client.get(
        url("booking_new", venue), {"court": court.pk, "start": "2026-12-08T18:00"}
    )
    html = response.content.decode()
    assert 'value="2026-12-08"' in html
    assert 'value="1080" selected' in html
    assert "60 min" in html
    assert response.context["form"].initial["court"] == court
    assert response.context["form"].initial["source"] == Source.PHONE  # tomorrow: not a walk-in


def test_walk_in_within_the_hour_defaults_to_walk_in(staff_client, venue, court, clock):
    response = staff_client.get(
        url("booking_new", venue), {"court": court.pk, "start": "2026-12-07T10:30"}
    )
    assert response.context["form"].initial["source"] == Source.WALK_IN
    later = staff_client.get(
        url("booking_new", venue), {"court": court.pk, "start": "2026-12-07T15:00"}
    )
    assert later.context["form"].initial["source"] == Source.PHONE


def test_save_walk_in_in_three_taps(staff_client, venue, court, clock):
    response = staff_client.post(url("booking_new", venue), new_booking_data(court), follow=True)
    booking = Booking.objects.get()
    assert (booking.source, booking.customer_name, booking.created_by) == (
        Source.WALK_IN,
        "Nimal",
        venue.staff,
    )
    assert "Booking saved." in response.content.decode()
    assert not SmsMessage.objects.exists()


def test_phone_booking_needs_a_number_and_sends_sms(staff_client, venue, court, clock):
    response = staff_client.post(url("booking_new", venue), new_booking_data(court, source="phone"))
    assert "Add a phone number for phone and WhatsApp bookings." in response.content.decode()
    response = staff_client.post(
        url("booking_new", venue),
        new_booking_data(court, source="phone", customer_phone="0715551234"),
        follow=True,
    )
    assert "SMS sent to the customer" in response.content.decode()
    assert SmsMessage.objects.get().to_phone == "+94715551234"


def test_two_hours(staff_client, venue, court, clock):
    staff_client.post(url("booking_new", venue), new_booking_data(court, slots="2"))
    assert Booking.objects.get().end_at == at(2026, 12, 8, 20, 0)


def test_slot_just_booked_online(staff_client, venue, court, player, clock):
    services.create_online_booking(user=player, court_id=court.pk, start_at=at(2026, 12, 8, 18, 0))
    response = staff_client.post(url("booking_new", venue), new_booking_data(court))
    assert f"This time was just booked online by {player.name}." in response.content.decode()
    assert Booking.objects.count() == 1


def test_outside_hours_offers_save_anyway(staff_client, venue, court, clock):
    data = new_booking_data(court, start_minute="240")
    response = staff_client.post(url("booking_new", venue), data)
    assert "This is outside your opening hours." in response.content.decode()
    assert not Booking.objects.exists()
    staff_client.post(url("booking_new", venue), {**data, "save_anyway": "1"})
    assert Booking.objects.count() == 1


def test_price_change_needs_reason(staff_client, venue, court, clock):
    response = staff_client.post(
        url("booking_new", venue), new_booking_data(court, change_price="on", price_lkr="2500")
    )
    assert "Give a short reason" in response.content.decode()
    staff_client.post(
        url("booking_new", venue),
        new_booking_data(
            court, change_price="on", price_lkr="2500", price_change_reason="Regulars"
        ),
    )
    assert Booking.objects.get().price_lkr == 2500


def test_customer_suggestion(staff_client, venue, court, clock):
    booking = walk_in(
        venue,
        court,
        at(2026, 12, 8, 18, 0),
        source=Source.PHONE,
        customer_phone="0715551234",
        customer_name="Ravi",
    )
    html = staff_client.get(
        url("customer_lookup", venue), {"customer_phone": "071 555 1234"}
    ).content.decode()
    assert "Ravi" in html
    assert "1 booking" in html
    assert "0 no-shows" in html
    assert booking.venue_customer.name == "Ravi"
    assert (
        staff_client.get(url("customer_lookup", venue), {"customer_phone": "abc"}).content.strip()
        == b""
    )


# ---------------------------------------------------------------- V11 details and actions


def test_booking_details_show_customer_history_and_actions(staff_client, venue, court, clock):
    booking = walk_in(
        venue, court, at(2026, 12, 8, 18, 0), source=Source.PHONE, customer_phone="0715551234"
    )
    html = staff_client.get(url("booking_detail", venue, booking_id=booking.pk)).content.decode()
    assert "Nimal" in html
    assert 'href="tel:+94715551234"' in html
    assert "1 booking" in html
    assert "Move" in html
    assert "Cancel booking" in html
    assert "No-show available from 6:15 pm" in html
    assert "Created" in html


def test_no_show_then_undo_from_details(staff_client, venue, court, clock):
    booking = walk_in(venue, court, NOW)
    clock.shift(timedelta(minutes=20))
    response = staff_client.post(url("booking_no_show", venue, booking_id=booking.pk), follow=True)
    assert "Marked as a no-show" in response.content.decode()
    response = staff_client.post(
        url("booking_undo_no_show", venue, booking_id=booking.pk), follow=True
    )
    assert "No-show undone." in response.content.decode()


def test_too_early_no_show_shows_message(staff_client, venue, court, clock):
    booking = walk_in(venue, court, at(2026, 12, 8, 18, 0))
    response = staff_client.post(url("booking_no_show", venue, booking_id=booking.pk), follow=True)
    assert "15 minutes after the start" in response.content.decode()


def test_arrived(staff_client, venue, court, clock):
    booking = walk_in(venue, court, NOW)
    response = staff_client.post(url("booking_arrived", venue, booking_id=booking.pk), follow=True)
    booking.refresh_from_db()
    assert booking.checked_in_at == NOW
    assert booking.checked_in_by == venue.staff
    assert booking.status == Status.CONFIRMED  # changes no rule
    assert "Arrived 10:00 am" in response.content.decode()
    assert BookingEvent.objects.filter(booking=booking, action="arrived").count() == 1


def test_arrived_rules(venue, court, clock):
    future = walk_in(venue, court, at(2026, 12, 8, 18, 0))
    with pytest.raises(RuleViolation, match="day of the booking"):
        services.mark_arrived(venue=venue, actor=venue.staff, booking_id=future.pk)
    today = walk_in(venue, court, at(2026, 12, 7, 18, 0))
    services.cancel_by_staff(venue=venue, actor=venue.staff, booking_id=today.pk, reason="other")
    with pytest.raises(RuleViolation, match="Only confirmed"):
        services.mark_arrived(venue=venue, actor=venue.staff, booking_id=today.pk)
    now_booking = walk_in(venue, court, NOW)
    services.mark_arrived(venue=venue, actor=venue.staff, booking_id=now_booking.pk)
    services.mark_arrived(
        venue=venue, actor=venue.owner, booking_id=now_booking.pk
    )  # twice is harmless
    now_booking.refresh_from_db()
    assert now_booking.checked_in_by == venue.staff


# ---------------------------------------------------------------- V12 move, V13 cancel


def test_move_page_lists_free_times_and_moves(staff_client, venue, court, court2, clock):
    booking = walk_in(
        venue, court, at(2026, 12, 8, 18, 0), source=Source.PHONE, customer_phone="0715551234"
    )
    walk_in(venue, court2, at(2026, 12, 8, 20, 0))
    html = staff_client.get(
        url("booking_move", venue, booking_id=booking.pk), {"court": court2.pk, "date": TUE}
    ).content.decode()
    assert 'value="1140"' in html  # 7:00 pm free on Court 2
    assert 'value="1200"' not in html  # 8:00 pm taken
    response = staff_client.post(
        url("booking_move", venue, booking_id=booking.pk),
        {"court": court2.pk, "date": TUE, "start_minute": "1140"},
        follow=True,
    )
    booking.refresh_from_db()
    assert (booking.court, booking.start_at, booking.price_lkr) == (
        court2,
        at(2026, 12, 8, 19, 0),
        2500,
    )
    assert "Booking moved." in response.content.decode()


def test_move_into_taken_time_shows_message(staff_client, venue, court, clock):
    booking = walk_in(venue, court, at(2026, 12, 8, 18, 0))
    walk_in(venue, court, at(2026, 12, 8, 20, 0))
    response = staff_client.post(
        url("booking_move", venue, booking_id=booking.pk),
        {"court": court.pk, "date": TUE, "start_minute": "1200"},
    )
    assert "That time was just booked. Choose another." in response.content.decode()


def test_staff_cancel_with_reason_and_late_warning(staff_client, venue, court, clock):
    booking = walk_in(venue, court, at(2026, 12, 7, 12, 0))
    page = staff_client.get(url("booking_cancel", venue, booking_id=booking.pk)).content.decode()
    assert "recorded as a late cancellation" in page
    response = staff_client.post(
        url("booking_cancel", venue, booking_id=booking.pk),
        {"reason": "customer_request"},
        follow=True,
    )
    booking.refresh_from_db()
    assert booking.status == Status.CANCELLED
    assert booking.is_late_cancellation
    assert "Booking cancelled." in response.content.decode()


def test_cancel_needs_a_reason(staff_client, venue, court, clock):
    booking = walk_in(venue, court, at(2026, 12, 8, 18, 0))
    response = staff_client.post(url("booking_cancel", venue, booking_id=booking.pk), {})
    assert response.status_code == 200
    booking.refresh_from_db()
    assert booking.status == Status.CONFIRMED


# ---------------------------------------------------------------- V14 blocks


def block_data(*courts, **overrides):
    data = {
        "courts": [c.pk for c in courts],
        "date": TUE,
        "start_minute": "360",
        "end_minute": "480",
        "reason": "maintenance",
    }
    data.update(overrides)
    return data


def test_block_time_on_two_courts(staff_client, venue, court, court2, clock):
    response = staff_client.post(
        url("block_new", venue), block_data(court, court2, notes="Painting"), follow=True
    )
    assert "Time blocked." in response.content.decode()
    assert Booking.objects.filter(kind=Kind.BLOCK).count() == 2


def test_block_over_bookings_lists_them(staff_client, venue, court, clock):
    booking = walk_in(venue, court, at(2026, 12, 8, 7, 0), customer_name="Ruwan")
    response = staff_client.post(url("block_new", venue), block_data(court))
    html = response.content.decode()
    assert "This time has bookings" in html
    assert "Ruwan" in html
    assert url("booking_detail", venue, booking_id=booking.pk) in html


def test_block_end_before_start(staff_client, venue, court, clock):
    response = staff_client.post(
        url("block_new", venue), block_data(court, start_minute="600", end_minute="540")
    )
    assert "End time must be after start time." in response.content.decode()


def test_block_details_and_remove(staff_client, venue, court, clock):
    (block,) = services.create_block(
        venue=venue,
        actor=venue.owner,
        court_ids=[court.pk],
        start_at=at(2026, 12, 8, 7, 0),
        end_at=at(2026, 12, 8, 8, 0),
        reason="coaching",
        notes="Kids",
    )
    html = staff_client.get(url("booking_detail", venue, booking_id=block.pk)).content.decode()
    assert "Coaching" in html
    assert "Kids" in html
    staff_client.post(url("block_remove", venue, booking_id=block.pk))
    block.refresh_from_db()
    assert block.status == Status.CANCELLED
    response = staff_client.post(url("block_remove", venue, booking_id=block.pk), follow=True)
    assert "already removed" in response.content.decode()


# ---------------------------------------------------------------- V24 staff


def test_owner_adds_staff_who_gets_an_sms(owner_client, venue, clock):
    response = owner_client.post(
        url("staff", venue),
        {"name": "Ruwan", "phone": "071 234 5678", "role": "staff"},
        follow=True,
    )
    assert (
        "They&#x27;ll get an SMS" in response.content.decode()
        or "They'll get an SMS" in response.content.decode()
    )
    user = User.objects.get(phone="+94712345678")
    assert user.name == "Ruwan"
    assert not user.has_usable_password()
    assert VenueMembership.objects.get(venue=venue, user=user).role == MemberRole.STAFF
    assert SmsMessage.objects.get(purpose="staff_added").to_phone == "+94712345678"


def test_existing_player_can_be_added(owner_client, venue, player, clock):
    owner_client.post(url("staff", venue), {"name": "X", "phone": player.phone, "role": "owner"})
    assert VenueMembership.objects.get(venue=venue, user=player).role == MemberRole.OWNER
    player.refresh_from_db()
    assert player.name == "Nimal Silva"  # their own name is kept


def test_cannot_add_twice_or_bad_numbers(owner_client, venue, clock):
    response = owner_client.post(
        url("staff", venue), {"name": "S", "phone": venue.staff.phone, "role": "staff"}
    )
    assert "already works at this venue" in response.content.decode()
    response = owner_client.post(
        url("staff", venue), {"name": "S", "phone": "0112345678", "role": "staff"}
    )
    assert "Enter a valid Sri Lankan mobile number" in response.content.decode()


def test_remove_staff_ends_access(owner_client, client, venue, clock):
    membership = VenueMembership.objects.get(venue=venue, user=venue.staff)
    owner_client.post(url("staff_remove", venue, membership_id=membership.pk))
    assert not VenueMembership.objects.filter(pk=membership.pk).exists()
    client.force_login(venue.staff)
    assert client.get(url("dashboard", venue)).status_code == 404


def test_last_owner_cannot_be_removed(owner_client, venue, clock):
    membership = VenueMembership.objects.get(venue=venue, user=venue.owner)
    response = owner_client.post(
        url("staff_remove", venue, membership_id=membership.pk), follow=True
    )
    assert "A venue needs at least one owner." in response.content.decode()
    assert VenueMembership.objects.filter(pk=membership.pk).exists()


def test_member_services_check_the_owner(venue, clock):
    with pytest.raises(NotAllowed):
        venue_services.add_member(venue, venue.staff, name="X", phone="+94712345678", role="staff")
    with pytest.raises(RuleViolation):
        venue_services.add_member(venue, venue.owner, name="X", phone="+94712345678", role="boss")
    with pytest.raises(RuleViolation):
        venue_services.add_member(venue, venue.owner, name=" ", phone="+94712345678", role="staff")
    inactive = User.objects.create_user(phone="+94719999999", name="Gone", is_active=False)
    with pytest.raises(RuleViolation, match="disabled"):
        venue_services.add_member(
            venue, venue.owner, name="Gone", phone=inactive.phone, role="staff"
        )
