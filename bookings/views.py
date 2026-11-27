"""Player screens: search, venue page, review, confirm, My bookings, cancel (P1-P3, P7-P11).

Views stay thin: they parse the request, call selectors/services and render. Prices are always
recalculated on the server; availability is always read from the database (NFR-01).
"""

from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import dateformat, timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.decorators import profile_required
from core import ratelimit
from core.exceptions import NotAllowed, RateLimited, RuleViolation, SlotTaken
from core.formatting import format_date, format_range, format_time
from core.timeutils import at_operating_minute, local, operating_date, operating_minute
from pricing import services as pricing
from teams import services as teams
from teams.models import Team
from venues.models import Court, Facility, Venue

from . import selectors, services
from .forms import BookingForm, SearchForm, WeeklyRequestForm, day_choices
from .models import Booking, Kind, RecurringSeries, Status
from .reference import normalise_reference

BOOKINGS_PER_HOUR = 10  # BR-27


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _hit_booking_limit(request) -> None:
    ratelimit.hit("booking", str(request.user.pk), limit=BOOKINGS_PER_HOUR, window=3600)


def _venue_url(venue, day: date | None = None) -> str:
    url = reverse("venue_page", args=[venue.slug])
    return f"{url}?{urlencode({'date': day.isoformat()})}" if day else url


def _review_url(court, start, slots=1) -> str:
    query = {"court": court.pk, "start": local(start).strftime("%Y-%m-%dT%H:%M"), "slots": slots}
    return f"{reverse('book_review')}?{urlencode(query)}"


def _directions_url(venue) -> str:
    if venue.latitude is None:
        return ""
    return f"https://www.google.com/maps/dir/?api=1&destination={venue.latitude},{venue.longitude}"


# ---------------------------------------------------------------- P1 search (home)


@require_GET
def home(request):
    next_game = None
    if request.user.is_authenticated:
        upcoming, _past = selectors.player_bookings(request.user)
        next_game = upcoming[0] if upcoming else None
    form = SearchForm()
    return render(request, "bookings/home.html", {"form": form, "next_game": next_game})


# ---------------------------------------------------------------- P2 results


@never_cache
@require_GET
def search(request):
    form = SearchForm(request.GET)
    context = {"form": form, "results": [], "searched": False}
    if form.is_valid():
        data = form.cleaned_data
        context.update(
            searched=True,
            results=selectors.search(
                sport=data["sport"], area=data["area"], day=data["date"], time_window=data["time"]
            ),
            day=data["date"],
            day_label=dict(form.fields["date"].choices).get(data["date"].isoformat()),
            next_day_query=_query(request.GET, date=(data["date"] + timedelta(days=1)).isoformat()),
            any_time_query=_query(request.GET, time="any"),
        )
    template = "bookings/_results.html" if _is_htmx(request) else "bookings/results.html"
    return render(request, template, context)


def _query(params, **changes) -> str:
    values = params.copy()
    for key, value in changes.items():
        values[key] = value
    return values.urlencode()


# ---------------------------------------------------------------- P3 venue page


@never_cache
@require_GET
def venue_page(request, slug):
    venue = get_object_or_404(Venue.objects.select_related("area", "settings"), slug=slug)
    today = operating_date(timezone.now())
    try:
        day = date.fromisoformat(request.GET.get("date", "")) if request.GET.get("date") else today
    except ValueError:
        day = today
    view = selectors.venue_day(venue, day)
    next_day = None
    if view.state == "open" and not view.has_free:
        next_day = selectors.next_free_day(venue, day)
    context = {
        "venue": venue,
        "view": view,
        "day": day,
        "day_label": format_date(day),
        "days": day_choices(today),
        "next_day": next_day,
        "facilities": [label for code, label in Facility.choices if code in venue.facilities],
        "directions_url": _directions_url(venue),
        "photos": venue.photos.all()[:6],
        "sports": sorted({sport for court, _chips in view.courts for sport in court.sports}),
    }
    template = "bookings/_venue_day.html" if _is_htmx(request) else "bookings/venue.html"
    return render(request, template, context)


# ---------------------------------------------------------------- P7 review, confirm, P8 done


def _parse_booking(data) -> tuple[Court, BookingForm]:
    form = BookingForm(data)
    if not form.is_valid():
        raise Http404
    court = get_object_or_404(
        Court.objects.select_related("venue", "venue__settings", "venue__area"),
        pk=form.cleaned_data["court"],
        is_active=True,
    )
    return court, form


@never_cache
@profile_required
@require_GET
def review(request):
    court, form = _parse_booking(request.GET)
    venue = court.venue
    start = form.cleaned_data["start"]
    if not venue.is_public:
        messages.error(request, _("This venue isn't taking online bookings yet."))
        return redirect(_venue_url(venue))
    max_slots = selectors.consecutive_free(court, start)
    if max_slots == 0:
        messages.error(
            request,
            _("Sorry, %(time)s was just taken. Here are the times still free.")
            % {"time": format_time(start)},
        )
        return redirect(_venue_url(venue, operating_date(start)))
    slots = min(form.cleaned_data["slots"], max_slots)
    length = timedelta(minutes=court.slot_minutes)
    end = start + slots * length
    options = []
    for n in range(1, max_slots + 1):
        total = pricing.price_for(court, start, start + n * length)
        options.append(
            {
                "slots": n,
                "minutes": n * court.slot_minutes,
                "total": total,
                "url": _review_url(court, start, n),
            }
        )
    context = {
        "venue": venue,
        "court": court,
        "start": start,
        "end": end,
        "slots": slots,
        "when": format_range(start, end),
        "breakdown": pricing.slot_prices(court, start, end),
        "total": pricing.price_for(court, start, end),
        "options": options,
        "deadline": start - timedelta(hours=venue.settings.cancellation_window_hours),
        "form": BookingForm(
            initial={
                "court": court.pk,
                "start": local(start).strftime("%Y-%m-%dT%H:%M"),
                "slots": slots,
            }
        ),
        "back_url": _venue_url(venue, operating_date(start)),
        "teams": teams.captained_teams(request.user),
        "weekly_url": (
            f"{reverse('book_weekly')}?"
            + urlencode(
                {
                    "court": court.pk,
                    "start": local(start).strftime("%Y-%m-%dT%H:%M"),
                    "slots": slots,
                }
            )
        ),
    }
    return render(request, "bookings/review.html", context)


@never_cache
@profile_required
@require_POST
def confirm(request):
    court, form = _parse_booking(request.POST)
    start, slots = form.cleaned_data["start"], form.cleaned_data["slots"]
    try:
        _hit_booking_limit(request)
        booking = services.create_online_booking(
            user=request.user,
            court_id=court.pk,
            start_at=start,
            slots=slots,
            team_id=form.cleaned_data.get("team") or None,
        )
    except SlotTaken:
        mine = Booking.objects.filter(
            court=court,
            start_at=start,
            status=Status.CONFIRMED,
            venue_customer__user=request.user,
        ).first()
        if mine:  # a double tap on Confirm: show the booking already made (screens 5.1)
            messages.info(request, _("You already booked this time."))
            return redirect("book_done", reference=mine.display_reference)
        messages.error(
            request,
            _("Sorry, %(time)s was just taken. Here are the times still free.")
            % {"time": format_time(start)},
        )
        return redirect(_venue_url(court.venue, operating_date(start)))
    except RateLimited:
        messages.error(request, _("Too many booking attempts. Please try again in an hour."))
        return redirect(_review_url(court, start, slots))
    except (RuleViolation, NotAllowed) as exc:
        messages.error(request, exc.message)
        return redirect(_venue_url(court.venue, operating_date(start)))
    except (Court.DoesNotExist, Team.DoesNotExist):
        raise Http404 from None
    return redirect("book_done", reference=booking.display_reference)


def _own_booking(request, reference) -> Booking:
    """A booking of the signed-in player only; anyone else's reference is 404 (NFR-06)."""
    services.link_phone_bookings(request.user)
    try:
        return Booking.objects.select_related("venue", "venue__settings", "court").get(
            reference=normalise_reference(reference),
            kind=Kind.BOOKING,
            venue_customer__user=request.user,
        )
    except Booking.DoesNotExist:
        raise Http404 from None


@never_cache
@profile_required
@require_GET
def done(request, reference):
    booking = _own_booking(request, reference)
    venue_link = request.build_absolute_uri(_venue_url(booking.venue))
    share_text = _("%(sport)s %(when)s at %(venue)s, %(area)s. %(link)s") % {
        "sport": booking.court.get_sports_display(),
        "when": format_range(booking.start_at, booking.end_at),
        "venue": booking.venue.name,
        "area": booking.venue.area.name,
        "link": venue_link,
    }
    context = {
        "booking": booking,
        "when": format_range(booking.start_at, booking.end_at),
        "share_url": "https://wa.me/?" + urlencode({"text": share_text}),
        "directions_url": _directions_url(booking.venue),
    }
    return render(request, "bookings/done.html", context)


# ---------------------------------------------------------------- P9-P11 my bookings


@never_cache
@profile_required
@require_GET
def my_bookings(request):
    services.link_phone_bookings(request.user)
    upcoming, past = selectors.player_bookings(request.user)
    tab = "past" if request.GET.get("tab") == "past" else "upcoming"
    return render(
        request,
        "bookings/my_bookings.html",
        {
            "tab": tab,
            "bookings": past if tab == "past" else upcoming,
            "upcoming_count": len(upcoming),
            "series_list": services.series_for_player(request.user).filter(
                status__in=["pending", "approved"]
            ),
        },
    )


def _detail_context(booking):
    now = timezone.now()
    return {
        "booking": booking,
        "when": format_range(booking.start_at, booking.end_at),
        "can_cancel": services.player_can_cancel(booking, now) and booking.start_at > now,
        "is_upcoming": booking.status == Status.CONFIRMED and booking.end_at > now,
        "deadline": booking.start_at
        - timedelta(hours=booking.venue.settings.cancellation_window_hours),
        "directions_url": _directions_url(booking.venue),
    }


@never_cache
@profile_required
@require_GET
def booking_detail(request, reference):
    booking = _own_booking(request, reference)
    return render(request, "bookings/booking_detail.html", _detail_context(booking))


@never_cache
@profile_required
@require_http_methods(["GET", "POST"])
def booking_cancel(request, reference):
    booking = _own_booking(request, reference)
    detail_url = reverse("booking_detail", args=[booking.display_reference])
    if request.method == "GET":
        context = _detail_context(booking)
        if not context["can_cancel"]:
            return redirect(detail_url)
        return render(request, "bookings/cancel.html", context)
    try:
        _hit_booking_limit(request)
        services.cancel_by_player(user=request.user, booking_id=booking.pk)
    except RateLimited:
        messages.error(request, _("Too many attempts. Please try again in an hour."))
        return redirect(detail_url)
    except RuleViolation as exc:
        # The window may have closed while the page was open (P11).
        messages.error(request, exc.message)
        return redirect(detail_url)
    messages.success(request, _("Booking cancelled. We've sent an SMS."))
    return redirect("my_bookings")


# ---------------------------------------------------------------- P12, P13 weekly slots


def _rule(series) -> str:
    start = at_operating_minute(series.first_date, series.start_minute)
    end = start + timedelta(minutes=series.duration_minutes)
    return f"{dateformat.format(series.first_date, 'l')}, {format_time(start)}–{format_time(end)}"


@never_cache
@profile_required
@require_http_methods(["GET", "POST"])
def weekly_request(request):
    """P12: same court, same time, every week. Captains only (a team feature)."""
    court, form = _parse_booking(request.GET)
    venue = court.venue
    start = form.cleaned_data["start"]
    captained = teams.captained_teams(request.user)
    if not captained.exists():
        messages.info(request, _("Create a team first: weekly slots are for teams."))
        return redirect("team_create")
    duration = court.slot_minutes * form.cleaned_data["slots"]
    request_form = WeeklyRequestForm(request.POST or None, teams=captained, venue=venue)
    weeks = venue.settings.recurring_default_weeks
    if request_form.is_bound and request_form.is_valid():
        weeks = request_form.cleaned_data["weeks"]
    plans = []
    try:
        plans = services.plan_weeks(
            court,
            first_date=operating_date(start),
            start_minute=operating_minute(start),
            duration_minutes=duration,
            weeks=weeks,
            for_staff=False,
        )
    except RuleViolation as exc:
        request_form.add_error(None, exc.message)
    if request.method == "POST" and request_form.is_valid() and "send" in request.POST:
        try:
            series = services.request_series(
                user=request.user,
                team_id=request_form.cleaned_data["team"].pk,
                court_id=court.pk,
                first_date=operating_date(start),
                start_minute=operating_minute(start),
                duration_minutes=duration,
                weeks=weeks,
            )
        except (RuleViolation, NotAllowed) as exc:
            request_form.add_error(None, exc.message)
        else:
            messages.success(request, _("Request sent. The venue will reply within 48 hours."))
            return redirect("my_weekly", series_id=series.pk)
    context = {
        "venue": venue,
        "court": court,
        "form": request_form,
        "plans": [(p, services.SKIP_LABELS.get(p.reason, "")) for p in plans],
        "rule": (
            f"{dateformat.format(local(start), 'l')}, "
            f"{format_time(start)}–{format_time(start + timedelta(minutes=duration))}"
        ),
    }
    return render(request, "bookings/weekly_request.html", context)


@never_cache
@profile_required
@require_GET
def my_weekly(request, series_id):
    """P13: status of a request or series, its weeks, and cancelling."""
    try:
        series = services.series_for_player(request.user).get(pk=series_id)
    except RecurringSeries.DoesNotExist:
        raise Http404 from None
    now = timezone.now()
    bookings = list(series.bookings.order_by("start_at"))
    context = {
        "series": series,
        "rule": _rule(series),
        "bookings": [
            (b, services.player_can_cancel(b, now) and b.start_at > now) for b in bookings
        ],
        "skipped": [
            (date.fromisoformat(s["date"]), services.SKIP_LABELS.get(s["reason"], s["reason"]))
            for s in series.skipped
        ],
    }
    return render(request, "bookings/my_weekly.html", context)


@never_cache
@profile_required
@require_POST
def my_weekly_cancel(request, series_id):
    try:
        cancelled, kept = services.cancel_series_by_player(user=request.user, series_id=series_id)
    except RecurringSeries.DoesNotExist:
        raise Http404 from None
    except RuleViolation as exc:
        messages.error(request, exc.message)
        return redirect("my_weekly", series_id=series_id)
    text = _("%(n)d weeks cancelled.") % {"n": len(cancelled)}
    if kept:
        text += " " + _("%(n)d week is too close to cancel online. Call the venue for it.") % {
            "n": len(kept)
        }
    messages.success(request, text)
    return redirect("my_weekly", series_id=series_id)
