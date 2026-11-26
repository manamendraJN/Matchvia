"""P1 search, P2 results and P3 venue page (US-P02, US-P03). 'Now' is Mon 7 Dec 2026 10:00."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from bookings import selectors, services
from bookings.models import Source
from venues.models import OpeningHours, Venue, VenueSettings
from venues.tests.factories import area, make_court, make_venue

from .conftest import NOW, at

pytestmark = pytest.mark.django_db

TUESDAY = "2026-12-08"


def search(client, **params):
    query = {"sport": "futsal", "area": "malabe", "date": TUESDAY, "time": "any", **params}
    return client.get(reverse("search"), query)


def approved_venue(name, area_slug="malabe", **court_fields):
    venue = make_venue(name=name, area_slug=area_slug)
    Venue.objects.filter(pk=venue.pk).update(status="approved")
    venue.refresh_from_db()
    make_court(venue, **court_fields)
    return venue


def walk_in(venue, court, start, hours=1):
    return services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=start,
        end_at=start + timedelta(hours=hours),
        source=Source.WALK_IN,
        customer_name="X",
    )


# ---------------------------------------------------------------- P1 home


def test_home_is_the_search_form(client, clock):
    html = client.get(reverse("home")).content.decode()
    assert "Book your court." in html
    assert "Find a court" in html
    assert "Futsal" in html
    assert "Indoor cricket" in html
    assert "Malabe" in html
    assert "Today" in html
    assert "Tomorrow" in html
    assert html.count('name="date"') == 14
    for label in ("Any time", "Morning", "Afternoon", "Evening", "Night"):
        assert label in html


def test_home_shows_next_game_for_signed_in_players(client, player, court, clock):
    booking = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 8, 18, 0)
    )
    client.force_login(player)
    html = client.get(reverse("home")).content.decode()
    assert "Next game" in html
    assert booking.display_reference in html


def test_bottom_navigation(client, clock):
    html = client.get(reverse("home")).content.decode()
    for label in ("Search", "My bookings", "Account"):
        assert f">{label}</a>" in html


# ---------------------------------------------------------------- P2 results


def test_results_list_free_times_with_prices(client, venue, court, clock):
    html = search(client).content.decode()
    assert "Arena A" in html
    assert "from Rs. 3,000" in html
    assert "6:00 am" in html
    assert f"court={court.pk}&amp;start=2026-12-08T06:00" in html
    assert "More times" in html


def test_only_approved_venues_in_the_area_with_the_sport(client, venue, court, clock):
    draft = make_venue(name="Draft Arena")
    make_court(draft)
    approved_venue("Kotte Arena", area_slug="kotte")
    approved_venue("Cricket Only", sports=["indoor_cricket"])
    html = search(client).content.decode()
    assert "Arena A" in html
    for name in ("Draft Arena", "Kotte Arena", "Cricket Only"):
        assert name not in html
    assert "Cricket Only" in search(client, sport="indoor_cricket").content.decode()


def test_time_of_day_filter(client, venue, court, clock):
    html = search(client, time="evening").content.decode()
    assert "5:00 pm" in html
    assert "8:00 pm" in html
    assert "4:00 pm" not in html
    assert "9:00 pm" not in html


def test_booked_slots_are_never_listed(client, venue, court, clock):
    walk_in(venue, court, at(2026, 12, 8, 17, 0), hours=4)
    html = search(client, time="evening").content.decode()
    assert "No free courts for" in html
    assert "Try the next day" in html
    assert "date=2026-12-09" in html
    assert "time=any" in html


def test_closed_venues_left_out(client, venue, court, clock):
    OpeningHours.objects.for_venue(venue).filter(weekday=1).update(is_closed=True)
    assert "Arena A" not in search(client).content.decode()


def test_today_hides_past_and_short_notice_slots(client, venue, court, clock):
    html = search(client, date=NOW.date().isoformat()).content.decode()
    assert "start=2026-12-07T11:00" in html
    assert "start=2026-12-07T10:00" not in html


def test_beyond_horizon_message(client, venue, court, clock):
    VenueSettings.objects.for_venue(venue).update(booking_horizon_days=3)
    html = search(client, date="2026-12-12").content.decode()
    assert "Bookings open up to 3 days ahead." in html


def test_htmx_filter_change_returns_only_results(client, venue, court, clock):
    response = client.get(
        reverse("search"),
        {"sport": "futsal", "area": "malabe", "date": TUESDAY, "time": "any"},
        HTTP_HX_REQUEST="true",
    )
    html = response.content.decode()
    assert "<html" not in html
    assert "Arena A" in html


def test_invalid_search_asks_for_filters(client, clock):
    response = client.get(reverse("search"), {"sport": "tennis"})
    assert response.status_code == 200
    assert "Choose a sport, an area and a day." in response.content.decode()


def test_search_query_count_does_not_grow_with_venues(clock):
    for i in range(2):
        approved_venue(f"Venue {i}")
    with CaptureQueriesContext(connection) as few:
        selectors.search(sport="futsal", area=area(), day=at(2026, 12, 8, 12, 0).date())
    for i in range(2, 8):
        approved_venue(f"Venue {i}")
    with CaptureQueriesContext(connection) as many:
        results = selectors.search(sport="futsal", area=area(), day=at(2026, 12, 8, 12, 0).date())
    assert len(results) == 8
    assert len(many) == len(few)


# ---------------------------------------------------------------- P3 venue page


def venue_page(client, venue, **params):
    return client.get(reverse("venue_page", args=[venue.slug]), params)


def test_venue_page_shows_courts_free_times_and_prices(client, venue, court, clock):
    html = venue_page(client, venue, date=TUESDAY).content.decode()
    assert "Arena A" in html
    assert "Court 1" in html
    assert "Futsal" in html
    assert "5:00 pm" in html
    assert "Rs. 4,000" in html
    assert f'href="tel:{venue.phone}"' in html
    assert "Free cancellation up to 6 hours before" in html


def test_booked_and_blocked_times_show_as_unavailable_without_reason(client, venue, court, clock):
    walk_in(venue, court, at(2026, 12, 8, 18, 0))
    services.create_block(
        venue=venue,
        actor=venue.owner,
        court_ids=[court.pk],
        start_at=at(2026, 12, 8, 7, 0),
        end_at=at(2026, 12, 8, 8, 0),
        reason="maintenance",
        notes="Painting",
    )
    html = venue_page(client, venue, date=TUESDAY).content.decode()
    assert html.count("Unavailable") == 2
    assert "Maintenance" not in html
    assert "Painting" not in html
    assert "start=2026-12-08T18:00" not in html


def test_day_strip_uses_htmx_partial(client, venue, court, clock):
    response = client.get(
        reverse("venue_page", args=[venue.slug]), {"date": TUESDAY}, HTTP_HX_REQUEST="true"
    )
    html = response.content.decode()
    assert "<html" not in html
    assert "Court 1" in html


@pytest.mark.parametrize(
    ("setup", "text"),
    [
        ("closed", "Closed on Tue 8 Dec."),
        ("horizon", "Online booking opens 3 days ahead."),
    ],
)
def test_day_messages(client, venue, court, clock, setup, text):
    if setup == "closed":
        OpeningHours.objects.for_venue(venue).filter(weekday=1).update(is_closed=True)
        date = TUESDAY
    else:
        VenueSettings.objects.for_venue(venue).update(booking_horizon_days=3)
        date = "2026-12-12"
    assert text in venue_page(client, venue, date=date).content.decode()


def test_fully_booked_day_points_to_the_next_free_day(client, venue, court, clock):
    walk_in(venue, court, at(2026, 12, 8, 6, 0), hours=18)
    html = venue_page(client, venue, date=TUESDAY).content.decode()
    assert "Fully booked on Tue 8 Dec." in html
    assert "?date=2026-12-09" in html


def test_unapproved_venue_shows_call_only(client, clock):
    draft = make_venue(name="Draft Arena")
    make_court(draft)
    html = venue_page(client, draft).content.decode()
    assert (
        "isn&#x27;t taking online bookings yet" in html
        or "isn't taking online bookings yet" in html
    )
    assert "book/review" not in html
    assert "tel:" in html


def test_bad_date_and_unknown_slug(client, venue, court, clock):
    assert venue_page(client, venue, date="not-a-date").status_code == 200
    assert (
        "Choose today or a later day."
        in venue_page(client, venue, date="2026-01-01").content.decode()
    )
    assert client.get(reverse("venue_page", args=["no-such-venue"])).status_code == 404


def test_late_night_slots_are_marked_next_day(client, venue, court, clock):
    OpeningHours.objects.for_venue(venue).filter(weekday=1).update(closes_minute=1500)
    html = venue_page(client, venue, date=TUESDAY).content.decode()
    assert "12:00 am" in html
    assert "next day" in html
