"""Venue dashboard: create a venue, profile and photos, courts, hours, prices (V1–V7, V21–V23, V25).

Views stay thin. Every view that takes a venue id gets the venue from a decorator in
decorators.py (404 unless a member), and every lookup inside uses ``.for_venue(venue)``.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import profile_required
from core.exceptions import RuleViolation
from core.phone import format_local
from pricing.models import PeakPeriod

from . import services
from .decorators import members_only, members_view_owner_edit, owner_only
from .forms import (
    CourtForm,
    CourtPriceForm,
    DayHoursFormSet,
    ImageUploadForm,
    PeakPeriodFormSet,
    VenueCreateForm,
    VenueProfileForm,
)
from .models import Court, MemberRole, OpeningHours, VenuePhoto

COURT_FIELDS = [
    "name",
    "sports",
    "is_indoor",
    "slot_minutes",
    "off_peak_price_lkr",
    "peak_price_lkr",
]


def _can_edit(venue) -> bool:
    return venue.member_role == MemberRole.OWNER


def _read_only(*forms_or_formsets) -> None:
    """Staff see owner pages read-only (US-O06); the server refuses their POSTs anyway."""
    for item in forms_or_formsets:
        for form in getattr(item, "forms", [item]):
            for field in form.fields.values():
                field.disabled = True


def _context(venue, **extra):
    return {"venue": venue, "can_edit": _can_edit(venue), **extra}


# ---------------------------------------------------------------- list and create (V7, V1)


@never_cache
@profile_required
def home(request):
    memberships = list(services.memberships_for_user(request.user))
    return render(request, "venues/home.html", {"memberships": memberships})


@never_cache
@profile_required
@require_http_methods(["GET", "POST"])
def create(request):
    form = VenueCreateForm(
        request.POST or None, initial={"phone": format_local(request.user.phone)}
    )
    if request.method == "POST" and form.is_valid():
        venue = services.create_venue(owner=request.user, **form.cleaned_data)
        messages.success(request, _("Your venue is created. Add the location and photos next."))
        return redirect("manage:profile", venue_id=venue.pk)
    return render(request, "venues/create.html", {"form": form})


# ---------------------------------------------------------------- dashboard home


@members_only
def dashboard(request, venue):
    context = _context(
        venue,
        missing=services.missing_for_submission(venue),
        court_count=Court.objects.for_venue(venue).filter(is_active=True).count(),
    )
    return render(request, "venues/dashboard.html", context)


# ---------------------------------------------------------------- profile and photos (V2, V25)


@members_view_owner_edit
@require_http_methods(["GET", "POST"])
def profile(request, venue):
    initial = {
        "name": venue.name,
        "area": venue.area_id,
        "phone": format_local(venue.phone),
        "address": venue.address,
        "description": venue.description,
        "latitude": venue.latitude,
        "longitude": venue.longitude,
        "facilities": venue.facilities,
    }
    form = VenueProfileForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_profile(venue, request.user, **form.cleaned_data)
        except RuleViolation as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, _("Venue details saved."))
            return redirect("manage:profile", venue_id=venue.pk)
    if not _can_edit(venue):
        _read_only(form)
    context = _context(
        venue,
        form=form,
        upload_form=ImageUploadForm(),
        photos=VenuePhoto.objects.for_venue(venue),
        max_photos=services.MAX_PHOTOS,
        missing=services.missing_for_submission(venue),
    )
    return render(request, "venues/profile.html", context)


@owner_only
@require_POST
def photo_add(request, venue):
    form = ImageUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, _("Choose a photo to upload."))
    else:
        try:
            services.add_photo(venue, request.user, form.cleaned_data["image"])
        except RuleViolation as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, _("Photo added."))
    return redirect("manage:profile", venue_id=venue.pk)


@owner_only
@require_POST
def photo_remove(request, venue, photo_id):
    photo = get_object_or_404(VenuePhoto.objects.for_venue(venue), pk=photo_id)
    services.remove_photo(venue, request.user, photo.pk)
    messages.success(request, _("Photo removed."))
    return redirect("manage:profile", venue_id=venue.pk)


@owner_only
@require_POST
def image_upload(request, venue, kind):
    form = ImageUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, _("Choose an image to upload."))
        return redirect("manage:profile", venue_id=venue.pk)
    setter = {"logo": services.set_logo, "cover": services.set_cover_photo}[kind]
    try:
        setter(venue, request.user, form.cleaned_data["image"])
    except RuleViolation as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, _("Image saved."))
    return redirect("manage:profile", venue_id=venue.pk)


@owner_only
@require_POST
def submit(request, venue):
    try:
        services.submit_for_approval(venue, request.user)
    except RuleViolation as exc:
        messages.error(request, exc.message)
    else:
        messages.success(
            request,
            _(
                "Sent for approval. We'll check your venue within 1–2 days. Meanwhile you can "
                "already use the calendar."
            ),
        )
    return redirect("manage:dashboard", venue_id=venue.pk)


# ---------------------------------------------------------------- courts (V3, V21)


@members_only
def courts(request, venue):
    context = _context(venue, courts=Court.objects.for_venue(venue))
    return render(request, "venues/courts.html", context)


@owner_only
@require_http_methods(["GET", "POST"])
def court_create(request, venue):
    count = Court.objects.for_venue(venue).count()
    form = CourtForm(
        request.POST or None,
        initial={
            "name": _("Court %(n)d") % {"n": count + 1},
            "is_indoor": True,
            "slot_minutes": 60,
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.create_court(venue, request.user, **form.cleaned_data)
        except RuleViolation as exc:
            form.add_error("name", exc.message)
        else:
            messages.success(request, _("Court added."))
            return redirect("manage:courts", venue_id=venue.pk)
    return render(request, "venues/court_form.html", _context(venue, form=form, court=None))


@owner_only
@require_http_methods(["GET", "POST"])
def court_edit(request, venue, court_id):
    court = get_object_or_404(Court.objects.for_venue(venue), pk=court_id)
    form = CourtForm(
        request.POST or None, initial={name: getattr(court, name) for name in COURT_FIELDS}
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.update_court(venue, request.user, court.pk, **form.cleaned_data)
        except RuleViolation as exc:
            form.add_error("name", exc.message)
        else:
            messages.success(request, _("Court saved. Existing bookings keep their price."))
            return redirect("manage:courts", venue_id=venue.pk)
    return render(request, "venues/court_form.html", _context(venue, form=form, court=court))


@owner_only
@require_POST
def court_toggle(request, venue, court_id):
    court = get_object_or_404(Court.objects.for_venue(venue), pk=court_id)
    court = services.set_court_active(venue, request.user, court.pk, active=not court.is_active)
    if court.is_active:
        messages.success(request, _("%(court)s is active again.") % {"court": court.name})
    else:
        messages.success(request, _("%(court)s is deactivated.") % {"court": court.name})
    return redirect("manage:courts", venue_id=venue.pk)


# ---------------------------------------------------------------- opening hours (V4, V22)


@members_view_owner_edit
@require_http_methods(["GET", "POST"])
def hours(request, venue):
    rows = OpeningHours.objects.for_venue(venue)
    initial = [
        {
            "weekday": row.weekday,
            "is_closed": row.is_closed,
            "opens_minute": row.opens_minute,
            "closes_minute": row.closes_minute,
        }
        for row in rows
    ]
    formset = DayHoursFormSet(request.POST or None, initial=initial, prefix="day")
    if request.method == "POST" and formset.is_valid():
        days = [
            services.DayHours(
                weekday=f.cleaned_data["weekday"],
                is_closed=f.cleaned_data["is_closed"],
                opens_minute=f.cleaned_data["opens_minute"],
                closes_minute=f.cleaned_data["closes_minute"],
            )
            for f in formset.forms
        ]
        try:
            services.set_opening_hours(venue, request.user, days)
        except (RuleViolation, ValueError) as exc:
            messages.error(request, getattr(exc, "message", "") or _("Check the hours."))
        else:
            messages.success(request, _("Opening hours saved. Existing bookings stay booked."))
            return redirect("manage:hours", venue_id=venue.pk)
    if not _can_edit(venue):
        _read_only(formset)
    return render(request, "venues/hours.html", _context(venue, formset=formset))


# ---------------------------------------------------------------- prices and peak times (V5, V23)


@members_view_owner_edit
@require_http_methods(["GET", "POST"])
def prices(request, venue):
    venue_courts = list(Court.objects.for_venue(venue).filter(is_active=True))
    data = request.POST or None
    # One form per court of this venue; court ids never come from the request (data-model 6.2).
    court_forms = [
        (
            court,
            CourtPriceForm(
                data,
                prefix=f"court-{court.pk}",
                initial={
                    "off_peak_price_lkr": court.off_peak_price_lkr,
                    "peak_price_lkr": court.peak_price_lkr,
                },
            ),
        )
        for court in venue_courts
    ]
    peak_initial = [
        {"weekday": p.weekday, "starts_minute": p.starts_minute, "ends_minute": p.ends_minute}
        for p in PeakPeriod.objects.for_venue(venue)
    ]
    peak_formset = PeakPeriodFormSet(data, initial=peak_initial, prefix="peak")

    forms_valid = all(form.is_valid() for _court, form in court_forms) and peak_formset.is_valid()
    if request.method == "POST" and forms_valid:
        court_prices = {
            court.pk: (form.cleaned_data["off_peak_price_lkr"], form.cleaned_data["peak_price_lkr"])
            for court, form in court_forms
        }
        periods = [
            (
                f.cleaned_data["weekday"],
                f.cleaned_data["starts_minute"],
                f.cleaned_data["ends_minute"],
            )
            for f in peak_formset.forms
            # Blank extra rows have empty cleaned_data; ticked rows are deleted.
            if f.cleaned_data and not f.cleaned_data.get("DELETE")
        ]
        try:
            services.update_prices(
                venue, request.user, court_prices=court_prices, peak_periods=periods
            )
        except RuleViolation as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, _("Prices saved. New prices apply to new bookings only."))
            return redirect("manage:prices", venue_id=venue.pk)

    if not _can_edit(venue):
        _read_only(peak_formset, *(form for _court, form in court_forms))
    context = _context(venue, court_forms=court_forms, peak_formset=peak_formset)
    return render(request, "venues/prices.html", context)
