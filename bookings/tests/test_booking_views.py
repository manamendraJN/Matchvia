"""P7 review, confirm, P8 done, P9-P11 My bookings and cancel (US-P04-P06)."""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client
from django.urls import reverse

from accounts.tests.factories import UserFactory
from bookings import services
from bookings.models import Booking, Source, Status
from notifications.models import SmsMessage
from venues.models import Venue, VenueCustomer

from .conftest import at

pytestmark = pytest.mark.django_db

START = "2026-12-08T18:00"


def review(client, court, start=START, follow=False, **extra):
    data = {"court": court.pk, "start": start, **extra}
    return client.get(reverse("book_review"), data, follow=follow)


def confirm(client, court, start=START, slots=1, follow=False, **extra):
    data = {"court": court.pk, "start": start, "slots": slots, **extra}
    return client.post(reverse("book_confirm"), data, follow=follow)


@pytest.fixture
def signed_in(client, player):
    client.force_login(player)
    return client


# ---------------------------------------------------------------- P7 review


def test_review_needs_sign_in_and_comes_back(client, court, clock):
    response = review(client, court)
    assert response.status_code == 302
    target = urlparse(response.url)
    assert target.path == reverse("accounts:phone")
    next_url = parse_qs(target.query)["next"][0]
    assert next_url.startswith(reverse("book_review"))
    assert f"court={court.pk}" in next_url


def test_review_shows_price_deadline_and_lengths(signed_in, court, clock):
    html = review(signed_in, court, start="2026-12-08T16:00").content.decode()
    assert "Tue 8 Dec, 4:00 pm–5:00 pm" in html
    assert "Rs. 3,000" in html
    assert "Pay at the venue" in html
    assert "Free cancellation until Tue 8 Dec, 10:00 am" in html
    assert "60 min" in html
    assert "120 min" in html
    assert "180 min" in html
    assert "Rs. 7,000" in html  # 2 slots: 16:00 normal + 17:00 peak


def test_review_with_three_slots(signed_in, court, clock):
    html = review(signed_in, court, start="2026-12-08T16:00", slots=3).content.decode()
    assert "4:00 pm–7:00 pm" in html
    assert "Rs. 11,000" in html


def test_lengths_stop_at_the_next_booking(signed_in, venue, court, clock):
    services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=at(2026, 12, 8, 19, 0),
        end_at=at(2026, 12, 8, 20, 0),
        source=Source.WALK_IN,
        customer_name="X",
    )
    html = review(signed_in, court, slots=3).content.decode()
    assert "How long?" not in html  # only 1 slot is free from 18:00
    assert "6:00 pm–7:00 pm" in html


def test_review_of_a_taken_time_goes_back_to_the_venue(signed_in, venue, court, clock):
    services.create_online_booking(
        user=UserFactory(), court_id=court.pk, start_at=at(2026, 12, 8, 18, 0)
    )
    response = review(signed_in, court, follow=True)
    html = response.content.decode()
    assert "Sorry, 6:00 pm was just taken. Here are the times still free." in html
    assert response.redirect_chain[-1][0].startswith(reverse("venue_page", args=[venue.slug]))


def test_review_bad_input_is_404(signed_in, court, other_venue, clock):
    assert signed_in.get(reverse("book_review"), {"court": "x", "start": START}).status_code == 404
    assert (
        signed_in.get(reverse("book_review"), {"court": court.pk, "start": "soon"}).status_code
        == 404
    )
    assert (
        signed_in.get(reverse("book_review"), {"court": 999999, "start": START}).status_code == 404
    )


def test_review_of_an_unapproved_venue(signed_in, venue, court, clock):
    Venue.objects.filter(pk=venue.pk).update(status="suspended")
    response = review(signed_in, court, follow=True)
    assert "isn&#x27;t taking online bookings yet" in response.content.decode()


# ---------------------------------------------------------------- confirm and P8


def test_confirm_books_and_shows_confirmation(signed_in, player, court, clock):
    response = confirm(signed_in, court, slots=2)
    booking = Booking.objects.get()
    assert response.url == reverse("book_done", args=[booking.display_reference])
    assert (booking.status, booking.source, booking.price_lkr) == (
        Status.CONFIRMED,
        Source.ONLINE,
        8000,
    )
    assert booking.venue_customer.user == player

    html = signed_in.get(response.url).content.decode()
    assert "You&#x27;re booked!" in html or "You're booked!" in html
    assert booking.display_reference in html
    assert "Rs. 8,000" in html
    assert "https://wa.me/?text=" in html
    assert SmsMessage.objects.filter(purpose="booking_confirmation", to_phone=player.phone).exists()


def test_price_from_the_browser_is_ignored(signed_in, court, clock):
    confirm(signed_in, court, price_lkr=1, total=1)
    assert Booking.objects.get().price_lkr == 4000


def test_slot_taken_meanwhile_returns_to_venue_with_message(signed_in, venue, court, clock):
    services.create_online_booking(
        user=UserFactory(), court_id=court.pk, start_at=at(2026, 12, 8, 18, 0)
    )
    response = confirm(signed_in, court, follow=True)
    html = response.content.decode()
    assert "Sorry, 6:00 pm was just taken. Here are the times still free." in html
    assert Booking.objects.count() == 1


def test_double_tap_on_confirm_shows_the_existing_booking(signed_in, court, clock):
    first = confirm(signed_in, court)
    second = confirm(signed_in, court, follow=True)
    assert second.redirect_chain[-1][0] == first.url
    assert "You already booked this time." in second.content.decode()
    assert Booking.objects.count() == 1


def test_rule_messages_shown(signed_in, player, venue, court, court2, clock):
    VenueCustomer.objects.create(venue=venue, phone=player.phone, name="X", is_blocked_online=True)
    response = confirm(signed_in, court, follow=True)
    assert "Please contact the venue to book" in response.content.decode()
    assert not Booking.objects.exists()


def test_booking_limit_message(signed_in, court, court2, clock):
    confirm(signed_in, court)
    confirm(signed_in, court2)
    response = confirm(signed_in, court, start="2026-12-09T18:00", follow=True)
    assert "You already have 2 upcoming bookings here." in response.content.decode()


def test_booking_attempts_are_rate_limited(signed_in, court, clock):
    for day in range(10):
        confirm(signed_in, court, start=f"2026-12-{8 + day:02d}T06:00")
    response = confirm(signed_in, court, start="2026-12-08T07:00", follow=True)
    assert "Too many booking attempts" in response.content.decode()


def test_confirm_requires_post_and_csrf(player, court, clock):
    client = Client(enforce_csrf_checks=True)
    client.force_login(player)
    assert client.get(reverse("book_confirm")).status_code == 405
    assert confirm(client, court).status_code == 403
    assert not Booking.objects.exists()


def test_confirmation_page_is_private(client, player, court, clock):
    booking = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 8, 18, 0)
    )
    client.force_login(UserFactory())
    assert client.get(reverse("book_done", args=[booking.display_reference])).status_code == 404


# ---------------------------------------------------------------- P9-P11


def test_my_bookings_upcoming_and_past(signed_in, player, venue, court, clock):
    booking = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 8, 18, 0)
    )
    html = signed_in.get(reverse("my_bookings")).content.decode()
    assert "Tue 8 Dec, 6:00 pm" in html
    assert booking.display_reference in html
    clock.shift(timedelta(days=2))
    html = signed_in.get(reverse("my_bookings")).content.decode()
    assert "No upcoming games." in html
    past = signed_in.get(reverse("my_bookings"), {"tab": "past"}).content.decode()
    assert "Played" in past


def test_phone_bookings_by_staff_appear_for_the_player(signed_in, player, venue, court, clock):
    """Staff booked with the number before the player had an account (US-P01, US-P05)."""
    customer = VenueCustomer.objects.create(venue=venue, phone=player.phone, name="Nimal")
    booking = services.create_staff_booking(
        venue=venue,
        actor=venue.staff,
        court_id=court.pk,
        start_at=at(2026, 12, 9, 18, 0),
        end_at=at(2026, 12, 9, 19, 0),
        source=Source.PHONE,
        customer_name="Nimal",
        customer_phone=player.phone,
    )
    VenueCustomer.objects.filter(pk=customer.pk).update(user=None)  # as if linked before sign-up
    html = signed_in.get(reverse("my_bookings")).content.decode()
    assert booking.display_reference in html
    assert "Booked by Phone" in html


def test_other_players_bookings_are_not_found(client, player, court, clock):
    booking = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 8, 18, 0)
    )
    client.force_login(UserFactory())
    for name in ("booking_detail", "booking_cancel"):
        assert client.get(reverse(name, args=[booking.display_reference])).status_code == 404
    assert (
        client.post(reverse("booking_cancel", args=[booking.display_reference])).status_code == 404
    )
    booking.refresh_from_db()
    assert booking.status == Status.CONFIRMED


def test_cancel_flow(signed_in, player, court, clock):
    booking = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 8, 18, 0)
    )
    detail = signed_in.get(
        reverse("booking_detail", args=[booking.display_reference])
    ).content.decode()
    assert "Free cancellation until Tue 8 Dec, 12:00 pm." in detail
    page = signed_in.get(
        reverse("booking_cancel", args=[booking.display_reference])
    ).content.decode()
    assert "The court will be offered to others." in page

    response = signed_in.post(
        reverse("booking_cancel", args=[booking.display_reference]), follow=True
    )

    assert (
        "Booking cancelled. We&#x27;ve sent an SMS." in response.content.decode()
        or "Booking cancelled. We've sent an SMS." in response.content.decode()
    )
    booking.refresh_from_db()
    assert booking.status == Status.CANCELLED


def test_inside_the_window_shows_call_the_venue(signed_in, player, court, clock):
    booking = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 7, 14, 0)
    )
    url = reverse("booking_detail", args=[booking.display_reference])
    html = signed_in.get(url).content.decode()
    assert "Free cancellation closed at 8:00 am. To cancel, call the venue" in html
    assert reverse("booking_cancel", args=[booking.display_reference]) not in html
    assert signed_in.get(reverse("booking_cancel", args=[booking.display_reference])).url == url


def test_window_closing_while_the_page_is_open(signed_in, player, court, clock):
    booking = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 7, 18, 0)
    )
    signed_in.get(reverse("booking_cancel", args=[booking.display_reference]))
    clock.shift(timedelta(hours=3))
    response = signed_in.post(
        reverse("booking_cancel", args=[booking.display_reference]), follow=True
    )
    assert "Cancellation closed. Call the venue" in response.content.decode()
    booking.refresh_from_db()
    assert booking.status == Status.CONFIRMED


def test_my_bookings_needs_sign_in(client):
    response = client.get(reverse("my_bookings"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:phone"))
