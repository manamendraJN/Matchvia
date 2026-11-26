"""Owner screens: create venue, profile, photos, courts, hours, prices, submit (V1–V7, V21–V25)."""

import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory
from pricing.models import PeakPeriod
from venues.models import Court, MemberRole, OpeningHours, Venue, VenueMembership, VenuePhoto

from .factories import area, image_file, make_court, ready_venue

pytestmark = pytest.mark.django_db


def url(name, venue, **kwargs):
    return reverse(f"manage:{name}", kwargs={"venue_id": venue.pk, **kwargs})


@pytest.fixture
def owner_client(client, owner):
    client.force_login(owner)
    return client


# ---------------------------------------------------------------- list and create


def test_venue_list_offers_to_list_a_venue(owner_client):
    response = owner_client.get(reverse("manage:home"))
    assert response.status_code == 200
    assert b"List my venue" in response.content


def test_create_venue_flow(owner_client, owner):
    page = owner_client.get(reverse("manage:create"))
    assert b"077" in page.content  # venue phone pre-filled with the owner's number

    response = owner_client.post(
        reverse("manage:create"),
        {"name": "Kick Off Arena", "area": area("kotte").pk, "phone": "077 999 8888"},
    )

    venue = Venue.objects.get(name="Kick Off Arena")
    assert response.url == url("profile", venue)
    assert venue.phone == "+94779998888"
    assert venue.area.slug == "kotte"
    assert VenueMembership.objects.get(venue=venue).role == MemberRole.OWNER


def test_create_venue_validates(owner_client):
    response = owner_client.post(reverse("manage:create"), {"name": "", "phone": "0112345678"})
    assert response.status_code == 200
    assert b"Enter a valid Sri Lankan mobile number" in response.content
    assert not Venue.objects.exists()


def test_create_venue_requires_sign_in_and_profile(client):
    assert client.get(reverse("manage:create")).status_code == 302
    client.force_login(UserFactory(name="", consented=False))
    response = client.get(reverse("manage:create"))
    assert response.url.startswith(reverse("accounts:welcome"))


def test_account_page_links_to_dashboard(owner_client):
    assert reverse("manage:home").encode() in owner_client.get(reverse("me:account")).content


# ---------------------------------------------------------------- dashboard and profile


def test_dashboard_shows_status_banner_and_missing_items(owner_client, venue):
    response = owner_client.get(url("dashboard", venue))
    assert b"Not live yet" in response.content
    assert b"Add at least one court" in response.content
    assert b"disabled" in response.content  # submit button disabled until ready


def test_save_profile(owner_client, venue):
    response = owner_client.post(
        url("profile", venue),
        {
            "name": "Arena A",
            "area": area().pk,
            "phone": "0771112222",
            "address": "12 Main Street",
            "description": "Two courts",
            "latitude": "6.904123",
            "longitude": "79.954321",
            "facilities": ["parking", "floodlights"],
        },
    )
    assert response.status_code == 302
    venue.refresh_from_db()
    assert venue.address == "12 Main Street"
    assert str(venue.latitude) == "6.904123"
    assert venue.facilities == ["parking", "floodlights"]


def test_pin_outside_sri_lanka_rejected(owner_client, venue):
    response = owner_client.post(
        url("profile", venue),
        {
            "name": "A",
            "area": area().pk,
            "phone": "0771112222",
            "latitude": "51.5",
            "longitude": "-0.1",
        },
    )
    assert b"The pin is outside Sri Lanka." in response.content
    venue.refresh_from_db()
    assert venue.latitude is None


def test_half_a_location_rejected(owner_client, venue):
    response = owner_client.post(
        url("profile", venue),
        {"name": "A", "area": area().pk, "phone": "0771112222", "latitude": "6.9"},
    )
    assert b"Set both latitude and longitude" in response.content


def test_profile_has_geolocation_button_without_inline_js(owner_client, venue):
    html = owner_client.get(url("profile", venue)).content.decode()
    assert "data-geolocate" in html
    assert "onclick" not in html


def test_upload_and_remove_photo(owner_client, venue):
    response = owner_client.post(url("photo_add", venue), {"image": image_file()}, follow=True)
    assert b"Photo added." in response.content
    photo = VenuePhoto.objects.for_venue(venue).get()
    assert photo.image.url.encode() in response.content

    owner_client.post(url("photo_remove", venue, photo_id=photo.pk))
    assert not VenuePhoto.objects.for_venue(venue).exists()


def test_bad_upload_shows_message(owner_client, venue):
    from django.core.files.uploadedfile import SimpleUploadedFile

    bad = SimpleUploadedFile("x.jpg", b"not an image", content_type="image/jpeg")
    response = owner_client.post(url("photo_add", venue), {"image": bad}, follow=True)
    assert b"This file is not a valid image." in response.content
    response = owner_client.post(url("photo_add", venue), {}, follow=True)
    assert b"Choose a photo to upload." in response.content


def test_logo_and_cover_upload(owner_client, venue):
    owner_client.post(url("logo", venue), {"image": image_file(fmt="PNG", name="l.png")})
    owner_client.post(url("cover", venue), {"image": image_file()})
    venue.refresh_from_db()
    assert venue.logo.name.endswith(".png")
    assert venue.cover_photo.name.endswith(".jpg")
    response = owner_client.post(url("cover", venue), {}, follow=True)
    assert b"Choose an image to upload." in response.content
    bad = owner_client.post(
        url("logo", venue), {"image": image_file(fmt="GIF", name="a.gif")}, follow=True
    )
    assert b"JPG, PNG or WebP" in bad.content


def test_submit_for_approval(client):
    venue = ready_venue()
    client.force_login(venue.memberships.get().user)
    response = client.post(url("submit", venue), follow=True)
    assert b"Sent for approval" in response.content
    assert b"Waiting for approval" in response.content
    venue.refresh_from_db()
    assert venue.status == "pending"


def test_submit_incomplete_venue_shows_what_is_missing(owner_client, venue):
    response = owner_client.post(url("submit", venue), follow=True)
    assert b"Before submitting" in response.content
    venue.refresh_from_db()
    assert venue.status == "draft"


@pytest.mark.parametrize(
    ("status", "text"),
    [("rejected", b"Not approved"), ("suspended", b"Suspended"), ("approved", b"Approved")],
)
def test_status_banners(owner_client, venue, status, text):
    Venue.objects.filter(pk=venue.pk).update(status=status, status_reason="Because.")
    response = owner_client.get(url("dashboard", venue))
    assert text in response.content


# ---------------------------------------------------------------- courts


COURT = {
    "name": "Court 1",
    "sports": ["futsal", "indoor_cricket"],
    "is_indoor": "False",
    "slot_minutes": "90",
    "off_peak_price_lkr": "2500",
    "peak_price_lkr": "3500",
}


def test_add_court(owner_client, venue):
    assert b"Court 1" in owner_client.get(url("court_create", venue)).content  # suggested name
    response = owner_client.post(url("court_create", venue), COURT)
    assert response.url == url("courts", venue)
    court = Court.objects.for_venue(venue).get()
    assert court.sports == ["futsal", "indoor_cricket"]
    assert court.slot_minutes == 90
    assert court.is_indoor is False
    page = owner_client.get(url("courts", venue)).content
    assert b"Rs. 2,500 normal" in page
    assert b"Futsal \xc2\xb7 Indoor cricket" in page


def test_court_form_errors(owner_client, venue, court):
    response = owner_client.post(url("court_create", venue), {**COURT, "name": "court 1"})
    assert b"Two courts can&#x27;t have the same name." in response.content
    response = owner_client.post(
        url("court_create", venue), {**COURT, "sports": [], "peak_price_lkr": ""}
    )
    assert b"Choose at least one sport." in response.content
    assert b"Enter a price (Rs. 0 if free)." in response.content
    response = owner_client.post(
        url("court_create", venue), {**COURT, "name": "Court 9", "slot_minutes": "45"}
    )
    assert response.status_code == 200
    assert Court.objects.for_venue(venue).count() == 1


def test_edit_court(owner_client, venue, court):
    assert owner_client.get(url("court_edit", venue, court_id=court.pk)).status_code == 200
    owner_client.post(url("court_edit", venue, court_id=court.pk), {**COURT, "name": "Main pitch"})
    court.refresh_from_db()
    assert court.name == "Main pitch"
    other = make_court(venue, name="Court 2")
    response = owner_client.post(
        url("court_edit", venue, court_id=other.pk), {**COURT, "name": "main pitch"}
    )
    assert b"same name" in response.content


def test_deactivate_and_reactivate_court(owner_client, venue, court):
    response = owner_client.post(url("court_toggle", venue, court_id=court.pk), follow=True)
    assert b"is deactivated" in response.content
    court.refresh_from_db()
    assert not court.is_active
    response = owner_client.post(url("court_toggle", venue, court_id=court.pk), follow=True)
    assert b"is active again" in response.content


# ---------------------------------------------------------------- hours


def hours_data(**overrides):
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
                f"day-{i}-opens_minute": "360",
                f"day-{i}-closes_minute": "1440",
            }
        )
    data.update(overrides)
    return data


def test_hours_page_lists_every_day_with_late_closing_choices(owner_client, venue):
    html = owner_client.get(url("hours", venue)).content.decode()
    for day in ["Monday", "Sunday"]:
        assert day in html
    assert "3:00 am (next day)" in html


def test_save_hours_with_closed_day_and_late_close(owner_client, venue):
    response = owner_client.post(
        url("hours", venue),
        hours_data(
            **{"day-0-is_closed": "on", "day-4-opens_minute": "1080", "day-4-closes_minute": "1560"}
        ),
    )
    assert response.status_code == 302
    rows = {h.weekday: h for h in OpeningHours.objects.for_venue(venue)}
    assert rows[0].is_closed
    assert (rows[4].opens_minute, rows[4].closes_minute) == (1080, 1560)


def test_hours_errors(owner_client, venue):
    response = owner_client.post(
        url("hours", venue),
        hours_data(**{"day-2-opens_minute": "900", "day-2-closes_minute": "600"}),
    )
    assert b"Closing time must be after opening time." in response.content
    all_closed = hours_data(**{f"day-{i}-is_closed": "on" for i in range(7)})
    response = owner_client.post(url("hours", venue), all_closed, follow=True)
    assert b"at least one open day" in response.content


# ---------------------------------------------------------------- prices


def prices_data(court, normal="3000", peak="4000", peaks=()):
    data = {
        f"court-{court.pk}-off_peak_price_lkr": normal,
        f"court-{court.pk}-peak_price_lkr": peak,
        "peak-TOTAL_FORMS": str(len(peaks)),
        "peak-INITIAL_FORMS": "0",
    }
    for i, (weekday, start, end, delete) in enumerate(peaks):
        data.update(
            {
                f"peak-{i}-weekday": weekday,
                f"peak-{i}-starts_minute": start,
                f"peak-{i}-ends_minute": end,
            }
        )
        if delete:
            data[f"peak-{i}-DELETE"] = "on"
    return data


def test_prices_page_shows_courts_and_default_peaks(owner_client, venue, court):
    html = owner_client.get(url("prices", venue)).content.decode()
    assert "Court 1" in html
    assert html.count('name="peak-') > 0
    assert "5:00 pm" in html


def test_save_prices_and_peak_times(owner_client, venue, court):
    response = owner_client.post(
        url("prices", venue),
        prices_data(
            court, "2000", "2800", peaks=[("5", "600", "1320", False), ("6", "600", "1320", True)]
        ),
    )
    assert response.status_code == 302
    court.refresh_from_db()
    assert (court.off_peak_price_lkr, court.peak_price_lkr) == (2000, 2800)
    assert list(
        PeakPeriod.objects.for_venue(venue).values_list("weekday", "starts_minute", "ends_minute")
    ) == [(5, 600, 1320)]


def test_price_errors(owner_client, venue, court):
    response = owner_client.post(url("prices", venue), prices_data(court, normal="200000"))
    assert response.status_code == 200
    response = owner_client.post(
        url("prices", venue), prices_data(court, peaks=[("1", "900", "600", False)])
    )
    assert b"Each peak time must end after it starts." in response.content
    court.refresh_from_db()
    assert court.off_peak_price_lkr == 3000


# ---------------------------------------------------------------- staff see pages read-only


def test_staff_see_profile_read_only(client, venue, staff):
    client.force_login(staff)
    html = client.get(url("profile", venue)).content.decode()
    assert "disabled" in html
    assert "Save details" not in html
    assert "Add photo" not in html
    assert "Use my current location" not in html


def test_staff_see_courts_without_edit_buttons(client, venue, staff, court):
    client.force_login(staff)
    html = client.get(url("courts", venue)).content.decode()
    assert "Court 1" in html
    assert "Add a court" not in html
    assert "Deactivate court" not in html


def test_staff_see_hours_and_prices_without_save(client, venue, staff, court):
    client.force_login(staff)
    assert b"Save hours" not in client.get(url("hours", venue)).content
    assert b"Save prices" not in client.get(url("prices", venue)).content
