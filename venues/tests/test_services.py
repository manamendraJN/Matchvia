import pytest
from django.http import Http404

from accounts.tests.factories import UserFactory
from core.exceptions import NotAllowed, RuleViolation
from notifications.models import SmsMessage
from pricing.models import PeakPeriod
from venues import services
from venues.models import (
    Court,
    MemberRole,
    OpeningHours,
    Venue,
    VenueMembership,
    VenuePhoto,
    VenueSettings,
    VenueStatus,
)

from .factories import area, image_file, make_court, make_venue, ready_venue

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- create_venue


def test_create_venue_sets_up_all_defaults(owner):
    venue = services.create_venue(owner=owner, name="  Arena X ", area=area(), phone=owner.phone)

    assert venue.name == "Arena X"
    assert venue.slug == "arena-x"
    assert venue.status == VenueStatus.DRAFT
    settings = VenueSettings.objects.for_venue(venue).get()
    assert (
        settings.booking_horizon_days,
        settings.min_notice_minutes,
        settings.max_slots_per_booking,
        settings.max_upcoming_online_bookings,
        settings.cancellation_window_hours,
        settings.reminder_lead_hours,
        settings.sms_on_phone_bookings,
        settings.sms_on_walk_ins,
        settings.recurring_approver,
        settings.recurring_default_weeks,
        settings.recurring_max_weeks,
        settings.staff_can_change_price,
    ) == (14, 60, 3, 2, 6, 3, True, False, "owner_or_staff", 8, 12, True)
    hours = list(OpeningHours.objects.for_venue(venue))
    assert [(h.weekday, h.is_closed, h.opens_minute, h.closes_minute) for h in hours] == [
        (d, False, 360, 1440) for d in range(7)
    ]
    assert PeakPeriod.objects.for_venue(venue).count() == 7
    membership = VenueMembership.objects.for_venue(venue).get()
    assert (membership.user, membership.role) == (owner, MemberRole.OWNER)


def test_slugs_stay_unique():
    """The same name is allowed in another area; the web address still differs."""

    def new(name, slug):
        owner = UserFactory()
        return services.create_venue(owner=owner, name=name, area=area(slug), phone=owner.phone)

    first, second, third = new("Arena X", "malabe"), new("Arena X", "kotte"), new("!!!", "malabe")
    assert (first.slug, second.slug, third.slug) == ("arena-x", "arena-x-2", "venue")


# ---------------------------------------------------------------- no duplicate venues


def test_one_venue_in_setup_at_a_time(owner):
    first = services.create_venue(owner=owner, name="Arena X", area=area(), phone=owner.phone)
    with pytest.raises(RuleViolation, match=r"Finish setting up Arena X first\."):
        services.create_venue(owner=owner, name="Arena Y", area=area(), phone=owner.phone)
    assert services.draft_venue_of(owner) == first

    Venue.objects.filter(pk=first.pk).update(status=VenueStatus.PENDING)  # submitted
    second = services.create_venue(owner=owner, name="Arena Y", area=area(), phone=owner.phone)
    assert services.draft_venue_of(owner) == second


@pytest.mark.parametrize("typed", ["Arena X", "arena x", "  ARENA   X "])
def test_same_name_in_the_same_area_is_refused(owner, typed):
    services.create_venue(owner=owner, name="Arena X", area=area(), phone=owner.phone)
    other = UserFactory()
    with pytest.raises(
        RuleViolation, match=r"A venue called Arena X is already listed in Malabe\."
    ):
        services.create_venue(owner=other, name=typed, area=area(), phone=other.phone)
    assert Venue.objects.count() == 1


def test_a_rejected_venue_does_not_block_its_name(owner):
    first = services.create_venue(owner=owner, name="Arena X", area=area(), phone=owner.phone)
    Venue.objects.filter(pk=first.pk).update(status=VenueStatus.REJECTED)
    other = UserFactory()
    services.create_venue(owner=other, name="Arena X", area=area(), phone=other.phone)
    assert Venue.objects.filter(name="Arena X").count() == 2


def test_renaming_to_a_taken_name_is_refused(owner):
    services.create_venue(owner=owner, name="Arena X", area=area(), phone=owner.phone)
    other = UserFactory()
    venue = services.create_venue(owner=other, name="Arena Y", area=area(), phone=other.phone)
    with pytest.raises(RuleViolation, match="already listed"):
        services.update_profile(venue, other, name="arena x")
    venue.refresh_from_db()
    assert venue.name == "Arena Y"
    services.update_profile(venue, other, name="  Arena   Y  ")  # its own name is fine
    venue.refresh_from_db()
    assert venue.name == "Arena Y"


def test_the_database_refuses_duplicates_too(owner):
    """Even if two requests pass the check at the same moment, the constraint stops one."""
    from django.db import IntegrityError, transaction

    services.create_venue(owner=owner, name="Arena X", area=area(), phone=owner.phone)
    with pytest.raises(IntegrityError, match="venue_name_unique_in_area"), transaction.atomic():
        Venue.objects.create(name="ARENA X", slug="arena-x-copy", area=area(), phone=owner.phone)


def test_race_on_create_shows_the_friendly_message(owner, monkeypatch):
    services.create_venue(owner=owner, name="Arena X", area=area(), phone=owner.phone)
    monkeypatch.setattr(services, "_check_name_free", lambda *a, **k: None)  # both passed the check
    other = UserFactory()
    with pytest.raises(RuleViolation, match="already listed"):
        services.create_venue(owner=other, name="Arena X", area=area(), phone=other.phone)
    venue = services.create_venue(owner=other, name="Arena Z", area=area(), phone=other.phone)
    with pytest.raises(RuleViolation, match="already listed"):
        services.update_profile(venue, other, name="Arena X")


# ---------------------------------------------------------------- get_venue_for_user


def test_owner_and_staff_get_in_with_their_role(venue, owner, staff):
    assert services.get_venue_for_user(owner, venue.pk).member_role == MemberRole.OWNER
    assert services.get_venue_for_user(staff, venue.pk).member_role == MemberRole.STAFF


def test_owner_only_access_refuses_staff(venue, staff):
    with pytest.raises(Http404):
        services.get_venue_for_user(staff, venue.pk, services.OWNER)


@pytest.mark.parametrize("venue_id", ["abc", None, 999_999])
def test_bad_ids_are_404(owner, venue_id):
    with pytest.raises(Http404):
        services.get_venue_for_user(owner, venue_id)


def test_non_members_inactive_and_anonymous_get_404(venue, other_venue, owner):
    from django.contrib.auth.models import AnonymousUser

    with pytest.raises(Http404):
        services.get_venue_for_user(owner, other_venue.pk)
    with pytest.raises(Http404):
        services.get_venue_for_user(UserFactory(), venue.pk)
    with pytest.raises(Http404):
        services.get_venue_for_user(AnonymousUser(), venue.pk)
    owner.is_active = False
    with pytest.raises(Http404):
        services.get_venue_for_user(owner, venue.pk)


def test_removing_membership_ends_access_immediately(venue, staff):
    services.get_venue_for_user(staff, venue.pk)
    VenueMembership.objects.for_venue(venue).filter(user=staff).delete()
    with pytest.raises(Http404):
        services.get_venue_for_user(staff, venue.pk)


def test_memberships_for_user(venue, other_venue, owner):
    assert [m.venue for m in services.memberships_for_user(owner)] == [venue]


# ---------------------------------------------------------------- owner-only changes


def test_staff_cannot_change_anything_even_through_services(venue, staff, court):
    calls = [
        lambda: services.update_profile(venue, staff, name="Hacked"),
        lambda: services.create_court(
            venue, staff, name="X", sports=["futsal"], off_peak_price_lkr=1, peak_price_lkr=1
        ),
        lambda: services.update_court(venue, staff, court.pk, name="X"),
        lambda: services.set_court_active(venue, staff, court.pk, active=False),
        lambda: services.update_prices(venue, staff, court_prices={}, peak_periods=[]),
        lambda: services.set_opening_hours(venue, staff, []),
        lambda: services.add_photo(venue, staff, image_file()),
        lambda: services.submit_for_approval(venue, staff),
    ]
    for call in calls:
        with pytest.raises(NotAllowed):
            call()
    venue.refresh_from_db()
    assert venue.name == "Arena A"


def test_owner_of_another_venue_cannot_change_this_one(venue, other_venue):
    other_owner = VenueMembership.objects.for_venue(other_venue).get().user
    with pytest.raises(NotAllowed):
        services.update_profile(venue, other_owner, name="Hacked")


def test_update_profile(venue, owner):
    services.update_profile(
        venue,
        owner,
        address=" 12 Main St ",
        latitude="6.9",
        longitude="79.95",
        facilities=["parking", "cafe"],
    )
    venue.refresh_from_db()
    assert venue.address == "12 Main St"
    assert venue.facilities == ["parking", "cafe"]


def test_update_profile_needs_both_coordinates(venue, owner):
    with pytest.raises(RuleViolation):
        services.update_profile(venue, owner, latitude="6.9")
    with pytest.raises(RuleViolation):
        services.update_profile(venue, owner, latitude="6.9", longitude=None)


def test_update_profile_refuses_status_and_other_fields(venue, owner):
    with pytest.raises(ValueError, match="Not editable"):
        services.update_profile(venue, owner, status="approved")


# ---------------------------------------------------------------- courts


def test_create_and_update_court(venue, owner):
    court = services.create_court(
        venue,
        owner,
        name=" Court  1 ",
        sports=["futsal", "indoor_cricket"],
        slot_minutes=90,
        off_peak_price_lkr=2500,
        peak_price_lkr=3500,
        is_indoor=False,
    )
    assert court.name == "Court 1"
    services.update_court(venue, owner, court.pk, peak_price_lkr=5000, name="Main pitch")
    court.refresh_from_db()
    assert (court.name, court.peak_price_lkr) == ("Main pitch", 5000)


def test_duplicate_court_names_refused_case_insensitively(venue, owner, court):
    with pytest.raises(RuleViolation, match="same name"):
        services.create_court(
            venue, owner, name="court 1", sports=["futsal"], off_peak_price_lkr=1, peak_price_lkr=1
        )
    other = make_court(venue, name="Court 2")
    with pytest.raises(RuleViolation):
        services.update_court(venue, owner, other.pk, name="COURT 1")
    with pytest.raises(RuleViolation):
        services.create_court(
            venue, owner, name="   ", sports=["futsal"], off_peak_price_lkr=1, peak_price_lkr=1
        )


def test_court_of_another_venue_is_not_found(venue, owner, other_venue):
    other_court = Court.objects.for_venue(other_venue).get()
    with pytest.raises(Court.DoesNotExist):
        services.update_court(venue, owner, other_court.pk, name="Mine now")
    with pytest.raises(Court.DoesNotExist):
        services.set_court_active(venue, owner, other_court.pk, active=False)
    with pytest.raises(Court.DoesNotExist):
        services.update_prices(venue, owner, court_prices={other_court.pk: (1, 1)}, peak_periods=[])
    other_court.refresh_from_db()
    assert other_court.name == "Court B1"
    assert other_court.is_active


def test_deactivate_and_reactivate_court(venue, owner, court):
    services.set_court_active(venue, owner, court.pk, active=False)
    court.refresh_from_db()
    assert not court.is_active
    services.set_court_active(venue, owner, court.pk, active=True)
    court.refresh_from_db()
    assert court.is_active


# ---------------------------------------------------------------- hours and prices


def test_set_opening_hours(venue, owner):
    services.set_opening_hours(
        venue,
        owner,
        [services.DayHours(d, d == 0, 600, 1500) for d in range(7)],
    )
    rows = {h.weekday: h for h in OpeningHours.objects.for_venue(venue)}
    assert rows[0].is_closed
    assert (rows[4].opens_minute, rows[4].closes_minute) == (600, 1500)


def test_hours_need_an_open_day_and_valid_windows(venue, owner):
    with pytest.raises(RuleViolation, match="at least one open day"):
        services.set_opening_hours(
            venue, owner, [services.DayHours(d, True, 360, 1440) for d in range(7)]
        )
    with pytest.raises(RuleViolation, match="after opening"):
        services.set_opening_hours(
            venue, owner, [services.DayHours(d, False, 900, 600) for d in range(7)]
        )
    with pytest.raises(ValueError, match="every weekday"):
        services.set_opening_hours(venue, owner, [services.DayHours(0, False, 360, 1440)])


def test_update_prices_replaces_peak_times(venue, owner, court):
    services.update_prices(
        venue, owner, court_prices={court.pk: (2000, 2500)}, peak_periods=[(5, 600, 1320)]
    )
    court.refresh_from_db()
    assert (court.off_peak_price_lkr, court.peak_price_lkr) == (2000, 2500)
    assert list(
        PeakPeriod.objects.for_venue(venue).values_list("weekday", "starts_minute", "ends_minute")
    ) == [(5, 600, 1320)]


def test_update_prices_rejects_bad_peak_times(venue, owner, court):
    with pytest.raises(RuleViolation):
        services.update_prices(venue, owner, court_prices={}, peak_periods=[(5, 900, 600)])
    assert PeakPeriod.objects.for_venue(venue).count() == 7  # unchanged


# ---------------------------------------------------------------- photos


def test_add_and_remove_photos(venue, owner):
    photo = services.add_photo(venue, owner, image_file())
    assert photo.image.name.startswith("venues/photos/")
    assert photo.image.storage.exists(photo.image.name)

    services.remove_photo(venue, owner, photo.pk)
    assert not VenuePhoto.objects.for_venue(venue).exists()
    assert not photo.image.storage.exists(photo.image.name)


def test_at_most_six_photos(venue, owner):
    for _ in range(services.MAX_PHOTOS):
        services.add_photo(venue, owner, image_file())
    with pytest.raises(RuleViolation, match="up to 6"):
        services.add_photo(venue, owner, image_file())


def test_photo_of_another_venue_cannot_be_removed(venue, owner, other_venue):
    other_owner = VenueMembership.objects.for_venue(other_venue).get().user
    other_photo = services.add_photo(other_venue, other_owner, image_file())
    with pytest.raises(VenuePhoto.DoesNotExist):
        services.remove_photo(venue, owner, other_photo.pk)
    assert VenuePhoto.objects.filter(pk=other_photo.pk).exists()


def test_logo_and_cover_replace_previous(venue, owner):
    services.set_logo(venue, owner, image_file(fmt="PNG", name="l.png"))
    first_logo = venue.logo.name
    services.set_logo(venue, owner, image_file(fmt="PNG", name="l.png"))
    assert venue.logo.name != first_logo
    assert not venue.logo.storage.exists(first_logo)
    services.set_cover_photo(venue, owner, image_file())
    first_cover = venue.cover_photo.name
    services.set_cover_photo(venue, owner, image_file())
    assert not venue.cover_photo.storage.exists(first_cover)


# ---------------------------------------------------------------- approval workflow


def admin_user():
    return UserFactory(is_staff=True)


def test_missing_items_listed_before_submission(venue, owner):
    missing = services.missing_for_submission(venue)
    assert len(missing) == 3  # address, location, court
    with pytest.raises(RuleViolation, match="Before submitting"):
        services.submit_for_approval(venue, owner)
    venue.refresh_from_db()
    assert venue.status == VenueStatus.DRAFT


def test_submit_then_approve_notifies_owner():
    venue = ready_venue()
    owner = VenueMembership.objects.for_venue(venue).get().user

    services.submit_for_approval(venue, owner)
    assert venue.status == VenueStatus.PENDING
    assert venue not in Venue.objects.public()
    with pytest.raises(RuleViolation, match="already been submitted"):
        services.submit_for_approval(venue, owner)

    admin = admin_user()
    services.approve_venue(venue, admin)

    venue.refresh_from_db()
    assert venue.status == VenueStatus.APPROVED
    assert venue.status_changed_by == admin
    assert venue in Venue.objects.public()
    sms = SmsMessage.objects.get(purpose="venue_status")
    assert sms.to_phone == owner.phone
    assert "approved" in sms.body


def test_reject_needs_reason_and_owner_can_resubmit():
    venue = ready_venue()
    owner = VenueMembership.objects.for_venue(venue).get().user
    services.submit_for_approval(venue, owner)
    admin = admin_user()

    with pytest.raises(RuleViolation, match="reason is required"):
        services.reject_venue(venue, admin, "   ")
    services.reject_venue(venue, admin, "Photos are not of a sports venue.")

    venue.refresh_from_db()
    assert venue.status == VenueStatus.REJECTED
    assert venue.status_reason == "Photos are not of a sports venue."
    assert "Photos are not of a sports venue." in SmsMessage.objects.get().body
    services.submit_for_approval(venue, owner)
    assert venue.status == VenueStatus.PENDING


def test_suspend_and_unsuspend():
    venue = ready_venue()
    owner = VenueMembership.objects.for_venue(venue).get().user
    admin = admin_user()
    services.submit_for_approval(venue, owner)
    services.approve_venue(venue, admin)

    services.suspend_venue(venue, admin, "Complaints from players.")
    assert venue.status == VenueStatus.SUSPENDED
    assert venue not in Venue.objects.public()

    services.unsuspend_venue(venue, admin)
    assert venue.status == VenueStatus.APPROVED
    assert SmsMessage.objects.filter(purpose="venue_status").count() == 3


@pytest.mark.parametrize(
    ("status", "action"),
    [
        ("draft", "approve"),
        ("approved", "approve"),
        ("draft", "reject"),
        ("pending", "suspend"),
        ("approved", "unsuspend"),
    ],
)
def test_invalid_transitions_refused(status, action):
    venue = ready_venue()
    Venue.objects.filter(pk=venue.pk).update(status=status)
    venue.refresh_from_db()
    admin = admin_user()
    call = {
        "approve": lambda: services.approve_venue(venue, admin),
        "reject": lambda: services.reject_venue(venue, admin, "x"),
        "suspend": lambda: services.suspend_venue(venue, admin, "x"),
        "unsuspend": lambda: services.unsuspend_venue(venue, admin),
    }[action]
    with pytest.raises(RuleViolation):
        call()
    assert SmsMessage.objects.count() == 0


def test_only_platform_admins_decide():
    venue = ready_venue()
    owner = VenueMembership.objects.for_venue(venue).get().user
    services.submit_for_approval(venue, owner)
    with pytest.raises(NotAllowed):
        services.approve_venue(venue, owner)
    with pytest.raises(NotAllowed):
        services.reject_venue(venue, UserFactory(), "x")


def test_reason_length_limited():
    venue = ready_venue()
    owner = VenueMembership.objects.for_venue(venue).get().user
    services.submit_for_approval(venue, owner)
    with pytest.raises(RuleViolation, match="255"):
        services.reject_venue(venue, admin_user(), "x" * 256)


def test_sms_goes_to_every_active_owner_only():
    venue = ready_venue()
    owner = VenueMembership.objects.for_venue(venue).get().user
    co_owner = UserFactory()
    VenueMembership.objects.create(venue=venue, user=co_owner, role=MemberRole.OWNER)
    staff = UserFactory()
    VenueMembership.objects.create(venue=venue, user=staff, role=MemberRole.STAFF)
    services.submit_for_approval(venue, owner)

    services.approve_venue(venue, admin_user())

    phones = set(SmsMessage.objects.values_list("to_phone", flat=True))
    assert phones == {owner.phone, co_owner.phone}


def test_make_venue_helper_works():
    assert make_venue(name="Helper").status == VenueStatus.DRAFT
