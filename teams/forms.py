from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import INPUT_CLASS
from core.phone import INVALID_PHONE_MESSAGE, InvalidPhone, normalise_phone

from .models import Team


class TeamForm(forms.Form):
    """P15: name and sport (US-C01)."""

    name = forms.CharField(
        label=_("Team name"),
        max_length=60,
        error_messages={"required": _("Enter a team name.")},
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "autofocus": True}),
    )
    sport = forms.ChoiceField(
        label=_("Sport"),
        choices=Team.Sport.choices,
        initial=Team.Sport.FUTSAL,
        widget=forms.RadioSelect(attrs={"class": "peer sr-only"}),
    )


class InviteForm(forms.Form):
    """P16: invite a player by mobile number (US-C02)."""

    phone = forms.CharField(
        label=_("Player's mobile number"),
        max_length=32,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "inputmode": "tel"}),
    )

    def clean_phone(self):
        try:
            return normalise_phone(self.cleaned_data["phone"])
        except InvalidPhone:
            raise forms.ValidationError(INVALID_PHONE_MESSAGE) from None
