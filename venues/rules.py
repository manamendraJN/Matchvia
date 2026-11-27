"""Booking rules as plain questions with allowed answers only (V20, US-O05, requirements 5).

Each answer list stays inside the range in requirements section 5; the database checks the same
ranges (VenueSettings constraints). No free typing.
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy


def _days(n):
    return ngettext_lazy("%(n)d day ahead", "%(n)d days ahead", n) % {"n": n}


def _hours_before(n):
    if n == 0:
        return _("Up to the start")
    return ngettext_lazy("%(n)d hour before", "%(n)d hours before", n) % {"n": n}


def _minutes_before(n):
    if n == 0:
        return _("Up to the start")
    if n < 60:
        return _("%(n)d minutes before") % {"n": n}
    return _hours_before(n // 60)


def _slots(n):
    return ngettext_lazy("%(n)d slot", "%(n)d slots", n) % {"n": n}


def _bookings(n):
    return ngettext_lazy("%(n)d booking", "%(n)d bookings", n) % {"n": n}


def _weeks(n):
    return ngettext_lazy("%(n)d week", "%(n)d weeks", n) % {"n": n}


ON_OFF = [(True, _("On")), (False, _("Off"))]
YES_NO = [(True, _("Yes")), (False, _("No"))]


@dataclass(frozen=True)
class Rule:
    field: str
    question: str
    example: str
    choices: list  # [(value, label)]


RULES = [
    Rule(
        "booking_horizon_days",
        _("How far ahead can players book online?"),
        _("With 14 days, on Monday players can book up to the Monday after next."),
        [(n, _days(n)) for n in (1, 2, 3, 7, 14, 21, 30, 45, 60)],
    ),
    Rule(
        "min_notice_minutes",
        _("How late can players book online?"),
        _("With 1 hour, a 7:00 pm slot can be booked online until 6:00 pm."),
        [(n, _minutes_before(n)) for n in (0, 15, 30, 60, 120, 180, 360, 720, 1440)],
    ),
    Rule(
        "max_slots_per_booking",
        _("Longest online booking"),
        _("With 3 slots of 1 hour, a player can book up to 3 hours in one go."),
        [(n, _slots(n)) for n in range(1, 7)],
    ),
    Rule(
        "max_upcoming_online_bookings",
        _("Bookings per player at a time"),
        _(
            "How many upcoming online bookings one player can hold at your venue. "
            "Bookings you enter and weekly slots don't count."
        ),
        [(n, _bookings(n)) for n in range(1, 11)],
    ),
    Rule(
        "cancellation_window_hours",
        _("Free cancellation until"),
        _("With 6 hours, a player can cancel a 7:00 pm game online until 1:00 pm."),
        [(n, _hours_before(n)) for n in (0, 1, 2, 3, 6, 12, 24, 48, 72)],
    ),
    Rule(
        "reminder_lead_hours",
        _("Reminder SMS"),
        _("Sent this long before the game (never between 10:00 pm and 7:00 am)."),
        [(n, _hours_before(n)) for n in (1, 2, 3, 4, 6, 12, 24)],
    ),
    Rule(
        "sms_on_phone_bookings",
        _("SMS for phone bookings"),
        _("Send a confirmation SMS when you enter a phone or WhatsApp booking."),
        ON_OFF,
    ),
    Rule(
        "sms_on_walk_ins",
        _("SMS for walk-ins"),
        _("Send a confirmation SMS when you enter a walk-in who gave a number."),
        ON_OFF,
    ),
    Rule(
        "recurring_approver",
        _("Who can approve weekly slots?"),
        _("When a team captain asks for the same time every week."),
        [("owner", _("Owner only")), ("owner_or_staff", _("Owner or staff"))],
    ),
    Rule(
        "recurring_max_weeks",
        _("Weekly slots: up to"),
        _("The longest weekly booking, in weeks."),
        [(n, _weeks(n)) for n in range(2, 13)],
    ),
    Rule(
        "staff_can_change_price",
        _("Staff can change prices"),
        _("Staff can give a different price on a booking, with a reason. Owners always can."),
        YES_NO,
    ),
]
RULES_BY_FIELD = {rule.field: rule for rule in RULES}
