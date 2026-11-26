import pytest
from django.urls import reverse

from accounts.models import User
from bookings import services
from bookings.models import Source

from .conftest import at

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
    client.force_login(root)
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
