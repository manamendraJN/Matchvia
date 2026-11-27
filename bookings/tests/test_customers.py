"""Customer book (V18, V19) and blocking a number from online booking (US-O09, BR-11)."""

import pytest
from django.urls import reverse

from accounts import services as accounts
from accounts.models import DELETED_USER_NAME
from bookings import selectors, services
from bookings.models import Source
from core.exceptions import NotAllowed, RuleViolation
from venues import services as venue_services
from venues.models import VenueCustomer

from .conftest import at

pytestmark = pytest.mark.django_db


def phone_booking(venue, court, day, hour, name, phone):
    return services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=at(2026, 12, day, hour, 0),
        end_at=at(2026, 12, day, hour + 1, 0),
        source=Source.PHONE,
        customer_name=name,
        customer_phone=phone,
    )


@pytest.fixture
def book(venue, court, clock):
    """Kasun: 2 bookings, one marked no-show later. Nimal: 1 booking, more recent."""
    kasun = phone_booking(venue, court, 8, 18, "Kasun", "+94775550001")
    phone_booking(venue, court, 9, 18, "Kasun", "+94775550001")
    nimal = phone_booking(venue, court, 10, 18, "Nimal", "+94775550002")
    return {"kasun": kasun.venue_customer, "nimal": nimal.venue_customer}


def test_list_has_counts_and_newest_first(venue, book):
    rows = list(selectors.customer_book(venue))
    assert [r.name for r in rows] == ["Nimal", "Kasun"]
    kasun = rows[1]
    assert (kasun.booking_count, kasun.no_show_count) == (2, 0)


@pytest.mark.parametrize("query", ["077 555 0001", "+94775550001", "kas", "KASUN"])
def test_search_by_phone_or_name(venue, book, query):
    assert [r.name for r in selectors.customer_book(venue, query)] == ["Kasun"]


def test_another_venues_customer_with_the_same_phone_never_shows(venue, other_venue, book, clock):
    services.create_staff_booking(
        venue=other_venue,
        actor=other_venue.owner,
        court_id=other_venue.court.pk,
        start_at=at(2026, 12, 8, 18, 0),
        end_at=at(2026, 12, 8, 19, 0),
        source=Source.PHONE,
        customer_name="Kasun at B",
        customer_phone="+94775550001",
    )
    names = [r.name for r in selectors.customer_book(venue)]
    assert "Kasun at B" not in names
    assert [r.name for r in selectors.customer_book(other_venue)] == ["Kasun at B"]


def test_customer_pages(client, venue, book):
    client.force_login(venue.staff)
    html = client.get(reverse("manage:customers", args=[venue.pk])).content.decode()
    assert "Kasun" in html
    assert "077 555 0001" in html
    assert 'href="tel:+94775550001"' in html
    detail = client.get(
        reverse("manage:customer_detail", args=[venue.pk, book["kasun"].pk])
    ).content.decode()
    assert "Late cancellations" in html or "Late cancellations" in detail
    assert "wa.me/94775550001" in detail
    assert "Block from online booking" not in detail  # staff: owner-only action hidden

    empty = client.get(reverse("manage:customers", args=[venue.pk]), {"q": "nobody"})
    assert "No customer found." in empty.content.decode()


def test_empty_customer_book(client, venue):
    client.force_login(venue.owner)
    html = client.get(reverse("manage:customers", args=[venue.pk])).content.decode()
    assert "Customers appear here after their first booking." in html


def test_staff_edit_name_and_notes(client, venue, book):
    client.force_login(venue.staff)
    url = reverse("manage:customer_detail", args=[venue.pk, book["kasun"].pk])
    response = client.post(url, {"name": "  Kasun   Perera ", "notes": "Regular Tuesday team"})
    assert response.status_code == 302
    customer = VenueCustomer.objects.get(pk=book["kasun"].pk)
    assert (customer.name, customer.notes) == ("Kasun Perera", "Regular Tuesday team")
    response = client.post(url, {"name": " ", "notes": ""})
    assert response.status_code == 200


def test_owner_blocks_and_unblocks(client, venue, court, player, book, clock):
    # The player's own number is in the book through a phone booking.
    customer = phone_booking(venue, court, 11, 18, "Player", player.phone).venue_customer
    services.link_phone_bookings(player)
    client.force_login(venue.owner)
    response = client.post(
        reverse("manage:customer_block", args=[venue.pk, customer.pk]), {"reason": "3 no-shows"}
    )
    assert response.status_code == 302
    customer.refresh_from_db()
    assert customer.is_blocked_online
    assert customer.block_reason == "3 no-shows"
    assert customer.blocked_by == venue.owner

    with pytest.raises(NotAllowed):
        services.create_online_booking(
            user=player, court_id=court.pk, start_at=at(2026, 12, 12, 18, 0)
        )
    # Staff can still book them, and their existing booking is untouched.
    phone_booking(venue, court, 12, 20, "Player", player.phone)

    client.post(reverse("manage:customer_unblock", args=[venue.pk, customer.pk]))
    customer.refresh_from_db()
    assert not customer.is_blocked_online
    assert customer.block_reason == ""
    services.create_online_booking(user=player, court_id=court.pk, start_at=at(2026, 12, 13, 18, 0))


def test_only_owners_block(client, venue, book):
    client.force_login(venue.staff)
    url = reverse("manage:customer_block", args=[venue.pk, book["kasun"].pk])
    assert client.post(url).status_code == 404
    with pytest.raises(NotAllowed):
        venue_services.block_customer_online(venue, venue.staff, book["kasun"].pk)
    book["kasun"].refresh_from_db()
    assert not book["kasun"].is_blocked_online


def test_deleted_user_shows_without_number_or_actions(client, venue, court, player, clock):
    customer = phone_booking(venue, court, 8, 18, "Player", player.phone).venue_customer
    services.link_phone_bookings(player)
    accounts.delete_account_on_request(player, admin=_admin())

    client.force_login(venue.owner)
    html = client.get(
        reverse("manage:customer_detail", args=[venue.pk, customer.pk])
    ).content.decode()
    assert DELETED_USER_NAME in html
    assert "This customer deleted their account." in html
    assert "Block from online booking" not in html
    assert "tel:" not in html
    with pytest.raises(RuleViolation, match="deleted their account"):
        venue_services.update_customer(venue, venue.owner, customer.pk, name="X", notes="")
    response = client.post(
        reverse("manage:customer_block", args=[venue.pk, customer.pk]), follow=True
    )
    assert "deleted their account" in response.content.decode()
    response = client.post(
        reverse("manage:customer_unblock", args=[venue.pk, customer.pk]), follow=True
    )
    assert "deleted their account" in response.content.decode()


def test_update_customer_needs_membership(venue, book):
    from accounts.tests.factories import UserFactory

    with pytest.raises(NotAllowed):
        venue_services.update_customer(venue, UserFactory(), book["kasun"].pk, name="X", notes="")


def _admin():
    from accounts.tests.factories import UserFactory

    return UserFactory(is_staff=True)
