"""Venue dashboard: create a venue, profile and photos, courts, hours, prices (V1–V7, V21–V23, V25).

Views stay thin. Every view that takes a venue id gets the venue from a decorator in
decorators.py (404 unless a member), and every lookup inside uses ``.for_venue(venue)``.
"""

from functools import wraps

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy
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
    CourtSetupForm,
    DayHoursFormSet,
    ImageUploadForm,
    PeakPeriodFormSet,
    StaffForm,
    VenueCreateForm,
    VenueDetailsForm,
    VenueLocationForm,
    VenueProfileForm,
)
from .models import Court, MemberRole, OpeningHours, VenueMembership, VenuePhoto
from .rules import RULES, RULES_BY_FIELD

# Setup steps (screens 3.1): number -> (URL name, title shown as "Step 2 of 6 · Location").
STEPS = {
    1: ("setup_details", _lazy("Details")),
    2: ("setup_location", _lazy("Location and photos")),
    3: ("setup_courts", _lazy("Courts")),
    4: ("setup_hours", _lazy("Opening hours")),
    5: ("setup_prices", _lazy("Prices and peak times")),
    6: ("setup_review", _lazy("Review and submit")),
}

SETUP_COURT_FIELDS = ["name", "sports", "is_indoor", "slot_minutes"]  # prices come in step 5
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
    draft = services.draft_venue_of(request.user)
    if draft is not None:  # one venue in setup at a time: finish that one first
        messages.info(request, _("Finish setting up %(venue)s first.") % {"venue": draft.name})
        return redirect("manage:setup", venue_id=draft.pk)
    form = VenueCreateForm(
        request.POST or None, initial={"phone": format_local(request.user.phone)}
    )
    if request.method == "POST" and form.is_valid():
        try:
            venue = services.create_venue(owner=request.user, **form.cleaned_data)
        except RuleViolation as exc:
            form.add_error("name", exc.message)
        else:
            return redirect("manage:setup_location", venue_id=venue.pk)
    return render(request, "venues/create.html", {"form": form, "step": 1, "steps": STEPS})


# ---------------------------------------------------------------- profile and photos (V2, V25)


def _back_to_photos(request, venue):
    """Photo forms post a ``return_to`` of "setup" from setup step 2; otherwise the Venue tab."""
    if request.POST.get("return_to") == "setup":
        return redirect("manage:setup_location", venue_id=venue.pk)
    return redirect("manage:profile", venue_id=venue.pk)


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
    return _back_to_photos(request, venue)


@owner_only
@require_POST
def photo_remove(request, venue, photo_id):
    photo = get_object_or_404(VenuePhoto.objects.for_venue(venue), pk=photo_id)
    services.remove_photo(venue, request.user, photo.pk)
    messages.success(request, _("Photo removed."))
    return _back_to_photos(request, venue)


@owner_only
@require_POST
def image_upload(request, venue, kind):
    form = ImageUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, _("Choose an image to upload."))
        return _back_to_photos(request, venue)
    setter = {"logo": services.set_logo, "cover": services.set_cover_photo}[kind]
    try:
        setter(venue, request.user, form.cleaned_data["image"])
    except RuleViolation as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, _("Image saved."))
    return _back_to_photos(request, venue)


@owner_only
@require_POST
def submit(request, venue):
    try:
        services.submit_for_approval(venue, request.user)
    except RuleViolation as exc:
        messages.error(request, exc.message)
        if services.in_setup(venue):
            return redirect("manage:setup_review", venue_id=venue.pk)
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


def _hours_formset(request, venue):
    """The opening-hours formset; on a valid POST it saves. Returns (formset, saved)."""
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
            return formset, True
    return formset, False


@members_view_owner_edit
@require_http_methods(["GET", "POST"])
def hours(request, venue):
    formset, saved = _hours_formset(request, venue)
    if saved:
        messages.success(request, _("Opening hours saved. Existing bookings stay booked."))
        return redirect("manage:hours", venue_id=venue.pk)
    if not _can_edit(venue):
        _read_only(formset)
    return render(request, "venues/hours.html", _context(venue, formset=formset))


# ---------------------------------------------------------------- prices and peak times (V5, V23)


def _price_forms(request, venue):
    """Court price forms and the peak-times formset; a valid POST saves.

    Returns (court_forms, peak_formset, saved).
    """
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
            return court_forms, peak_formset, True
    return court_forms, peak_formset, False


@members_view_owner_edit
@require_http_methods(["GET", "POST"])
def prices(request, venue):
    court_forms, peak_formset, saved = _price_forms(request, venue)
    if saved:
        messages.success(request, _("Prices saved. New prices apply to new bookings only."))
        return redirect("manage:prices", venue_id=venue.pk)
    if not _can_edit(venue):
        _read_only(peak_formset, *(form for _court, form in court_forms))
    context = _context(venue, court_forms=court_forms, peak_formset=peak_formset)
    return render(request, "venues/prices.html", context)


# ---------------------------------------------------------------- More (phone menu, screens 3)


@members_only
@require_http_methods(["GET"])
def more(request, venue):
    """Every venue section on one page, for the phone bottom bar's "More"."""
    return render(request, "venues/more.html", _context(venue))


# ---------------------------------------------------------------- booking rules (V20)


@owner_only
@require_http_methods(["GET", "POST"])
def rules(request, venue):
    """Each rule as a plain question; Save per rule (US-O05)."""
    if request.method == "POST":
        field = request.POST.get("rule", "")
        if field not in RULES_BY_FIELD:
            return redirect("manage:rules", venue_id=venue.pk)
        try:
            services.update_rule(venue, request.user, field, request.POST.get("value", ""))
        except RuleViolation as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, _("Saved. Applies to new bookings."))
        return redirect(f"{reverse('manage:rules', args=[venue.pk])}#rule-{field}")
    current = venue.settings
    items = [{"rule": rule, "current": str(getattr(current, rule.field))} for rule in RULES]
    return render(request, "venues/rules.html", _context(venue, items=items))


# ---------------------------------------------------------------- staff (V24)


@owner_only
@require_http_methods(["GET", "POST"])
def staff(request, venue):
    form = StaffForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.add_member(venue, request.user, **form.cleaned_data)
        except RuleViolation as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(
                request, _("Added. They'll get an SMS and can sign in with their number.")
            )
            return redirect("manage:staff", venue_id=venue.pk)
    members = (
        VenueMembership.objects.for_venue(venue)
        .select_related("user")
        .order_by("role", "created_at")
    )
    return render(request, "venues/staff.html", _context(venue, form=form, members=members))


@owner_only
@require_POST
def staff_remove(request, venue, membership_id):
    membership = get_object_or_404(VenueMembership.objects.for_venue(venue), pk=membership_id)
    try:
        services.remove_member(venue, request.user, membership.pk)
    except RuleViolation as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, _("Removed. Their access has ended."))
    return redirect("manage:staff", venue_id=venue.pk)


# ---------------------------------------------------------------- setup wizard (V1-V6)
# A draft venue is set up step by step, "Step 2 of 6 · Location", and setup reopens where the
# owner stopped (screens 3.1). Steps save through the same services as the tabs (V21-V25).


def _setup(venue, step, **extra):
    title = STEPS[step][1]
    return {
        "venue": venue,
        "can_edit": True,
        "step": step,
        "steps": STEPS,
        "step_title": title,
        "back_url": reverse(f"manage:{STEPS[step - 1][0]}", args=[venue.pk]) if step > 1 else "",
        **extra,
    }


def _next_step(request, venue, finished: int):
    services.finish_setup_step(venue, request.user, finished)
    return redirect(f"manage:{STEPS[finished + 1][0]}", venue_id=venue.pk)


def _setup_only(view):
    """Setup pages are for draft venues; after submitting, the tabs are used instead."""

    @wraps(view)
    def wrapper(request, venue, *args, **kwargs):
        if not services.in_setup(venue):
            return redirect("manage:dashboard", venue_id=venue.pk)
        return view(request, venue, *args, **kwargs)

    return wrapper


@owner_only
@_setup_only
def setup(request, venue):
    """Continue where the owner stopped."""
    url_name, _title = STEPS[services.next_setup_step(venue)]
    return redirect(f"manage:{url_name}", venue_id=venue.pk)


@owner_only
@_setup_only
@require_http_methods(["GET", "POST"])
def setup_details(request, venue):
    initial = {"name": venue.name, "area": venue.area_id, "phone": format_local(venue.phone)}
    form = VenueDetailsForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_profile(venue, request.user, **form.cleaned_data)
        except RuleViolation as exc:
            form.add_error("name", exc.message)
        else:
            return _next_step(request, venue, 1)
    return render(request, "venues/setup/details.html", _setup(venue, 1, form=form))


@owner_only
@_setup_only
@require_http_methods(["GET", "POST"])
def setup_location(request, venue):
    initial = {
        "address": venue.address,
        "description": venue.description,
        "latitude": venue.latitude,
        "longitude": venue.longitude,
        "facilities": venue.facilities,
    }
    form = VenueLocationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        services.update_profile(venue, request.user, **form.cleaned_data)
        return _next_step(request, venue, 2)
    context = _setup(
        venue,
        2,
        form=form,
        upload_form=ImageUploadForm(),
        photos=VenuePhoto.objects.for_venue(venue),
        max_photos=services.MAX_PHOTOS,
        return_to="setup",
    )
    return render(request, "venues/setup/location.html", context)


@owner_only
@_setup_only
@require_http_methods(["GET", "POST"])
def setup_courts(request, venue):
    """Courts so far, a form to add one more, and Next (needs at least one court)."""
    venue_courts = Court.objects.for_venue(venue)
    count = venue_courts.count()
    adding = request.method == "POST" and "add" in request.POST
    form = CourtSetupForm(
        request.POST if adding else None,
        initial={
            "name": _("Court %(n)d") % {"n": count + 1},
            "is_indoor": True,
            "slot_minutes": 60,
        },
    )
    if adding and form.is_valid():
        try:
            services.create_court(
                venue, request.user, off_peak_price_lkr=0, peak_price_lkr=0, **form.cleaned_data
            )
        except RuleViolation as exc:
            form.add_error("name", exc.message)
        else:
            messages.success(request, _("Court added."))
            return redirect("manage:setup_courts", venue_id=venue.pk)
    elif request.method == "POST" and not adding:
        if venue_courts.filter(is_active=True).exists():
            return _next_step(request, venue, 3)
        messages.error(request, _("Add at least one court."))
    return render(
        request, "venues/setup/courts.html", _setup(venue, 3, form=form, courts=venue_courts)
    )


@owner_only
@_setup_only
@require_http_methods(["GET", "POST"])
def setup_court_edit(request, venue, court_id):
    court = get_object_or_404(Court.objects.for_venue(venue), pk=court_id)
    form = CourtSetupForm(
        request.POST or None,
        initial={
            name: getattr(court, name) for name in ("name", "sports", "is_indoor", "slot_minutes")
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.update_court(venue, request.user, court.pk, **form.cleaned_data)
        except RuleViolation as exc:
            form.add_error("name", exc.message)
        else:
            return redirect("manage:setup_courts", venue_id=venue.pk)
    context = _setup(venue, 3, form=form, court=court)
    return render(request, "venues/setup/court_edit.html", context)


@owner_only
@_setup_only
@require_http_methods(["GET", "POST"])
def setup_hours(request, venue):
    formset, saved = _hours_formset(request, venue)
    if saved:
        return _next_step(request, venue, 4)
    return render(request, "venues/setup/hours.html", _setup(venue, 4, formset=formset))


@owner_only
@_setup_only
@require_http_methods(["GET", "POST"])
def setup_prices(request, venue):
    court_forms, peak_formset, saved = _price_forms(request, venue)
    if saved:
        return _next_step(request, venue, 5)
    context = _setup(venue, 5, court_forms=court_forms, peak_formset=peak_formset)
    return render(request, "venues/setup/prices.html", context)


@owner_only
@_setup_only
def setup_review(request, venue):
    """V6: everything on one page with Edit links; Submit for approval."""
    venue_courts = Court.objects.for_venue(venue).filter(is_active=True)
    context = _setup(
        venue,
        6,
        courts=venue_courts,
        free_courts=[
            c.name for c in venue_courts if not c.off_peak_price_lkr and not c.peak_price_lkr
        ],
        hours=OpeningHours.objects.for_venue(venue),
        peaks=PeakPeriod.objects.for_venue(venue),
        photos=VenuePhoto.objects.for_venue(venue),
        missing=services.missing_for_submission(venue),
    )
    return render(request, "venues/setup/review.html", context)
