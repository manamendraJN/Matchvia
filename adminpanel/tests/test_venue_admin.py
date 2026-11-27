"""Platform admin: review, approve, reject, suspend venues; area list (A1–A3, US-A01–A03)."""

import pytest
from django.urls import reverse

from accounts.models import User
from accounts.tests.factories import UserFactory
from adminpanel.testing import sign_in_admin
from notifications.models import SmsMessage
from venues import services
from venues.models import Venue, VenueStatus
from venues.tests.factories import make_venue, ready_venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    root = User.objects.create_superuser(
        phone="+94711234567", name="Founder", password="a-long-admin-password"
    )
    sign_in_admin(client, root)
    return client


@pytest.fixture
def pending_venue():
    venue = ready_venue(name="Pending Arena")
    services.submit_for_approval(venue, venue.memberships.get().user)
    return venue


def review_url(venue):
    return reverse("admin:venues_venue_review", args=[venue.pk])


def test_changelist_shows_review_links(admin_client, pending_venue):
    response = admin_client.get(
        reverse("admin:venues_venue_changelist"), {"status__exact": "pending"}
    )
    assert response.status_code == 200
    assert b"Pending Arena" in response.content
    assert review_url(pending_venue).encode() in response.content


def test_review_page_shows_details(admin_client, pending_venue):
    response = admin_client.get(review_url(pending_venue))
    assert response.status_code == 200
    assert b"12 Main Street, Malabe" in response.content
    assert b"Court 1" in response.content


def test_approve_from_review_page(admin_client, pending_venue):
    response = admin_client.post(review_url(pending_venue), {"decision": "approve"})
    assert response.status_code == 302
    pending_venue.refresh_from_db()
    assert pending_venue.status == VenueStatus.APPROVED
    assert pending_venue in Venue.objects.public()
    assert SmsMessage.objects.filter(purpose="venue_status").count() == 1


def test_reject_needs_reason(admin_client, pending_venue):
    response = admin_client.post(review_url(pending_venue), {"decision": "reject", "reason": ""})
    assert response.status_code == 200
    assert b"A reason is required" in response.content
    pending_venue.refresh_from_db()
    assert pending_venue.status == VenueStatus.PENDING

    admin_client.post(review_url(pending_venue), {"decision": "reject", "reason": "No photos"})
    pending_venue.refresh_from_db()
    assert pending_venue.status == VenueStatus.REJECTED
    assert pending_venue.status_reason == "No photos"


def test_invalid_transition_shows_error(admin_client):
    draft = make_venue(name="Draft Arena")
    response = admin_client.post(review_url(draft), {"decision": "approve"})
    assert response.status_code == 200
    assert b"Only venues waiting for approval can be approved." in response.content


def test_suspend_and_unsuspend_from_review_page(admin_client, pending_venue):
    admin_client.post(review_url(pending_venue), {"decision": "approve"})
    admin_client.post(review_url(pending_venue), {"decision": "suspend", "reason": "Complaints"})
    pending_venue.refresh_from_db()
    assert pending_venue.status == VenueStatus.SUSPENDED
    admin_client.post(review_url(pending_venue), {"decision": "unsuspend"})
    pending_venue.refresh_from_db()
    assert pending_venue.status == VenueStatus.APPROVED


def test_status_cannot_be_edited_directly(admin_client, pending_venue):
    response = admin_client.get(reverse("admin:venues_venue_change", args=[pending_venue.pk]))
    assert response.status_code == 200
    assert b'name="status"' not in response.content


def test_venues_cannot_be_deleted(admin_client, pending_venue):
    response = admin_client.get(reverse("admin:venues_venue_delete", args=[pending_venue.pk]))
    assert response.status_code == 403


def test_area_admin(admin_client):
    response = admin_client.get(reverse("admin:venues_area_changelist"))
    assert response.status_code == 200
    assert b"Malabe" in response.content
    admin_client.post(
        reverse("admin:venues_area_add"),
        {"name": "Kandy", "slug": "kandy", "is_active": "on", "position": "9"},
    )
    from venues.models import Area

    assert Area.objects.filter(slug="kandy").exists()


def test_players_and_venue_owners_cannot_review(client, pending_venue):
    client.force_login(pending_venue.memberships.get().user)
    response = client.get(review_url(pending_venue))
    assert response.status_code == 302
    assert "login" in response.url


def test_staff_without_change_permission_is_sent_away(client, pending_venue):
    limited = UserFactory(is_staff=True)  # admin site access but no venue permissions
    client.force_login(limited)
    response = client.get(review_url(pending_venue))
    assert response.status_code == 302
    pending_venue.refresh_from_db()
    assert pending_venue.status == VenueStatus.PENDING
