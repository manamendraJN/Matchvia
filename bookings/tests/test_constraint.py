"""The database itself refuses double bookings and malformed rows (CLAUDE.md rule 1, NFR-01).

These tests write rows directly, bypassing the services, to prove correctness never depends on
the application's own checks.
"""

import threading
import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from bookings import services
from bookings.models import Booking, Kind, Source, Status
from bookings.reference import generate_reference
from core.exceptions import SlotTaken
from core.timeutils import operating_date
from venues.models import VenueCustomer

from .conftest import at

pytestmark = pytest.mark.django_db


def row(court, start, end, **fields):
    """A booking row written straight to the database."""
    values = {
        "reference": generate_reference(),
        "venue_id": court.venue_id,
        "court": court,
        "kind": Kind.BOOKING,
        "status": Status.CONFIRMED,
        "source": Source.WALK_IN,
        "start_at": start,
        "end_at": end,
        "operating_date": operating_date(start),
        "customer_name": "Test",
    }
    values.update(fields)
    with transaction.atomic():
        return Booking.objects.create(**values)


def rejected(court, start, end, **fields):
    with pytest.raises(IntegrityError):
        row(court, start, end, **fields)


S, E = at(2026, 12, 8, 18, 0), at(2026, 12, 8, 19, 0)


# ---------------------------------------------------------------- the overlap rule


def test_exact_same_time_rejected(court):
    row(court, S, E)
    rejected(court, S, E)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (at(2026, 12, 8, 17, 30), at(2026, 12, 8, 18, 30)),  # overlaps the start
        (at(2026, 12, 8, 18, 30), at(2026, 12, 8, 19, 30)),  # overlaps the end
        (at(2026, 12, 8, 18, 15), at(2026, 12, 8, 18, 45)),  # inside
        (at(2026, 12, 8, 17, 0), at(2026, 12, 8, 20, 0)),  # covers it
    ],
)
def test_partial_overlaps_rejected(court, start, end):
    row(court, S, E)
    rejected(court, start, end)


def test_touching_bookings_allowed(court):
    """10:00-11:00 and 11:00-12:00 don't overlap: ranges are start-inclusive, end-exclusive."""
    row(court, at(2026, 12, 8, 10, 0), at(2026, 12, 8, 11, 0))
    row(court, at(2026, 12, 8, 11, 0), at(2026, 12, 8, 12, 0))
    row(court, at(2026, 12, 8, 9, 0), at(2026, 12, 8, 10, 0))
    assert Booking.objects.count() == 3


def test_different_courts_at_the_same_time_allowed(court, court2):
    row(court, S, E)
    row(court2, S, E)


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        (Status.CANCELLED, {"cancelled_at": timezone.now()}),
        (Status.NO_SHOW, {"no_show_marked_at": timezone.now()}),
        (Status.EXPIRED, {}),
    ],
)
def test_cancelled_no_show_and_expired_free_the_court(court, status, extra):
    row(court, S, E, status=status, **extra)
    row(court, S, E)  # a new confirmed booking fits


def test_held_rows_occupy_the_court(court):
    """Phase 2 holds are protected by the same constraint."""
    row(court, S, E, status=Status.HELD, hold_expires_at=timezone.now() + timedelta(minutes=10))
    rejected(court, S, E)


def test_reactivating_into_a_rebooked_time_is_rejected(court):
    first = row(court, S, E, status=Status.NO_SHOW, no_show_marked_at=timezone.now())
    row(court, S, E)
    with pytest.raises(IntegrityError), transaction.atomic():
        Booking.objects.filter(pk=first.pk).update(status=Status.CONFIRMED, no_show_marked_at=None)


def block(court, start, end, **fields):
    return row(
        court,
        start,
        end,
        kind=Kind.BLOCK,
        source=None,
        customer_name="",
        block_reason="maintenance",
        **fields,
    )


def test_blocks_and_bookings_collide_both_ways(court, court2):
    block(court, S, E)
    rejected(court, S, E)
    row(court2, S, E)
    with pytest.raises(IntegrityError):
        block(court2, S, E)


def test_moving_into_a_taken_time_is_rejected(court):
    row(court, S, E)
    other = row(court, at(2026, 12, 8, 20, 0), at(2026, 12, 8, 21, 0))
    with pytest.raises(IntegrityError), transaction.atomic():
        Booking.objects.filter(pk=other.pk).update(start_at=S, end_at=E)


# ---------------------------------------------------------------- row shape checks


@pytest.mark.parametrize(
    "fields",
    [
        {"end_at": S},  # empty range
        {"end_at": S - timedelta(hours=1)},  # negative range
        {"end_at": S + timedelta(hours=25)},  # longer than 24 h
        {"status": "completed"},  # not stored (derived)
        {"source": "email"},
        {"kind": "event"},
        {"block_reason": "maintenance"},  # bookings have no block reason
        {"source": None},  # bookings need a source
        {"status": Status.CANCELLED},  # without cancelled_at
        {"status": Status.NO_SHOW},  # without no_show_marked_at
        {"status": Status.HELD},  # without expiry
        {"hold_expires_at": S},  # expiry on a non-held booking
        {"cancel_reason": "bored"},
    ],
)
def test_malformed_bookings_rejected(court, fields):
    end = fields.pop("end_at", E)
    rejected(court, S, end, **fields)


@pytest.mark.parametrize(
    "fields",
    [
        {"price_lkr": 100},
        {"source": Source.PHONE},
        {"block_reason": ""},
        {"status": Status.NO_SHOW, "no_show_marked_at": S},
        {"status": Status.HELD, "hold_expires_at": S},
    ],
)
def test_malformed_blocks_rejected(court, fields):
    values = {
        "kind": Kind.BLOCK,
        "source": None,
        "block_reason": "maintenance",
        "customer_name": "",
    }
    values.update(fields)
    rejected(court, S, E, **values)


def test_block_with_customer_rejected(court):
    customer = VenueCustomer.objects.create(venue_id=court.venue_id, phone="+94771234567", name="X")
    with pytest.raises(IntegrityError):
        block(court, S, E, venue_customer=customer)


def test_one_hold_per_user(court, court2, player):
    expiry = timezone.now() + timedelta(minutes=10)
    row(court, S, E, status=Status.HELD, hold_expires_at=expiry, created_by=player)
    rejected(court2, S, E, status=Status.HELD, hold_expires_at=expiry, created_by=player)


def test_reference_unique(court):
    first = row(court, S, E)
    rejected(court, E, E + timedelta(hours=1), reference=first.reference)


# ------------------------------------------------------------ venue consistency (data-model 6.3)


def test_booking_cannot_use_another_venues_court(court, other_venue):
    rejected(court, S, E, venue_id=other_venue.pk)  # venue A in the row, but court of venue... A
    rejected(other_venue.court, S, E, venue_id=court.venue_id)


def test_booking_cannot_use_another_venues_customer(court, other_venue):
    stranger = VenueCustomer.objects.create(
        venue=other_venue, phone="+94771234567", name="B's customer"
    )
    rejected(court, S, E, venue_customer=stranger)


def test_moving_to_another_venues_court_rejected(court, other_venue):
    booking = row(court, S, E)
    with pytest.raises(IntegrityError), transaction.atomic():
        Booking.objects.filter(pk=booking.pk).update(court=other_venue.court)


def test_composite_keys_exist_in_the_database():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'bookings_booking'::regclass "
            "AND conname IN ('booking_no_overlap', 'booking_court_same_venue', "
            "'booking_customer_same_venue')"
        )
        names = {r[0] for r in cursor.fetchall()}
    assert names == {
        "booking_no_overlap",
        "booking_court_same_venue",
        "booking_customer_same_venue",
    }


# ---------------------------------------------------------------- concurrency (NFR-01)


@pytest.mark.django_db(transaction=True)
def test_twenty_parallel_bookings_for_one_slot_exactly_one_wins(venue, court):
    """20 staff members book the same slot at the same instant: exactly 1 succeeds."""
    barrier = threading.Barrier(20)
    results = []
    lock = threading.Lock()

    def attempt(i):
        barrier.wait()
        try:
            services.create_staff_booking(
                venue=venue,
                actor=venue.owner,
                court_id=court.pk,
                start_at=S,
                end_at=E,
                source=Source.WALK_IN,
                customer_name=f"Player {i}",
            )
            outcome = "ok"
        except SlotTaken:
            outcome = "taken"
        finally:
            connection.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == ["ok"] + ["taken"] * 19
    assert Booking.objects.filter(court=court, status=Status.CONFIRMED).count() == 1


@pytest.mark.django_db(transaction=True)
def test_parallel_overlapping_ranges_never_both_saved(venue, court):
    """Two different but overlapping ranges race: only one can exist."""
    barrier = threading.Barrier(2)
    results = []

    def attempt(start, end):
        barrier.wait()
        try:
            services.create_staff_booking(
                venue=venue,
                actor=venue.owner,
                court_id=court.pk,
                start_at=start,
                end_at=end,
                source=Source.WALK_IN,
                customer_name="X",
            )
            results.append("ok")
        except SlotTaken:
            results.append("taken")
        finally:
            connection.close()

    a = threading.Thread(target=attempt, args=(S, E + timedelta(hours=1)))
    b = threading.Thread(target=attempt, args=(E, E + timedelta(hours=1)))
    a.start()
    b.start()
    a.join(timeout=30)
    b.join(timeout=30)
    assert sorted(results) == ["ok", "taken"]


def test_block_groups_share_a_uuid(court, court2):
    group = uuid.uuid4()
    block(court, S, E, block_group=group)
    block(court2, S, E, block_group=group)
    assert Booking.objects.filter(block_group=group).count() == 2
