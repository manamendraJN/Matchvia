import pytest

from accounts.tests.factories import UserFactory

from .factories import add_staff, make_court, make_venue


@pytest.fixture
def owner(db):
    return UserFactory(name="Owner A")


@pytest.fixture
def venue(owner):
    return make_venue(owner=owner, name="Arena A")


@pytest.fixture
def staff(venue):
    return add_staff(venue, UserFactory(name="Staff A"))


@pytest.fixture
def court(venue):
    return make_court(venue)


@pytest.fixture
def other_venue(db):
    """Venue B, with its own owner, court and settings: must never be reachable from venue A."""
    venue_b = make_venue(owner=UserFactory(name="Owner B"), name="Arena B")
    make_court(venue_b, name="Court B1")
    return venue_b
