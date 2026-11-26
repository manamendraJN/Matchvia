from django import forms
from django.utils.translation import gettext_lazy as _


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
