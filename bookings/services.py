"""The booking engine: online and staff bookings, cancellations, blocks, moves and no-shows.

Rules: requirements section 5 (BR-02 to BR-12, BR-17, BR-19, BR-23). Every function owns its
transaction, writes a BookingEvent and queues SMS in the same transaction (CLAUDE.md).

Double bookings are prevented by the database (exclusion constraint ``booking_no_overlap``).
Every insert or move runs inside a savepoint; if PostgreSQL rejects it because someone else got
the time first, the caller gets SlotTaken ("Sorry, this slot was just taken") and nothing changes.
The availability checks before that exist only to give clearer messages.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import dateformat, timezone
from django.utils.translation import gettext as _

from core.exceptions import NotAllowed, RuleViolation, SlotTaken
from core.formatting import format_date, format_time
from core.phone import INVALID_PHONE_MESSAGE, InvalidPhone, format_local, normalise_phone
from core.timeutils import at_operating_minute, operating_date, operating_minute
from notifications import services as notifications
from pricing import services as pricing
from venues import services as venue_services
from venues.models import Court, MemberRole, OpeningHours, VenueCustomer, VenueStatus

from .models import (
    ACTIVE_STATUSES,
    BlockReason,
    Booking,
    BookingEvent,
    CancelReason,
    EventAction,
    Kind,
    RecurringSeries,
    SeriesOrigin,
    SeriesStatus,
    Source,
    Status,
)
from .reference import generate_reference
from .selectors import booking_horizon_end, get_available_slots, slot_grid

logger = logging.getLogger(__name__)

REFERENCE_ATTEMPTS = 5
NO_SHOW_FROM = timedelta(minutes=15)  # after start (BR-10)
NO_SHOW_UNTIL = timedelta(hours=48)  # after end (BR-10)
STAFF_SOURCES = {Source.PHONE, Source.WHATSAPP, Source.WALK_IN}
NAME_MAX_LENGTH = 80


class OutsideOpeningHours(RuleViolation):
    """Staff may still save after confirming (BR-23); the view offers 'Save anyway'."""


class BlockConflict(RuleViolation):
    """A block would cover confirmed bookings (BR-17). ``conflicts`` lists them."""

    def __init__(self, conflicts):
        super().__init__(_("This time has bookings. Move or cancel them first."))
        self.conflicts = conflicts


# ---------------------------------------------------------------- helpers


def _now(now: datetime | None) -> datetime:
    return now or timezone.now()


def _constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None)


def _save_checked(booking: Booking, *, insert: bool) -> None:
    """Save inside a savepoint; turn the overlap violation into SlotTaken.

    Inserts retry with a fresh reference if the random code is already used.
    """
    for _attempt in range(REFERENCE_ATTEMPTS):
        if insert:
            booking.reference = generate_reference()
        try:
            with transaction.atomic():
                booking.save(force_insert=insert)
            return
        except IntegrityError as exc:
            name = _constraint_name(exc)
            if name == "booking_no_overlap":
                raise SlotTaken(_("Sorry, this slot was just taken.")) from None
            if insert and name == "booking_reference_unique":
                continue
            raise
    raise RuntimeError("Could not generate a unique booking reference.")  # pragma: no cover


def _snapshot(booking: Booking) -> dict:
    """Non-personal fields for the audit log (no names or phones, BR-25)."""
    return {
        "court": booking.court_id,
        "start": booking.start_at.isoformat(),
        "end": booking.end_at.isoformat(),
        "price_lkr": booking.price_lkr,
        "status": booking.status,
    }


def _event(booking: Booking, actor, action: str, **changes) -> None:
    BookingEvent.objects.create(
        venue_id=booking.venue_id, booking=booking, actor=actor, action=action, changes=changes
    )


def _require_member(venue, actor) -> str:
    role = venue_services.member_role(venue, actor)
    if role is None:
        raise NotAllowed(_("You don't work at this venue."))
    return role


def _clean_name(value: str) -> str:
    name = " ".join((value or "").split())
    if not name:
        raise RuleViolation(_("Enter the customer's name."))
    if len(name) > NAME_MAX_LENGTH:
        raise RuleViolation(_("Use at most 80 characters for the name."))
    return name


def _whole_slots(court: Court, start_at: datetime, end_at: datetime) -> int:
    length = end_at - start_at
    slot = timedelta(minutes=court.slot_minutes)
    if length <= timedelta(0) or length % slot:
        raise RuleViolation(
            _("Bookings on %(court)s are made of %(m)d-minute slots.")
            % {"court": court.name, "m": court.slot_minutes}
        )
    return length // slot


def _within_opening_hours(court: Court, start_at: datetime, end_at: datetime) -> bool:
    day = operating_date(start_at)
    hours = OpeningHours.objects.for_venue(court.venue_id).filter(weekday=day.weekday()).first()
    if hours is None or hours.is_closed:
        return False
    start_minute = operating_minute(start_at)
    end_minute = start_minute + int((end_at - start_at).total_seconds() // 60)
    return hours.opens_minute <= start_minute and end_minute <= hours.closes_minute


def _customer_for(venue, *, phone: str, name: str, user=None) -> VenueCustomer:
    """The venue's customer row for this phone, created if new; links a registered player."""
    if user is None:
        user = get_user_model().objects.filter(phone=phone, is_active=True).first()
    try:
        with transaction.atomic():
            customer, created = VenueCustomer.objects.get_or_create(
                venue=venue, phone=phone, defaults={"name": name, "user": user}
            )
    except IntegrityError:  # created by a parallel request
        customer, created = VenueCustomer.objects.get(venue=venue, phone=phone), False
    if not created:
        changed = []
        if name and customer.name != name:
            customer.name = name
            changed.append("name")
        if user is not None and customer.user_id is None:
            customer.user = user
            changed.append("user")
        if changed:
            customer.save(update_fields=[*changed, "updated_at"])
    return customer


def _price_override(venue, role, calculated, price_lkr, reason) -> tuple[int, str]:
    """BR-19: staff may change the calculated price with a reason, if the owner allows it."""
    if price_lkr is None or price_lkr == calculated:
        return calculated, ""
    if price_lkr < 0:
        raise RuleViolation(_("The price can't be negative."))
    if role != MemberRole.OWNER and not venue.settings.staff_can_change_price:
        raise NotAllowed(_("Only the owner can change prices at this venue."))
    reason = " ".join((reason or "").split())
    if not reason:
        raise RuleViolation(_("Give a short reason for changing the price."))
    return price_lkr, reason[:255]


# ---------------------------------------------------------------- online booking (US-P04)


def create_online_booking(
    *, user, court_id, start_at: datetime, slots: int = 1, now: datetime | None = None
) -> Booking:
    """A player books ``slots`` consecutive slots, confirmed at once (BR-07: no hold in MVP).

    Raises SlotTaken, RuleViolation (rules) or NotAllowed (blocked player). ``Court.DoesNotExist``
    for an unknown or inactive court.
    """
    now = _now(now)
    court = Court.objects.select_related("venue", "venue__settings").get(
        pk=court_id, is_active=True
    )
    venue = court.venue
    settings = venue.settings
    if venue.status != VenueStatus.APPROVED:
        raise RuleViolation(_("This venue is not taking online bookings."))
    if not (user.is_authenticated and user.is_active and user.phone and user.name):
        raise NotAllowed(_("Sign in to book."))
    if not 1 <= slots <= settings.max_slots_per_booking:
        raise RuleViolation(
            _("You can book up to %(n)d slots in a row online.")
            % {"n": settings.max_slots_per_booking}
        )

    length = timedelta(minutes=court.slot_minutes)
    end_at = start_at + slots * length
    day = operating_date(start_at)
    wanted = {start_at + k * length for k in range(slots)}
    free = {slot.start for slot in get_available_slots(court, day, now=now)}
    if not wanted <= free:
        grid = {slot.start for slot in slot_grid(court, day)}
        if not wanted <= grid:
            raise RuleViolation(_("This time can't be booked. Choose another slot."))
        if start_at < now + timedelta(minutes=settings.min_notice_minutes):
            raise RuleViolation(
                _("Online booking closes %(m)d minutes before the start. Call the venue.")
                % {"m": settings.min_notice_minutes}
            )
        if day > booking_horizon_end(venue, now):
            raise RuleViolation(
                _("Bookings open up to %(n)d days ahead.") % {"n": settings.booking_horizon_days}
            )
        raise SlotTaken(_("Sorry, this slot was just taken."))

    with transaction.atomic():
        customer = _customer_for(venue, phone=user.phone, name=user.name, user=user)
        # Lock the customer so parallel bookings can't both pass the limit below (BR-12).
        customer = VenueCustomer.objects.select_for_update().get(pk=customer.pk)
        if customer.is_blocked_online:
            raise NotAllowed(
                _("Please contact the venue to book: %(phone)s")
                % {"phone": format_local(venue.phone)}
            )
        upcoming = (
            Booking.objects.for_venue(venue)
            .filter(
                venue_customer=customer,
                kind=Kind.BOOKING,
                source=Source.ONLINE,
                status=Status.CONFIRMED,
                start_at__gt=now,
                series__isnull=True,  # approved weekly series don't count (BR-12)
            )
            .count()
        )
        if upcoming >= settings.max_upcoming_online_bookings:
            raise RuleViolation(
                _("You already have %(n)d upcoming bookings here. Call the venue to book more.")
                % {"n": upcoming}
            )
        booking = Booking(
            venue=venue,
            court=court,
            kind=Kind.BOOKING,
            status=Status.CONFIRMED,
            source=Source.ONLINE,
            start_at=start_at,
            end_at=end_at,
            operating_date=day,
            venue_customer=customer,
            customer_name=customer.name,
            price_lkr=pricing.price_for(court, start_at, end_at),
            created_by=user,
        )
        _save_checked(booking, insert=True)
        _event(booking, user, EventAction.CREATED, **_snapshot(booking), source=Source.ONLINE)
        notifications.queue_booking_sms(booking, "booking_confirmation")
        notifications.schedule_reminder(booking, now=now)
    logger.info("booking.created id=%s venue=%s source=online", booking.pk, venue.pk)
    return booking


# ---------------------------------------------------------------- staff booking (US-S02, US-S03)


def create_staff_booking(
    *,
    venue,
    actor,
    court_id,
    start_at: datetime,
    end_at: datetime,
    source: str,
    customer_name: str,
    customer_phone: str = "",
    price_lkr: int | None = None,
    price_change_reason: str = "",
    notes: str = "",
    allow_outside_hours: bool = False,
) -> Booking:
    """Walk-in, phone or WhatsApp booking by owner or staff.

    Staff are not limited by notice, horizon or the per-player limit (US-S03). Outside opening
    hours raises OutsideOpeningHours unless ``allow_outside_hours`` (BR-23).
    """
    role = _require_member(venue, actor)
    court = Court.objects.for_venue(venue).get(pk=court_id)
    if not court.is_active:
        raise RuleViolation(_("This court is deactivated."))
    if source not in STAFF_SOURCES:
        raise RuleViolation(_("Choose walk-in, phone or WhatsApp."))
    name = _clean_name(customer_name)
    phone = ""
    if customer_phone and customer_phone.strip():
        try:
            phone = normalise_phone(customer_phone)
        except InvalidPhone:
            raise RuleViolation(str(INVALID_PHONE_MESSAGE)) from None
    if source in {Source.PHONE, Source.WHATSAPP} and not phone:
        raise RuleViolation(_("Enter the customer's phone number."))
    _whole_slots(court, start_at, end_at)
    if not allow_outside_hours and not _within_opening_hours(court, start_at, end_at):
        raise OutsideOpeningHours(_("This is outside your opening hours. Save anyway?"))

    calculated = pricing.price_for(court, start_at, end_at)
    price, reason = _price_override(venue, role, calculated, price_lkr, price_change_reason)

    with transaction.atomic():
        customer = _customer_for(venue, phone=phone, name=name) if phone else None
        booking = Booking(
            venue=venue,
            court=court,
            kind=Kind.BOOKING,
            status=Status.CONFIRMED,
            source=source,
            start_at=start_at,
            end_at=end_at,
            operating_date=operating_date(start_at),
            venue_customer=customer,
            customer_name=name,
            price_lkr=price,
            price_change_reason=reason,
            notes=(notes or "").strip()[:255],
            created_by=actor,
        )
        _save_checked(booking, insert=True)
        _event(booking, actor, EventAction.CREATED, **_snapshot(booking), source=source)
        if reason:
            _event(booking, actor, EventAction.PRICE_CHANGED, before=calculated, after=price)
        settings = venue.settings
        wants_sms = (
            settings.sms_on_walk_ins if source == Source.WALK_IN else settings.sms_on_phone_bookings
        )
        if wants_sms:
            notifications.queue_booking_sms(booking, "booking_confirmation")
        notifications.schedule_reminder(booking)
    logger.info("booking.created id=%s venue=%s source=%s", booking.pk, venue.pk, source)
    return booking


# ---------------------------------------------------------------- cancelling (US-P06, US-S05)


def _cancel(booking: Booking, *, actor, reason: str, late: bool, now: datetime) -> None:
    booking.status = Status.CANCELLED
    booking.cancelled_at = now
    booking.cancelled_by = actor
    booking.cancel_reason = reason
    booking.is_late_cancellation = late
    booking.save()
    _event(booking, actor, EventAction.CANCELLED, reason=reason, late=late)
    notifications.cancel_reminder(booking)


def player_can_cancel(booking: Booking, now: datetime | None = None) -> bool:
    """True while the booking starts more than the venue's window from now (BR-08)."""
    now = _now(now)
    window = timedelta(hours=booking.venue.settings.cancellation_window_hours)
    return booking.status == Status.CONFIRMED and booking.start_at - now > window


def cancel_by_player(*, user, booking_id, now: datetime | None = None) -> Booking:
    """The player cancels their own booking outside the venue's window (BR-08).

    Works for staff-entered bookings linked to their number too. Another player's booking id
    raises Booking.DoesNotExist (shown as 404).
    """
    now = _now(now)
    with transaction.atomic():
        booking = (
            Booking.objects.select_for_update(of=("self",))
            .select_related("venue", "venue__settings", "court", "venue_customer")
            .get(pk=booking_id, kind=Kind.BOOKING, venue_customer__user=user)
        )
        if booking.status != Status.CONFIRMED:
            raise RuleViolation(_("This booking is not active."))
        if booking.start_at <= now:
            raise RuleViolation(_("This booking has already started."))
        if not player_can_cancel(booking, now):
            raise RuleViolation(
                _("Cancellation closed. Call the venue: %(phone)s")
                % {"phone": format_local(booking.venue.phone)}
            )
        _cancel(booking, actor=user, reason=CancelReason.CUSTOMER_REQUEST, late=False, now=now)
        notifications.queue_booking_sms(booking, "booking_cancelled")
    return booking


def cancel_by_staff(
    *, venue, actor, booking_id, reason: str, now: datetime | None = None
) -> Booking:
    """Staff cancel any future booking at any time, with a reason (BR-09).

    A customer-requested cancellation inside the window is recorded as late (US-S05).
    """
    now = _now(now)
    _require_member(venue, actor)
    if reason not in CancelReason.values:
        raise RuleViolation(_("Choose a reason for cancelling."))
    with transaction.atomic():
        booking = (
            Booking.objects.for_venue(venue)
            .select_for_update(of=("self",))
            .select_related("venue", "venue__settings", "court", "venue_customer")
            .get(pk=booking_id, kind=Kind.BOOKING)
        )
        if booking.status != Status.CONFIRMED:
            raise RuleViolation(_("This booking is not active."))
        if booking.start_at <= now:
            raise RuleViolation(_("This booking has already started. Mark a no-show instead."))
        window = timedelta(hours=venue.settings.cancellation_window_hours)
        late = reason == CancelReason.CUSTOMER_REQUEST and booking.start_at - now <= window
        _cancel(booking, actor=actor, reason=reason, late=late, now=now)
        notifications.queue_booking_sms(booking, "booking_cancelled")
    return booking


# ---------------------------------------------------------------- blocks (US-S06, BR-17)


def create_block(
    *,
    venue,
    actor,
    court_ids,
    start_at: datetime,
    end_at: datetime,
    reason: str,
    notes: str = "",
) -> list[Booking]:
    """Block one or more courts. All or nothing: refused if any booking is in the way."""
    _require_member(venue, actor)
    if reason not in BlockReason.values:
        raise RuleViolation(_("Choose a reason for the block."))
    if end_at <= start_at:
        raise RuleViolation(_("The end must be after the start."))
    if end_at - start_at > timedelta(hours=24):
        raise RuleViolation(_("A block can be at most 24 hours."))
    wanted = set(court_ids)
    courts = list(Court.objects.for_venue(venue).filter(pk__in=wanted))
    if not wanted or len(courts) != len(wanted):
        raise Court.DoesNotExist

    def conflicts():
        return list(
            Booking.objects.for_venue(venue)
            .filter(
                court__in=courts,
                status__in=ACTIVE_STATUSES,
                start_at__lt=end_at,
                end_at__gt=start_at,
            )
            .select_related("court")
            .order_by("start_at")
        )

    if found := conflicts():
        raise BlockConflict(found)
    group = uuid.uuid4()
    blocks = []
    try:
        with transaction.atomic():
            for court in courts:
                block = Booking(
                    venue=venue,
                    court=court,
                    kind=Kind.BLOCK,
                    status=Status.CONFIRMED,
                    start_at=start_at,
                    end_at=end_at,
                    operating_date=operating_date(start_at),
                    block_reason=reason,
                    block_group=group,
                    notes=(notes or "").strip()[:255],
                    created_by=actor,
                )
                _save_checked(block, insert=True)
                _event(block, actor, EventAction.CREATED, **_snapshot(block), kind=Kind.BLOCK)
                blocks.append(block)
    except SlotTaken:
        raise BlockConflict(conflicts()) from None
    return blocks


def cancel_block(*, venue, actor, booking_id, now: datetime | None = None) -> Booking:
    _require_member(venue, actor)
    with transaction.atomic():
        block = (
            Booking.objects.for_venue(venue)
            .select_for_update()
            .get(pk=booking_id, kind=Kind.BLOCK, status=Status.CONFIRMED)
        )
        block.status = Status.CANCELLED
        block.cancelled_at = _now(now)
        block.cancelled_by = actor
        block.save()
        _event(block, actor, EventAction.CANCELLED)
    return block


# ---------------------------------------------------------------- moving (US-S04)


def move_booking(
    *,
    venue,
    actor,
    booking_id,
    court_id,
    start_at: datetime,
    keep_price: bool = False,
    price_change_reason: str = "",
    allow_outside_hours: bool = False,
    now: datetime | None = None,
) -> Booking:
    """Move a future booking to another time and/or court of the same venue.

    The price is recalculated unless ``keep_price`` (with a reason, BR-19). If the new time is
    taken, the database refuses the update and the booking stays exactly as it was.
    """
    now = _now(now)
    role = _require_member(venue, actor)
    with transaction.atomic():
        booking = (
            Booking.objects.for_venue(venue)
            .select_for_update(of=("self",))
            .select_related("venue", "venue__settings", "court", "venue_customer")
            .get(pk=booking_id, kind=Kind.BOOKING)
        )
        if booking.status != Status.CONFIRMED or booking.start_at <= now:
            raise RuleViolation(_("Only future confirmed bookings can be moved."))
        court = Court.objects.for_venue(venue).get(pk=court_id)
        if not court.is_active:
            raise RuleViolation(_("This court is deactivated."))
        end_at = start_at + (booking.end_at - booking.start_at)
        _whole_slots(court, start_at, end_at)
        if not allow_outside_hours and not _within_opening_hours(court, start_at, end_at):
            raise OutsideOpeningHours(_("This is outside your opening hours. Save anyway?"))

        before = _snapshot(booking)
        old_price = booking.price_lkr
        new_price = pricing.price_for(court, start_at, end_at)
        if keep_price and new_price != old_price:
            price, reason = _price_override(venue, role, new_price, old_price, price_change_reason)
        else:
            price, reason = new_price, ""

        booking.court = court
        booking.start_at = start_at
        booking.end_at = end_at
        booking.operating_date = operating_date(start_at)
        booking.price_lkr = price
        if reason:
            booking.price_change_reason = reason
        _save_checked(booking, insert=False)
        _event(booking, actor, EventAction.MOVED, before=before, after=_snapshot(booking))
        if price != old_price:
            _event(booking, actor, EventAction.PRICE_CHANGED, before=old_price, after=price)
        notifications.queue_booking_sms(booking, "booking_changed")
        notifications.reschedule_reminder(booking, now=now)
    return booking


# ---------------------------------------------------------------- no-shows (US-S07, BR-10)


def mark_no_show(*, venue, actor, booking_id, now: datetime | None = None) -> Booking:
    """From 15 minutes after the start until 48 hours after the end. Frees the court."""
    now = _now(now)
    _require_member(venue, actor)
    with transaction.atomic():
        booking = (
            Booking.objects.for_venue(venue)
            .select_for_update()
            .get(pk=booking_id, kind=Kind.BOOKING)
        )
        if booking.status != Status.CONFIRMED:
            raise RuleViolation(_("Only confirmed bookings can be marked as a no-show."))
        if now < booking.start_at + NO_SHOW_FROM:
            raise RuleViolation(_("You can mark a no-show from 15 minutes after the start."))
        if now > booking.end_at + NO_SHOW_UNTIL:
            raise RuleViolation(_("It's too late to mark this booking as a no-show."))
        booking.status = Status.NO_SHOW
        booking.no_show_marked_at = now
        booking.no_show_marked_by = actor
        booking.save()
        _event(booking, actor, EventAction.NO_SHOW)
        notifications.cancel_reminder(booking)
    return booking


def undo_no_show(*, venue, actor, booking_id, now: datetime | None = None) -> Booking:
    """Within 48 hours after the end, and only if nobody has booked the time since."""
    now = _now(now)
    _require_member(venue, actor)
    with transaction.atomic():
        booking = (
            Booking.objects.for_venue(venue)
            .select_for_update()
            .get(pk=booking_id, kind=Kind.BOOKING)
        )
        if booking.status != Status.NO_SHOW:
            raise RuleViolation(_("This booking is not marked as a no-show."))
        if now > booking.end_at + NO_SHOW_UNTIL:
            raise RuleViolation(_("It's too late to undo this no-show."))
        booking.status = Status.CONFIRMED
        booking.no_show_marked_at = None
        booking.no_show_marked_by = None
        try:
            _save_checked(booking, insert=False)
        except SlotTaken:
            raise SlotTaken(
                _("This time has been booked again, so the no-show can't be undone.")
            ) from None
        _event(booking, actor, EventAction.NO_SHOW_UNDONE)
    return booking


# ---------------------------------------------------------------- linking phone bookings (US-P01)


def link_phone_bookings(user) -> int:
    """Attach venue customer rows with the player's verified number to their account.

    Bookings staff entered by phone or WhatsApp then appear in My bookings and can be cancelled
    by the player (US-P01, US-P05). Safe to call often: only unlinked rows change. The number
    was proven by OTP at sign-in, so matching on it is safe.
    """
    if not user.phone:
        return 0
    return VenueCustomer.objects.filter(phone=user.phone, user__isnull=True).update(user=user)


# ---------------------------------------------------------------- arrived (C6)


def mark_arrived(*, venue, actor, booking_id, now: datetime | None = None) -> Booking:
    """Front-desk tick that the customer has arrived. Records who and when; changes no rule.

    Only for confirmed bookings on or before today's operating day (not future days).
    """
    now = _now(now)
    _require_member(venue, actor)
    with transaction.atomic():
        booking = (
            Booking.objects.for_venue(venue)
            .select_for_update()
            .get(pk=booking_id, kind=Kind.BOOKING)
        )
        if booking.status != Status.CONFIRMED:
            raise RuleViolation(_("Only confirmed bookings can be marked as arrived."))
        if booking.operating_date > operating_date(now):
            raise RuleViolation(_("You can mark arrivals on the day of the booking."))
        if booking.checked_in_at is None:
            booking.checked_in_at = now
            booking.checked_in_by = actor
            booking.save(update_fields=["checked_in_at", "checked_in_by", "updated_at"])
            _event(booking, actor, EventAction.ARRIVED)
    return booking


# ---------------------------------------------------------------- weekly series (data-model 5)

MIN_SERIES_WEEKS = 2
MAX_SKIPPED_IN_SMS = 3


@dataclass(frozen=True)
class WeekPlan:
    """One week of a series as previewed: free, or skipped with a reason (V16, V17)."""

    day: date
    start: datetime
    end: datetime
    reason: str = ""  # "", "booked", "blocked", "closed", "outside_hours", "too_soon"

    @property
    def ok(self) -> bool:
        return not self.reason


SKIP_LABELS = {
    "booked": _("already booked"),
    "blocked": _("blocked"),
    "closed": _("closed"),
    "outside_hours": _("outside opening hours"),
    "too_soon": _("too soon"),
}


def plan_weeks(
    court: Court,
    *,
    first_date: date,
    start_minute: int,
    duration_minutes: int,
    weeks: int,
    for_staff: bool,
    now: datetime | None = None,
) -> list[WeekPlan]:
    """Which weeks are free (data-model 5.2). Read-only; recalculated every time it's shown.

    Weeks clash with bookings and blocks (including closed days), closed weekdays, opening
    hours, and the past (staff) or the minimum notice (captain requests).
    """
    now = _now(now)
    start0 = at_operating_minute(first_date, start_minute)
    _whole_slots(court, start0, start0 + timedelta(minutes=duration_minutes))
    hours = (
        OpeningHours.objects.for_venue(court.venue_id).filter(weekday=first_date.weekday()).first()
    )
    earliest = (
        now if for_staff else now + timedelta(minutes=court.venue.settings.min_notice_minutes)
    )
    days = [first_date + timedelta(weeks=k) for k in range(weeks)]
    starts = [at_operating_minute(d, start_minute) for d in days]
    length = timedelta(minutes=duration_minutes)
    taken = list(
        Booking.objects.filter(
            court=court,
            status__in=ACTIVE_STATUSES,
            start_at__lt=starts[-1] + length,
            end_at__gt=starts[0],
        ).values_list("start_at", "end_at", "kind")
    )
    plans = []
    for day, start in zip(days, starts, strict=True):
        end = start + length
        clash = [kind for s, e, kind in taken if s < end and e > start]
        if hours is None or hours.is_closed:
            reason = "closed"
        elif (
            start_minute < hours.opens_minute
            or start_minute + duration_minutes > hours.closes_minute
        ):
            reason = "outside_hours"
        elif start < earliest:
            reason = "too_soon"
        elif clash:
            reason = "blocked" if all(k == Kind.BLOCK for k in clash) else "booked"
        else:
            reason = ""
        plans.append(WeekPlan(day=day, start=start, end=end, reason=reason))
    return plans


def _check_weeks(venue, weeks: int) -> None:
    limit = venue.settings.recurring_max_weeks
    if not MIN_SERIES_WEEKS <= weeks <= limit:
        raise RuleViolation(
            _("Choose between %(min)d and %(max)d weeks.") % {"min": MIN_SERIES_WEEKS, "max": limit}
        )


def _expand(series: RecurringSeries, *, actor, source: str, now: datetime, for_staff: bool) -> list:
    """Create one confirmed booking per free week (data-model 5.2 step 3).

    Each week is inserted in its own savepoint: if the overlap constraint fires for a week that
    looked free a moment ago, only that week is skipped. Prices are today's (US-C04).
    """
    court = series.court
    plans = plan_weeks(
        court,
        first_date=series.first_date,
        start_minute=series.start_minute,
        duration_minutes=series.duration_minutes,
        weeks=series.weeks,
        for_staff=for_staff,
        now=now,
    )
    created, skipped = [], []
    customer = series.venue_customer
    for plan in plans:
        if not plan.ok:
            skipped.append({"date": plan.day.isoformat(), "reason": plan.reason})
            continue
        booking = Booking(
            venue=series.venue,
            court=court,
            kind=Kind.BOOKING,
            status=Status.CONFIRMED,
            source=source,
            start_at=plan.start,
            end_at=plan.end,
            operating_date=plan.day,
            venue_customer=customer,
            customer_name=customer.name,
            price_lkr=pricing.price_for(court, plan.start, plan.end),
            series=series,
            created_by=actor,
        )
        try:
            _save_checked(booking, insert=True)
        except SlotTaken:
            skipped.append({"date": plan.day.isoformat(), "reason": "booked"})
            continue
        _event(booking, actor, EventAction.CREATED, **_snapshot(booking), series=series.pk)
        notifications.schedule_reminder(booking, now=now)
        created.append(booking)
    series.skipped = skipped
    series.save(update_fields=["skipped", "updated_at"])
    return created


def series_summary_sms(series: RecurringSeries, booked: int) -> None:
    """One SMS for the whole series, not one per week (US-C04, US-S08)."""
    phone = series.venue_customer.phone
    if not phone:
        return
    skipped_days = [date.fromisoformat(s["date"]) for s in series.skipped]
    skipped_text = ", ".join(
        format_date(d).split(" ", 1)[1] for d in skipped_days[:MAX_SKIPPED_IN_SMS]
    )
    if len(skipped_days) > MAX_SKIPPED_IN_SMS:
        skipped_text += f" +{len(skipped_days) - MAX_SKIPPED_IN_SMS}"
    start = at_operating_minute(series.first_date, series.start_minute)
    notifications.queue_sms(
        to_phone=phone,
        purpose="series_summary",
        body=notifications.render_sms(
            "series_summary",
            venue=series.venue.name,
            court=series.court.name,
            weekday=dateformat.format(series.first_date, "D"),
            time=format_time(start),
            booked=booked,
            first=format_date(series.first_date).split(" ", 1)[1],
            skipped=skipped_text,
        ),
        venue=series.venue,
    )


def create_staff_series(
    *,
    venue,
    actor,
    court_id,
    first_date: date,
    start_minute: int,
    duration_minutes: int,
    weeks: int,
    customer_name: str,
    customer_phone: str,
    now: datetime | None = None,
) -> tuple[RecurringSeries, list[Booking]]:
    """A regular team's weekly slot entered by staff: no approval step (US-S08).

    Clashing weeks are skipped and recorded; if every week clashes nothing is created.
    """
    now = _now(now)
    _require_member(venue, actor)
    court = Court.objects.for_venue(venue).get(pk=court_id)
    if not court.is_active:
        raise RuleViolation(_("This court is deactivated."))
    name = _clean_name(customer_name)
    try:
        phone = normalise_phone(customer_phone or "")
    except InvalidPhone:
        raise RuleViolation(_("Add a phone number so we can send the schedule.")) from None
    _check_weeks(venue, weeks)
    plans = plan_weeks(
        court,
        first_date=first_date,
        start_minute=start_minute,
        duration_minutes=duration_minutes,
        weeks=weeks,
        for_staff=True,
        now=now,
    )
    if not any(p.ok for p in plans):
        raise RuleViolation(_("All weeks clash. Choose another time."))

    with transaction.atomic():
        customer = _customer_for(venue, phone=phone, name=name)
        series = RecurringSeries.objects.create(
            venue=venue,
            court=court,
            origin=SeriesOrigin.STAFF,
            status=SeriesStatus.APPROVED,
            requested_by=actor,
            venue_customer=customer,
            weekday=first_date.weekday(),
            start_minute=start_minute,
            duration_minutes=duration_minutes,
            first_date=first_date,
            weeks=weeks,
            decided_by=actor,
            decided_at=now,
        )
        created = _expand(series, actor=actor, source=Source.PHONE, now=now, for_staff=True)
        if not created:
            raise RuleViolation(_("All weeks clash. Choose another time."))
        series_summary_sms(series, len(created))
    logger.info("series.created id=%s venue=%s weeks=%s", series.pk, venue.pk, len(created))
    return series, created


def _cancel_series_bookings(series, *, actor, reason, now, window: timedelta | None):
    """Cancel future weeks; with ``window`` (captain), weeks already inside it stay booked."""
    cancelled, kept = [], []
    future = (
        Booking.objects.filter(series=series, status=Status.CONFIRMED, start_at__gt=now)
        .select_for_update()
        .order_by("start_at")
    )
    for booking in future:
        if window is not None and booking.start_at - now <= window:
            kept.append(booking)
            continue
        _cancel(booking, actor=actor, reason=reason, late=False, now=now)
        cancelled.append(booking)
    series.status = SeriesStatus.CANCELLED
    series.cancelled_from = operating_date(now)
    series.save(update_fields=["status", "cancelled_from", "updated_at"])
    if cancelled and series.venue_customer.phone:
        start = at_operating_minute(series.first_date, series.start_minute)
        notifications.queue_sms(
            to_phone=series.venue_customer.phone,
            purpose="series_decision",
            body=notifications.render_sms(
                "series_cancelled",
                venue=series.venue.name,
                weekday=dateformat.format(series.first_date, "D"),
                time=format_time(start),
                first=format_date(cancelled[0].operating_date).split(" ", 1)[1],
            ),
            venue=series.venue,
        )
    return cancelled, kept


def cancel_series_by_staff(*, venue, actor, series_id, reason: str, now: datetime | None = None):
    """Staff cancel every future week, any time, with a reason (US-S08, BR-09)."""
    now = _now(now)
    _require_member(venue, actor)
    if reason not in CancelReason.values:
        raise RuleViolation(_("Choose a reason for cancelling."))
    with transaction.atomic():
        series = RecurringSeries.objects.for_venue(venue).select_for_update().get(pk=series_id)
        if series.status != SeriesStatus.APPROVED:
            raise RuleViolation(_("This weekly booking is not active."))
        return _cancel_series_bookings(series, actor=actor, reason=reason, now=now, window=None)


def cancel_series_by_player(*, user, series_id, now: datetime | None = None):
    """The captain cancels the rest of the series (US-C05, BR-14).

    Weeks outside the cancellation window are cancelled; weeks already inside it stay booked
    and are returned so the captain can be told to call the venue.
    """
    now = _now(now)
    with transaction.atomic():
        series = (
            RecurringSeries.objects.select_for_update(of=("self",))
            .select_related("venue__settings", "venue_customer")
            .get(pk=series_id, venue_customer__user=user)
        )
        if series.status != SeriesStatus.APPROVED:
            raise RuleViolation(_("This weekly booking is not active."))
        window = timedelta(hours=series.venue.settings.cancellation_window_hours)
        return _cancel_series_bookings(
            series, actor=user, reason=CancelReason.CUSTOMER_REQUEST, now=now, window=window
        )
