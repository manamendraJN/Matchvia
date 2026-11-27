import pytest
from django.urls import reverse

from accounts import services as accounts
from accounts.models import User
from accounts.tests.factories import UserFactory
from adminpanel import services as admin_services
from adminpanel.models import AdminAccessLog
from adminpanel.testing import sign_in_admin
from bookings import services
from bookings.models import Source
from core.exceptions import NotAllowed, RuleViolation
from notifications.models import SmsMessage

from .conftest import at
from .test_account_deletion import phone_is_gone

pytestmark = pytest.mark.django_db


def test_admin_finds_a_booking_by_reference_in_any_format(client, venue, court, clock):
    booking = services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=at(2026, 12, 8, 18, 0),
        end_at=at(2026, 12, 8, 19, 0),
        source=Source.WALK_IN,
        customer_name="Kasun",
    )
    root = User.objects.create_superuser(
        phone="+94711234567", name="Founder", password="a-long-admin-password"
    )
    sign_in_admin(client, root)
    url = reverse("admin:bookings_booking_changelist")
    for typed in (f"MV-{booking.reference}", booking.reference.lower()):
        response = client.get(url, {"q": typed})
        assert booking.reference.encode() in response.content
    detail = client.get(reverse("admin:bookings_booking_change", args=[booking.pk]))
    assert detail.status_code == 200
    assert b"created" in detail.content
    assert client.get(reverse("admin:bookings_booking_add")).status_code == 403
    assert client.get(url, {"q": "Kasun"}).status_code == 200
    assert client.get(reverse("admin:venues_venuecustomer_changelist")).status_code == 200


# ---------------------------------------------------------------- phone lookup, access log (C9)


@pytest.fixture
def root_client(client, clock):  # sign in at the frozen "now"
    root = User.objects.create_superuser(
        phone="+94711234567", name="Founder", password="a-long-admin-password"
    )
    sign_in_admin(client, root)
    client.root = root
    return client


@pytest.fixture
def phone_booking(venue, court, clock):
    return services.create_staff_booking(
        venue=venue,
        actor=venue.owner,
        court_id=court.pk,
        start_at=at(2026, 12, 8, 18, 0),
        end_at=at(2026, 12, 8, 19, 0),
        source=Source.PHONE,
        customer_name="Ruwan",
        customer_phone="+94775550001",
    )


def test_admin_finds_bookings_by_phone_in_any_format(root_client, phone_booking):
    url = reverse("admin:bookings_booking_changelist")
    for typed in ("077 555 0001", "+94775550001", "775550001"):
        response = root_client.get(url, {"q": typed})
        assert phone_booking.reference.encode() in response.content
    response = root_client.get(url, {"q": "077 555 0002"})
    assert phone_booking.reference.encode() not in response.content


def test_opening_and_searching_bookings_is_logged(root_client, phone_booking):
    from adminpanel.models import AdminAccessLog

    root_client.get(reverse("admin:bookings_booking_changelist"), {"q": "077 555 0001"})
    root_client.get(reverse("admin:bookings_booking_change", args=[phone_booking.pk]))
    customer = phone_booking.venue_customer
    root_client.get(reverse("admin:venues_venuecustomer_change", args=[customer.pk]))
    root_client.get(reverse("admin:venues_venuecustomer_changelist"))

    entries = list(AdminAccessLog.objects.order_by("id"))
    assert [(e.action, e.object_type, e.object_id) for e in entries] == [
        ("search", "booking", None),
        ("view", "booking", phone_booking.pk),
        ("view", "venue_customer", customer.pk),
        ("view", "venue_customer", None),
    ]
    assert all(e.admin == root_client.root for e in entries)
    # The phone number searched for is stored masked.
    assert entries[0].detail == "+9477****001"


def test_plain_booking_list_is_not_logged_but_a_missing_booking_is_not_either(
    root_client, phone_booking
):
    from adminpanel.models import AdminAccessLog

    root_client.get(reverse("admin:bookings_booking_changelist"))
    root_client.get(reverse("admin:bookings_booking_change", args=[999999]))
    assert not AdminAccessLog.objects.exists()


def test_user_and_sms_screens_are_logged(root_client, phone_booking):
    from adminpanel.models import AdminAccessLog

    root_client.get(reverse("admin:accounts_user_changelist"), {"q": "071 123 4567"})
    root_client.get(reverse("admin:accounts_user_change", args=[root_client.root.pk]))
    root_client.get(reverse("admin:notifications_smsmessage_changelist"))
    assert list(AdminAccessLog.objects.order_by("id").values_list("action", "object_type")) == [
        ("search", "user"),
        ("view", "user"),
        ("view", "sms"),
    ]


# ---------------------------------------------------------------- PDPA deletion on request (C9)


def test_admin_carries_out_a_deletion_request(root_client, venue, court, player):
    services.create_online_booking(user=player, court_id=court.pk, start_at=at(2026, 12, 10, 18, 0))
    phone = player.phone
    change = root_client.get(reverse("admin:accounts_user_change", args=[player.pk]))
    assert "Delete account (PDPA request)" in change.content.decode()
    url = reverse("admin:accounts_user_delete_account", args=[player.pk])
    page = root_client.get(url)
    assert page.status_code == 200
    assert "1 upcoming booking is cancelled" in page.content.decode()

    missing = root_client.post(url, {"reason": "", "confirm": "on"})
    assert missing.status_code == 200
    player.refresh_from_db()
    assert player.phone == phone

    response = root_client.post(url, {"reason": "Email of 9 Dec", "confirm": "on"})

    assert response.status_code == 302
    player.refresh_from_db()
    assert player.is_deleted
    assert phone_is_gone(phone)
    entry = AdminAccessLog.objects.get(action="delete_account")
    assert (entry.admin, entry.object_id, entry.detail) == (
        root_client.root,
        player.pk,
        "Email of 9 Dec",
    )
    assert SmsMessage.objects.filter(purpose="venue_notice").count() == 1
    assert root_client.get(url).status_code == 404  # already deleted


def test_admin_deletion_respects_the_hand_over_rule(root_client, venue):
    url = reverse("admin:accounts_user_delete_account", args=[venue.owner.pk])
    page = root_client.get(url)
    assert "You own Arena A" in page.content.decode()
    root_client.post(url, {"reason": "Phone call", "confirm": "on"})
    venue.owner.refresh_from_db()
    assert not venue.owner.is_deleted
    assert not AdminAccessLog.objects.filter(action="delete_account").exists()


def test_admin_cannot_delete_their_own_account_here(root_client):
    root = root_client.root
    url = reverse("admin:accounts_user_delete_account", args=[root.pk])
    response = root_client.post(url, {"reason": "Testing", "confirm": "on"})
    assert "Delete your own account from your account page." in response.content.decode()
    root.refresh_from_db()
    assert not root.is_deleted


def test_only_platform_admins_can_delete_on_request(player):
    with pytest.raises(NotAllowed):
        accounts.delete_account_on_request(player, admin=UserFactory())
    root = UserFactory(is_superuser=True)
    with pytest.raises(RuleViolation, match="how the request came in"):
        admin_services.delete_account_on_request(admin=root, user=player, reason="  ")


def test_admin_without_user_permissions_cannot_delete(client, player, clock):
    limited = UserFactory(is_staff=True)  # platform admin with no permissions on users
    sign_in_admin(client, limited)
    url = reverse("admin:accounts_user_delete_account", args=[player.pk])
    assert client.post(url, {"reason": "Email", "confirm": "on"}).status_code == 302
    player.refresh_from_db()
    assert not player.is_deleted
