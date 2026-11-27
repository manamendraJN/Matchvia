from django import forms
from django.utils.translation import gettext_lazy as _

from core.exceptions import RuleViolation
from core.phone import INVALID_PHONE_MESSAGE, InvalidPhone, normalise_phone

from . import services

_INPUT = "input text-lg"  # assets/tailwind.css @utility input


class PhoneForm(forms.Form):
    phone = forms.CharField(
        label=_("Mobile number"),
        max_length=32,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT,
                "inputmode": "tel",
                "autocomplete": "tel",
                "placeholder": "077 123 4567",
                "autofocus": True,
            }
        ),
    )

    def clean_phone(self):
        try:
            return normalise_phone(self.cleaned_data["phone"])
        except InvalidPhone:
            raise forms.ValidationError(INVALID_PHONE_MESSAGE, code="invalid_phone") from None


class CodeForm(forms.Form):
    code = forms.CharField(
        label=_("6-digit code"),
        max_length=12,
        widget=forms.TextInput(
            attrs={
                "class": _INPUT + " tracking-[0.5em] text-center",
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9 ]*",
                "autofocus": True,
            }
        ),
    )

    def clean_code(self):
        code = "".join(self.cleaned_data["code"].split())
        if len(code) != services.OTP_LENGTH or not code.isascii() or not code.isdigit():
            raise forms.ValidationError(_("Enter the 6-digit code from the SMS."), code="format")
        return code


class _NameMixin:
    def clean_name(self):
        try:
            return services.clean_name(self.cleaned_data["name"])
        except RuleViolation as exc:
            raise forms.ValidationError(exc.message) from None


class ProfileForm(_NameMixin, forms.Form):
    """First sign-in: name and consent only (US-P01, BR-24)."""

    name = forms.CharField(
        label=_("Your name"),
        max_length=services.NAME_MAX_LENGTH,
        widget=forms.TextInput(attrs={"class": _INPUT, "autocomplete": "name", "autofocus": True}),
    )
    accept = forms.BooleanField(
        label=_("I agree to the privacy notice and terms of use"),
        error_messages={"required": _("Please accept the privacy notice and terms to continue.")},
        widget=forms.CheckboxInput(attrs={"class": "checkbox mt-1"}),
    )


class NameForm(_NameMixin, forms.Form):
    name = forms.CharField(
        label=_("Name"),
        max_length=services.NAME_MAX_LENGTH,
        widget=forms.TextInput(attrs={"class": _INPUT, "autocomplete": "name"}),
    )
