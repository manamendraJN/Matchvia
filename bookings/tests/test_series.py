"""Weekly series (data-model 5, US-S08, US-C05, BR-13, BR-14). 'Now' is Mon 7 Dec 2026 10:00;
the first week below is Tuesday 8 Dec, 8 pm."""

from datetime import date, timedelta

import pytest
from django.urls import reverse

from bookings import services
from bookings.models import Booking, RecurringSeries, Source, Status
from core.exceptions import RuleViolation
from notifications.models import SmsMessage
from venues.models import OpeningHours, VenueSettings

from .conftest import at

pytestmark = pytest.mark.django_db

TUE = date(2026, 12, 8)
EIGHT_PM = 1200


def staff_series(venue, court, *, first=TUE, minute=EIGHT_PM, duration=60, weeks=4, **kw):
    params = {"customer_name": "Malabe Strikers", "customer_phone": "0715551234"}
    params.update(kw)
    return services.create_staff_series(
        venue=venue,
        actor=venue.staff,
        court_id=court.pk,
        first_date=first,
        start_minute=minute,
        duration_minutes=duration,
        weeks=weeks,
        **params,
    )


def walk_in(venue, court, start, hours=1):
    return services.create_staff_booking(
        venue=venue,
        actor=venue.staff,
        court_id=court.pk,
        start_at=start,
        end_at=start + timedelta(hours=hours),
        source=Source.WALK_IN,
        customer_name="X",
    )


# ---------------------------------------------------------------- planning


def test_plan_marks_each_week(venue, court, clock):
    walk_in(venue, court, at(2026, 12, 15, 20, 0))  # week 2 booked
    services.create_block(
        venue=venue,
        actor=venue.owner,
        court_ids=[court.pk],
        start_at=at(2026, 12, 22, 19, 0),
        end_at=at(2026, 12, 22, 22, 0),
        reason="private_event",
    )  # week 3 blocked
    plans = services.plan_weeks(
        court, first_date=TUE, start_minute=EIGHT_PM, duration_minutes=60, weeks=4, for_staff=True
    )
    assert [p.day for p in plans] == [TUE + timedelta(weeks=k) for k in range(4)]
    assert [p.reason for p in plans] == ["", "booked", "blocked", ""]
    assert plans[0].start == at(2026, 12, 8, 20, 0)
    assert plans[0].ok


def test_plan_closed_outside_hours_and_too_soon(venue, court, clock):
    OpeningHours.objects.for_venue(venue).filter(weekday=0).update(is_closed=True)
    monday = date(2026, 12, 7)
    plans = services.plan_weeks(
        court, first_date=monday, start_minute=600, duration_minutes=60, weeks=2, for_staff=True
    )
    assert [p.reason for p in plans] == ["closed", "closed"]
    plans = services.plan_weeks(
        court, first_date=TUE, start_minute=300, duration_minutes=60, weeks=2, for_staff=True
    )
    assert [p.reason for p in plans] == ["outside_hours", "outside_hours"]
    OpeningHours.objects.for_venue(venue).filter(weekday=0).update(is_closed=False)
    plans = services.plan_weeks(
        court, first_date=monday, start_minute=540, duration_minutes=60, weeks=2, for_staff=True
    )
    assert [p.reason for p in plans] == ["too_soon", ""]  # 9:00 today is over
    plans = services.plan_weeks(
        court, first_date=monday, start_minute=600, duration_minutes=60, weeks=2, for_staff=True
    )
    assert plans[0].reason == ""  # staff may book what starts right now
    # Captains also respect the 60-minute notice.
    plans = services.plan_weeks(
        court, first_date=monday, start_minute=630, duration_minutes=60, weeks=2, for_staff=False
    )
    assert plans[0].reason == "too_soon"
    plans = services.plan_weeks(
        court, first_date=monday, start_minute=660, duration_minutes=60, weeks=2, for_staff=False
    )
    assert plans[0].reason == ""  # 11:00 is exactly the notice


def test_plan_needs_whole_slots(court, clock):
    with pytest.raises(RuleViolation, match="60-minute slots"):
        services.plan_weeks(
            court,
            first_date=TUE,
            start_minute=EIGHT_PM,
            duration_minutes=45,
            weeks=2,
            for_staff=True,
        )


def test_late_night_series_belongs_to_the_opening_day(venue, court, clock):
    OpeningHours.objects.for_venue(venue).filter(weekday=1).update(closes_minute=1560)
    series, created = staff_series(venue, court, minute=1500, weeks=2)  # Tue 1:00 am next day
    assert created[0].start_at == at(2026, 12, 9, 1, 0)
    assert created[0].operating_date == TUE
    assert series.weekday == 1


# ---------------------------------------------------------------- creating (US-S08)


def test_staff_series_books_free_weeks_and_skips_clashes(venue, court, clock):
    walk_in(venue, court, at(2026, 12, 22, 20, 0))
    series, created = staff_series(venue, court, weeks=4)

    assert series.status == "approved"
    assert series.origin == "staff"
    assert len(created) == 3
    assert series.skipped == [{"date": "2026-12-22", "reason": "booked"}]
    for booking in created:
        assert booking.series == series
        assert booking.status == Status.CONFIRMED
        assert booking.price_lkr == 4000  # Tuesday 8 pm peak, priced today
        assert booking.customer_name == "Malabe Strikers"
    assert SmsMessage.objects.filter(purpose="reminder").count() == 3


def test_one_summary_sms_with_skipped_dates(venue, court, clock):
    walk_in(venue, court, at(2026, 12, 22, 20, 0))
    staff_series(venue, court, weeks=4)
    summaries = SmsMessage.objects.filter(purpose="series_summary")
    assert summaries.count() == 1
    body = summaries.get().body
    assert "Tue 8:00 pm, 3 weeks from 8 Dec." in body
    assert "Skipped: 22 Dec." in body
    assert not SmsMessage.objects.filter(purpose="booking_confirmation").exists()


def test_week_limits(venue, court, clock):
    with pytest.raises(RuleViolation, match="between 2 and 12 weeks"):
        staff_series(venue, court, weeks=1)
    with pytest.raises(RuleViolation):
        staff_series(venue, court, weeks=13)
    VenueSettings.objects.for_venue(venue).update(recurring_max_weeks=6, recurring_default_weeks=4)
    venue.settings.refresh_from_db()
    with pytest.raises(RuleViolation, match="between 2 and 6 weeks"):
        staff_series(venue, court, weeks=8)


def test_all_weeks_clash_creates_nothing(venue, court, clock):
    for k in range(2):
        walk_in(venue, court, at(2026, 12, 8, 20, 0) + timedelta(weeks=k))
    with pytest.raises(RuleViolation, match="All weeks clash"):
        staff_series(venue, court, weeks=2)
    assert not RecurringSeries.objects.exists()


def test_phone_is_required(venue, court, clock):
    with pytest.raises(RuleViolation, match="phone number"):
        staff_series(venue, court, customer_phone="")


def test_week_taken_at_the_last_moment_is_skipped_not_double_booked(
    venue, court, clock, monkeypatch
):
    """The plan says free, but someone books week 1 first: the database skips it safely."""
    real_plan = services.plan_weeks

    def stale_plan(*args, **kwargs):
        plans = real_plan(*args, **kwargs)
        walk_in(venue, court, at(2026, 12, 8, 20, 0))  # booked between plan and insert
        monkeypatch.setattr(services, "plan_weeks", real_plan)
        return plans

    monkeypatch.setattr(services, "plan_weeks", stale_plan)
    series, created = staff_series(venue, court, weeks=3)
    assert len(created) == 2
    assert series.skipped == [{"date": "2026-12-08", "reason": "booked"}]
    assert (
        Booking.objects.filter(
            court=court, start_at=at(2026, 12, 8, 20, 0), status="confirmed"
        ).count()
        == 1
    )


def test_series_bookings_do_not_count_towards_the_online_limit(venue, court, court2, player, clock):
    staff_series(venue, court, customer_phone=player.phone, weeks=4)
    services.create_online_booking(user=player, court_id=court2.pk, start_at=at(2026, 12, 9, 18, 0))
    services.create_online_booking(
        user=player, court_id=court2.pk, start_at=at(2026, 12, 10, 18, 0)
    )


# ---------------------------------------------------------------- cancelling (BR-14)


def test_cancel_one_week_keeps_the_series(venue, court, clock):
    series, created = staff_series(venue, court, weeks=3)
    services.cancel_by_staff(
        venue=venue, actor=venue.staff, booking_id=created[1].pk, reason="customer_request"
    )
    series.refresh_from_db()
    assert series.status == "approved"
    assert [b.status for b in series.bookings.order_by("start_at")] == [
        "confirmed",
        "cancelled",
        "confirmed",
    ]


def test_staff_cancel_the_rest(venue, court, clock):
    series, created = staff_series(venue, court, first=date(2026, 12, 7), minute=1260, weeks=3)
    clock.shift(timedelta(hours=12))  # Mon 22:00: week 1 (21:00) is over
    cancelled, kept = services.cancel_series_by_staff(
        venue=venue, actor=venue.owner, series_id=series.pk, reason="customer_request"
    )
    series.refresh_from_db()
    assert series.status == "cancelled"
    assert series.cancelled_from == date(2026, 12, 7)
    assert [b.pk for b in cancelled] == [created[1].pk, created[2].pk]
    assert kept == []
    created[0].refresh_from_db()
    assert created[0].status == Status.CONFIRMED  # the played week stays
    assert SmsMessage.objects.filter(purpose="series_decision").count() == 1
    assert not SmsMessage.objects.filter(
        purpose="reminder", status="queued", booking__in=cancelled
    ).exists()


def test_staff_cancel_rules(venue, court, other_venue, clock):
    series, _created = staff_series(venue, court, weeks=2)
    with pytest.raises(RuleViolation, match="reason"):
        services.cancel_series_by_staff(
            venue=venue, actor=venue.owner, series_id=series.pk, reason=""
        )
    with pytest.raises(RecurringSeries.DoesNotExist):
        services.cancel_series_by_staff(
            venue=other_venue, actor=other_venue.owner, series_id=series.pk, reason="other"
        )
    services.cancel_series_by_staff(
        venue=venue, actor=venue.owner, series_id=series.pk, reason="other"
    )
    with pytest.raises(RuleViolation, match="not active"):
        services.cancel_series_by_staff(
            venue=venue, actor=venue.owner, series_id=series.pk, reason="other"
        )


def test_captain_cancel_keeps_weeks_inside_the_window(venue, court, player, clock):
    # Week 1 is today 14:00 (inside the 6-hour window); weeks 2-3 are next Mondays.
    series, created = staff_series(
        venue, court, first=date(2026, 12, 7), minute=840, weeks=3, customer_phone=player.phone
    )
    cancelled, kept = services.cancel_series_by_player(user=player, series_id=series.pk)
    assert [b.pk for b in kept] == [created[0].pk]
    assert [b.pk for b in cancelled] == [created[1].pk, created[2].pk]
    created[0].refresh_from_db()
    assert created[0].status == Status.CONFIRMED


def test_captain_can_only_cancel_their_own_series(venue, court, player, clock):
    series, _created = staff_series(venue, court, weeks=2)  # someone else's number
    with pytest.raises(RecurringSeries.DoesNotExist):
        services.cancel_series_by_player(user=player, series_id=series.pk)


# ---------------------------------------------------------------- screens (V16)


@pytest.fixture
def staff_client(client, venue):
    client.force_login(venue.staff)
    return client


def weekly_data(court, **overrides):
    data = {
        "customer_name": "Malabe Strikers",
        "customer_phone": "0715551234",
        "court": court.pk,
        "first_date": TUE.isoformat(),
        "start_minute": str(EIGHT_PM),
        "slots": "1",
        "weeks": "4",
    }
    data.update(overrides)
    return data


def test_preview_then_create(staff_client, venue, court, clock):
    walk_in(venue, court, at(2026, 12, 22, 20, 0))
    url = reverse("manage:weekly_new", args=[venue.pk])
    preview = staff_client.post(url, {**weekly_data(court), "preview": "1"}).content.decode()
    assert "3 of 4 weeks are free" in preview
    assert "Clash: already booked" in preview
    assert not RecurringSeries.objects.exists()

    response = staff_client.post(url, {**weekly_data(court), "create": "1"}, follow=True)
    html = response.content.decode()
    assert "3 weeks booked. 1 skipped (22 Dec)." in html
    assert "Malabe Strikers" in html
    assert RecurringSeries.objects.count() == 1


def test_weekly_form_errors(staff_client, venue, court, clock):
    url = reverse("manage:weekly_new", args=[venue.pk])
    html = staff_client.post(
        url, {**weekly_data(court, customer_phone="", weeks="20"), "preview": "1"}
    ).content.decode()
    assert "Add a phone number so we can send the schedule." in html
    assert "less than or equal to 12" in html


def test_weekly_list_detail_and_cancel(staff_client, venue, court, clock):
    series, _created = staff_series(venue, court, weeks=2)
    assert (
        "Malabe Strikers"
        in staff_client.get(reverse("manage:weekly", args=[venue.pk])).content.decode()
    )
    detail = staff_client.get(
        reverse("manage:series_detail", args=[venue.pk, series.pk])
    ).content.decode()
    assert "Tue 8 Dec" in detail
    assert "Cancel remaining weeks" in detail
    response = staff_client.post(
        reverse("manage:series_cancel", args=[venue.pk, series.pk]),
        {"reason": "venue_issue"},
        follow=True,
    )
    assert "2 weeks cancelled." in response.content.decode()
    response = staff_client.post(
        reverse("manage:series_cancel", args=[venue.pk, series.pk]), {}, follow=True
    )
    assert "Choose a reason" in response.content.decode()


def test_calendar_and_details_mark_series_bookings(staff_client, venue, court, clock):
    _series, created = staff_series(venue, court, weeks=2)
    calendar = staff_client.get(
        reverse("manage:dashboard", args=[venue.pk]), {"date": "2026-12-08"}
    ).content.decode()
    assert "🔁 Malabe Strikers" in calendar
    detail = staff_client.get(
        reverse("manage:booking_detail", args=[venue.pk, created[0].pk])
    ).content.decode()
    assert "Part of a weekly booking" in detail


def test_repeat_weekly_link_prefills(staff_client, venue, court, clock):
    response = staff_client.get(
        reverse("manage:weekly_new", args=[venue.pk]),
        {"court": court.pk, "start": "2026-12-08T20:00"},
    )
    assert response.context["form"].initial["start_minute"] == EIGHT_PM
    assert response.context["form"].initial["court"] == court
