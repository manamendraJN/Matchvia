"""Operating days and operating minutes (data-model 1.2). The 03:00 rule lives only here.

Venues may close after midnight, up to 03:00 (BR-15). A Friday 00:30 slot belongs to Friday's
operating day, in the calendar, in search and in pricing.

- Operating day: 03:00 local time to 03:00 the next day. ``operating_date`` is the date it
  starts on.
- Operating minute: local wall-clock time as minutes from midnight of the operating date, from
  180 (03:00) to 1620 (03:00 next day). 06:00 = 360, midnight = 1440, 01:00 next day = 1500.

Sri Lanka has no daylight saving, so every operating day is exactly 24 hours.
"""

from datetime import date, datetime, time, timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

DAY_START_MINUTE = 180  # 03:00
DAY_END_MINUTE = 1620  # 03:00 next day
MINUTES_PER_DAY = 1440
_DAY_START = time(3, 0)


def local(dt: datetime) -> datetime:
    """An aware datetime in Asia/Colombo."""
    return timezone.localtime(dt)


def operating_date(dt: datetime) -> date:
    """The operating date an instant belongs to (before 03:00 counts as the previous day)."""
    value = local(dt)
    if value.time() < _DAY_START:
        return value.date() - timedelta(days=1)
    return value.date()


def operating_minute(dt: datetime) -> int:
    """Minutes from midnight of the instant's operating date (180 to 1619)."""
    value = local(dt)
    minute = value.hour * 60 + value.minute
    if value.time() < _DAY_START:
        minute += MINUTES_PER_DAY
    return minute


def at_operating_minute(day: date, minute: int) -> datetime:
    """The aware instant for ``minute`` on operating date ``day``."""
    if not DAY_START_MINUTE <= minute <= DAY_END_MINUTE:
        raise ValueError(f"Operating minute out of range: {minute}")
    midnight = timezone.make_aware(datetime.combine(day, time.min))
    return midnight + timedelta(minutes=minute)


def minute_label(minute: int) -> str:
    """12-hour label for an operating minute (UX1): '6:00 am', '12:00 am', '1:00 am (next day)'."""
    wall = minute % MINUTES_PER_DAY
    hour, mins = divmod(wall, 60)
    suffix = _("am") if hour < 12 else _("pm")
    hour12 = hour % 12 or 12
    label = f"{hour12}:{mins:02d} {suffix}"
    if minute > MINUTES_PER_DAY:
        label = _("%(time)s (next day)") % {"time": label}
    return label


def minute_choices(first: int, last: int, step: int = 30) -> list[tuple[int, str]]:
    """(minute, label) pairs for time pickers, both ends included."""
    return [(m, minute_label(m)) for m in range(first, last + 1, step)]
