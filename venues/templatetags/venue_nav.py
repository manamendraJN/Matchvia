"""Venue dashboard navigation helpers (screens 3: Calendar · + New · Requests · More)."""

from django import template

register = template.Library()


@register.simple_tag
def pending_requests(venue) -> int:
    """Weekly-slot requests waiting for this venue's answer (badge on Requests)."""
    from bookings.models import RecurringSeries, SeriesStatus

    return RecurringSeries.objects.for_venue(venue).filter(status=SeriesStatus.PENDING).count()
