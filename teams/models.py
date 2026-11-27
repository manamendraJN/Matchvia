"""Teams, members and invites (data-model 3.5, US-C01-C03, US-P09)."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.fields import PhoneField

MAX_MEMBERS = 15  # BR-26, captain included


class Team(models.Model):
    class Sport(models.TextChoices):
        FUTSAL = "futsal", _("Futsal")
        INDOOR_CRICKET = "indoor_cricket", _("Indoor cricket")

    name = models.CharField(_("team name"), max_length=60)  # names needn't be unique (US-C01)
    sport = models.CharField(_("sport"), max_length=20, choices=Sport.choices)
    captain = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="captained_teams"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("team")
        constraints = [
            models.CheckConstraint(
                condition=Q(sport__in=["futsal", "indoor_cricket"]), name="team_sport_valid"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class TeamMembership(models.Model):
    """The captain has a row too, so 'team members' is one query."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships"
    )
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = _("team member")
        constraints = [models.UniqueConstraint(fields=["team", "user"], name="team_member_once")]

    def __str__(self) -> str:
        return f"{self.user} in {self.team}"


class InviteStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    ACCEPTED = "accepted", _("Accepted")
    DECLINED = "declined", _("Declined")
    EXPIRED = "expired", _("Expired")
    REVOKED = "revoked", _("Revoked")


class TeamInvite(models.Model):
    """An SMS invite. Only a SHA-256 of the link's random token is stored (architecture 5 A02)."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="invites")
    phone = PhoneField(_("mobile number"))
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=10, choices=InviteStatus.choices, default=InviteStatus.PENDING
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    expires_at = models.DateTimeField()  # 7 days (BR-26)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("team invite")
        constraints = [
            # Inviting the same number again re-sends the open invite (US-C02).
            models.UniqueConstraint(
                fields=["team", "phone"],
                condition=Q(status="pending"),
                name="invite_one_pending_per_phone",
            ),
            models.CheckConstraint(
                condition=Q(status__in=InviteStatus.values), name="invite_status_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"Invite #{self.pk} to {self.team}"
