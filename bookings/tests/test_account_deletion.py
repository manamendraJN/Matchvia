"""Complete account deletion across apps (US-P08, BR-25, data-model 9)."""

from datetime import date

import pytest
from django.urls import reverse

from accounts import services as accounts
from accounts.models import DELETED_USER_NAME, OTPChallenge, User
from accounts.tests.conftest import last_code
from accounts.tests.factories import UserFactory
from bookings import services
from bookings.models import Booking, BookingEvent, RecurringSeries, Source, Status
from core.exceptions import RuleViolation
from notifications.models import SmsMessage
from teams import services as teams
from teams.models import TeamInvite, TeamMembership
from venues.models import Venue, VenueCustomer, VenueMembership
from venues.tests.factories import add_staff, make_venue

from .conftest import at

pytestmark = pytest.mark.django_db

IP = "198.51.100.7"


def delete_with_code(user):
    accounts.request_deletion_code(user, ip=IP)
    return accounts.delete_account(user, code=last_code(user.phone), ip=IP)


def phone_is_gone(phone):
    """A database search for the number finds nothing (build-plan S26 'done when')."""
    return not any(
        [
            User.objects.filter(phone=phone).exists(),
            VenueCustomer.objects.filter(phone=phone).exists(),
            SmsMessage.objects.filter(to_phone=phone).exists(),
            TeamInvite.objects.filter(phone=phone).exists(),
            OTPChallenge.objects.filter(phone=phone).exists(),
        ]
    )


def test_deletion_cancels_future_bookings_and_anonymises_everything(
    venue, court, court2, other_venue, player, clock
):
    phone = player.phone
    past = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 8, 18, 0)
    )
    future = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 10, 18, 0)
    )
    series, weeks = services.create_staff_series(
        venue=venue,
        actor=venue.owner,
        court_id=court2.pk,
        first_date=date(2026, 12, 14),
        start_minute=20 * 60,
        duration_minutes=60,
        weeks=4,
        customer_name="Nimal",
        customer_phone=phone,
    )
    captain = UserFactory(name="Kasun")
    team = teams.create_team(captain, name="Malabe Strikers", sport="futsal")
    TeamMembership.objects.create(team=team, user=player)
    other_team = teams.create_team(captain, name="Kandy Kings", sport="futsal")
    teams.invite(captain, other_team.pk, phone=phone)
    add_staff(other_venue, user=player)
    events_before = BookingEvent.objects.count()

    clock.move_to(at(2026, 12, 9, 9, 0))  # the first booking is now in the past
    cancelled = delete_with_code(player)

    assert cancelled == 1 + len(weeks)
    past.refresh_from_db()
    future.refresh_from_db()
    assert past.status == Status.CONFIRMED
    assert past.customer_name == DELETED_USER_NAME
    assert future.status == Status.CANCELLED
    assert future.cancel_reason == "customer_request"
    assert future.customer_name == DELETED_USER_NAME
    assert not Booking.objects.filter(series=series, status=Status.CONFIRMED).exists()
    series.refresh_from_db()
    assert series.status == "cancelled"
    customer = VenueCustomer.objects.get(pk=future.venue_customer_id)
    assert (customer.phone, customer.user, customer.name) == (None, None, DELETED_USER_NAME)
    # Teams and staff roles end; invites to the number are gone.
    assert not TeamMembership.objects.filter(user=player).exists()
    assert not VenueMembership.objects.filter(user=player).exists()
    # One SMS to the venue's owner, with no name or number in it; none for the other venue.
    notices = list(SmsMessage.objects.filter(purpose="venue_notice"))
    assert len(notices) == 1
    assert notices[0].to_phone == venue.owner.phone
    assert notices[0].venue_id == venue.pk
    assert f"{cancelled} upcoming bookings at Arena A are cancelled" in notices[0].body
    assert "Nimal" not in notices[0].body
    # The audit log only grew (cancel events); nothing was rewritten.
    assert BookingEvent.objects.count() == events_before + cancelled
    assert phone_is_gone(phone)


def test_one_cancelled_booking_gets_the_short_venue_sms(venue, court, player, clock):
    services.create_online_booking(user=player, court_id=court.pk, start_at=at(2026, 12, 10, 18, 0))
    delete_with_code(player)
    body = SmsMessage.objects.get(purpose="venue_notice").body
    assert body.startswith("Matchvia: A player deleted their account. Their booking at Arena A on")
    assert len(body) <= 160


def test_phone_bookings_on_the_number_are_covered_too(venue, court, player, clock):
    """A staff booking for the number made before it was linked still loses the name."""
    booking = services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=at(2026, 12, 10, 18, 0),
        end_at=at(2026, 12, 10, 19, 0),
        source=Source.PHONE,
        customer_name="Nimal",
        customer_phone=player.phone,
    )
    VenueCustomer.objects.filter(pk=booking.venue_customer_id).update(user=None)
    phone = player.phone

    delete_with_code(player)

    booking.refresh_from_db()
    assert booking.status == Status.CANCELLED
    assert booking.customer_name == DELETED_USER_NAME
    assert phone_is_gone(phone)


def test_pending_weekly_request_is_withdrawn(venue, court, player, clock):
    team = teams.create_team(player, name="Nimal's Five", sport="futsal")
    series = services.request_series(
        user=player,
        team_id=team.pk,
        court_id=court.pk,
        first_date=date(2026, 12, 15),
        start_minute=20 * 60,
        duration_minutes=60,
        weeks=4,
    )
    teams.close_team(player, team.pk)  # a captain must close or hand over first

    delete_with_code(player)

    series.refresh_from_db()
    assert series.status == "cancelled"


# ---------------------------------------------------------------- who must hand over first


def test_sole_owner_of_a_live_venue_must_hand_over_first(client, venue, clock):
    owner = venue.owner
    blockers = accounts.deletion_blockers(owner)
    assert [b.message for b in blockers] == [
        "You own Arena A. Add another owner on its Staff page first, "
        "or ask Matchvia support to close it."
    ]
    assert blockers[0].url == reverse("manage:staff", args=[venue.pk])
    with pytest.raises(RuleViolation, match="You own Arena A"):
        accounts.request_deletion_code(owner, ip=IP)

    client.force_login(owner)
    page = client.get(reverse("me:delete"))
    assert "You own Arena A" in page.content.decode()
    assert "Send confirmation code" not in page.content.decode()
    response = client.post(reverse("me:delete"))
    assert response.status_code == 409
    assert not SmsMessage.objects.filter(purpose="otp").exists()


def test_co_owner_and_draft_venue_owner_can_delete(venue, clock):
    co_owner = UserFactory(name="Co")
    VenueMembership.objects.create(venue=venue, user=co_owner, role="owner")
    assert accounts.deletion_blockers(venue.owner) == []
    assert accounts.deletion_blockers(co_owner) == []

    drafter = UserFactory(name="Drafter")
    draft = make_venue(owner=drafter, name="Draft Arena")
    assert Venue.objects.get(pk=draft.pk).status == "draft"
    assert accounts.deletion_blockers(drafter) == []
    delete_with_code(drafter)
    assert not VenueMembership.objects.filter(user=drafter).exists()


def test_captain_must_hand_over_or_close_first(player, clock):
    team = teams.create_team(player, name="Nimal's Five", sport="futsal")
    blockers = accounts.deletion_blockers(player)
    assert [b.message for b in blockers] == [
        "You captain Nimal's Five. Make another player captain or close the team first."
    ]
    assert blockers[0].url == reverse("team_detail", args=[team.pk])

    mate = UserFactory(name="Mate")
    TeamMembership.objects.create(team=team, user=mate)
    teams.make_captain(player, team.pk, mate.pk)

    assert accounts.deletion_blockers(player) == []
    delete_with_code(player)
    assert TeamMembership.objects.filter(team=team).count() == 1


def test_delete_page_counts_upcoming_bookings(client, venue, court, player, clock):
    services.create_online_booking(user=player, court_id=court.pk, start_at=at(2026, 12, 10, 18, 0))
    client.force_login(player)
    html = client.get(reverse("me:delete")).content.decode()
    assert "Your upcoming booking is cancelled and the venue is told." in html


def test_series_bookings_count_once(venue, court, player, clock):
    services.create_staff_series(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        first_date=date(2026, 12, 14),
        start_minute=20 * 60,
        duration_minutes=60,
        weeks=3,
        customer_name="Nimal",
        customer_phone=player.phone,
    )
    assert services.upcoming_count_for_deletion(player) == 3
    assert RecurringSeries.objects.count() == 1
