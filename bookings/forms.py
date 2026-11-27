from datetime import date, timedelta

from django import forms
from django.core.validators import MaxValueValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.formatting import format_date
from core.forms import SELECT_CLASS
from core.timeutils import operating_date
from venues.models import Area, Sport

from .selectors import TIME_WINDOWS

DAYS_SHOWN = 14
TIME_LABELS = {
    "any": _("Any time"),
    "morning": _("Morning"),
    "afternoon": _("Afternoon"),
    "evening": _("Evening"),
    "night": _("Night"),
}
CHIP = {"class": "peer sr-only"}


def day_choices(today: date, count: int = DAYS_SHOWN) -> list[tuple[str, str]]:
    """The next ``count`` days as (iso date, label): Today, Tomorrow, Wed 9 Dec, ..."""
    choices = []
    for offset in range(count):
        day = today + timedelta(days=offset)
        if offset == 0:
            label = _("Today")
        elif offset == 1:
            label = _("Tomorrow")
        else:
            label = format_date(day)
        choices.append((day.isoformat(), label))
    return choices


class SearchForm(forms.Form):
    """P1/P2: sport, area, day and time of day (US-P02)."""

    sport = forms.ChoiceField(
        label=_("Sport"),
        choices=Sport.choices,
        initial=Sport.FUTSAL,
        widget=forms.RadioSelect(attrs=CHIP),
    )
    area = forms.ModelChoiceField(
        label=_("Area"),
        queryset=Area.objects.filter(is_active=True),
        to_field_name="slug",
        empty_label=_("Choose an area"),
        error_messages={"required": _("Choose an area.")},
        widget=forms.Select(attrs={"class": SELECT_CLASS}),
    )
    date = forms.TypedChoiceField(
        label=_("Day"), coerce=date.fromisoformat, widget=forms.RadioSelect(attrs=CHIP)
    )
    time = forms.ChoiceField(
        label=_("Time"),
        choices=[(key, TIME_LABELS[key]) for key in TIME_WINDOWS],
        initial="any",
        required=False,
        widget=forms.RadioSelect(attrs=CHIP),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = operating_date(timezone.now())
        self.fields["date"].choices = day_choices(today)
        self.fields["date"].initial = today.isoformat()

    def clean_time(self):
        return self.cleaned_data.get("time") or "any"


class BookingForm(forms.Form):
    """The chosen court, start and number of slots, carried from P3 to P7 to Confirm.

    The price is never part of this form: it is always recalculated on the server (A08).
    """

    court = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    start = forms.DateTimeField(input_formats=["%Y-%m-%dT%H:%M"], widget=forms.HiddenInput)
    slots = forms.IntegerField(min_value=1, max_value=6, required=False, initial=1)
    team = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def clean_start(self):
        value = self.cleaned_data["start"]
        if timezone.is_naive(value):  # pragma: no cover - USE_TZ makes it aware already
            value = timezone.make_aware(value)
        return value

    def clean_slots(self):
        return self.cleaned_data.get("slots") or 1


class WeeklyRequestForm(forms.Form):
    """P12: a captain asks for the same court every week (US-C04)."""

    team = forms.ModelChoiceField(
        label=_("Team"), queryset=None, widget=forms.Select(attrs={"class": SELECT_CLASS})
    )
    weeks = forms.IntegerField(
        label=_("Number of weeks"),
        min_value=2,
        widget=forms.NumberInput(attrs={"class": SELECT_CLASS, "inputmode": "numeric"}),
    )

    def __init__(self, *args, teams, venue, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"].queryset = teams
        limit = venue.settings.recurring_max_weeks
        self.fields["weeks"].max_value = limit
        self.fields["weeks"].validators.append(MaxValueValidator(limit))
        self.fields["weeks"].initial = venue.settings.recurring_default_weeks
        self.fields["weeks"].error_messages["max_value"] = _(
            "This venue allows up to %(limit_value)s weeks."
        )
