from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import time_machine

from accounts.tests.factories import UserFactory
from venues.models import Venue
from venues.tests.factories import add_staff, make_court, make_venue

COLOMBO = ZoneInfo("Asia/Colombo")
# "Now" for every booking test: Monday 7 Dec 2026, 10:00 in Colombo.
NOW = datetime(2026, 12, 7, 10, 0, tzinfo=COLOMBO)


def at(*args) -> datetime:
    """A Colombo wall-clock time."""
    return datetime(*args, tzinfo=COLOMBO)


@pytest.fixture
def clock():
    with time_machine.travel(NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture
def venue(db):
    """An approved venue open 06:00-24:00 every day, peak Mon-Fri from 17:00 (defaults)."""
    venue = make_venue(name="Arena A")
    Venue.objects.filter(pk=venue.pk).update(status="approved")
    venue.refresh_from_db()
    venue.owner = venue.memberships.get().user
    venue.staff = add_staff(venue)
    return venue


@pytest.fixture
def court(venue):
    return make_court(venue, name="Court 1", off_peak_price_lkr=3000, peak_price_lkr=4000)


@pytest.fixture
def court2(venue):
    return make_court(venue, name="Court 2", off_peak_price_lkr=2000, peak_price_lkr=2500)


@pytest.fixture
def player(db):
    return UserFactory(name="Nimal Silva")


@pytest.fixture
def other_venue(db):
    venue = make_venue(name="Arena B")
    Venue.objects.filter(pk=venue.pk).update(status="approved")
    venue.refresh_from_db()
    venue.owner = venue.memberships.get().user
    venue.court = make_court(venue, name="B1")
    return venue
