"""Template filters so screens format times, dates and money like SMS do (screens 1.5)."""

from datetime import date, datetime

from django import template

from core import formatting
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
