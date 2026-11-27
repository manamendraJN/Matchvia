"""Business logic for teams: teams, members and invites (US-C01-C03, US-P09, BR-26).

Services own the transaction; views stay thin. Cross-app calls go through the other
app's services.py (CLAUDE.md "Code conventions").
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from core import ratelimit
from core.exceptions import NotAllowed, RuleViolation
from core.phone import format_local, mask_phone
from notifications import services as notifications

from .models import MAX_MEMBERS, InviteStatus, Team, TeamInvite, TeamMembership

logger = logging.getLogger(__name__)

INVITE_LIFETIME = timedelta(days=7)  # BR-26
INVITES_PER_DAY = 20  # architecture 5.1
NAME_MAX = 60


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now(now: datetime | None) -> datetime:
    return now or timezone.now()


def _clean_name(value: str) -> str:
    name = " ".join((value or "").split())
    if not name:
        raise RuleViolation(_("Enter a team name."))
    if len(name) > NAME_MAX:
        raise RuleViolation(_("Use at most 60 characters."))
    return name


def _captains_team(user, team_id) -> Team:
    """The team, only if ``user`` is its captain; otherwise Team.DoesNotExist (shown as 404)."""
    return Team.objects.get(pk=team_id, captain=user, is_active=True)


# ---------------------------------------------------------------- reading


def teams_for(user):
    """Teams the user captains or plays in (P14)."""
    return (
        Team.objects.filter(memberships__user=user, is_active=True)
        .select_related("captain")
        .distinct()
        .order_by("name")
    )


def team_for_member(user, team_id) -> Team:
    """A team the user belongs to; anyone else gets Team.DoesNotExist (404)."""
    return Team.objects.select_related("captain").get(
        pk=team_id, is_active=True, memberships__user=user
    )


def captained_teams(user):
    return Team.objects.filter(captain=user, is_active=True).order_by("name")


def is_member(user, team) -> bool:
    return TeamMembership.objects.filter(team=team, user=user).exists()


def pending_invites_for(user, *, now: datetime | None = None):
    """Open invites sent to the user's number (P14)."""
    if not user.phone:
        return TeamInvite.objects.none()
    return TeamInvite.objects.filter(
        phone=user.phone,
        status=InviteStatus.PENDING,
        expires_at__gt=_now(now),
        team__is_active=True,
    ).select_related("team", "invited_by")


def invite_by_token(token: str) -> TeamInvite:
    return TeamInvite.objects.select_related("team", "invited_by").get(token_hash=_hash(token))


# ---------------------------------------------------------------- teams


def create_team(user, *, name: str, sport: str) -> Team:
    """The creator becomes the captain and the first member (US-C01)."""
    if sport not in Team.Sport.values:
        raise RuleViolation(_("Choose futsal or indoor cricket."))
    with transaction.atomic():
        team = Team.objects.create(name=_clean_name(name), sport=sport, captain=user)
        TeamMembership.objects.create(team=team, user=user)
    logger.info("team.created id=%s", team.pk)
    return team


def rename_team(user, team_id, name: str) -> Team:
    team = _captains_team(user, team_id)
    team.name = _clean_name(name)
    team.save(update_fields=["name", "updated_at"])
    return team


def remove_member(captain, team_id, user_id) -> None:
    """A removed member no longer sees the team's bookings (US-C02)."""
    team = _captains_team(captain, team_id)
    if int(user_id) == captain.pk:
        raise RuleViolation(_("The captain can't be removed from the team."))
    deleted, _rows = TeamMembership.objects.filter(team=team, user_id=user_id).delete()
    if not deleted:
        raise TeamMembership.DoesNotExist


def make_captain(captain, team_id, user_id) -> Team:
    """Hand the team to another member (US-P08: a captain hands over before deleting)."""
    with transaction.atomic():
        team = Team.objects.select_for_update().get(
            pk=_captains_team(captain, team_id).pk, is_active=True
        )
        if int(user_id) == captain.pk:
            raise RuleViolation(_("You are already the captain."))
        member = TeamMembership.objects.select_related("user").get(team=team, user_id=user_id)
        if not member.user.is_active:
            raise TeamMembership.DoesNotExist
        team.captain = member.user
        team.save(update_fields=["captain", "updated_at"])
    logger.info("team.captain_changed id=%s", team.pk)
    return team


def close_team(captain, team_id) -> None:
    """Close the team: it disappears for every member and open invites stop working.

    Bookings already tagged with the team stay booked; they are the captain's bookings.
    """
    with transaction.atomic():
        team = Team.objects.select_for_update().get(
            pk=_captains_team(captain, team_id).pk, is_active=True
        )
        team.is_active = False
        team.save(update_fields=["is_active", "updated_at"])
        TeamInvite.objects.filter(team=team, status=InviteStatus.PENDING).update(
            status=InviteStatus.REVOKED
        )
    logger.info("team.closed id=%s", team.pk)


def leave_all_teams(user) -> None:
    """Account deletion: remove the user from every team and drop invites to their number.

    The caller has already checked they captain no active team (accounts.services).
    """
    TeamMembership.objects.filter(user=user).delete()
    if user.phone:
        TeamInvite.objects.filter(phone=user.phone).delete()


# ---------------------------------------------------------------- invites


def invite(captain, team_id, *, phone: str, now: datetime | None = None) -> TeamInvite:
    """SMS a join link to ``phone`` (normalised). Inviting again re-sends the open invite."""
    now = _now(now)
    team = _captains_team(captain, team_id)
    ratelimit.hit("team-invite", str(captain.pk), limit=INVITES_PER_DAY, window=24 * 3600)
    if TeamMembership.objects.filter(team=team, user__phone=phone).exists():
        raise RuleViolation(_("This player is already in the team."))
    if TeamMembership.objects.filter(team=team).count() >= MAX_MEMBERS:
        raise RuleViolation(_("Teams can have up to 15 players."))
    token = secrets.token_urlsafe(16)
    with transaction.atomic():
        existing = (
            TeamInvite.objects.select_for_update()
            .filter(team=team, phone=phone, status=InviteStatus.PENDING)
            .first()
        )
        if existing:
            # Re-send: a new link replaces the old one (the old token stops working).
            existing.token_hash = _hash(token)
            existing.expires_at = now + INVITE_LIFETIME
            existing.invited_by = captain
            existing.save(update_fields=["token_hash", "expires_at", "invited_by"])
            invitation = existing
        else:
            invitation = TeamInvite.objects.create(
                team=team,
                phone=phone,
                token_hash=_hash(token),
                invited_by=captain,
                expires_at=now + INVITE_LIFETIME,
                created_at=now,
            )
        link = settings.SITE_URL + reverse("team_invite", args=[token])
        notifications.queue_sms(
            to_phone=phone,
            purpose="team_invite",
            body=notifications.render_sms(
                "team_invite",
                captain=captain.name,
                team=team.name,
                sport=team.get_sport_display(),
                link=link,
            ),
        )
    logger.info("team.invited team=%s phone=%s", team.pk, mask_phone(phone))
    return invitation


def _open_invite(token: str, now: datetime) -> TeamInvite:
    invitation = invite_by_token(token)
    if invitation.status == InviteStatus.PENDING and invitation.expires_at <= now:
        invitation.status = InviteStatus.EXPIRED
        invitation.save(update_fields=["status"])
    if invitation.status == InviteStatus.EXPIRED:
        raise RuleViolation(_("This invite has expired. Ask the captain to send a new one."))
    if invitation.status != InviteStatus.PENDING or not invitation.team.is_active:
        raise RuleViolation(_("This invite is no longer open."))
    return invitation


def _check_number(invitation: TeamInvite, user) -> None:
    if user.phone != invitation.phone:
        local = format_local(invitation.phone)  # 077 123 4567
        hidden = f"{local[:3]} *** {local[-4:]}"  # 077 *** 4567 (P17)
        raise NotAllowed(
            _("This invite was sent to %(phone)s. Sign in with that number.") % {"phone": hidden}
        )


def accept_invite(user, token: str, *, now: datetime | None = None) -> Team:
    """Join the team (US-P09). Locks the team so two accepts can't exceed 15 (data-model 3.5)."""
    now = _now(now)
    # Checked before the transaction, so marking an expired invite isn't rolled back.
    invitation = _open_invite(token, now)
    _check_number(invitation, user)
    with transaction.atomic():
        team = Team.objects.select_for_update().get(pk=invitation.team_id)
        invitation = TeamInvite.objects.select_for_update().get(pk=invitation.pk)
        if invitation.status != InviteStatus.PENDING:
            raise RuleViolation(_("This invite is no longer open."))
        if not TeamMembership.objects.filter(team=team, user=user).exists():
            if TeamMembership.objects.filter(team=team).count() >= MAX_MEMBERS:
                raise RuleViolation(_("Teams can have up to 15 players."))
            try:
                with transaction.atomic():
                    TeamMembership.objects.create(team=team, user=user, joined_at=now)
            except IntegrityError:  # already joined in a parallel request
                pass
        invitation.status = InviteStatus.ACCEPTED
        invitation.responded_at = now
        invitation.save(update_fields=["status", "responded_at"])
    return team


def decline_invite(user, token: str, *, now: datetime | None = None) -> None:
    now = _now(now)
    invitation = _open_invite(token, now)
    _check_number(invitation, user)
    with transaction.atomic():
        invitation.status = InviteStatus.DECLINED
        invitation.responded_at = now
        invitation.save(update_fields=["status", "responded_at"])


def revoke_invite(captain, team_id, invite_id) -> None:
    team = _captains_team(captain, team_id)
    updated = TeamInvite.objects.filter(
        pk=invite_id, team=team, status=InviteStatus.PENDING
    ).update(status=InviteStatus.REVOKED)
    if not updated:
        raise TeamInvite.DoesNotExist


def expire_old_invites(*, now: datetime | None = None) -> int:
    """Worker job: pending invites past 7 days become expired (data-model 11)."""
    return TeamInvite.objects.filter(status=InviteStatus.PENDING, expires_at__lte=_now(now)).update(
        status=InviteStatus.EXPIRED
    )
