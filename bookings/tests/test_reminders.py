"""Reminder SMS (US-P07, BR-20): when, for whom, and what happens on cancel, move, no-show.
'Now' is Mon 7 Dec 2026 10:00 in Colombo; the venue's lead time is 3 hours (default)."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction

from bookings import services
from bookings.models import Source
from notifications import services as notifications
from notifications.backends import locmem
from notifications.backends.locmem import LocmemBackend
from notifications.models import SmsMessage
from notifications.worker import send_due_messages
from venues.models import VenueSettings

from .conftest import NOW, at

pytestmark = pytest.mark.django_db


def phone_booking(venue, court, start, **kw):
    params = {"source": Source.PHONE, "customer_name": "Ravi", "customer_phone": "0715551234"}
    params.update(kw)
    return services.create_staff_booking(
        venue=venue,
        actor=venue.staff,
        court_id=court.pk,
        start_at=start,
        end_at=start + timedelta(hours=1),
        **params,
    )


def reminders(booking=None):
    qs = SmsMessage.objects.filter(purpose="reminder")
    return qs.filter(booking=booking) if booking else qs


# ---------------------------------------------------------------- reminder time (BR-20)


@pytest.mark.parametrize(
    ("start", "lead", "expected"),
    [
        (at(2026, 12, 8, 19, 0), 3, at(2026, 12, 8, 16, 0)),  # normal
        (at(2026, 12, 8, 19, 0), 2, at(2026, 12, 8, 17, 0)),  # venue chose 2 hours
        (at(2026, 12, 8, 8, 0), 3, at(2026, 12, 7, 21, 0)),  # 05:00 is quiet: 21:00 evening before
        (at(2026, 12, 8, 9, 0), 3, at(2026, 12, 7, 21, 0)),  # 06:00 is quiet too
        (at(2026, 12, 8, 10, 0), 3, at(2026, 12, 8, 7, 0)),  # 07:00 is fine
        (at(2026, 12, 9, 1, 0), 3, at(2026, 12, 8, 21, 0)),  # 22:00 is quiet: 21:00 same evening
        (at(2026, 12, 9, 0, 59), 3, at(2026, 12, 8, 21, 59)),  # 21:59 is just before quiet hours
        (at(2026, 12, 9, 6, 0), 24, at(2026, 12, 7, 21, 0)),  # Tue 06:00 is quiet: Mon 21:00
    ],
)
def test_reminder_time(start, lead, expected):
    assert notifications.reminder_time(start, lead) == expected


# ---------------------------------------------------------------- who gets one


def test_phone_booking_gets_one_reminder(venue, court, clock):
    booking = phone_booking(venue, court, at(2026, 12, 8, 19, 0))
    reminder = reminders(booking).get()
    assert reminder.scheduled_for == at(2026, 12, 8, 16, 0)
    assert reminder.to_phone == "+94715551234"
    assert reminder.venue == venue
    assert "Matchvia reminder: Court 1 at Arena A, Tue 8 Dec, 7:00 pm-8:00 pm." in reminder.body
    assert booking.display_reference in reminder.body


def test_online_booking_gets_a_reminder(player, court, clock):
    booking = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 8, 19, 0)
    )
    assert reminders(booking).get().to_phone == player.phone


def test_lead_time_is_a_venue_setting(venue, court, clock):
    VenueSettings.objects.for_venue(venue).update(reminder_lead_hours=2)
    venue.settings.refresh_from_db()
    booking = phone_booking(venue, court, at(2026, 12, 8, 19, 0))
    assert reminders(booking).get().scheduled_for == at(2026, 12, 8, 17, 0)


def test_no_reminder_for_walk_ins_or_without_phone(venue, court, clock):
    services.create_staff_booking(
        venue=venue,
        actor=venue.staff,
        court_id=court.pk,
        start_at=at(2026, 12, 8, 19, 0),
        end_at=at(2026, 12, 8, 20, 0),
        source=Source.WALK_IN,
        customer_name="Nimal",
        customer_phone="0715551234",
    )
    services.create_staff_booking(
        venue=venue,
        actor=venue.staff,
        court_id=court.pk,
        start_at=at(2026, 12, 8, 20, 0),
        end_at=at(2026, 12, 8, 21, 0),
        source=Source.WALK_IN,
        customer_name="No phone",
    )
    assert not reminders().exists()


def test_no_reminder_when_booked_after_the_reminder_time(venue, court, clock):
    phone_booking(venue, court, NOW + timedelta(hours=2))  # reminder would be 1 hour ago
    assert not reminders().exists()


# ---------------------------------------------------------------- changes


def test_cancelling_cancels_the_reminder(venue, court, clock):
    booking = phone_booking(venue, court, at(2026, 12, 8, 19, 0))
    services.cancel_by_staff(venue=venue, actor=venue.staff, booking_id=booking.pk, reason="other")
    assert reminders(booking).get().status == SmsMessage.Status.CANCELLED


def test_player_cancel_cancels_the_reminder(player, court, clock):
    booking = services.create_online_booking(
        user=player, court_id=court.pk, start_at=at(2026, 12, 8, 19, 0)
    )
    services.cancel_by_player(user=player, booking_id=booking.pk)
    assert not reminders(booking).filter(status="queued").exists()


def test_moving_reschedules_the_reminder(venue, court, court2, clock):
    booking = phone_booking(venue, court, at(2026, 12, 8, 19, 0))
    services.move_booking(
        venue=venue,
        actor=venue.staff,
        booking_id=booking.pk,
        court_id=court2.pk,
        start_at=at(2026, 12, 9, 20, 0),
    )
    queued = reminders(booking).filter(status="queued").get()
    assert queued.scheduled_for == at(2026, 12, 9, 17, 0)
    assert "Court 2" in queued.body
    assert reminders(booking).filter(status="cancelled").count() == 1


def test_no_show_cancels_the_reminder(venue, court, clock):
    booking = phone_booking(venue, court, at(2026, 12, 7, 18, 0))  # reminder at 15:00
    clock.shift(timedelta(hours=8, minutes=20))
    services.mark_no_show(venue=venue, actor=venue.staff, booking_id=booking.pk)
    assert not reminders(booking).filter(status="queued").exists()


def test_database_allows_only_one_live_reminder(venue, court, clock):
    booking = phone_booking(venue, court, at(2026, 12, 8, 19, 0))
    with pytest.raises(IntegrityError), transaction.atomic():
        notifications.queue_sms(
            to_phone="+94715551234", purpose="reminder", body="again", booking=booking, venue=venue
        )


# ---------------------------------------------------------------- the worker


def test_reminder_is_sent_at_its_time(venue, court, clock):
    booking = phone_booking(venue, court, at(2026, 12, 8, 19, 0))
    send_due_messages(backend=LocmemBackend())
    assert not any("reminder" in sms.text for sms in locmem.outbox)
    clock.shift(timedelta(days=1, hours=6))  # Tue 16:00
    send_due_messages(backend=LocmemBackend())
    assert any(sms.text.startswith("Matchvia reminder") for sms in locmem.outbox)
    assert reminders(booking).get().status == SmsMessage.Status.SENT


def test_late_reminder_is_dropped_once_the_game_started(venue, court, clock):
    booking = phone_booking(venue, court, at(2026, 12, 8, 19, 0))
    clock.shift(timedelta(days=1, hours=9, minutes=30))  # worker was down until 19:30
    send_due_messages(backend=LocmemBackend())
    reminder = reminders(booking).get()
    assert reminder.status == SmsMessage.Status.CANCELLED
    assert "started" in reminder.last_error
    assert not any(sms.text.startswith("Matchvia reminder") for sms in locmem.outbox)
