from django import forms
from django.forms import formset_factory
from django.utils.translation import gettext_lazy as _

from core.forms import CHECKBOX_CLASS, INPUT_CLASS, SELECT_CLASS
from core.phone import INVALID_PHONE_MESSAGE, InvalidPhone, normalise_phone
from core.timeutils import DAY_END_MINUTE, DAY_START_MINUTE, minute_choices

from .models import (
    LAT_MAX,
    LAT_MIN,
    LNG_MAX,
    LNG_MIN,
    MAX_PRICE_LKR,
    SLOT_MINUTES,
    Area,
    Facility,
    Sport,
)

WEEKDAYS = [
    (0, _("Monday")),
    (1, _("Tuesday")),
    (2, _("Wednesday")),
    (3, _("Thursday")),
    (4, _("Friday")),
    (5, _("Saturday")),
    (6, _("Sunday")),
]
OUTSIDE_SRI_LANKA = {
    "min_value": _("The pin is outside Sri Lanka."),
    "max_value": _("The pin is outside Sri Lanka."),
}
OPENS_CHOICES = minute_choices(DAY_START_MINUTE, DAY_END_MINUTE - 30)
CLOSES_CHOICES = minute_choices(DAY_START_MINUTE + 30, DAY_END_MINUTE)


def _text(**attrs):
    return forms.TextInput(attrs={"class": INPUT_CLASS, **attrs})


def _price_field(label):
    return forms.IntegerField(
        label=label,
        min_value=0,
        max_value=MAX_PRICE_LKR,
        error_messages={"required": _("Enter a price (Rs. 0 if free).")},
        widget=forms.NumberInput(attrs={"class": INPUT_CLASS, "inputmode": "numeric"}),
    )


class _PhoneMixin:
    def clean_phone(self):
        try:
            return normalise_phone(self.cleaned_data["phone"])
        except InvalidPhone:
            raise forms.ValidationError(INVALID_PHONE_MESSAGE) from None


class VenueCreateForm(_PhoneMixin, forms.Form):
    """V1: the minimum to start a venue."""

    name = forms.CharField(label=_("Venue name"), max_length=100, widget=_text(autofocus=True))
    area = forms.ModelChoiceField(
        label=_("Area"),
        queryset=Area.objects.filter(is_active=True),
        empty_label=_("Choose your area"),
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    phone = forms.CharField(
        label=_("Venue phone number"),
        max_length=32,
        help_text=_("Players will call this number."),
        widget=_text(inputmode="tel", autocomplete="tel"),
    )


class VenueDetailsForm(VenueCreateForm):
    """V1 again, for a venue that already exists (setup step 1)."""

    name = forms.CharField(label=_("Venue name"), max_length=100, widget=_text())


class VenueProfileForm(_PhoneMixin, forms.Form):
    """V2/V25: details, location and facilities."""

    name = forms.CharField(label=_("Venue name"), max_length=100, widget=_text())
    area = forms.ModelChoiceField(
        label=_("Area"),
        queryset=Area.objects.filter(is_active=True),
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    phone = forms.CharField(
        label=_("Venue phone number"), max_length=32, widget=_text(inputmode="tel")
    )
    address = forms.CharField(label=_("Address"), max_length=255, required=False, widget=_text())
    description = forms.CharField(
        label=_("About the venue"),
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"class": INPUT_CLASS, "rows": 3}),
    )
    latitude = forms.DecimalField(
        label=_("Latitude"),
        required=False,
        max_digits=9,
        decimal_places=6,
        min_value=LAT_MIN,
        max_value=LAT_MAX,
        error_messages=OUTSIDE_SRI_LANKA,
        widget=forms.NumberInput(attrs={"class": INPUT_CLASS, "step": "0.000001"}),
    )
    longitude = forms.DecimalField(
        label=_("Longitude"),
        required=False,
        max_digits=9,
        decimal_places=6,
        min_value=LNG_MIN,
        max_value=LNG_MAX,
        error_messages=OUTSIDE_SRI_LANKA,
        widget=forms.NumberInput(attrs={"class": INPUT_CLASS, "step": "0.000001"}),
    )
    facilities = forms.MultipleChoiceField(
        label=_("Facilities"),
        required=False,
        choices=Facility.choices,
        widget=forms.CheckboxSelectMultiple,
    )

    def clean(self):
        data = super().clean()
        if self.has_error("latitude") or self.has_error("longitude"):
            return data  # out of range: "The pin is outside Sri Lanka" shown on the field
        if (data.get("latitude") is None) != (data.get("longitude") is None):
            raise forms.ValidationError(_("Set both latitude and longitude, or neither."))
        return data


class VenueLocationForm(VenueProfileForm):
    """V2: address, map pin, description and facilities (name, area and phone are step 1)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("name", "area", "phone"):
            del self.fields[name]


class ImageUploadForm(forms.Form):
    image = forms.FileField(
        label=_("Photo"),
        widget=forms.ClearableFileInput(
            attrs={"accept": "image/jpeg,image/png,image/webp", "class": "block w-full text-sm"}
        ),
    )


class CourtForm(forms.Form):
    """V3/V21: one court."""

    name = forms.CharField(label=_("Court name"), max_length=40, widget=_text())
    sports = forms.MultipleChoiceField(
        label=_("Sports"),
        choices=Sport.choices,
        widget=forms.CheckboxSelectMultiple,
        help_text=_("A court used for both is booked as one space."),
        error_messages={"required": _("Choose at least one sport.")},
    )
    is_indoor = forms.TypedChoiceField(
        label=_("Indoor or outdoor"),
        choices=[(True, _("Indoor")), (False, _("Outdoor"))],
        coerce=lambda value: value in (True, "True"),
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    slot_minutes = forms.TypedChoiceField(
        label=_("How long is one booking slot?"),
        choices=[(m, _("%(m)d minutes") % {"m": m}) for m in SLOT_MINUTES],
        coerce=int,
        initial=60,
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    off_peak_price_lkr = _price_field(_("Normal price per slot (Rs.)"))
    peak_price_lkr = _price_field(_("Peak price per slot (Rs.)"))


class CourtSetupForm(CourtForm):
    """V3: a court without prices; prices come in step 5 (V5)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["off_peak_price_lkr"]
        del self.fields["peak_price_lkr"]


class CourtPriceForm(forms.Form):
    """V23: prices for one court. The view builds one per court of this venue only."""

    off_peak_price_lkr = _price_field(_("Normal (Rs.)"))
    peak_price_lkr = _price_field(_("Peak (Rs.)"))


class DayHoursForm(forms.Form):
    weekday = forms.TypedChoiceField(choices=WEEKDAYS, coerce=int, widget=forms.HiddenInput)
    is_closed = forms.BooleanField(
        label=_("Closed"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
    )
    opens_minute = forms.TypedChoiceField(
        label=_("Opens"),
        choices=OPENS_CHOICES,
        coerce=int,
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    closes_minute = forms.TypedChoiceField(
        label=_("Closes"),
        choices=CLOSES_CHOICES,
        coerce=int,
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )

    def clean(self):
        data = super().clean()
        if not data.get("is_closed"):
            opens, closes = data.get("opens_minute"), data.get("closes_minute")
            if opens is not None and closes is not None and opens >= closes:
                raise forms.ValidationError(_("Closing time must be after opening time."))
        return data

    @property
    def weekday_label(self):
        return dict(WEEKDAYS)[int(self["weekday"].value())]


class PeakPeriodForm(forms.Form):
    weekday = forms.TypedChoiceField(
        label=_("Day"),
        choices=WEEKDAYS,
        coerce=int,
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    starts_minute = forms.TypedChoiceField(
        label=_("From"),
        choices=OPENS_CHOICES,
        coerce=int,
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    ends_minute = forms.TypedChoiceField(
        label=_("To"),
        choices=CLOSES_CHOICES,
        coerce=int,
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )

    def clean(self):
        data = super().clean()
        start, end = data.get("starts_minute"), data.get("ends_minute")
        if start is not None and end is not None and start >= end:
            raise forms.ValidationError(_("Each peak time must end after it starts."))
        return data


DayHoursFormSet = formset_factory(DayHoursForm, extra=0, min_num=7, max_num=7, validate_max=True)
PeakPeriodFormSet = formset_factory(PeakPeriodForm, extra=1, can_delete=True, max_num=30)


class StaffForm(_PhoneMixin, forms.Form):
    """V24: add an owner or staff member by name and mobile number (US-O06)."""

    name = forms.CharField(label=_("Name"), max_length=80, widget=_text())
    phone = forms.CharField(label=_("Mobile number"), max_length=32, widget=_text(inputmode="tel"))
    role = forms.ChoiceField(
        label=_("Role"),
        choices=[("staff", _("Staff")), ("owner", _("Owner"))],
        initial="staff",
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
        help_text=_("Staff take bookings. Owners can also change settings, prices and staff."),
    )
