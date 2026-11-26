"""Venue isolation (CLAUDE.md rule 2, NFR-06, data-model 6.4).

For every venue-side URL: the owner and the staff of venue A use venue B's ids and get 404, and
nothing about venue B changes. A meta-test fails if a new venue URL is not registered here.
"""

import pytest
from django.urls import URLPattern, reverse

from accounts.tests.factories import UserFactory
from venues import services, urls
from venues.models import Court, OpeningHours, Venue, VenuePhoto

from .factories import add_staff, area, image_file, make_court, make_venue

pytestmark = pytest.mark.django_db


def _court_data(prefix=""):
    return {
        f"{prefix}name": "Hacked court",
        f"{prefix}sports": ["futsal"],
        f"{prefix}is_indoor": "True",
        f"{prefix}slot_minutes": "60",
        f"{prefix}off_peak_price_lkr": "1",
        f"{prefix}peak_price_lkr": "1",
    }


def _hours_data():
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
                f"day-{i}-opens_minute": "600",
                f"day-{i}-closes_minute": "660",
            }
        )
    return data


def _prices_data(target):
    data = {"peak-TOTAL_FORMS": "0", "peak-INITIAL_FORMS": "0"}
    for court in Court.objects.for_venue(target):
        data[f"court-{court.pk}-off_peak_price_lkr"] = "1"
        data[f"court-{court.pk}-peak_price_lkr"] = "1"
    return data


def _profile_data():
    return {"name": "Hacked", "area": str(area().pk), "phone": "0711111111", "address": "x"}


# URL name -> (extra URL kwargs for target venue T, POST data for target venue T).
# Every URL under /manage/<venue_id>/ must be listed (see test_every_venue_url_is_registered).
REGISTRY = {
    "dashboard": (lambda t: {}, lambda t: {}),
    "profile": (lambda t: {}, lambda t: _profile_data()),
    "photo_add": (lambda t: {}, lambda t: {"image": image_file()}),
    "photo_remove": (lambda t: {"photo_id": t.photo.pk}, lambda t: {}),
    "logo": (lambda t: {}, lambda t: {"image": image_file(fmt="PNG", name="l.png")}),
    "cover": (lambda t: {}, lambda t: {"image": image_file()}),
    "submit": (lambda t: {}, lambda t: {}),
    "courts": (lambda t: {}, lambda t: {}),
    "court_create": (lambda t: {}, lambda t: _court_data()),
    "court_edit": (lambda t: {"court_id": t.court.pk}, lambda t: _court_data()),
    "court_toggle": (lambda t: {"court_id": t.court.pk}, lambda t: {}),
    "hours": (lambda t: {}, lambda t: _hours_data()),
    "prices": (lambda t: {}, lambda t: _prices_data(t)),
}
# Who may use each URL on their own venue: "members" (owner and staff can GET; only owners
# POST) or "owner" (staff get 404 for every method). "all" = owner and staff, any method.
ACCESS = {
    "dashboard": "all",
    "courts": "all",
    "profile": "members",
    "hours": "members",
    "prices": "members",
    "photo_add": "owner",
    "photo_remove": "owner",
    "logo": "owner",
    "cover": "owner",
    "submit": "owner",
    "court_create": "owner",
    "court_edit": "owner",
    "court_toggle": "owner",
}


def venue_urls() -> set[str]:
    return {
        p.name
        for p in urls.urlpatterns
        if isinstance(p, URLPattern) and "venue_id" in p.pattern.converters
    }


def test_every_venue_url_is_registered():
    """Adding a venue URL without an isolation test fails here (data-model 6.4)."""
    assert venue_urls() == set(REGISTRY)
    assert set(ACCESS) == set(REGISTRY)


def fingerprint(venue: Venue):
    venue = Venue.objects.get(pk=venue.pk)
    return (
        venue.name,
        venue.status,
        venue.address,
        venue.phone,
        venue.facilities,
        venue.logo.name,
        venue.cover_photo.name,
        venue.updated_at,
        list(
            Court.objects.for_venue(venue).values_list(
                "name", "is_active", "off_peak_price_lkr", "peak_price_lkr", "updated_at"
            )
        ),
        list(
            OpeningHours.objects.for_venue(venue).values_list(
                "is_closed", "opens_minute", "closes_minute"
            )
        ),
        list(venue.peak_periods.values_list("weekday", "starts_minute", "ends_minute")),
        list(VenuePhoto.objects.for_venue(venue).values_list("pk", "image")),
        venue.memberships.count(),
    )


@pytest.fixture
def venue_a():
    venue = make_venue(name="Arena A", address="1 A Road", latitude="6.9", longitude="79.9")
    venue.owner = venue.memberships.get().user
    venue.staff = add_staff(venue)
    venue.court = make_court(venue)
    venue.photo = services.add_photo(venue, venue.owner, image_file())
    return venue


@pytest.fixture
def venue_b():
    venue = make_venue(name="Arena B", address="2 B Road", latitude="6.8", longitude="79.8")
    venue.owner = venue.memberships.get().user
    venue.court = make_court(venue, name="Court B1")
    venue.photo = services.add_photo(venue, venue.owner, image_file())
    return venue


@pytest.mark.parametrize("name", sorted(REGISTRY))
@pytest.mark.parametrize("attacker_role", ["owner", "staff"])
def test_other_venue_is_not_found_and_unchanged(client, venue_a, venue_b, name, attacker_role):
    attacker = getattr(venue_a, attacker_role)
    client.force_login(attacker)
    kwargs_for, data_for = REGISTRY[name]
    url = reverse(f"manage:{name}", kwargs={"venue_id": venue_b.pk, **kwargs_for(venue_b)})
    before = fingerprint(venue_b)

    assert client.get(url).status_code == 404
    assert client.post(url, data_for(venue_b)).status_code == 404
    assert fingerprint(venue_b) == before


def urls_with_object_ids() -> set[str]:
    return {
        p.name
        for p in urls.urlpatterns
        if isinstance(p, URLPattern) and set(p.pattern.converters) - {"venue_id"}
    }


OBJECT_URLS = ["court_edit", "court_toggle", "photo_remove"]


def test_object_url_list_is_complete():
    assert urls_with_object_ids() == set(OBJECT_URLS)


@pytest.mark.parametrize("name", OBJECT_URLS)
def test_other_venues_objects_not_found_through_own_venue(client, venue_a, venue_b, name):
    """Own venue id in the URL, but venue B's court or photo id: 404, B unchanged."""
    client.force_login(venue_a.owner)
    kwargs_for, data_for = REGISTRY[name]
    url = reverse(f"manage:{name}", kwargs={"venue_id": venue_a.pk, **kwargs_for(venue_b)})
    before = fingerprint(venue_b)

    assert client.get(url).status_code in (404, 405)
    assert client.post(url, data_for(venue_b)).status_code == 404
    assert fingerprint(venue_b) == before


def test_prices_post_ignores_other_venues_court_fields(client, venue_a, venue_b):
    """Court ids never come from the request: B's court fields in A's form are ignored."""
    client.force_login(venue_a.owner)
    data = {**_prices_data(venue_a), **_prices_data(venue_b)}
    data[f"court-{venue_a.court.pk}-off_peak_price_lkr"] = "2222"
    before = fingerprint(venue_b)

    response = client.post(reverse("manage:prices", kwargs={"venue_id": venue_a.pk}), data)

    assert response.status_code == 302
    venue_a.court.refresh_from_db()
    assert venue_a.court.off_peak_price_lkr == 2222
    assert fingerprint(venue_b) == before


@pytest.mark.parametrize("name", sorted(n for n, a in ACCESS.items() if a == "owner"))
def test_staff_get_404_on_owner_only_urls(client, venue_a, name):
    client.force_login(venue_a.staff)
    kwargs_for, data_for = REGISTRY[name]
    url = reverse(f"manage:{name}", kwargs={"venue_id": venue_a.pk, **kwargs_for(venue_a)})
    before = fingerprint(venue_a)

    assert client.get(url).status_code == 404
    assert client.post(url, data_for(venue_a)).status_code == 404
    assert fingerprint(venue_a) == before


@pytest.mark.parametrize("name", sorted(n for n, a in ACCESS.items() if a == "members"))
def test_staff_can_view_but_not_change_settings(client, venue_a, name):
    client.force_login(venue_a.staff)
    kwargs_for, data_for = REGISTRY[name]
    url = reverse(f"manage:{name}", kwargs={"venue_id": venue_a.pk, **kwargs_for(venue_a)})
    before = fingerprint(venue_a)

    response = client.get(url)
    assert response.status_code == 200
    assert b"Only the owner can change these settings." in response.content
    assert client.post(url, data_for(venue_a)).status_code == 404
    assert fingerprint(venue_a) == before


@pytest.mark.parametrize("name", sorted(n for n, a in ACCESS.items() if a == "all"))
def test_staff_can_open_shared_pages(client, venue_a, name):
    client.force_login(venue_a.staff)
    kwargs_for, _data = REGISTRY[name]
    url = reverse(f"manage:{name}", kwargs={"venue_id": venue_a.pk, **kwargs_for(venue_a)})
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_anonymous_users_are_sent_to_sign_in(client, venue_a, name):
    kwargs_for, _data = REGISTRY[name]
    url = reverse(f"manage:{name}", kwargs={"venue_id": venue_a.pk, **kwargs_for(venue_a)})
    response = client.get(url)
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:phone"))


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_players_without_membership_get_404(client, venue_a, name):
    client.force_login(UserFactory())
    kwargs_for, data_for = REGISTRY[name]
    url = reverse(f"manage:{name}", kwargs={"venue_id": venue_a.pk, **kwargs_for(venue_a)})
    before = fingerprint(venue_a)
    assert client.get(url).status_code == 404
    assert client.post(url, data_for(venue_a)).status_code == 404
    assert fingerprint(venue_a) == before


def test_removed_staff_lose_access_on_next_request(client, venue_a):
    client.force_login(venue_a.staff)
    url = reverse("manage:dashboard", kwargs={"venue_id": venue_a.pk})
    assert client.get(url).status_code == 200
    venue_a.memberships.filter(user=venue_a.staff).delete()
    assert client.get(url).status_code == 404


def test_venue_list_shows_only_own_venues(client, venue_a, venue_b):
    client.force_login(venue_a.staff)
    response = client.get(reverse("manage:home"))
    assert b"Arena A" in response.content
    assert b"Arena B" not in response.content


def test_meta_test_catches_an_unregistered_url(monkeypatch):
    """Proves the guard works: a new venue URL without an isolation test is detected."""
    from django.urls import path

    from venues import views

    extra = path("<int:venue_id>/secret/", views.dashboard, name="secret")
    monkeypatch.setattr(urls, "urlpatterns", [*urls.urlpatterns, extra])
    assert "secret" in venue_urls() - set(REGISTRY)
