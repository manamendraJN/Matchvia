from datetime import datetime
from zoneinfo import ZoneInfo

from core.formatting import format_day, format_lkr, format_range, format_time

COLOMBO = ZoneInfo("Asia/Colombo")


def test_formats():
    start = datetime(2026, 12, 5, 19, 0, tzinfo=COLOMBO)
    end = datetime(2026, 12, 5, 20, 30, tzinfo=COLOMBO)
    assert format_time(start) == "7:00 pm"
    assert format_time(datetime(2026, 12, 6, 0, 15, tzinfo=COLOMBO)) == "12:15 am"
    assert format_day(start) == "Sat 5 Dec"
    assert format_range(start, end) == "Sat 5 Dec, 7:00 pm–8:30 pm"
    assert format_lkr(3500) == "Rs. 3,500"
    assert format_lkr(0) == "Rs. 0"
    assert format_lkr(100000) == "Rs. 100,000"
