"""Template filters so screens format times, dates and money like SMS do (screens 1.5)."""

from datetime import date, datetime

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from core import formatting, timeutils
from core.icons import ICONS
from core.phone import format_local

register = template.Library()


@register.filter
def time12(value: datetime) -> str:
    """{{ slot.start|time12 }} -> '7:00 pm'"""
    return formatting.format_time(value) if value else ""


@register.filter
def day(value) -> str:
    """{{ booking.start_at|day }} -> 'Sat 5 Dec' (datetimes in Colombo time, or plain dates)."""
    if isinstance(value, datetime):
        return formatting.format_day(value)
    if isinstance(value, date):
        return formatting.format_date(value)
    return ""


@register.filter
def lkr(value) -> str:
    """{{ 3500|lkr }} -> 'Rs. 3,500'"""
    return formatting.format_lkr(value) if value is not None else ""


@register.filter
def local_phone(value: str) -> str:
    """{{ venue.phone|local_phone }} -> '077 123 4567'"""
    return format_local(value)


@register.filter
def minute_label(value) -> str:
    """Operating minute -> "6:00 am" ("1:00 am" for 1500, the night after)."""
    return timeutils.minute_label(int(value))


_SVG_OPEN = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="{}" '
)


@register.simple_tag
def icon(name: str, css: str = "size-5", label: str = ""):
    """Inline SVG icon from core.icons. Decorative (hidden from screen readers) unless a label
    is given; css and label are escaped. Unknown names fail loudly in development."""
    paths = mark_safe(ICONS[name])  # noqa: S308  # nosec B308 B703  constant paths, never user input
    if label:
        return format_html(_SVG_OPEN + 'role="img" aria-label="{}">{}</svg>', css, label, paths)
    return format_html(_SVG_OPEN + 'aria-hidden="true" focusable="false">{}</svg>', css, paths)
