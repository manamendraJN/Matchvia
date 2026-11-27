"""Venue dashboard for owners and staff: calendar, new booking, details, move, cancel, no-show,
arrived and blocks (V8-V14, US-S01-S07).

Every view gets the venue from a decorator in venues/decorators.py (404 unless a member) and
looks things up only through ``.for_venue(venue)`` (CLAUDE.md rule 2). The booking rules are all
in bookings/services.py; these views only collect input and show results.
"""

from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.exceptions import NotAllowed, RuleViolation, SlotTaken
from core.formatting import format_date, format_range, format_time
from core.timeutils import at_operating_minute, operating_date, operating_minute
from pricing import services as pricing
from venues import services as venue_services
from venues.decorators import members_only, owner_only
from venues.models import Court, MemberRole, VenueCustomer, VenueStatus

from . import calendar as cal
from . import selectors, services
from .forms_manage import (
    MAX_STAFF_SLOTS,
    BlockForm,
    CloseDayForm,
    CustomerBlockForm,
    CustomerForm,
    MoveForm,
    NewBookingForm,
    SeriesCancelForm,
    StaffCancelForm,
    WeeklyForm,
)
from .models import (
    ACTIVE_STATUSES,
    Booking,
    Kind,
    RecurringSeries,
    SeriesStatus,
    Source,
    Status,
)
from .selectors import get_available_slots


def _context(venue, **extra):
    return {"venue": venue, "can_edit": venue.member_role == MemberRole.OWNER, **extra}


def _day(request) -> date:
    today = operating_date(timezone.now())
    try:
        return date.fromisoformat(request.GET["date"])
    except (KeyError, ValueError):
        return today


def _calendar_url(venue, day: date) -> str:
    return f"{reverse('manage:dashboard', args=[venue.pk])}?{urlencode({'date': day.isoformat()})}"


def _booking(venue, booking_id) -> Booking:
    return get_object_or_404(
        Booking.objects.for_venue(venue).select_related("court", "venue_customer", "created_by"),
        pk=booking_id,
    )


def _court_param(venue, value):
    try:
        return Court.objects.for_venue(venue).filter(is_active=True).get(pk=int(value))
    except (TypeError, ValueError, Court.DoesNotExist):
        return None


# ---------------------------------------------------------------- V8 day, V9 week


@members_only
@require_GET
def calendar(request, venue):
    day = _day(request)
    show_cancelled = request.GET.get("cancelled") == "1"
    closure = services.day_closure(venue, day)
    context = _context(
        venue,
        cal=cal.day_calendar(venue, day, show_cancelled=show_cancelled),
        closure=closure,
        closure_note=services.closure_note(closure),
        day=day,
        today=operating_date(timezone.now()),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        show_cancelled=show_cancelled,
        missing=(
            venue_services.missing_for_submission(venue)
            if venue.status in {VenueStatus.DRAFT, VenueStatus.REJECTED}
            else []
        ),
    )
    if request.headers.get("HX-Request") == "true":
        return render(request, "bookings/manage/_day_grid.html", context)
    return render(request, "bookings/manage/calendar.html", context)


@members_only
@require_GET
def week(request, venue):
    courts = list(Court.objects.for_venue(venue).filter(is_active=True))
    court = _court_param(venue, request.GET.get("court")) or (courts[0] if courts else None)
    first = _day(request)
    context = _context(venue, courts=courts, court=court, first=first)
    if court is not None:
        context.update(
            week=cal.week_calendar(venue, court, first),
            prev_week=first - timedelta(days=7),
            next_week=first + timedelta(days=7),
        )
    return render(request, "bookings/manage/week.html", context)


# ---------------------------------------------------------------- V10 new booking


def _duration_choices(court, start) -> list[int]:
    """How many slots in a row are free from ``start`` (staff view), at most 8 (V10)."""
    if court is None or start is None:
        return list(range(1, 5))
    free = {s.start for s in get_available_slots(court, operating_date(start), for_staff=True)}
    step = timedelta(minutes=court.slot_minutes)
    count = 0
    while count < MAX_STAFF_SLOTS and start + count * step in free:
        count += 1
    return list(range(1, max(count, 1) + 1))


def _taken_message(court, start, end) -> str:
    other = (
        Booking.objects.filter(
            court=court, status__in=ACTIVE_STATUSES, start_at__lt=end, end_at__gt=start
        )
        .exclude(kind=Kind.BLOCK)
        .first()
    )
    if other and other.source == Source.ONLINE and other.customer_name:
        return _("This time was just booked online by %(name)s.") % {"name": other.customer_name}
    return _("This time was just booked. Choose another free time.")


@members_only
@require_http_methods(["GET", "POST"])
def new_booking(request, venue):
    court = _court_param(venue, request.GET.get("court"))
    start = None
    if request.GET.get("start"):
        try:
            start = timezone.make_aware(datetime.strptime(request.GET["start"], "%Y-%m-%dT%H:%M"))
        except ValueError:
            start = None
    soon = start is not None and start - timezone.now() <= timedelta(hours=1)
    initial = {
        "court": court,
        "date": operating_date(start) if start else operating_date(timezone.now()),
        "start_minute": operating_minute(start) if start else None,
        "slots": 1,
        # UX4: walk-in if the slot starts within the hour, otherwise phone.
        "source": Source.WALK_IN if (soon or start is None) else Source.PHONE,
    }
    form = NewBookingForm(request.POST or None, initial=initial, venue=venue)
    outside_hours = False
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        court = data["court"]
        start = at_operating_minute(data["date"], data["start_minute"])
        end = start + timedelta(minutes=court.slot_minutes * data["slots"])
        try:
            booking = services.create_staff_booking(
                venue=venue,
                actor=request.user,
                court_id=court.pk,
                start_at=start,
                end_at=end,
                source=data["source"],
                customer_name=data["customer_name"],
                customer_phone=data["customer_phone"],
                price_lkr=data["price_lkr"] if data["change_price"] else None,
                price_change_reason=data["price_change_reason"],
                notes=data["notes"],
                allow_outside_hours="save_anyway" in request.POST,
            )
        except services.OutsideOpeningHours:
            outside_hours = True
        except SlotTaken:
            form.add_error(None, _taken_message(court, start, end))
        except (RuleViolation, NotAllowed) as exc:
            form.add_error(None, exc.message)
        else:
            text = _("Booking saved.")
            if (
                booking.venue_customer_id
                and data["source"] != Source.WALK_IN
                and venue.settings.sms_on_phone_bookings
            ):
                text = _("Booking saved. SMS sent to the customer.")
            messages.success(request, text)
            return redirect(_calendar_url(venue, booking.operating_date))
    context = _context(
        venue,
        form=form,
        outside_hours=outside_hours,
        durations=_duration_choices(court, start),
        slot_minutes=court.slot_minutes if court else None,
        price=pricing.price_for(court, start) if court and start else None,
        start=start,
        court=court,
    )
    return render(request, "bookings/manage/new_booking.html", context)


@members_only
@require_GET
def customer_lookup(request, venue):
    """Suggestion under the phone field (V10): name, bookings and no-shows at this venue only."""
    from core.phone import InvalidPhone, normalise_phone

    customer = None
    try:
        phone = normalise_phone(request.GET.get("customer_phone", ""))
        customer = VenueCustomer.objects.for_venue(venue).filter(phone=phone).first()
    except InvalidPhone:
        pass
    context = {"customer": customer, "stats": cal.customer_stats(customer) if customer else None}
    return render(request, "bookings/manage/_customer_hint.html", context)


# ---------------------------------------------------------------- V11 details and actions


@members_only
@require_GET
def booking_detail(request, venue, booking_id):
    booking = _booking(venue, booking_id)
    now = timezone.now()
    context = _context(
        venue,
        booking=booking,
        when=format_range(booking.start_at, booking.end_at),
        events=booking.events.select_related("actor"),
        stats=cal.customer_stats(booking.venue_customer) if booking.venue_customer_id else None,
        no_show_from=booking.start_at + services.NO_SHOW_FROM,
        can_no_show=(
            booking.status == Status.CONFIRMED
            and booking.start_at + services.NO_SHOW_FROM
            <= now
            <= booking.end_at + services.NO_SHOW_UNTIL
        ),
        can_undo=booking.status == Status.NO_SHOW
        and now <= booking.end_at + services.NO_SHOW_UNTIL,
        is_future=booking.status == Status.CONFIRMED and booking.start_at > now,
        can_arrive=(
            booking.status == Status.CONFIRMED
            and booking.checked_in_at is None
            and booking.operating_date <= operating_date(now)
        ),
    )
    template = (
        "bookings/manage/block_detail.html"
        if booking.kind == Kind.BLOCK
        else "bookings/manage/booking_detail.html"
    )
    return render(request, template, context)


def _action(request, venue, booking_id, call, success):
    booking = _booking(venue, booking_id)
    try:
        call(venue=venue, actor=request.user, booking_id=booking.pk)
    except (RuleViolation, SlotTaken, NotAllowed) as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, success)
    return redirect("manage:booking_detail", venue_id=venue.pk, booking_id=booking.pk)


@members_only
@require_POST
def mark_no_show(request, venue, booking_id):
    return _action(
        request,
        venue,
        booking_id,
        services.mark_no_show,
        _("Marked as a no-show. The rest of the time is free for walk-ins."),
    )


@members_only
@require_POST
def undo_no_show(request, venue, booking_id):
    return _action(request, venue, booking_id, services.undo_no_show, _("No-show undone."))


@members_only
@require_POST
def mark_arrived(request, venue, booking_id):
    return _action(request, venue, booking_id, services.mark_arrived, _("Marked as arrived."))


# ---------------------------------------------------------------- V12 move, V13 cancel


@members_only
@require_http_methods(["GET", "POST"])
def move_booking(request, venue, booking_id):
    booking = _booking(venue, booking_id)
    if booking.kind != Kind.BOOKING:
        return redirect("manage:booking_detail", venue_id=venue.pk, booking_id=booking.pk)
    duration = int((booking.end_at - booking.start_at).total_seconds() // 60)
    court = _court_param(venue, request.GET.get("court")) or booking.court
    day = _day(request) if request.GET.get("date") else booking.operating_date
    form = MoveForm(
        request.POST or None,
        initial={"court": court, "date": day, "start_minute": operating_minute(booking.start_at)},
        venue=venue,
    )
    outside_hours = False
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.move_booking(
                venue=venue,
                actor=request.user,
                booking_id=booking.pk,
                court_id=data["court"].pk,
                start_at=at_operating_minute(data["date"], data["start_minute"]),
                keep_price=data["keep_price"],
                price_change_reason=data["price_change_reason"],
                allow_outside_hours="save_anyway" in request.POST,
            )
        except services.OutsideOpeningHours:
            outside_hours = True
        except SlotTaken:
            form.add_error(None, _("That time was just booked. Choose another."))
        except (RuleViolation, NotAllowed) as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(
                request, _("Booking moved. The customer gets an SMS if we have their number.")
            )
            return redirect("manage:booking_detail", venue_id=venue.pk, booking_id=booking.pk)
    starts = (
        cal.free_starts(court, day, duration, exclude=booking)
        if duration % court.slot_minutes == 0
        else []
    )
    context = _context(
        venue,
        booking=booking,
        form=form,
        when=format_range(booking.start_at, booking.end_at),
        court=court,
        day=day,
        starts=[(s, operating_minute(s), format_time(s)) for s in starts],
        outside_hours=outside_hours,
        courts=Court.objects.for_venue(venue).filter(is_active=True),
    )
    return render(request, "bookings/manage/move.html", context)


@members_only
@require_http_methods(["GET", "POST"])
def cancel_booking(request, venue, booking_id):
    booking = _booking(venue, booking_id)
    if booking.kind != Kind.BOOKING:
        return redirect("manage:booking_detail", venue_id=venue.pk, booking_id=booking.pk)
    form = StaffCancelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.cancel_by_staff(
                venue=venue,
                actor=request.user,
                booking_id=booking.pk,
                reason=form.cleaned_data["reason"],
            )
        except (RuleViolation, NotAllowed) as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, _("Booking cancelled."))
            return redirect(_calendar_url(venue, booking.operating_date))
    window = timedelta(hours=venue.settings.cancellation_window_hours)
    context = _context(
        venue,
        booking=booking,
        form=form,
        when=format_range(booking.start_at, booking.end_at),
        inside_window=booking.start_at - timezone.now() <= window,
    )
    return render(request, "bookings/manage/cancel.html", context)


# ---------------------------------------------------------------- V14 blocks


@members_only
@require_http_methods(["GET", "POST"])
def new_block(request, venue):
    day = _day(request)
    form = BlockForm(
        request.POST or None,
        initial={"date": day, "start_minute": 360, "end_minute": 480, "reason": "maintenance"},
        venue=venue,
    )
    conflicts = []
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.create_block(
                venue=venue,
                actor=request.user,
                court_ids=[c.pk for c in data["courts"]],
                start_at=at_operating_minute(data["date"], data["start_minute"]),
                end_at=at_operating_minute(data["date"], data["end_minute"]),
                reason=data["reason"],
                notes=data["notes"],
            )
        except services.BlockConflict as exc:
            conflicts = exc.conflicts
            form.add_error(None, exc.message)
        except RuleViolation as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, _("Time blocked. Players see it as unavailable."))
            return redirect(_calendar_url(venue, data["date"]))
    return render(
        request, "bookings/manage/block.html", _context(venue, form=form, conflicts=conflicts)
    )


@members_only
@require_POST
def remove_block(request, venue, booking_id):
    block = get_object_or_404(Booking.objects.for_venue(venue), pk=booking_id, kind=Kind.BLOCK)
    try:
        services.cancel_block(venue=venue, actor=request.user, booking_id=block.pk)
    except Booking.DoesNotExist:
        messages.error(request, _("This block was already removed."))
    except RuleViolation as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, _("Block removed."))
    return redirect(_calendar_url(venue, block.operating_date))


# ---------------------------------------------------------------- V18, V19 customer book


@members_only
@require_GET
def customers(request, venue):
    query = request.GET.get("q", "")
    rows = list(selectors.customer_book(venue, query)[:200])
    context = _context(venue, customers=rows, query=query)
    return render(request, "bookings/manage/customers.html", context)


def _customer_or_404(venue, customer_id) -> VenueCustomer:
    return get_object_or_404(VenueCustomer.objects.for_venue(venue), pk=customer_id)


@members_only
@require_http_methods(["GET", "POST"])
def customer_detail(request, venue, customer_id):
    """V19. Owner and staff edit name and notes; blocking is on its own owner-only URLs."""
    customer = _customer_or_404(venue, customer_id)
    deleted = customer.phone is None
    form = CustomerForm(
        request.POST or None, initial={"name": customer.name, "notes": customer.notes}
    )
    if request.method == "POST" and form.is_valid():
        try:
            venue_services.update_customer(venue, request.user, customer.pk, **form.cleaned_data)
        except RuleViolation as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, _("Saved."))
            return redirect("manage:customer_detail", venue_id=venue.pk, customer_id=customer.pk)
    context = _context(
        venue,
        customer=customer,
        deleted=deleted,
        form=form,
        block_form=CustomerBlockForm(),
        stats=cal.customer_stats(customer),
        **selectors.customer_history(venue, customer),
    )
    return render(request, "bookings/manage/customer_detail.html", context)


@owner_only
@require_POST
def customer_block(request, venue, customer_id):
    customer = _customer_or_404(venue, customer_id)
    form = CustomerBlockForm(request.POST)
    reason = form.cleaned_data["reason"] if form.is_valid() else ""
    try:
        venue_services.block_customer_online(venue, request.user, customer.pk, reason=reason)
    except RuleViolation as exc:
        messages.error(request, exc.message)
    else:
        messages.success(
            request, _("Blocked from online booking here. They can still book through you.")
        )
    return redirect("manage:customer_detail", venue_id=venue.pk, customer_id=customer.pk)


@owner_only
@require_POST
def customer_unblock(request, venue, customer_id):
    customer = _customer_or_404(venue, customer_id)
    try:
        venue_services.unblock_customer_online(venue, request.user, customer.pk)
    except RuleViolation as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, _("Unblocked. They can book online again."))
    return redirect("manage:customer_detail", venue_id=venue.pk, customer_id=customer.pk)


# ---------------------------------------------------------------- V15 close the venue for a day


@members_only
@require_http_methods(["GET", "POST"])
def close_day(request, venue):
    """Close a whole day. With bookings, show them and offer "Cancel all and send SMS" (BR-16)."""
    form = CloseDayForm(request.POST or None, initial={"date": _day(request)})
    in_the_way = []
    if request.method == "POST" and form.is_valid():
        day, note = form.cleaned_data["date"], form.cleaned_data["note"]
        try:
            cancelled = services.close_day(
                venue=venue,
                actor=request.user,
                day=day,
                note=note,
                cancel_bookings=request.POST.get("cancel_all") == "1",
            )
        except services.DayHasBookings as exc:
            in_the_way = exc.bookings
        except RuleViolation as exc:
            form.add_error(None, exc.message)
        else:
            if cancelled:
                messages.success(
                    request,
                    ngettext(
                        "Day closed. %(count)d booking was cancelled; the customer gets an SMS.",
                        "Day closed. %(count)d bookings were cancelled; customers get an SMS.",
                        cancelled,
                    )
                    % {"count": cancelled},
                )
            else:
                messages.success(request, _("Day closed. Players see it as closed."))
            return redirect(_calendar_url(venue, day))
    context = _context(venue, form=form, in_the_way=in_the_way)
    return render(request, "bookings/manage/close_day.html", context)


@members_only
@require_POST
def reopen_day(request, venue):
    form = CloseDayForm(request.POST)
    if not form.is_valid():
        return redirect("manage:dashboard", venue_id=venue.pk)
    day = form.cleaned_data["date"]
    try:
        services.reopen_day(venue=venue, actor=request.user, day=day)
    except RuleViolation as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, _("The day is open again."))
    return redirect(_calendar_url(venue, day))


# ---------------------------------------------------------------- V16 weekly bookings (US-S08)


def _short(day) -> str:
    """'29 Dec' (without the weekday)."""
    return format_date(day).split(" ", 1)[1]


@members_only
@require_GET
def weekly(request, venue):
    series_list = (
        RecurringSeries.objects.for_venue(venue)
        .filter(status__in=[SeriesStatus.APPROVED, SeriesStatus.PENDING])
        .select_related("court", "venue_customer", "team")
        .order_by("-status", "weekday", "start_minute")
    )
    rows = [
        (s, format_time(at_operating_minute(s.first_date, s.start_minute))) for s in series_list
    ]
    return render(request, "bookings/manage/weekly.html", _context(venue, rows=rows))


@members_only
@require_http_methods(["GET", "POST"])
def weekly_new(request, venue):
    court = _court_param(venue, request.GET.get("court"))
    start = None
    if request.GET.get("start"):
        try:
            start = timezone.make_aware(datetime.strptime(request.GET["start"], "%Y-%m-%dT%H:%M"))
        except ValueError:
            start = None
    form = WeeklyForm(
        request.POST or None,
        initial={
            "court": court,
            "first_date": operating_date(start) if start else operating_date(timezone.now()),
            "start_minute": operating_minute(start) if start else 1200,
            "slots": 1,
        },
        venue=venue,
    )
    plans = None
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        duration = data["court"].slot_minutes * data["slots"]
        try:
            if "create" in request.POST:
                series, created = services.create_staff_series(
                    venue=venue,
                    actor=request.user,
                    court_id=data["court"].pk,
                    first_date=data["first_date"],
                    start_minute=data["start_minute"],
                    duration_minutes=duration,
                    weeks=data["weeks"],
                    customer_name=data["customer_name"],
                    customer_phone=data["customer_phone"],
                )
                text = _("%(n)d weeks booked.") % {"n": len(created)}
                if series.skipped:
                    days = ", ".join(_short(date.fromisoformat(s["date"])) for s in series.skipped)
                    text += " " + _("%(n)d skipped (%(days)s).") % {
                        "n": len(series.skipped),
                        "days": days,
                    }
                messages.success(request, text)
                return redirect("manage:series_detail", venue_id=venue.pk, series_id=series.pk)
            plans = services.plan_weeks(
                data["court"],
                first_date=data["first_date"],
                start_minute=data["start_minute"],
                duration_minutes=duration,
                weeks=data["weeks"],
                for_staff=True,
            )
        except (RuleViolation, NotAllowed) as exc:
            form.add_error(None, exc.message)
    context = _context(
        venue,
        form=form,
        plans=[(p, services.SKIP_LABELS.get(p.reason, "")) for p in plans] if plans else None,
        free_weeks=sum(1 for p in plans if p.ok) if plans else 0,
    )
    return render(request, "bookings/manage/weekly_new.html", context)


@members_only
@require_GET
def series_detail(request, venue, series_id):
    series = get_object_or_404(
        RecurringSeries.objects.for_venue(venue).select_related("court", "venue_customer"),
        pk=series_id,
    )
    context = _context(
        venue,
        series=series,
        bookings=series.bookings.order_by("start_at"),
        skipped=[
            (date.fromisoformat(s["date"]), services.SKIP_LABELS.get(s["reason"], s["reason"]))
            for s in series.skipped
        ],
        time=format_time(at_operating_minute(series.first_date, series.start_minute)),
        cancel_form=SeriesCancelForm(),
        can_decide=services.can_decide(venue, request.user),
    )
    if series.status == SeriesStatus.PENDING:
        plans = services.plan_weeks(
            series.court,
            first_date=series.first_date,
            start_minute=series.start_minute,
            duration_minutes=series.duration_minutes,
            weeks=series.weeks,
            for_staff=False,
        )
        context["plans"] = [(p, services.SKIP_LABELS.get(p.reason, "")) for p in plans]
        context["free_weeks"] = sum(1 for p in plans if p.ok)
        context["skip_weeks"] = len(plans) - context["free_weeks"]
        context["history"] = cal.customer_stats(series.venue_customer)
    return render(request, "bookings/manage/series_detail.html", context)


@members_only
@require_POST
def series_cancel(request, venue, series_id):
    series = get_object_or_404(RecurringSeries.objects.for_venue(venue), pk=series_id)
    form = SeriesCancelForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Choose a reason for cancelling."))
    else:
        try:
            cancelled, _kept = services.cancel_series_by_staff(
                venue=venue,
                actor=request.user,
                series_id=series.pk,
                reason=form.cleaned_data["reason"],
            )
        except RuleViolation as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, _("%(n)d weeks cancelled.") % {"n": len(cancelled)})
    return redirect("manage:series_detail", venue_id=venue.pk, series_id=series.pk)


# ---------------------------------------------------------------- V17 captain requests (US-O07)


@members_only
@require_POST
def series_approve(request, venue, series_id):
    series = get_object_or_404(RecurringSeries.objects.for_venue(venue), pk=series_id)
    try:
        approved, created = services.approve_series(
            venue=venue, actor=request.user, series_id=series.pk
        )
    except (RuleViolation, NotAllowed) as exc:
        messages.error(request, exc.message)
    else:
        text = _("Approved: %(n)d weeks booked.") % {"n": len(created)}
        if approved.skipped:
            text += " " + _("%(n)d skipped.") % {"n": len(approved.skipped)}
        messages.success(request, text)
    return redirect("manage:series_detail", venue_id=venue.pk, series_id=series.pk)


@members_only
@require_POST
def series_reject(request, venue, series_id):
    series = get_object_or_404(RecurringSeries.objects.for_venue(venue), pk=series_id)
    try:
        services.reject_series(
            venue=venue,
            actor=request.user,
            series_id=series.pk,
            reason=request.POST.get("reason", ""),
        )
    except (RuleViolation, NotAllowed) as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, _("Request rejected. The captain gets an SMS."))
    return redirect("manage:series_detail", venue_id=venue.pk, series_id=series.pk)
