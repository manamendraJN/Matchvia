"""Database constraints: bad values are rejected even if written outside Django (data-model 1)."""

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from pricing.models import PeakPeriod
from venues.models import (
    Area,
    Court,
    MemberRole,
    OpeningHours,
    Venue,
    VenueMembership,
    VenueSettings,
)

from .factories import make_court

pytestmark = pytest.mark.django_db


def rejected(queryset, **values):
    with pytest.raises(IntegrityError), transaction.atomic():
        queryset.update(**values)


def test_launch_areas_exist():
    assert list(Area.objects.values_list("name", flat=True)) == [
        "Malabe",
        "Battaramulla",
        "Athurugiriya",
        "Kaduwela",
        "Kotte",
        "Maharagama",
        "Nugegoda",
    ]
    assert str(Area.objects.first()) == "Malabe"


@pytest.mark.parametrize("minutes", [0, 45, 15, 180])
def test_court_slot_length_must_be_30_60_90_or_120(court, minutes):
    rejected(Court.objects.filter(pk=court.pk), slot_minutes=minutes)


def test_court_prices_capped_at_100000(court):
    rejected(Court.objects.filter(pk=court.pk), peak_price_lkr=100_001)
    Court.objects.filter(pk=court.pk).update(peak_price_lkr=100_000)


@pytest.mark.parametrize("sports", [[], ["tennis"], ["futsal", "badminton"]])
def test_court_sports_must_be_known_and_not_empty(court, sports):
    rejected(Court.objects.filter(pk=court.pk), sports=sports)


def test_court_can_support_both_sports(venue):
    court = make_court(venue, sports=["futsal", "indoor_cricket"])
    assert court.get_sports_display() == "Futsal · Indoor cricket"
    assert str(court) == "Court 1"


def test_court_names_unique_per_venue(venue, other_venue):
    make_court(venue, name="Court 1")
    make_court(other_venue, name="Court 1")  # same name at another venue is fine
    with pytest.raises(IntegrityError), transaction.atomic():
        make_court(venue, name="Court 1")


@pytest.mark.parametrize(
    ("opens", "closes"),
    [
        (120, 1440),
        (600, 600),
        (900, 600),
        (360, 1650),
    ],  # before 03:00, empty, reversed, after 03:00
)
def test_opening_hours_window_checked(venue, opens, closes):
    rejected(
        OpeningHours.objects.for_venue(venue).filter(weekday=0),
        opens_minute=opens,
        closes_minute=closes,
    )


def test_closed_day_skips_the_window_check(venue):
    OpeningHours.objects.for_venue(venue).filter(weekday=0).update(
        is_closed=True, opens_minute=0, closes_minute=0
    )


def test_one_hours_row_per_weekday(venue):
    with pytest.raises(IntegrityError), transaction.atomic():
        OpeningHours.objects.create(venue=venue, weekday=0)
    rejected(OpeningHours.objects.for_venue(venue).filter(weekday=6), weekday=7)


def test_closing_at_three_am_allowed(venue):
    OpeningHours.objects.for_venue(venue).filter(weekday=4).update(
        opens_minute=1080, closes_minute=1620
    )


@pytest.mark.parametrize(
    ("lat", "lng"),
    [("51.5", "-0.12"), ("6.9", None), (None, "79.9"), ("6.9", "85.0"), ("4.0", "79.9")],
)
def test_location_must_be_in_sri_lanka_and_complete(venue, lat, lng):
    rejected(
        Venue.objects.filter(pk=venue.pk),
        latitude=Decimal(lat) if lat else None,
        longitude=Decimal(lng) if lng else None,
    )


def test_unknown_facility_and_status_rejected(venue):
    rejected(Venue.objects.filter(pk=venue.pk), facilities=["pool"])
    rejected(Venue.objects.filter(pk=venue.pk), status="live")
    from django.db import connection

    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE venues_venue SET phone = %s WHERE id = %s", ["0771234567", venue.pk])


@pytest.mark.parametrize(
    "values",
    [
        {"booking_horizon_days": 0},
        {"booking_horizon_days": 61},
        {"min_notice_minutes": 1441},
        {"max_slots_per_booking": 7},
        {"max_upcoming_online_bookings": 11},
        {"cancellation_window_hours": 73},
        {"reminder_lead_hours": 0},
        {"recurring_approver": "anyone"},
        {"recurring_default_weeks": 13},
        {"recurring_max_weeks": 13},
        {"recurring_default_weeks": 10, "recurring_max_weeks": 8},
    ],
)
def test_settings_ranges_enforced(venue, values):
    rejected(VenueSettings.objects.for_venue(venue), **values)


def test_one_membership_per_person_per_venue(venue, owner):
    with pytest.raises(IntegrityError), transaction.atomic():
        VenueMembership.objects.create(venue=venue, user=owner, role=MemberRole.STAFF)
    rejected(VenueMembership.objects.for_venue(venue), role="manager")


def test_peak_period_window_checked(venue):
    period = PeakPeriod.objects.for_venue(venue).first()
    rejected(PeakPeriod.objects.filter(pk=period.pk), starts_minute=1000, ends_minute=900)
    rejected(PeakPeriod.objects.filter(pk=period.pk), weekday=7)


def test_for_venue_scopes_every_venue_table(venue, court, other_venue):
    for model in (Court, OpeningHours, PeakPeriod, VenueMembership, VenueSettings):
        rows = model.objects.for_venue(venue)
        assert rows.exists()
        assert not rows.filter(venue=other_venue).exists()


def test_public_venues_are_approved_only(venue, other_venue):
    assert list(Venue.objects.public()) == []
    Venue.objects.filter(pk=other_venue.pk).update(status="approved")
    assert list(Venue.objects.public()) == [other_venue]
    for status in ["draft", "pending", "rejected", "suspended"]:
        Venue.objects.filter(pk=venue.pk).update(status=status)
        assert venue not in Venue.objects.public()


def test_str_methods(venue, owner):
    assert str(venue) == "Arena A"
    assert str(venue.settings).startswith("Settings for venue")
    assert "owner" in str(VenueMembership.objects.for_venue(venue).get())
    assert str(OpeningHours.objects.for_venue(venue).first()) == "Weekday 0"
    assert str(PeakPeriod.objects.for_venue(venue).first()).startswith("Weekday 0")
    assert not venue.is_public


def test_venue_court_composite_key_target_exists(venue):
    """UQ (id, venue) on Court is what bookings' composite foreign key will point at (C4)."""
    names = {c.name for c in Court._meta.constraints}
    assert "court_id_venue_unique" in names
