"""How times, dates and money look to people (screens.md 1.5, NFR-10, UX1 12-hour time)."""

from datetime import datetime

from django.contrib.humanize.templatetags.humanize import intcomma
from django.utils import dateformat
from django.utils.translation import gettext as _

from core.timeutils import local


def format_time(dt: datetime) -> str:
    """'7:00 pm' in Colombo time."""
    value = local(dt)
    hour12 = value.hour % 12 or 12
    suffix = _("am") if value.hour < 12 else _("pm")
    return f"{hour12}:{value.minute:02d} {suffix}"


def format_day(dt: datetime) -> str:
    """'Sat 5 Dec' in Colombo time."""
    return dateformat.format(local(dt), "D j M")


def format_range(start: datetime, end: datetime) -> str:
    """'Sat 5 Dec, 7:00 pm–8:00 pm'."""
    return f"{format_day(start)}, {format_time(start)}–{format_time(end)}"


def format_lkr(amount: int) -> str:
    """'Rs. 3,500' (whole rupees)."""
    return f"Rs. {intcomma(int(amount), use_l10n=False)}"
