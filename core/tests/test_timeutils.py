from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from core import timeutils

COLOMBO = ZoneInfo("Asia/Colombo")


def colombo(*args):
    return datetime(*args, tzinfo=COLOMBO)


@pytest.mark.parametrize(
    ("instant", "expected_date", "expected_minute"),
    [
        (colombo(2026, 12, 4, 18, 0), date(2026, 12, 4), 1080),  # Fri 18:00
        (colombo(2026, 12, 5, 0, 30), date(2026, 12, 4), 1470),  # Sat 00:30 = Friday night
        (colombo(2026, 12, 5, 2, 59), date(2026, 12, 4), 1619),
        (colombo(2026, 12, 5, 3, 0), date(2026, 12, 5), 180),  # 03:00 starts a new day
        (colombo(2026, 12, 5, 6, 0), date(2026, 12, 5), 360),
        (colombo(2026, 12, 5, 23, 59), date(2026, 12, 5), 1439),
    ],
)
def test_operating_date_and_minute(instant, expected_date, expected_minute):
    assert timeutils.operating_date(instant) == expected_date
    assert timeutils.operating_minute(instant) == expected_minute


def test_utc_instants_are_converted_to_colombo_first():
    # 19:00 UTC Friday = 00:30 Saturday in Colombo = Friday night.
    instant = datetime(2026, 12, 4, 19, 0, tzinfo=UTC)
    assert timeutils.operating_date(instant) == date(2026, 12, 4)
    assert timeutils.operating_minute(instant) == 1470


@pytest.mark.parametrize("minute", [180, 360, 1020, 1439, 1440, 1500, 1620])
def test_operating_minute_round_trips(minute):
    day = date(2026, 12, 4)
    instant = timeutils.at_operating_minute(day, minute)
    if minute < timeutils.DAY_END_MINUTE:
        assert timeutils.operating_date(instant) == day
        assert timeutils.operating_minute(instant) == minute
    assert instant.tzinfo is not None


def test_minute_1500_on_friday_is_saturday_01_00():
    instant = timeutils.at_operating_minute(date(2026, 12, 4), 1500)
    assert timeutils.local(instant) == colombo(2026, 12, 5, 1, 0)


@pytest.mark.parametrize("minute", [179, 1621, -1])
def test_out_of_range_minutes_rejected(minute):
    with pytest.raises(ValueError, match="out of range"):
        timeutils.at_operating_minute(date(2026, 12, 4), minute)


@pytest.mark.parametrize(
    ("minute", "label"),
    [
        (360, "6:00 am"),
        (720, "12:00 pm"),
        (1020, "5:00 pm"),
        (1410, "11:30 pm"),
        (1440, "12:00 am"),
        (1500, "1:00 am (next day)"),
        (1620, "3:00 am (next day)"),
    ],
)
def test_minute_labels(minute, label):
    assert timeutils.minute_label(minute) == label


def test_minute_choices_include_both_ends():
    choices = timeutils.minute_choices(360, 480, step=60)
    assert [m for m, _label in choices] == [360, 420, 480]
