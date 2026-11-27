"""Business logic for venues (US-O01–O04, US-A01, US-A02).

Access rule (CLAUDE.md rule 2, data-model 6.2): venue-side code gets a venue only through
``get_venue_for_user()``, which raises Http404 unless the user is a member with an allowed role.
Changes below also check the actor's role again, so a missed check in a view can't open a hole.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Subquery
from django.http import Http404
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from core.db import advisory_xact_lock
from core.exceptions import NotAllowed, RuleViolation
from notifications import services as notifications
from pricing import services as pricing

from .images import process_logo, process_photo
from .models import (
    Court,
    MemberRole,
    OpeningHours,
    Venue,
    VenueCustomer,
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


def owner_phones(venue: Venue) -> list[str]:
    """Numbers of the venue's active owners, for notices to the venue."""
    return list(
        VenueMembership.objects.for_venue(venue)
        .filter(role=MemberRole.OWNER, user__is_active=True, user__phone__isnull=False)
        .values_list("user__phone", flat=True)
    )


# Venues that are live or on their way: an owner must hand them over before deleting (US-P08).
# Drafts and rejected venues were never public, so they don't block deletion.
HANDOVER_STATUSES = [VenueStatus.PENDING, VenueStatus.APPROVED, VenueStatus.SUSPENDED]


def sole_owned_venues(user):
    """Venues where ``user`` is the only owner and that must be handed over first (US-P08)."""
    other_owner = VenueMembership.objects.filter(
        venue=OuterRef("venue"), role=MemberRole.OWNER
    ).exclude(user=user)
    venue_ids = (
        VenueMembership.objects.filter(
            user=user, role=MemberRole.OWNER, venue__status__in=HANDOVER_STATUSES
        )
        .exclude(Exists(other_owner))
        .values("venue_id")
    )
    return Venue.objects.filter(pk__in=venue_ids).order_by("name")


def leave_all_venues(user) -> int:
    """Account deletion: end every owner and staff role the user has. Returns rows removed."""
    deleted, _rows = VenueMembership.objects.filter(user=user).delete()
    return deleted


def forget_customer(user, *, phone: str | None, name: str) -> int:
    """Account deletion: remove the person's name and number from every venue's customer book.

    Rows stay (bookings point at them) as "Deleted user" with no number and no account link.
    Staff notes and block reasons about the person go too. Returns the number of rows changed.
    """
    rows = VenueCustomer.objects.filter(user=user)
    if phone:
        rows = rows | VenueCustomer.objects.filter(phone=phone)
    return rows.update(phone=None, name=name, user=None, notes="", block_reason="")


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


NAME_TAKEN_CONSTRAINT = "venue_name_unique_in_area"


def clean_venue_name(name: str) -> str:
    return " ".join((name or "").split())


def _name_taken(name: str, area) -> RuleViolation:
    return RuleViolation(
        _("A venue called %(name)s is already listed in %(area)s.")
        % {"name": name, "area": area.name if area else ""}
    )


def _check_name_free(name: str, area, exclude_pk=None) -> None:
    """No two venues with the same name in one area (rejected ones don't count). The database
    enforces it too (NAME_TAKEN_CONSTRAINT); this gives the friendly message first."""
    clash = Venue.objects.filter(name__iexact=name, area=area).exclude(status=VenueStatus.REJECTED)
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    existing = clash.first()
    if existing is not None:
        raise _name_taken(existing.name, area)


def _is_name_clash(exc: IntegrityError) -> bool:
    return NAME_TAKEN_CONSTRAINT in str(exc)


def draft_venue_of(user) -> Venue | None:
    """The venue this owner is still setting up, if any (one draft at a time)."""
    return (
        Venue.objects.filter(
            status=VenueStatus.DRAFT, memberships__user=user, memberships__role=MemberRole.OWNER
        )
        .order_by("created_at", "pk")
        .first()
    )


def create_venue(*, owner, name: str, area, phone: str) -> Venue:
    """Create a draft venue with default settings, hours and peak times; ``owner`` owns it.

    The calendar can be used before approval (BR-22); players can't see it until approved.
    An owner sets up one venue at a time: while they have a draft, they finish that one first.
    Two venues can't have the same name in the same area.
    """
    name = clean_venue_name(name)
    with transaction.atomic():
        # Serialise this owner's create requests: a double tap can't make two drafts.
        advisory_xact_lock(f"venue-create:{owner.pk}")
        draft = draft_venue_of(owner)
        if draft is not None:
            raise RuleViolation(_("Finish setting up %(venue)s first.") % {"venue": draft.name})
        _check_name_free(name, area)
        try:
            with transaction.atomic():
                venue = Venue.objects.create(
                    name=name, slug=_unique_slug(name), area=area, phone=phone
                )
        except IntegrityError as exc:  # listed by someone else a moment ago
            if _is_name_clash(exc):
                raise _name_taken(name, area) from None
            raise
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
    if "name" in fields:
        fields["name"] = clean_venue_name(fields["name"])
    for name, value in fields.items():
        setattr(venue, name, value.strip() if isinstance(value, str) else value)
    if "name" in fields or "area" in fields:
        _check_name_free(venue.name, venue.area, exclude_pk=venue.pk)
    try:
        with transaction.atomic():
            venue.save()
    except IntegrityError as exc:
        if _is_name_clash(exc):
            raise _name_taken(venue.name, venue.area) from None
        raise
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


SETUP_STEPS = 6  # V1 details, V2 location, V3 courts, V4 hours, V5 prices, V6 review


def finish_setup_step(venue: Venue, actor, step: int) -> Venue:
    """Remember that the owner finished ``step`` (1-5) so setup reopens at the next one."""
    _require_owner(venue, actor)
    if not 1 <= step < SETUP_STEPS:
        raise ValueError(f"Unknown setup step: {step}")
    if step > venue.setup_step:
        venue.setup_step = step
        venue.save(update_fields=["setup_step", "updated_at"])
    return venue


def next_setup_step(venue: Venue) -> int:
    return min(venue.setup_step + 1, SETUP_STEPS)


def in_setup(venue: Venue) -> bool:
    """Draft venues go through the setup steps (V1-V6) before submitting."""
    return venue.status == VenueStatus.DRAFT


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


def status_counts() -> dict[str, int]:
    """Number of venues per status (admin home, A1)."""
    counts = dict.fromkeys(VenueStatus.values, 0)
    rows = Venue.objects.values("status").annotate(n=Count("pk")).values_list("status", "n")
    counts.update(rows)
    return counts


def waiting_for_review():
    """Venues waiting for approval, oldest first, with one owner's name and number (A1)."""
    owner = VenueMembership.objects.filter(venue=OuterRef("pk"), role=MemberRole.OWNER).order_by(
        "created_at", "pk"
    )
    return (
        Venue.objects.filter(status=VenueStatus.PENDING)
        .select_related("area")
        .annotate(
            owner_name=Subquery(owner.values("user__name")[:1]),
            owner_phone=Subquery(owner.values("user__phone")[:1]),
        )
        .order_by("status_changed_at", "pk")
    )


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
