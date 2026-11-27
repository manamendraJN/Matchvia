"""Venue dashboard navigation: Calendar · + New · Requests · More (screens 3)."""

from datetime import date

import pytest
from django.urls import reverse

from bookings.models import RecurringSeries
from venues.models import VenueCustomer

from .factories import make_court

pytestmark = pytest.mark.django_db


def bottom_bar(html: str) -> str:
    return html[html.index('aria-label="Venue"') :]


def test_bottom_bar_has_the_four_documented_items(client, owner, venue):
    client.force_login(owner)
    html = client.get(reverse("manage:dashboard", args=[venue.pk])).content.decode()
    bar = bottom_bar(html)
    for label in ("Calendar", "New", "Requests", "More"):
        assert label in bar
    assert reverse("manage:more", args=[venue.pk]) in bar
    # The old row of 11 pill tabs is gone; the laptop sidebar has the full menu instead.
    assert 'aria-label="Venue sections"' in html


def test_requests_badge_counts_waiting_requests(client, owner, venue):
    court = make_court(venue)
    customer = VenueCustomer.objects.create(venue=venue, phone="+94775550001", name="Captain")
    RecurringSeries.objects.create(
        venue=venue,
        court=court,
        origin="captain_request",
        status="pending",
        venue_customer=customer,
        weekday=1,
        start_minute=1200,
        duration_minutes=60,
        first_date=date(2026, 12, 8),
        weeks=4,
    )
    client.force_login(owner)
    bar = bottom_bar(client.get(reverse("manage:dashboard", args=[venue.pk])).content.decode())
    assert '<span class="sr-only">: 1</span>' in bar


def test_more_page_lists_every_section(client, owner, venue):
    client.force_login(owner)
    html = client.get(reverse("manage:more", args=[venue.pk])).content.decode()
    for label in (
        "Customers",
        "Courts",
        "Opening hours",
        "Prices",
        "Booking rules",
        "Staff",
        "Venue profile",
        "Switch venue",
        "Back to player view",
    ):
        assert label in html


def test_staff_do_not_see_owner_only_sections(client, venue, staff):
    client.force_login(staff)
    html = client.get(reverse("manage:more", args=[venue.pk])).content.decode()
    assert "Customers" in html
    assert reverse("manage:rules", args=[venue.pk]) not in html
    assert reverse("manage:staff", args=[venue.pk]) not in html
