"""Admin home counts (A1) and the read-only access log (A5)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from adminpanel import services
from adminpanel.models import AccessAction, AdminAccessLog
from adminpanel.testing import sign_in_admin
from venues import services as venue_services
from venues.models import Venue
from venues.tests.factories import ready_venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def root(db):
    return User.objects.create_superuser(
        phone="+94711234567", name="Founder", password="a-long-admin-password"
    )


@pytest.fixture
def admin_client(client, root):
    sign_in_admin(client, root)
    return client


def test_admin_home_shows_counts_and_waiting_venues_oldest_first(admin_client):
    older = ready_venue(name="Older Arena")
    newer = ready_venue(name="Newer Arena")
    for venue in (older, newer):
        venue_services.submit_for_approval(venue, venue.memberships.get().user)
    Venue.objects.filter(pk=older.pk).update(status_changed_at=timezone.now() - timedelta(days=2))
    live = ready_venue(name="Live Arena")
    Venue.objects.filter(pk=live.pk).update(status="approved")

    response = admin_client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert response.context["pending_count"] == 2
    assert response.context["live_count"] == 1
    assert response.context["suspended_count"] == 0
    assert response.context["bookings_today"] == 0
    html = response.content.decode()
    assert html.index("Older Arena") < html.index("Newer Arena")
    assert "Live Arena" not in html
    owner = older.memberships.get().user
    assert owner.name in html


def test_admin_home_with_nothing_waiting(admin_client):
    assert "No venues waiting." in admin_client.get(reverse("admin:index")).content.decode()


def test_venue_review_page_is_logged(admin_client, root):
    venue = ready_venue(name="Pending Arena")
    venue_services.submit_for_approval(venue, venue.memberships.get().user)
    admin_client.get(reverse("admin:venues_venue_review", args=[venue.pk]))
    entry = AdminAccessLog.objects.get()
    assert (entry.admin, entry.action, entry.object_type, entry.object_id) == (
        root,
        "view",
        "venue",
        venue.pk,
    )


def test_access_log_is_read_only_and_filterable(admin_client, root):
    entry = services.log_access(root, AccessAction.VIEW, "booking", 42)
    url = reverse("admin:adminpanel_adminaccesslog_changelist")

    response = admin_client.get(url, {"admin__id__exact": root.pk})

    assert response.status_code == 200
    assert "booking" in response.content.decode()
    assert admin_client.get(reverse("admin:adminpanel_adminaccesslog_add")).status_code == 403
    change_url = reverse("admin:adminpanel_adminaccesslog_change", args=[entry.pk])
    assert admin_client.post(change_url, {"detail": "edited"}).status_code == 403
    delete_url = reverse("admin:adminpanel_adminaccesslog_delete", args=[entry.pk])
    assert admin_client.post(delete_url, {"post": "yes"}).status_code == 403
    entry.refresh_from_db()
    assert entry.detail == ""
    # Looking at the log is not itself logged.
    assert AdminAccessLog.objects.count() == 1


def test_access_log_hidden_from_everyone_else(client, root):
    client.force_login(root)  # no code step
    response = client.get(reverse("admin:adminpanel_adminaccesslog_changelist"))
    assert response.status_code == 302


def test_log_access_tidies_input(root):
    entry = services.log_access(root, AccessAction.VIEW, "booking", "abc", detail="x" * 300)
    assert entry.object_id is None
    assert len(entry.detail) == 255
    assert services.masked_term("  077  123 4567 ") != "+94771234567"
    assert services.masked_term("Kasun   Perera") == "Kasun Perera"
    assert str(entry) == "Viewed booking #None"
