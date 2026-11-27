"""Business logic for venues (US-O01–O04, US-A01, US-A02).

Access rule (CLAUDE.md rule 2, data-model 6.2): venue-side code gets a venue only through
``get_venue_for_user()``, which raises Http404 unless the user is a member with an allowed role.
Changes below also check the actor's role again, so a missed check in a view can't open a hole.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from core.exceptions import NotAllowed, RuleViolation
from notifications import services as notifications
from pricing import services as pricing

from .images import process_logo, process_photo
from .models import (
    Court,
    MemberRole,
    OpeningHours,
    Venue,
    VenueMembership,
    VenuePhoto,
    VenueSettings,
    VenueStatus,
)

logger = logging.getLogger(__name__)

OWNER = frozenset({MemberRole.OWNER})
MEMBERS = frozenset({MemberRole.OWNER, MemberRole.STAFF})
MAX_PHOTOS = 6
EDITABLE_PROFILE_FIELDS = {
    "name",
    "area",
    "address",
    "latitude",
    "longitude",
    "phone",
    "description",
    "facilities",
}


# ---------------------------------------------------------------- access


def get_venue_for_user(user, venue_id, roles: Iterable[str] = MEMBERS) -> Venue:
    """The venue, if ``user`` is a member with one of ``roles``; otherwise Http404.

    404 rather than 403, so other venues' ids are not confirmed to exist (NFR-06). The member's
    role is available as ``venue.member_role``.
    """
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        raise Http404
    try:
        membership = VenueMembership.objects.select_related("venue", "venue__area").get(
            venue_id=venue_id, user=user, role__in=list(roles)
        )
    except (VenueMembership.DoesNotExist, ValueError, TypeError):
        raise Http404 from None
    venue = membership.venue
    venue.member_role = membership.role
    return venue


def member_role(venue: Venue, user) -> str | None:
    """The user's role at this venue ("owner" or "staff"), or None. Used by other apps' services."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return None
    return (
        VenueMembership.objects.for_venue(venue).filter(user=user).values_list("role", flat=True)
    ).first()


def approver_phones(venue: Venue) -> list[str]:
    """Numbers to tell about a new weekly request: owners, plus staff if they may approve."""
    roles = [MemberRole.OWNER]
    if venue.settings.recurring_approver == "owner_or_staff":
        roles.append(MemberRole.STAFF)
    return list(
        VenueMembership.objects.for_venue(venue)
        .filter(role__in=roles, user__is_active=True, user__phone__isnull=False)
        .values_list("user__phone", flat=True)
    )


def memberships_for_user(user):
    """The venues a user works at, for the venue switcher (V7)."""
    return (
        VenueMembership.objects.filter(user=user)
        .select_related("venue", "venue__area")
        .order_by("venue__name")
    )


def _require_owner(venue: Venue, actor) -> None:
    if (
        not VenueMembership.objects.for_venue(venue)
        .filter(user=actor, role=MemberRole.OWNER)
        .exists()
    ):
        raise NotAllowed(_("Only the venue owner can change this."))


# ---------------------------------------------------------------- creating a venue


def _unique_slug(name: str) -> str:
    base = slugify(name)[:50] or "venue"
    slug, n = base, 2
    while Venue.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def create_venue(*, owner, name: str, area, phone: str) -> Venue:
    """Create a draft venue with default settings, hours and peak times; ``owner`` owns it.

    The calendar can be used before approval (BR-22); players can't see it until approved.
    """
    with transaction.atomic():
        venue = Venue.objects.create(
            name=name.strip(), slug=_unique_slug(name), area=area, phone=phone
        )
        VenueSettings.objects.create(venue=venue)
        OpeningHours.objects.bulk_create(OpeningHours(venue=venue, weekday=d) for d in range(7))
        pricing.create_default_peak_periods(venue)
        VenueMembership.objects.create(
            venue=venue, user=owner, role=MemberRole.OWNER, added_by=owner
        )
    logger.info("venue.created venue_id=%s owner_id=%s", venue.pk, owner.pk)
    return venue


# ---------------------------------------------------------------- profile and photos


def update_profile(venue: Venue, actor, **fields) -> Venue:
    _require_owner(venue, actor)
    unknown = set(fields) - EDITABLE_PROFILE_FIELDS
    if unknown:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    if ("latitude" in fields) != ("longitude" in fields) or (
        (fields.get("latitude") is None) != (fields.get("longitude") is None)
    ):
        raise RuleViolation(_("Set both latitude and longitude, or neither."))
    for name, value in fields.items():
        setattr(venue, name, value.strip() if isinstance(value, str) else value)
    venue.save()
    return venue


def add_photo(venue: Venue, actor, upload) -> VenuePhoto:
    _require_owner(venue, actor)
    processed = process_photo(upload)
    with transaction.atomic():
        # Lock the venue row so two uploads can't both pass the limit.
        Venue.objects.select_for_update().get(pk=venue.pk)
        count = VenuePhoto.objects.for_venue(venue).count()
        if count >= MAX_PHOTOS:
            raise RuleViolation(_("A venue can have up to 6 photos. Remove one first."))
        return VenuePhoto.objects.create(venue=venue, image=processed, position=count)


def remove_photo(venue: Venue, actor, photo_id) -> None:
    _require_owner(venue, actor)
    photo = VenuePhoto.objects.for_venue(venue).get(pk=photo_id)
    photo.image.delete(save=False)
    photo.delete()


def set_logo(venue: Venue, actor, upload) -> Venue:
    _require_owner(venue, actor)
    processed = process_logo(upload)
    if venue.logo:
        venue.logo.delete(save=False)
    venue.logo.save(processed.name, processed, save=True)
    return venue


def set_cover_photo(venue: Venue, actor, upload) -> Venue:
    _require_owner(venue, actor)
    processed = process_photo(upload)
    if venue.cover_photo:
        venue.cover_photo.delete(save=False)
    venue.cover_photo.save(processed.name, processed, save=True)
    return venue


# ---------------------------------------------------------------- courts


def _check_court_name(venue: Venue, name: str, exclude_pk=None) -> str:
    name = " ".join(name.split())
    if not name:
        raise RuleViolation(_("Enter a court name."))
    clash = Court.objects.for_venue(venue).filter(name__iexact=name)
    if exclude_pk:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        raise RuleViolation(_("Two courts can't have the same name."))
    return name


def create_court(venue: Venue, actor, **fields) -> Court:
    _require_owner(venue, actor)
    fields["name"] = _check_court_name(venue, fields.get("name", ""))
    position = Court.objects.for_venue(venue).count()
    return Court.objects.create(venue=venue, position=position, **fields)


def update_court(venue: Venue, actor, court_id, **fields) -> Court:
    """Change a court. Existing bookings keep their stored price and times (US-O04)."""
    _require_owner(venue, actor)
    court = Court.objects.for_venue(venue).get(pk=court_id)
    if "name" in fields:
        fields["name"] = _check_court_name(venue, fields["name"], exclude_pk=court.pk)
    for name, value in fields.items():
        setattr(court, name, value)
    court.save()
    return court


def set_court_active(venue: Venue, actor, court_id, *, active: bool) -> Court:
    """Deactivate or reactivate a court.

    C4 adds the check from US-O02: a court with future confirmed bookings can't be deactivated
    until they are moved or cancelled.
    """
    _require_owner(venue, actor)
    court = Court.objects.for_venue(venue).get(pk=court_id)
    court.is_active = active
    court.save(update_fields=["is_active", "updated_at"])
    return court


def update_prices(
    venue: Venue,
    actor,
    *,
    court_prices: dict[int, tuple[int, int]],
    peak_periods: Iterable[tuple[int, int, int]],
) -> None:
    """Save court prices and peak times together (V23). New prices apply to new bookings only.

    ``court_prices`` maps court id -> (normal, peak) in whole rupees; ``peak_periods`` is a list
    of (weekday, starts_minute, ends_minute) that replaces the venue's peak times.
    """
    _require_owner(venue, actor)
    peak_periods = list(peak_periods)
    for weekday, start, end in peak_periods:
        if not 0 <= weekday <= 6 or not start < end:
            raise RuleViolation(_("Each peak time must end after it starts."))
    with transaction.atomic():
        courts = {c.pk: c for c in Court.objects.for_venue(venue).filter(pk__in=list(court_prices))}
        if len(courts) != len(court_prices):
            raise Court.DoesNotExist  # an id that isn't this venue's court
        for court_id, (normal, peak) in court_prices.items():
            court = courts[court_id]
            court.off_peak_price_lkr, court.peak_price_lkr = normal, peak
            court.save(update_fields=["off_peak_price_lkr", "peak_price_lkr", "updated_at"])
        pricing.replace_peak_periods(venue, peak_periods)


# ---------------------------------------------------------------- hours and peak times


@dataclass(frozen=True)
class DayHours:
    weekday: int
    is_closed: bool
    opens_minute: int
    closes_minute: int


def set_opening_hours(venue: Venue, actor, days: Iterable[DayHours]) -> None:
    """Replace the weekly hours. Existing bookings stay valid even outside new hours (US-O03)."""
    _require_owner(venue, actor)
    days = list(days)
    if sorted(d.weekday for d in days) != list(range(7)):
        raise ValueError("Hours must cover every weekday exactly once.")
    if all(d.is_closed for d in days):
        raise RuleViolation(_("Your venue needs at least one open day."))
    for day in days:
        if not day.is_closed and not day.opens_minute < day.closes_minute:
            raise RuleViolation(_("Closing time must be after opening time."))
    with transaction.atomic():
        rows = {h.weekday: h for h in OpeningHours.objects.for_venue(venue).select_for_update()}
        for day in days:
            row = rows.get(day.weekday) or OpeningHours(venue=venue, weekday=day.weekday)
            row.is_closed = day.is_closed
            if not day.is_closed:
                row.opens_minute, row.closes_minute = day.opens_minute, day.closes_minute
            row.save()


# ---------------------------------------------------------------- staff (US-O06, V24)


def add_member(venue: Venue, actor, *, name: str, phone: str, role: str) -> VenueMembership:
    """The owner gives someone access to this venue. They sign in with OTP on their own number.

    A new number gets an account with the name the owner typed; on first sign-in they still
    accept the privacy notice and terms themselves (NFR-07). They get an SMS (US-O06).
    """
    from django.contrib.auth import get_user_model

    _require_owner(venue, actor)
    if role not in MemberRole.values:
        raise RuleViolation(_("Choose staff or owner."))
    name = " ".join((name or "").split())
    if not name:
        raise RuleViolation(_("Enter their name."))
    User = get_user_model()
    with transaction.atomic():
        user = User.objects.filter(phone=phone).first()
        if user is None:
            user = User.objects.create_user(phone=phone, name=name[:80])
        elif not user.is_active:
            raise RuleViolation(_("This account is disabled."))
        if VenueMembership.objects.for_venue(venue).filter(user=user).exists():
            raise RuleViolation(_("This person already works at this venue."))
        membership = VenueMembership.objects.create(
            venue=venue, user=user, role=role, added_by=actor
        )
        notifications.queue_sms(
            to_phone=phone,
            purpose="staff_added",
            body=notifications.render_sms("staff_added", venue=venue.name),
        )
    logger.info("venue.member_added venue_id=%s user_id=%s role=%s", venue.pk, user.pk, role)
    return membership


def remove_member(venue: Venue, actor, membership_id) -> None:
    """Access ends on their next request (US-O06). A venue always keeps at least one owner."""
    _require_owner(venue, actor)
    with transaction.atomic():
        memberships = VenueMembership.objects.for_venue(venue).select_for_update()
        membership = memberships.get(pk=membership_id)
        if (
            membership.role == MemberRole.OWNER
            and memberships.filter(role=MemberRole.OWNER).count() == 1
        ):
            raise RuleViolation(_("A venue needs at least one owner."))
        membership.delete()
    logger.info("venue.member_removed venue_id=%s membership_id=%s", venue.pk, membership_id)


# ---------------------------------------------------------------- approval workflow (BR-22)


def missing_for_submission(venue: Venue) -> list[str]:
    """What still has to be done before the venue can be submitted (V6)."""
    missing = []
    if not venue.address:
        missing.append(_("Add the address"))
    if venue.latitude is None:
        missing.append(_("Set the map location"))
    if not Court.objects.for_venue(venue).filter(is_active=True).exists():
        missing.append(_("Add at least one court"))
    if not OpeningHours.objects.for_venue(venue).filter(is_closed=False).exists():
        missing.append(_("Open on at least one day"))
    return missing


def _set_status(venue: Venue, status: str, *, by, reason: str = "") -> None:
    venue.status = status
    venue.status_reason = reason
    venue.status_changed_at = timezone.now()
    venue.status_changed_by = by
    venue.save(
        update_fields=[
            "status",
            "status_reason",
            "status_changed_at",
            "status_changed_by",
            "updated_at",
        ]
    )
    logger.info("venue.status venue_id=%s status=%s by=%s", venue.pk, status, by.pk)


def submit_for_approval(venue: Venue, actor) -> Venue:
    _require_owner(venue, actor)
    if venue.status not in {VenueStatus.DRAFT, VenueStatus.REJECTED}:
        raise RuleViolation(_("This venue has already been submitted."))
    missing = missing_for_submission(venue)
    if missing:
        raise RuleViolation(_("Before submitting: %(items)s.") % {"items": "; ".join(missing)})
    with transaction.atomic():
        _set_status(venue, VenueStatus.PENDING, by=actor)
    return venue


def _require_platform_admin(admin) -> None:
    if not (admin.is_active and admin.is_staff):
        raise NotAllowed(_("Only platform admins can do this."))


def _notify_owners(venue: Venue, text: str) -> None:
    owners = VenueMembership.objects.for_venue(venue).filter(
        role=MemberRole.OWNER, user__phone__isnull=False, user__is_active=True
    )
    for membership in owners.select_related("user"):
        notifications.queue_sms(
            to_phone=membership.user.phone, purpose="venue_status", body=text, venue=venue
        )


def _reason(reason: str) -> str:
    reason = " ".join((reason or "").split())
    if not reason:
        raise RuleViolation(_("A reason is required (the owner will see it)."))
    if len(reason) > 255:
        raise RuleViolation(_("Keep the reason under 255 characters."))
    return reason


def approve_venue(venue: Venue, admin) -> Venue:
    _require_platform_admin(admin)
    if venue.status != VenueStatus.PENDING:
        raise RuleViolation(_("Only venues waiting for approval can be approved."))
    with transaction.atomic():
        _set_status(venue, VenueStatus.APPROVED, by=admin)
        _notify_owners(venue, notifications.render_sms("venue_approved", venue=venue.name))
    return venue


def reject_venue(venue: Venue, admin, reason: str) -> Venue:
    _require_platform_admin(admin)
    reason = _reason(reason)
    if venue.status != VenueStatus.PENDING:
        raise RuleViolation(_("Only venues waiting for approval can be rejected."))
    with transaction.atomic():
        _set_status(venue, VenueStatus.REJECTED, by=admin, reason=reason)
        _notify_owners(
            venue, notifications.render_sms("venue_rejected", venue=venue.name, reason=reason)
        )
    return venue


def suspend_venue(venue: Venue, admin, reason: str) -> Venue:
    """Hide a live venue from players; existing bookings stay (US-A02)."""
    _require_platform_admin(admin)
    reason = _reason(reason)
    if venue.status != VenueStatus.APPROVED:
        raise RuleViolation(_("Only approved venues can be suspended."))
    with transaction.atomic():
        _set_status(venue, VenueStatus.SUSPENDED, by=admin, reason=reason)
        _notify_owners(
            venue, notifications.render_sms("venue_suspended", venue=venue.name, reason=reason)
        )
    return venue


def unsuspend_venue(venue: Venue, admin) -> Venue:
    _require_platform_admin(admin)
    if venue.status != VenueStatus.SUSPENDED:
        raise RuleViolation(_("Only suspended venues can be unsuspended."))
    with transaction.atomic():
        _set_status(venue, VenueStatus.APPROVED, by=admin)
        _notify_owners(venue, notifications.render_sms("venue_unsuspended", venue=venue.name))
    return venue
