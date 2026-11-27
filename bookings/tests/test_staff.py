"""Staff bookings (US-S02, US-S03, BR-19, BR-21, BR-23) and blocks (US-S06, BR-17)."""

from datetime import timedelta

import pytest

from accounts.tests.factories import UserFactory
from bookings import services
from bookings.models import Booking, BookingEvent, Kind, Source, Status
from core.exceptions import NotAllowed, RuleViolation, SlotTaken
from notifications.models import SmsMessage
from venues.models import Court, VenueCustomer, VenueSettings

from .conftest import NOW, at

pytestmark = pytest.mark.django_db

S, E = at(2026, 12, 8, 18, 0), at(2026, 12, 8, 19, 0)


def staff_book(venue, court, *, actor=None, start=S, end=E, **kw):
    params = {"source": Source.WALK_IN, "customer_name": "Kasun"}
    params.update(kw)
    return services.create_staff_booking(
        venue=venue,
        actor=actor or venue.staff,
        court_id=court.pk,
        start_at=start,
        end_at=end,
        **params,
    )


# ---------------------------------------------------------------- walk-ins and phone bookings


def test_walk_in_with_name_only(venue, court, clock):
    booking = staff_book(venue, court)
    assert booking.status == Status.CONFIRMED
    assert booking.source == Source.WALK_IN
    assert booking.venue_customer is None
    assert booking.customer_name == "Kasun"
    assert booking.price_lkr == 4000
    assert booking.created_by == venue.staff
    assert not SmsMessage.objects.exists()  # no phone, no SMS (US-S02)


def test_phone_booking_needs_a_number_and_sends_sms(venue, court, clock):
    with pytest.raises(RuleViolation, match="phone number"):
        staff_book(venue, court, source=Source.PHONE)
    booking = staff_book(venue, court, source=Source.PHONE, customer_phone="071 555 1234")
    assert booking.venue_customer.phone == "+94715551234"
    assert SmsMessage.objects.get(purpose="booking_confirmation").to_phone == "+94715551234"


def test_invalid_customer_phone_refused(venue, court, clock):
    with pytest.raises(RuleViolation, match="valid Sri Lankan mobile"):
        staff_book(venue, court, source=Source.WHATSAPP, customer_phone="0112345678")


def test_sms_follows_venue_settings(venue, court, court2, clock):
    VenueSettings.objects.for_venue(venue).update(sms_on_phone_bookings=False, sms_on_walk_ins=True)
    venue.settings.refresh_from_db()
    staff_book(venue, court, source=Source.PHONE, customer_phone="0715551234")
    confirmations = SmsMessage.objects.filter(purpose="booking_confirmation")
    assert not confirmations.exists()  # BR-21 setting covers the confirmation SMS
    staff_book(venue, court2, customer_phone="0715551234")  # a walk-in with a phone
    assert confirmations.count() == 1


def test_staff_skip_notice_and_horizon(venue, court, clock):
    staff_book(venue, court, start=NOW, end=NOW + timedelta(hours=1))
    far = at(2027, 2, 1, 18, 0)
    staff_book(venue, court, start=far, end=far + timedelta(hours=1))


def test_staff_bookings_ignore_the_online_limit_and_block(venue, court, player, clock):
    VenueCustomer.objects.create(venue=venue, phone=player.phone, name="X", is_blocked_online=True)
    for day in (8, 9, 10):
        start = at(2026, 12, day, 18, 0)
        staff_book(
            venue,
            court,
            start=start,
            end=start + timedelta(hours=1),
            source=Source.PHONE,
            customer_phone=player.phone,
        )
    assert Booking.objects.count() == 3


def test_outside_opening_hours_warns_then_allows(venue, court, clock):
    early = at(2026, 12, 8, 5, 0)
    with pytest.raises(services.OutsideOpeningHours):
        staff_book(venue, court, start=early, end=early + timedelta(hours=1))
    booking = staff_book(
        venue, court, start=early, end=early + timedelta(hours=1), allow_outside_hours=True
    )
    assert booking.price_lkr == 3000


def test_must_be_whole_slots(venue, court, clock):
    with pytest.raises(RuleViolation, match="60-minute slots"):
        staff_book(venue, court, end=S + timedelta(minutes=45))
    with pytest.raises(RuleViolation):
        staff_book(venue, court, end=S)


def test_customer_name_required(venue, court, clock):
    with pytest.raises(RuleViolation, match="customer's name"):
        staff_book(venue, court, customer_name="   ")
    with pytest.raises(RuleViolation):
        staff_book(venue, court, customer_name="x" * 81)
    with pytest.raises(RuleViolation, match="walk-in, phone or WhatsApp"):
        staff_book(venue, court, source=Source.ONLINE)


def test_phone_customer_is_linked_to_a_registered_player(venue, court, player, clock):
    booking = staff_book(
        venue, court, source=Source.PHONE, customer_phone=player.phone, customer_name="Nimal"
    )
    assert booking.venue_customer.user == player


def test_same_number_reuses_the_customer_and_updates_name(venue, court, clock):
    first = staff_book(
        venue, court, source=Source.PHONE, customer_phone="0715551234", customer_name="Ravi"
    )
    later = at(2026, 12, 9, 18, 0)
    second = staff_book(
        venue,
        court,
        start=later,
        end=later + timedelta(hours=1),
        source=Source.PHONE,
        customer_phone="+94715551234",
        customer_name="Ravi K",
    )
    assert first.venue_customer_id == second.venue_customer_id
    assert VenueCustomer.objects.get().name == "Ravi K"


def test_overlap_gives_slot_taken(venue, court, clock):
    staff_book(venue, court)
    with pytest.raises(SlotTaken, match="just taken"):
        staff_book(venue, court, start=S + timedelta(hours=0), end=E)


def test_inactive_court_refused(venue, court, clock):
    court.is_active = False
    court.save()
    with pytest.raises(RuleViolation, match="deactivated"):
        staff_book(venue, court)


# ---------------------------------------------------------------- price changes (BR-19)


def test_price_change_needs_a_reason_and_is_logged(venue, court, clock):
    with pytest.raises(RuleViolation, match="reason"):
        staff_book(venue, court, price_lkr=3000)
    booking = staff_book(venue, court, price_lkr=3000, price_change_reason="Regular team")
    assert (booking.price_lkr, booking.price_change_reason) == (3000, "Regular team")
    event = BookingEvent.objects.get(booking=booking, action="price_changed")
    assert event.changes == {"before": 4000, "after": 3000}
    assert event.actor == venue.staff


def test_same_price_needs_no_reason(venue, court, clock):
    booking = staff_book(venue, court, price_lkr=4000)
    assert booking.price_change_reason == ""


def test_owner_can_stop_staff_changing_prices(venue, court, court2, clock):
    VenueSettings.objects.for_venue(venue).update(staff_can_change_price=False)
    venue.settings.refresh_from_db()
    with pytest.raises(NotAllowed, match="Only the owner"):
        staff_book(venue, court, price_lkr=1000, price_change_reason="Friend")
    staff_book(venue, court2, actor=venue.owner, price_lkr=1000, price_change_reason="Friend")


def test_negative_price_refused(venue, court, clock):
    with pytest.raises(RuleViolation, match="negative"):
        staff_book(venue, court, price_lkr=-1, price_change_reason="x")


# ------------------------------------------------------------ venue isolation (CLAUDE.md rule 2)


def test_other_venues_court_is_not_found(venue, other_venue, clock):
    with pytest.raises(Court.DoesNotExist):
        services.create_staff_booking(
            venue=venue,
            actor=venue.owner,
            court_id=other_venue.court.pk,
            start_at=S,
            end_at=E,
            source=Source.WALK_IN,
            customer_name="X",
        )
    assert not Booking.objects.exists()


def test_non_members_cannot_book_for_a_venue(venue, other_venue, court, clock):
    for outsider in (UserFactory(), other_venue.owner):
        with pytest.raises(NotAllowed):
            staff_book(venue, court, actor=outsider)


# ---------------------------------------------------------------- blocks


def block(venue, courts, start=S, end=E, reason="maintenance"):
    return services.create_block(
        venue=venue,
        actor=venue.staff,
        court_ids=[c.pk for c in courts],
        start_at=start,
        end_at=end,
        reason=reason,
    )


def test_block_one_court(venue, court, clock):
    (created,) = block(venue, [court])
    assert (created.kind, created.status, created.source, created.price_lkr) == (
        Kind.BLOCK,
        Status.CONFIRMED,
        None,
        0,
    )
    with pytest.raises(SlotTaken):
        staff_book(venue, court)


def test_block_several_courts_shares_a_group(venue, court, court2, clock):
    blocks = block(venue, [court, court2], reason="private_event")
    assert len({b.block_group for b in blocks}) == 1


def test_block_over_a_booking_is_refused_with_the_list(venue, court, court2, clock):
    booking = staff_book(venue, court)
    with pytest.raises(services.BlockConflict) as exc:
        block(venue, [court, court2], start=at(2026, 12, 8, 17, 0), end=at(2026, 12, 8, 20, 0))
    assert exc.value.conflicts == [booking]
    assert not Booking.objects.filter(kind=Kind.BLOCK).exists()  # all or nothing


def test_block_validation(venue, court, other_venue, clock):
    with pytest.raises(RuleViolation, match="reason"):
        block(venue, [court], reason="party")
    with pytest.raises(RuleViolation, match="after the start"):
        block(venue, [court], start=E, end=S)
    with pytest.raises(RuleViolation, match="24 hours"):
        block(venue, [court], end=S + timedelta(hours=25))
    with pytest.raises(Court.DoesNotExist):
        block(venue, [court, other_venue.court])
    with pytest.raises(Court.DoesNotExist):
        block(venue, [])


def test_cancel_block_frees_the_time(venue, court, clock):
    (created,) = block(venue, [court])
    services.cancel_block(venue=venue, actor=venue.owner, booking_id=created.pk)
    created.refresh_from_db()
    assert created.status == Status.CANCELLED
    staff_book(venue, court)


def test_cannot_cancel_another_venues_block(venue, other_venue, clock):
    (theirs,) = services.create_block(
        venue=other_venue,
        actor=other_venue.owner,
        court_ids=[other_venue.court.pk],
        start_at=S,
        end_at=E,
        reason="maintenance",
    )
    with pytest.raises(Booking.DoesNotExist):
        services.cancel_block(venue=venue, actor=venue.owner, booking_id=theirs.pk)


def test_reference_collision_is_retried(venue, court, monkeypatch, clock):
    """Two bookings drawing the same random reference: the second simply gets a new one."""
    first = staff_book(venue, court)
    codes = iter([first.reference, "ZZZZZZ"])
    monkeypatch.setattr(services, "generate_reference", lambda: next(codes))
    later = at(2026, 12, 9, 18, 0)
    second = staff_book(venue, court, start=later, end=later + timedelta(hours=1))
    assert second.reference == "ZZZZZZ"
