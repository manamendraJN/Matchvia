"""Teams and invites (US-C01, US-C02, US-P09, BR-26)."""

import hashlib
import re
import threading
from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from django.db import connection
from django.urls import reverse

from accounts.tests.factories import UserFactory
from core.exceptions import NotAllowed, RateLimited, RuleViolation
from notifications.models import SmsMessage
from teams import services
from teams.models import MAX_MEMBERS, Team, TeamInvite, TeamMembership

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 12, 7, 4, 30, tzinfo=UTC)


@pytest.fixture
def captain(db):
    return UserFactory(name="Kasun")


@pytest.fixture
def team(captain):
    return services.create_team(captain, name="Malabe Strikers", sport="futsal")


def token_from_sms(phone):
    body = SmsMessage.objects.filter(purpose="team_invite", to_phone=phone).latest("pk").body
    return re.search(r"/t/([^/\s]+)/", body).group(1)


# ---------------------------------------------------------------- teams


def test_creator_is_captain_and_member(captain, team):
    assert team.captain == captain
    assert TeamMembership.objects.filter(team=team, user=captain).exists()
    assert list(services.teams_for(captain)) == [team]
    assert str(team) == "Malabe Strikers"


def test_team_validation(captain):
    with pytest.raises(RuleViolation, match="team name"):
        services.create_team(captain, name="  ", sport="futsal")
    with pytest.raises(RuleViolation):
        services.create_team(captain, name="X", sport="tennis")
    services.create_team(captain, name="Malabe Strikers", sport="indoor_cricket")  # names repeat


def test_rename_only_by_captain(captain, team):
    services.rename_team(captain, team.pk, "Strikers FC")
    team.refresh_from_db()
    assert team.name == "Strikers FC"
    with pytest.raises(Team.DoesNotExist):
        services.rename_team(UserFactory(), team.pk, "Hijack")


# ---------------------------------------------------------------- invites


def test_invite_sends_link_and_stores_only_a_hash(captain, team):
    invitation = services.invite(captain, team.pk, phone="+94711112222")
    token = token_from_sms("+94711112222")
    assert invitation.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(TeamInvite.objects.values().get())
    body = SmsMessage.objects.get(purpose="team_invite").body
    assert "Kasun invited you to join Malabe Strikers (Futsal)." in body
    assert "http://localhost:8000/t/" in body


def test_inviting_again_resends_the_same_invite(captain, team):
    first = services.invite(captain, team.pk, phone="+94711112222")
    old_token = token_from_sms("+94711112222")
    second = services.invite(captain, team.pk, phone="+94711112222")
    assert first.pk == second.pk
    assert TeamInvite.objects.count() == 1
    assert SmsMessage.objects.filter(purpose="team_invite").count() == 2
    with pytest.raises(TeamInvite.DoesNotExist):
        services.invite_by_token(old_token)  # the old link stops working


def test_only_the_captain_invites(team):
    with pytest.raises(Team.DoesNotExist):
        services.invite(UserFactory(), team.pk, phone="+94711112222")


def test_cannot_invite_a_member(captain, team):
    with pytest.raises(RuleViolation, match="already in the team"):
        services.invite(captain, team.pk, phone=captain.phone)


def test_invites_are_rate_limited(captain, team):
    for i in range(services.INVITES_PER_DAY):
        services.invite(captain, team.pk, phone=f"+9471100{i:04d}")
    with pytest.raises(RateLimited):
        services.invite(captain, team.pk, phone="+94719999999")


def test_accept_with_the_invited_number(captain, team):
    player = UserFactory(phone="+94711112222")
    services.invite(captain, team.pk, phone=player.phone)
    joined = services.accept_invite(player, token_from_sms(player.phone))
    assert joined == team
    assert TeamMembership.objects.filter(team=team, user=player).exists()
    assert TeamInvite.objects.get().status == "accepted"
    with pytest.raises(RuleViolation, match="no longer open"):
        services.accept_invite(player, token_from_sms(player.phone))


def test_wrong_number_is_told_which_number(captain, team):
    services.invite(captain, team.pk, phone="+94771234567")
    with pytest.raises(NotAllowed, match=r"sent to 077 \*\*\* 4567"):
        services.accept_invite(UserFactory(phone="+94711112222"), token_from_sms("+94771234567"))


def test_invite_expires_after_seven_days(captain, team):
    player = UserFactory(phone="+94711112222")
    with time_machine.travel(T0, tick=False) as clock:
        services.invite(captain, team.pk, phone=player.phone)
        token = token_from_sms(player.phone)
        clock.shift(timedelta(days=7))
        with pytest.raises(RuleViolation, match="expired"):
            services.accept_invite(player, token)
    assert TeamInvite.objects.get().status == "expired"


def test_expire_job(captain, team):
    with time_machine.travel(T0, tick=False) as clock:
        services.invite(captain, team.pk, phone="+94711112222")
        clock.shift(timedelta(days=8))
        assert services.expire_old_invites() == 1


def test_decline_and_revoke(captain, team):
    player = UserFactory(phone="+94711112222")
    services.invite(captain, team.pk, phone=player.phone)
    services.decline_invite(player, token_from_sms(player.phone))
    assert TeamInvite.objects.get().status == "declined"
    invitation = services.invite(captain, team.pk, phone="+94711113333")
    services.revoke_invite(captain, team.pk, invitation.pk)
    invitation.refresh_from_db()
    assert invitation.status == "revoked"
    with pytest.raises(TeamInvite.DoesNotExist):
        services.revoke_invite(captain, team.pk, invitation.pk)


def test_team_is_full_at_fifteen(captain, team):
    for _ in range(MAX_MEMBERS - 1):
        TeamMembership.objects.create(team=team, user=UserFactory())
    with pytest.raises(RuleViolation, match="up to 15 players"):
        services.invite(captain, team.pk, phone="+94711112222")


@pytest.mark.django_db(transaction=True)
def test_two_accepts_at_once_cannot_exceed_fifteen():
    captain = UserFactory(name="Kasun")
    team = services.create_team(captain, name="Full", sport="futsal")
    for _ in range(MAX_MEMBERS - 2):
        TeamMembership.objects.create(team=team, user=UserFactory())
    players = [UserFactory(phone=f"+9471222000{i}") for i in range(2)]
    from django.db import transaction

    with transaction.atomic():
        for player in players:
            services.invite(captain, team.pk, phone=player.phone)
    tokens = [token_from_sms(p.phone) for p in players]
    # Fill the last place so only one of the two can still join.
    TeamMembership.objects.create(team=team, user=UserFactory())
    barrier = threading.Barrier(2)
    results = []

    def accept(player, token):
        barrier.wait()
        try:
            services.accept_invite(player, token)
            results.append("joined")
        except RuleViolation:
            results.append("full")
        finally:
            connection.close()

    threads = [
        threading.Thread(target=accept, args=pair) for pair in zip(players, tokens, strict=True)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert results == ["full", "full"]
    assert TeamMembership.objects.filter(team=team).count() == MAX_MEMBERS


def test_remove_member(captain, team):
    player = UserFactory()
    TeamMembership.objects.create(team=team, user=player)
    with pytest.raises(RuleViolation, match="captain can't be removed"):
        services.remove_member(captain, team.pk, captain.pk)
    services.remove_member(captain, team.pk, player.pk)
    assert not TeamMembership.objects.filter(team=team, user=player).exists()
    with pytest.raises(TeamMembership.DoesNotExist):
        services.remove_member(captain, team.pk, player.pk)


# ---------------------------------------------------------------- screens (P14-P17)


def test_teams_pages(client, captain, team):
    client.force_login(captain)
    assert "Malabe Strikers" in client.get(reverse("my_teams")).content.decode()
    response = client.post(
        reverse("team_create"), {"name": "Night Owls", "sport": "futsal"}, follow=True
    )
    assert "Team created. Invite your players." in response.content.decode()
    detail = client.get(reverse("team_detail", args=[team.pk])).content.decode()
    assert "Invite a player" in detail
    response = client.post(
        reverse("team_detail", args=[team.pk]), {"phone": "071 111 2222"}, follow=True
    )
    assert "Invite sent by SMS." in response.content.decode()
    response = client.post(reverse("team_detail", args=[team.pk]), {"phone": "0112345678"})
    assert "Enter a valid Sri Lankan mobile number" in response.content.decode()


def test_members_see_the_team_but_cannot_manage_it(client, captain, team):
    member = UserFactory()
    TeamMembership.objects.create(team=team, user=member)
    client.force_login(member)
    html = client.get(reverse("team_detail", args=[team.pk])).content.decode()
    assert "Malabe Strikers" in html
    assert "Invite a player" not in html
    assert (
        client.post(reverse("team_detail", args=[team.pk]), {"phone": "0711112222"}).status_code
        == 404
    )
    assert client.post(reverse("team_remove_member", args=[team.pk, captain.pk])).status_code == 404


def test_strangers_get_404(client, team):
    client.force_login(UserFactory())
    assert client.get(reverse("team_detail", args=[team.pk])).status_code == 404


def test_invite_link_flow(client, captain, team):
    player = UserFactory(phone="+94711112222")
    services.invite(captain, team.pk, phone=player.phone)
    url = reverse("team_invite", args=[token_from_sms(player.phone)])
    assert client.get(url).status_code == 302  # sign in first
    client.force_login(player)
    assert "Kasun invited you to join" in client.get(url).content.decode()
    response = client.post(url, {"join": "1"}, follow=True)
    assert "You joined Malabe Strikers." in response.content.decode()
    assert client.get(reverse("team_invite", args=["nope"])).status_code == 404


def test_invite_link_wrong_number_and_decline(client, captain, team):
    services.invite(captain, team.pk, phone="+94771234567")
    url = reverse("team_invite", args=[token_from_sms("+94771234567")])
    client.force_login(UserFactory(phone="+94711112222"))
    response = client.post(url, {"join": "1"}, follow=True)
    assert "Sign in with that number." in response.content.decode()
    client.force_login(UserFactory(phone="+94771234567"))
    client.post(url, {"decline": "1"})
    assert TeamInvite.objects.get().status == "declined"


def test_my_teams_lists_pending_invites(client, captain, team):
    player = UserFactory(phone="+94711112222")
    services.invite(captain, team.pk, phone=player.phone)
    client.force_login(player)
    assert "Kasun invited you to join" in client.get(reverse("my_teams")).content.decode()


def test_captain_removes_and_revokes_from_the_page(client, captain, team):
    member = UserFactory()
    TeamMembership.objects.create(team=team, user=member)
    invitation = services.invite(captain, team.pk, phone="+94711113333")
    client.force_login(captain)
    client.post(reverse("team_remove_member", args=[team.pk, member.pk]))
    client.post(reverse("team_revoke_invite", args=[team.pk, invitation.pk]))
    assert not TeamMembership.objects.filter(user=member).exists()
    invitation.refresh_from_db()
    assert invitation.status == "revoked"
