from django import forms
from django.utils.translation import gettext_lazy as _

from core.phone import INVALID_PHONE_MESSAGE, InvalidPhone, normalise_phone


class VenueDecisionForm(forms.Form):
    """A2: approve, reject, suspend or unsuspend a venue. Reject and suspend need a reason."""

    APPROVE, REJECT, SUSPEND, UNSUSPEND = "approve", "reject", "suspend", "unsuspend"

    decision = forms.ChoiceField(
        label=_("Decision"),
        choices=[
            (APPROVE, _("Approve")),
            (REJECT, _("Reject")),
            (SUSPEND, _("Suspend")),
            (UNSUSPEND, _("Unsuspend")),
        ],
        widget=forms.RadioSelect,
    )
    reason = forms.CharField(
        label=_("Reason (the owner will see it)"),
        required=False,
        max_length=255,
        widget=forms.Textarea(attrs={"rows": 3, "cols": 60}),
    )

    def clean(self):
        data = super().clean()
        if (
            data.get("decision") in {self.REJECT, self.SUSPEND}
            and not data.get("reason", "").strip()
        ):
            self.add_error("reason", _("A reason is required (the owner will see it)."))
        return data


class AdminLoginForm(forms.Form):
    """Admin sign-in step 1: mobile number and password."""

    phone = forms.CharField(
        label=_("Mobile number"),
        max_length=32,
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label=_("Password"),
        strip=False,
        max_length=256,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def clean_phone(self):
        try:
            return normalise_phone(self.cleaned_data["phone"])
        except InvalidPhone:
            raise forms.ValidationError(INVALID_PHONE_MESSAGE) from None


class AccountDeletionForm(forms.Form):
    """Carry out a PDPA deletion request for someone (admin)."""

    reason = forms.CharField(
        label=_("How the request came in"),
        max_length=255,
        help_text=_("For example: email of 27 Nov. Don't type the person's name or number."),
        widget=forms.TextInput(attrs={"size": 60}),
    )
    confirm = forms.BooleanField(
        label=_("I checked this is the right account. This can't be undone."), required=True
    )
