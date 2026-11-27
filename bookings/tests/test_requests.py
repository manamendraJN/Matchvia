"""Captain weekly requests, approval and team bookings (US-C03, US-C04, US-O07, BR-13).
'Now' is Mon 7 Dec 2026 10:00 in Colombo."""

from datetime import date, timedelta

import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory
from bookings import services
from bookings.models import Booking, RecurringSeries
from core.exceptions import NotAllowed, RuleViolation
from notifications.models import SmsMessage
from teams import services as teams
from teams.models import Team, TeamMembership
from venues.models import VenueCustomer, VenueSettings

from .conftest import at

pytestmark = pytest.mark.django_db

TUE = date(2026, 12, 8)


@pytest.fixture
def team(player):
    return teams.create_team(player, name="Malabe Strikers", sport="futsal")


def request(player, team, court, *, first=TUE, minute=1200, weeks=4):
    return services.request_series(
        user=player,
        team_id=team.pk,
        court_id=court.pk,
        first_date=first,
        start_minute=minute,
        duration_minutes=60,
        weeks=weeks,
    )


# ---------------------------------------------------------------- requests (US-C04)


def test_request_is_pending_and_reserves_nothing(player, team, venue, court, clock):
    series = request(player, team, court)
    assert series.status == "pending"
    assert series.origin == "captain_request"
    assert series.team == team
    assert series.request_expires_at == at(2026, 12, 9, 10, 0)
    assert not Booking.objects.exists()
    services.create_online_booking(
        user=UserFactory(), court_id=court.pk, start_at=at(2026, 12, 8, 20, 0)
    )


def test_venue_is_notified(player, team, venue, court, clock):
    request(player, team, court)
    phones = set(
        SmsMessage.objects.filter(purpose="venue_notice").values_list("to_phone", flat=True)
    )
    assert phones == {venue.owner.phone, venue.staff.phone}  # owner_or_staff by default (BR-13)
    body = SmsMessage.objects.filter(purpose="venue_notice").first().body
    assert "Malabe Strikers asks for a weekly slot at Arena A: Tue 8:00 pm, 4 weeks." in body


def test_only_captains_can_request(player, venue, court, clock):
    stranger_team = teams.create_team(UserFactory(), name="Other", sport="futsal")
    with pytest.raises(Team.DoesNotExist):
        request(player, stranger_team, court)


def test_first_week_inside_the_notice_moves_a_week(player, team, venue, court, clock):
    series = request(player, team, court, first=date(2026, 12, 7), minute=630)  # today 10:30
    assert series.first_date == date(2026, 12, 14)


def test_request_rules(player, team, venue, court, clock):
    with pytest.raises(RuleViolation, match="between 2 and 12"):
        request(player, team, court, weeks=13)
    VenueCustomer.objects.create(venue=venue, phone=player.phone, name="X", is_blocked_online=True)
    with pytest.raises(NotAllowed, match="contact the venue"):
        request(player, team, court)


# ---------------------------------------------------------------- approve / reject (US-O07)


def test_approve_creates_free_weeks_and_tells_the_captain(player, team, venue, court, clock):
    series = request(player, team, court)
    services.create_staff_booking(
        venue=venue,
        actor=venue.staff,
        court_id=court.pk,
        start_at=at(2026, 12, 15, 20, 0),
        end_at=at(2026, 12, 15, 21, 0),
        source="walk_in",
        customer_name="X",
    )
    approved, created = services.approve_series(venue=venue, actor=venue.staff, series_id=series.pk)
    assert approved.status == "approved"
    assert approved.decided_by == venue.staff
    assert len(created) == 3
    assert approved.skipped == [{"date": "2026-12-15", "reason": "booked"}]
    assert all(b.team == team for b in created)
    summary = SmsMessage.objects.get(purpose="series_summary")
    assert summary.to_phone == player.phone
    assert "Skipped: 15 Dec." in summary.body


def test_owner_only_approval_setting(player, team, venue, court, clock):
    VenueSettings.objects.for_venue(venue).update(recurring_approver="owner")
    venue.settings.refresh_from_db()
    series = request(player, team, court)
    assert venue.staff.phone not in SmsMessage.objects.filter(purpose="venue_notice").values_list(
        "to_phone", flat=True
    )
    with pytest.raises(NotAllowed, match="Only the owner"):
        services.approve_series(venue=venue, actor=venue.staff, series_id=series.pk)
    services.approve_series(venue=venue, actor=venue.owner, series_id=series.pk)


def test_reject_with_reason(player, team, venue, court, clock):
    series = request(player, team, court)
    services.reject_series(
        venue=venue, actor=venue.owner, series_id=series.pk, reason="Court reserved for coaching."
    )
    series.refresh_from_db()
    assert (series.status, series.decision_reason) == ("rejected", "Court reserved for coaching.")
    assert "Court reserved for coaching." in SmsMessage.objects.get(purpose="series_decision").body
    with pytest.raises(RuleViolation, match="already been answered"):
        services.approve_series(venue=venue, actor=venue.owner, series_id=series.pk)


def test_requests_expire_after_48_hours(player, team, venue, court, clock):
    series = request(player, team, court)
    clock.shift(timedelta(hours=47))
    assert services.expire_series_requests() == 0
    clock.shift(timedelta(hours=1))
    assert services.expire_series_requests() == 1
    series.refresh_from_db()
    assert series.status == "expired"
    assert "didn't reply" in SmsMessage.objects.get(purpose="series_decision").body
    with pytest.raises(RuleViolation, match="expired"):
        services.approve_series(venue=venue, actor=venue.owner, series_id=series.pk)


def test_opening_an_expired_request_expires_it(player, team, venue, court, clock):
    series = request(player, team, court)
    clock.shift(timedelta(hours=49))
    with pytest.raises(RuleViolation, match="expired"):
        services.approve_series(venue=venue, actor=venue.owner, series_id=series.pk)


def test_all_weeks_clash_cannot_be_approved(player, team, venue, court, clock):
    series = request(player, team, court, weeks=2)
    for k in range(2):
        services.create_staff_booking(
            venue=venue,
            actor=venue.staff,
            court_id=court.pk,
            start_at=at(2026, 12, 8, 20, 0) + timedelta(weeks=k),
            end_at=at(2026, 12, 8, 21, 0) + timedelta(weeks=k),
            source="walk_in",
            customer_name="X",
        )
    with pytest.raises(RuleViolation, match="All weeks clash"):
        services.approve_series(venue=venue, actor=venue.owner, series_id=series.pk)
    series.refresh_from_db()
    assert series.status == "pending"


def test_other_venue_cannot_decide(player, team, venue, court, other_venue, clock):
    series = request(player, team, court)
    with pytest.raises(RecurringSeries.DoesNotExist):
        services.approve_series(venue=other_venue, actor=other_venue.owner, series_id=series.pk)


# ---------------------------------------------------------------- team bookings (US-C03, US-P09)


def test_captain_tags_a_booking_and_members_see_it(client, player, team, court, clock):
    member = UserFactory()
    TeamMembership.objects.create(team=team, user=member)
    booking = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 8, 18, 0), team_id=team.pk
    )
    assert booking.team == team
    client.force_login(member)
    html = client.get(reverse("my_bookings")).content.decode()
    assert booking.display_reference in html
    assert "Malabe Strikers" in html
    TeamMembership.objects.filter(user=member).delete()
    assert booking.display_reference not in client.get(reverse("my_bookings")).content.decode()


def test_only_the_captain_can_tag(player, team, court, clock):
    with pytest.raises(Team.DoesNotExist):
        services.create_online_booking(
            user=UserFactory(), court_id=court.pk, start_at=at(2026, 12, 8, 18, 0), team_id=team.pk
        )


# ---------------------------------------------------------------- screens


def test_review_offers_team_and_weekly_request_to_captains(client, player, team, court, clock):
    client.force_login(player)
    html = client.get(
        reverse("book_review"), {"court": court.pk, "start": "2026-12-08T20:00"}
    ).content.decode()
    assert "Team (optional)" in html
    assert "Ask for this time every week" in html
    client.post(
        reverse("book_confirm"),
        {"court": court.pk, "start": "2026-12-08T20:00", "slots": 1, "team": team.pk},
    )
    assert Booking.objects.get().team == team


def test_weekly_request_page_and_send(client, player, team, venue, court, clock):
    client.force_login(player)
    url = reverse("book_weekly") + f"?court={court.pk}&start=2026-12-08T20:00&slots=1"
    html = client.get(url).content.decode()
    assert "Every Tuesday, 8:00 pm–9:00 pm" in html
    assert "Free" in html
    response = client.post(url, {"team": team.pk, "weeks": "4", "send": "1"}, follow=True)
    assert "Request sent." in response.content.decode()
    series = RecurringSeries.objects.get()
    assert series.status == "pending"
    assert "Waiting for the venue" in response.content.decode()


def test_weekly_request_needs_a_team(client, player, court, clock):
    client.force_login(player)
    response = client.get(reverse("book_weekly") + f"?court={court.pk}&start=2026-12-08T20:00")
    assert response.url == reverse("team_create")


def test_weekly_request_week_limit_message(client, player, team, court, clock):
    client.force_login(player)
    url = reverse("book_weekly") + f"?court={court.pk}&start=2026-12-08T20:00"
    response = client.post(url, {"team": team.pk, "weeks": "20", "send": "1"})
    assert "This venue allows up to 12 weeks." in response.content.decode()


def test_venue_approves_from_the_series_page(client, player, team, venue, court, clock):
    series = request(player, team, court)
    client.force_login(venue.staff)
    page = client.get(reverse("manage:series_detail", args=[venue.pk, series.pk])).content.decode()
    assert "Approve: 4 weeks will be booked, 0 skipped" in page
    assert "Malabe Strikers" in page
    response = client.post(
        reverse("manage:series_approve", args=[venue.pk, series.pk]), follow=True
    )
    assert "Approved: 4 weeks booked." in response.content.decode()


def test_venue_rejects_and_owner_only_note(client, player, team, venue, court, clock):
    series = request(player, team, court)
    VenueSettings.objects.for_venue(venue).update(recurring_approver="owner")
    client.force_login(venue.staff)
    page = client.get(reverse("manage:series_detail", args=[venue.pk, series.pk])).content.decode()
    assert "Only the owner can approve requests." in page
    response = client.post(reverse("manage:series_reject", args=[venue.pk, series.pk]), follow=True)
    assert "Only the owner can approve or reject" in response.content.decode()
    client.force_login(venue.owner)
    response = client.post(
        reverse("manage:series_reject", args=[venue.pk, series.pk]), {"reason": "Full"}, follow=True
    )
    assert "Request rejected." in response.content.decode()


def test_player_weekly_page_and_cancel(client, player, team, venue, court, clock):
    series = request(player, team, court, weeks=3)
    services.approve_series(venue=venue, actor=venue.owner, series_id=series.pk)
    client.force_login(player)
    html = client.get(reverse("my_bookings")).content.decode()
    assert "Weekly slots" in html
    page = client.get(reverse("my_weekly", args=[series.pk])).content.decode()
    assert "Cancel this week" in page
    response = client.post(reverse("my_weekly_cancel", args=[series.pk]), follow=True)
    assert "3 weeks cancelled." in response.content.decode()
    client.force_login(UserFactory())
    assert client.get(reverse("my_weekly", args=[series.pk])).status_code == 404
    assert client.post(reverse("my_weekly_cancel", args=[series.pk])).status_code == 404


def test_approving_a_staff_series_is_refused_cleanly(venue, court, clock):
    series, _weeks = services.create_staff_series(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        first_date=TUE,
        start_minute=1200,
        duration_minutes=60,
        weeks=2,
        customer_name="Regulars",
        customer_phone="0715551234",
    )
    with pytest.raises(RuleViolation, match="isn't a request"):
        services.approve_series(venue=venue, actor=venue.owner, series_id=series.pk)
