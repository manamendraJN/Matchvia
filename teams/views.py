"""Player team screens: My teams, create, team details, invite link (P14-P17).

A player only ever sees teams they belong to; captain-only actions look the team up through
the captain (``Team.DoesNotExist`` -> 404 for anyone else).
"""

from functools import wraps

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import profile_required
from bookings import selectors as booking_selectors
from core.exceptions import NotAllowed, RateLimited, RuleViolation

from . import services
from .forms import InviteForm, TeamForm
from .models import InviteStatus, Team, TeamInvite, TeamMembership


def _404_if_missing(func):
    """Another team, member or invite id is simply 'not found' (never 'forbidden')."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (Team.DoesNotExist, TeamMembership.DoesNotExist, TeamInvite.DoesNotExist):
            raise Http404 from None

    return wrapper


@never_cache
@profile_required
def my_teams(request):
    context = {
        "teams": services.teams_for(request.user),
        "invites": services.pending_invites_for(request.user),
    }
    return render(request, "teams/my_teams.html", context)


@never_cache
@profile_required
@require_http_methods(["GET", "POST"])
def create(request):
    form = TeamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            team = services.create_team(request.user, **form.cleaned_data)
        except RuleViolation as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, _("Team created. Invite your players."))
            return redirect("team_detail", team_id=team.pk)
    return render(request, "teams/create.html", {"form": form})


@never_cache
@profile_required
@_404_if_missing
@require_http_methods(["GET", "POST"])
def detail(request, team_id):
    team = services.team_for_member(request.user, team_id)
    is_captain = team.captain_id == request.user.pk
    form = InviteForm(request.POST or None) if is_captain else None
    if request.method == "POST":
        if not is_captain:
            raise Http404
        if form.is_valid():
            try:
                services.invite(request.user, team.pk, phone=form.cleaned_data["phone"])
            except RateLimited:
                form.add_error(None, _("You've sent a lot of invites today. Try again tomorrow."))
            except RuleViolation as exc:
                form.add_error(None, exc.message)
            else:
                messages.success(request, _("Invite sent by SMS."))
                return redirect("team_detail", team_id=team.pk)
    context = {
        "team": team,
        "is_captain": is_captain,
        "form": form,
        "members": team.memberships.select_related("user").order_by("joined_at"),
        "invites": (
            team.invites.filter(status=InviteStatus.PENDING).order_by("-created_at")
            if is_captain
            else []
        ),
        "bookings": booking_selectors.team_bookings(team),
    }
    return render(request, "teams/detail.html", context)


@never_cache
@profile_required
@_404_if_missing
@require_POST
def remove_member(request, team_id, user_id):
    try:
        services.remove_member(request.user, team_id, user_id)
    except RuleViolation as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, _("Removed from the team."))
    return redirect("team_detail", team_id=team_id)


@never_cache
@profile_required
@_404_if_missing
@require_POST
def make_captain(request, team_id, user_id):
    try:
        team = services.make_captain(request.user, team_id, user_id)
    except RuleViolation as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, _("%(name)s is now the captain.") % {"name": team.captain.name})
    return redirect("team_detail", team_id=team_id)


@never_cache
@profile_required
@_404_if_missing
@require_http_methods(["GET", "POST"])
def close(request, team_id):
    """Confirm, then close the team (captain only)."""
    team = services.captained_teams(request.user).get(pk=team_id)
    if request.method == "POST":
        services.close_team(request.user, team.pk)
        messages.success(request, _("%(team)s is closed.") % {"team": team.name})
        return redirect("my_teams")
    return render(request, "teams/close.html", {"team": team})


@never_cache
@profile_required
@_404_if_missing
@require_POST
def revoke_invite(request, team_id, invite_id):
    services.revoke_invite(request.user, team_id, invite_id)
    messages.success(request, _("Invite removed."))
    return redirect("team_detail", team_id=team_id)


@never_cache
@profile_required
@require_http_methods(["GET", "POST"])
def invite_landing(request, token):
    """P17: the SMS link. Signed-out users sign in first and come back here."""
    try:
        invitation = services.invite_by_token(token)
    except TeamInvite.DoesNotExist:
        raise Http404 from None
    if request.method == "POST":
        try:
            if "decline" in request.POST:
                services.decline_invite(request.user, token)
                messages.success(request, _("Invite declined."))
                return redirect("home")
            team = services.accept_invite(request.user, token)
        except (RuleViolation, NotAllowed) as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, _("You joined %(team)s.") % {"team": team.name})
            return redirect("team_detail", team_id=team.pk)
    return render(request, "teams/invite.html", {"invite": invitation, "token": token})
