"""Sri Lankan mobile numbers: one normalised format everywhere (data-model 1.1, US-P01).

Every phone number is normalised here before any save or lookup, and stored as E.164 text,
for example ``+94771234567``. Only mobile numbers (``+947…``) are accepted: OTP and booking
SMS go to mobiles, and refusing other numbers blocks SMS-pumping fraud (architecture 3.1).
"""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# +94, then a 9-digit national number that starts with 7 (mobile).
E164_LK_MOBILE = re.compile(r"^\+947\d{8}$")
# Characters people type between digits: any whitespace (\s also matches no-break spaces),
# dashes, dots and brackets.
_SEPARATORS = re.compile(r"[\s\-.()]")

INVALID_PHONE_MESSAGE = _("Enter a valid Sri Lankan mobile number")


class InvalidPhone(ValueError):
    """Raised when a value is not a Sri Lankan mobile number."""


def normalise_phone(value: str) -> str:
    """Return ``+947XXXXXXXX`` for any common way of typing a Sri Lankan mobile number.

    Accepts ``0771234567``, ``771234567``, ``+94771234567``, ``94771234567`` and
    ``0094771234567``, with spaces, dashes, dots or brackets. Raises InvalidPhone otherwise.
    """
    if not isinstance(value, str):
        raise InvalidPhone("not a string")
    compact = _SEPARATORS.sub("", value.strip())

    if compact.startswith("+"):
        digits = compact[1:]
        if not digits.startswith("94"):
            raise InvalidPhone("not a Sri Lankan number")
    else:
        digits = compact
        if digits.startswith("0094"):
            digits = digits[2:]
        elif digits.startswith("0"):
            digits = "94" + digits[1:]
        elif len(digits) == 9:
            digits = "94" + digits

    # ASCII digits only: str.isdigit() would also accept other scripts' digits.
    if not digits.isascii() or not digits.isdigit():
        raise InvalidPhone("contains non-digits")
    normalised = "+" + digits
    if not E164_LK_MOBILE.match(normalised):
        raise InvalidPhone("not a Sri Lankan mobile number")
    return normalised


def validate_phone(value: str) -> None:
    """Model/form validator: the value must already be in normalised form."""
    if not isinstance(value, str) or not E164_LK_MOBILE.match(value):
        raise ValidationError(INVALID_PHONE_MESSAGE, code="invalid_phone")


def mask_phone(phone: str | None) -> str:
    """Mask a number for logs: ``+94771234567`` -> ``+9477****567`` (architecture 5 A09)."""
    if not phone:
        return "-"
    if len(phone) < 9:
        return "****"
    return f"{phone[:5]}****{phone[-3:]}"


def format_local(phone: str) -> str:
    """Show a normalised number the way Sri Lankans write it: ``077 123 4567``."""
    if not phone or not E164_LK_MOBILE.match(phone):
        return phone or ""
    national = "0" + phone[3:]
    return f"{national[:3]} {national[3:6]} {national[6:]}"
