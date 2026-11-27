"""Forms for the venue dashboard (V10-V14). Every court choice is scoped to the venue (6.2)."""

from django import forms
from django.core.validators import MaxValueValidator
from django.utils.translation import gettext_lazy as _

from core.forms import CHECKBOX_CLASS, INPUT_CLASS, SELECT_CLASS
from core.phone import INVALID_PHONE_MESSAGE, InvalidPhone, normalise_phone
from core.timeutils import DAY_END_MINUTE, DAY_START_MINUTE, minute_choices
from venues.models import Court

from .models import BlockReason, CancelReason, Source

START_CHOICES = minute_choices(DAY_START_MINUTE, DAY_END_MINUTE - 30)
END_CHOICES = minute_choices(DAY_START_MINUTE + 30, DAY_END_MINUTE)
CHIP = {"class": "peer sr-only"}
MAX_STAFF_SLOTS = 8


def _date_field():
    return forms.DateField(
        label=_("Date"), widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CLASS})
    )


def _minute_field(label, choices):
    return forms.TypedChoiceField(
        label=label, choices=choices, coerce=int, widget=forms.Select(attrs={"class": SELECT_CLASS})
    )


class _VenueCourtMixin:
    def scope_courts(self, venue, field="court"):
        # A tampered POST can't attach another venue's court: it isn't in the choices.
        self.fields[field].queryset = Court.objects.for_venue(venue).filter(is_active=True)


class NewBookingForm(_VenueCourtMixin, forms.Form):
    """V10: walk-in, phone or WhatsApp booking (US-S02, US-S03)."""

    court = forms.ModelChoiceField(
        label=_("Court"),
        queryset=Court.objects.none(),
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    date = _date_field()
    start_minute = _minute_field(_("Start"), START_CHOICES)
    slots = forms.TypedChoiceField(
        label=_("How long?"),
        coerce=int,
        initial=1,
        choices=[(n, n) for n in range(1, MAX_STAFF_SLOTS + 1)],
        widget=forms.RadioSelect(attrs=CHIP),
    )
    source = forms.ChoiceField(
        label=_("Booked by"),
        choices=[
            (Source.WALK_IN, _("Walk-in")),
            (Source.PHONE, _("Phone")),
            (Source.WHATSAPP, _("WhatsApp")),
        ],
        widget=forms.RadioSelect(attrs=CHIP),
    )
    customer_name = forms.CharField(
        label=_("Name"),
        max_length=80,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "autocomplete": "off"}),
    )
    customer_phone = forms.CharField(
        label=_("Phone (optional for walk-ins)"),
        max_length=32,
        required=False,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASS, "inputmode": "tel", "autocomplete": "off"}
        ),
    )
    change_price = forms.BooleanField(
        label=_("Change the price"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
    )
    price_lkr = forms.IntegerField(
        label=_("New price (Rs.)"),
        required=False,
        min_value=0,
        max_value=1_000_000,
        widget=forms.NumberInput(attrs={"class": INPUT_CLASS, "inputmode": "numeric"}),
    )
    price_change_reason = forms.CharField(
        label=_("Reason for the price change"),
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS}),
    )
    notes = forms.CharField(
        label=_("Notes (staff only)"),
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS}),
    )

    def __init__(self, *args, venue, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_courts(venue)

    def clean_customer_phone(self):
        value = self.cleaned_data["customer_phone"].strip()
        if not value:
            return ""
        try:
            return normalise_phone(value)
        except InvalidPhone:
            raise forms.ValidationError(INVALID_PHONE_MESSAGE) from None

    def clean(self):
        data = super().clean()
        needs_phone = data.get("source") in {Source.PHONE, Source.WHATSAPP}
        if needs_phone and not data.get("customer_phone") and not self.has_error("customer_phone"):
            self.add_error(
                "customer_phone", _("Add a phone number for phone and WhatsApp bookings.")
            )
        if data.get("change_price") and data.get("price_lkr") is None:
            self.add_error("price_lkr", _("Enter the new price."))
        return data


class MoveForm(_VenueCourtMixin, forms.Form):
    """V12: move to another time or court (US-S04)."""

    court = forms.ModelChoiceField(
        label=_("Court"),
        queryset=Court.objects.none(),
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    date = _date_field()
    start_minute = _minute_field(_("New start"), START_CHOICES)
    keep_price = forms.BooleanField(
        label=_("Keep the old price"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": CHECKBOX_CLASS}),
    )
    price_change_reason = forms.CharField(
        label=_("Reason for keeping the old price"),
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS}),
    )

    def __init__(self, *args, venue, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_courts(venue)


class StaffCancelForm(forms.Form):
    """V13: cancel for a customer (US-S05, BR-09)."""

    reason = forms.ChoiceField(
        label=_("Why?"), choices=CancelReason.choices, widget=forms.RadioSelect(attrs=CHIP)
    )


class BlockForm(_VenueCourtMixin, forms.Form):
    """V14: block one or more courts (US-S06, BR-17)."""

    courts = forms.ModelMultipleChoiceField(
        label=_("Courts"), queryset=Court.objects.none(), widget=forms.CheckboxSelectMultiple
    )
    date = _date_field()
    start_minute = _minute_field(_("From"), START_CHOICES)
    end_minute = _minute_field(_("To"), END_CHOICES)
    reason = forms.ChoiceField(
        label=_("Reason"), choices=BlockReason.choices, widget=forms.RadioSelect(attrs=CHIP)
    )
    notes = forms.CharField(
        label=_("Note (staff only, never shown to players)"),
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS}),
    )

    def __init__(self, *args, venue, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_courts(venue, field="courts")

    def clean(self):
        data = super().clean()
        start, end = data.get("start_minute"), data.get("end_minute")
        if start is not None and end is not None and end <= start:
            raise forms.ValidationError(_("End time must be after start time."))
        return data


class WeeklyForm(_VenueCourtMixin, forms.Form):
    """V16: a regular team's weekly slot entered by staff (US-S08)."""

    customer_name = forms.CharField(
        label=_("Customer or team name"),
        max_length=80,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS}),
    )
    customer_phone = forms.CharField(
        label=_("Phone"),
        max_length=32,
        error_messages={"required": _("Add a phone number so we can send the schedule.")},
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "inputmode": "tel"}),
    )
    court = forms.ModelChoiceField(
        label=_("Court"),
        queryset=Court.objects.none(),
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    first_date = forms.DateField(
        label=_("First week"),
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CLASS}),
    )
    start_minute = _minute_field(_("Start"), START_CHOICES)
    slots = forms.TypedChoiceField(
        label=_("How long? (slots)"),
        coerce=int,
        choices=[(n, n) for n in range(1, MAX_STAFF_SLOTS + 1)],
        initial=1,
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    weeks = forms.IntegerField(
        label=_("Number of weeks"),
        min_value=2,
        widget=forms.NumberInput(attrs={"class": INPUT_CLASS, "inputmode": "numeric"}),
    )

    def __init__(self, *args, venue, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope_courts(venue)
        limit = venue.settings.recurring_max_weeks
        self.fields["weeks"].max_value = limit
        self.fields["weeks"].validators.append(MaxValueValidator(limit))
        self.fields["weeks"].initial = venue.settings.recurring_default_weeks

    def clean_customer_phone(self):
        try:
            return normalise_phone(self.cleaned_data["customer_phone"])
        except InvalidPhone:
            raise forms.ValidationError(
                _("Add a phone number so we can send the schedule.")
            ) from None


class SeriesCancelForm(forms.Form):
    reason = forms.ChoiceField(
        label=_("Why?"), choices=CancelReason.choices, widget=forms.RadioSelect(attrs=CHIP)
    )


class CloseDayForm(forms.Form):
    """V15: close the whole venue for one day. The note is for staff only."""

    date = forms.DateField(
        label=_("Date"),
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CLASS}),
    )
    note = forms.CharField(
        label=_("Note for staff (optional)"),
        required=False,
        max_length=100,
        help_text=_('For example: Poya day, repairs. Players only see "Closed".'),
        widget=forms.TextInput(attrs={"class": INPUT_CLASS}),
    )


class CustomerForm(forms.Form):
    """V19: the venue's own name and notes for a customer."""

    name = forms.CharField(
        label=_("Name"), max_length=80, widget=forms.TextInput(attrs={"class": INPUT_CLASS})
    )
    notes = forms.CharField(
        label=_("Notes"),
        required=False,
        max_length=255,
        help_text=_("For example: Regular Tuesday team. Only your venue sees this."),
        widget=forms.TextInput(attrs={"class": INPUT_CLASS}),
    )


class CustomerBlockForm(forms.Form):
    reason = forms.CharField(
        label=_("Reason (optional, only your venue sees it)"),
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS}),
    )
