"""Setup wizard for a draft venue: V1-V6, "Step N of 6", continues where the owner stopped."""

import pytest
from django.urls import reverse

from venues import services
from venues.models import Court, OpeningHours, Venue, VenueStatus

from .factories import area, image_file, make_court

pytestmark = pytest.mark.django_db


def url(name, venue, **kwargs):
    return reverse(f"manage:{name}", kwargs={"venue_id": venue.pk, **kwargs})


@pytest.fixture
def owner_client(client, owner):
    client.force_login(owner)
    return client


def hours_data(opens="600", closes="1440"):
    data = {
        "day-TOTAL_FORMS": "7",
        "day-INITIAL_FORMS": "7",
        "day-MIN_NUM_FORMS": "7",
        "day-MAX_NUM_FORMS": "7",
    }
    for i in range(7):
        data.update(
            {
                f"day-{i}-weekday": str(i),
                f"day-{i}-opens_minute": opens,
                f"day-{i}-closes_minute": closes,
            }
        )
    return data


def test_full_setup_from_list_my_venue_to_submitted(owner_client, owner):
    # V1: details. The page already says step 1 of 6.
    page = owner_client.get(reverse("manage:create"))
    assert "Step 1 of 6 · Details" in page.content.decode()
    response = owner_client.post(
        reverse("manage:create"),
        {"name": "Kick Off Arena", "area": area().pk, "phone": "077 999 8888"},
    )
    venue = Venue.objects.get(name="Kick Off Arena")
    assert response.url == url("setup_location", venue)

    # V2: location, with the map and the photo forms on the page.
    page = owner_client.get(url("setup_location", venue)).content.decode()
    assert "Step 2 of 6 · Location and photos" in page
    assert "data-venue-map" in page
    assert "vendor/leaflet/leaflet.js" in page
    assert 'name="return_to" value="setup"' in page
    response = owner_client.post(
        url("setup_location", venue),
        {"address": "12 Main Street", "latitude": "6.904", "longitude": "79.954"},
    )
    assert response.url == url("setup_courts", venue)

    # V3: courts. Next without a court is refused.
    response = owner_client.post(url("setup_courts", venue), {"next": "1"}, follow=True)
    assert "Add at least one court." in response.content.decode()
    response = owner_client.post(
        url("setup_courts", venue),
        {
            "add": "1",
            "name": "Court 1",
            "sports": ["futsal", "indoor_cricket"],
            "is_indoor": "True",
            "slot_minutes": "60",
        },
    )
    assert response.url == url("setup_courts", venue)
    court = Court.objects.get(venue=venue)
    assert (court.off_peak_price_lkr, court.peak_price_lkr) == (0, 0)  # priced in step 5
    response = owner_client.post(url("setup_courts", venue), {"next": "1"})
    assert response.url == url("setup_hours", venue)

    # V4: hours (defaults filled in).
    assert "Step 4 of 6" in owner_client.get(url("setup_hours", venue)).content.decode()
    response = owner_client.post(url("setup_hours", venue), hours_data())
    assert response.url == url("setup_prices", venue)
    assert OpeningHours.objects.get(venue=venue, weekday=0).opens_minute == 600

    # V5: prices.
    response = owner_client.post(
        url("setup_prices", venue),
        {
            f"court-{court.pk}-off_peak_price_lkr": "3000",
            f"court-{court.pk}-peak_price_lkr": "4000",
            "peak-TOTAL_FORMS": "0",
            "peak-INITIAL_FORMS": "0",
        },
    )
    assert response.url == url("setup_review", venue)

    # V6: review shows every part with Edit, then submit.
    page = owner_client.get(url("setup_review", venue)).content.decode()
    assert "Step 6 of 6 · Review and submit" in page
    assert "12 Main Street" in page
    assert "Rs. 3,000 normal" in page
    assert "Still to do" not in page
    response = owner_client.post(url("submit", venue))
    venue.refresh_from_db()
    assert venue.status == VenueStatus.PENDING
    assert response.url == url("dashboard", venue)


def test_setup_continues_where_the_owner_stopped(owner_client, venue):
    assert owner_client.get(url("setup", venue)).url == url("setup_location", venue)
    services.finish_setup_step(venue, venue.memberships.get().user, 3)
    assert owner_client.get(url("setup", venue)).url == url("setup_hours", venue)
    services.finish_setup_step(venue, venue.memberships.get().user, 5)
    assert owner_client.get(url("setup", venue)).url == url("setup_review", venue)


def test_going_back_never_loses_progress(owner, venue):
    services.finish_setup_step(venue, owner, 4)
    services.finish_setup_step(venue, owner, 2)
    venue.refresh_from_db()
    assert venue.setup_step == 4
    with pytest.raises(ValueError, match="Unknown setup step"):
        services.finish_setup_step(venue, owner, 6)


def test_my_venues_opens_setup_for_a_draft(owner_client, venue):
    html = owner_client.get(reverse("manage:home")).content.decode()
    assert url("setup", venue) in html
    page = owner_client.get(url("dashboard", venue)).content.decode()
    assert "Continue setup" in page


def test_staff_and_submitted_venues_use_the_dashboard(client, owner, venue, staff):
    client.force_login(staff)
    assert url("setup", venue) not in client.get(reverse("manage:home")).content.decode()
    assert client.get(url("setup", venue)).status_code == 404

    owner_client = client
    owner_client.force_login(owner)
    Venue.objects.filter(pk=venue.pk).update(status=VenueStatus.PENDING)
    assert owner_client.get(url("setup_location", venue)).url == url("dashboard", venue)
    assert url("setup", venue) not in owner_client.get(reverse("manage:home")).content.decode()


def test_details_step_edits_name_area_and_phone(owner_client, venue):
    page = owner_client.get(url("setup_details", venue)).content.decode()
    assert "Step 1 of 6 · Details" in page
    response = owner_client.post(
        url("setup_details", venue), {"name": "New Name", "area": area().pk, "phone": "0771112222"}
    )
    assert response.url == url("setup_location", venue)
    venue.refresh_from_db()
    assert (venue.name, venue.phone, venue.setup_step) == ("New Name", "+94771112222", 1)


def test_location_step_checks_the_pin(owner_client, venue):
    response = owner_client.post(
        url("setup_location", venue), {"latitude": "51.5", "longitude": "0.1"}
    )
    assert response.status_code == 200
    assert "The pin is outside Sri Lanka." in response.content.decode()


def test_photos_added_during_setup_return_to_the_setup_step(owner_client, venue):
    response = owner_client.post(
        url("photo_add", venue), {"image": image_file(), "return_to": "setup"}
    )
    assert response.url == url("setup_location", venue)
    response = owner_client.post(url("photo_add", venue), {"image": image_file()})
    assert response.url == url("profile", venue)


def test_court_edit_and_duplicate_names_in_setup(owner_client, venue):
    court = make_court(venue)
    page = owner_client.get(url("setup_court_edit", venue, court_id=court.pk)).content.decode()
    assert "Normal price" not in page  # prices are step 5
    data = {"name": "Main court", "sports": ["futsal"], "is_indoor": "False", "slot_minutes": "90"}
    response = owner_client.post(url("setup_court_edit", venue, court_id=court.pk), data)
    assert response.url == url("setup_courts", venue)
    court.refresh_from_db()
    assert (court.name, court.is_indoor, court.slot_minutes) == ("Main court", False, 90)

    response = owner_client.post(url("setup_courts", venue), {**data, "add": "1"})
    assert response.status_code == 200
    assert Court.objects.filter(venue=venue).count() == 1


def test_review_lists_what_is_missing_and_free_courts(owner_client, venue):
    make_court(venue, off_peak_price_lkr=0, peak_price_lkr=0)
    page = owner_client.get(url("setup_review", venue)).content.decode()
    assert "Still to do before you can submit" in page
    assert "Add the address" in page
    assert "Court 1: the price is Rs. 0. Is that right?" in page
    assert "disabled" in page
    response = owner_client.post(url("submit", venue))
    assert response.url == url("setup_review", venue)


def test_hours_and_prices_steps_show_errors(owner_client, venue):
    response = owner_client.post(url("setup_hours", venue), hours_data("900", "600"))
    assert response.status_code == 200
    assert "Closing time must be after opening time." in response.content.decode()
    court = make_court(venue)
    response = owner_client.post(
        url("setup_prices", venue),
        {
            f"court-{court.pk}-off_peak_price_lkr": "",
            f"court-{court.pk}-peak_price_lkr": "4000",
            "peak-TOTAL_FORMS": "0",
            "peak-INITIAL_FORMS": "0",
        },
    )
    assert response.status_code == 200
    assert "Enter a price (Rs. 0 if free)." in response.content.decode()


def test_venue_tab_has_the_map_too(owner_client, venue):
    page = owner_client.get(url("profile", venue)).content.decode()
    assert "data-venue-map" in page
