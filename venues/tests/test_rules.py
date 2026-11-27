"""Booking rules as plain questions (V20, US-O05)."""

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from core.exceptions import NotAllowed, RuleViolation
from venues import services
from venues.models import VenueSettings
from venues.rules import RULES

pytestmark = pytest.mark.django_db


def url(venue):
    return reverse("manage:rules", args=[venue.pk])


def test_every_rule_is_a_question_with_the_current_answer(client, owner, venue):
    client.force_login(owner)
    html = client.get(url(venue)).content.decode()
    for rule in RULES:
        assert str(rule.question) in html
    assert "How far ahead can players book online?" in html
    assert '<option value="14" selected>14 days ahead</option>' in html
    assert '<option value="True" selected>On</option>' in html  # SMS for phone bookings


def test_saving_one_rule(client, owner, venue):
    client.force_login(owner)
    response = client.post(url(venue), {"rule": "cancellation_window_hours", "value": "24"})
    assert response.status_code == 302
    assert response.url.endswith("#rule-cancellation_window_hours")
    page = client.get(response.url.split("#")[0]).content.decode()
    assert "Saved. Applies to new bookings." in page
    assert VenueSettings.objects.get(venue=venue).cancellation_window_hours == 24

    client.post(url(venue), {"rule": "sms_on_walk_ins", "value": "True"})
    client.post(url(venue), {"rule": "recurring_approver", "value": "owner"})
    s = VenueSettings.objects.get(venue=venue)
    assert s.sms_on_walk_ins is True
    assert s.recurring_approver == "owner"


@pytest.mark.parametrize(
    ("rule", "value"),
    [("booking_horizon_days", "61"), ("reminder_lead_hours", "0"), ("sms_on_walk_ins", "maybe")],
)
def test_only_allowed_answers(client, owner, venue, rule, value):
    client.force_login(owner)
    before = VenueSettings.objects.get(venue=venue).updated_at
    response = client.post(url(venue), {"rule": rule, "value": value}, follow=True)
    assert "Choose one of the answers." in response.content.decode()
    assert VenueSettings.objects.get(venue=venue).updated_at == before


def test_unknown_rule_is_ignored(client, owner, venue):
    client.force_login(owner)
    assert client.post(url(venue), {"rule": "is_superuser", "value": "1"}).status_code == 302
    with pytest.raises(ValueError, match="Unknown rule"):
        services.update_rule(venue, owner, "status", "approved")


def test_lowering_max_weeks_lowers_the_default(owner, venue):
    services.update_rule(venue, owner, "recurring_max_weeks", 4)
    s = VenueSettings.objects.get(venue=venue)
    assert (s.recurring_max_weeks, s.recurring_default_weeks) == (4, 4)


def test_staff_cannot_reach_rules(client, venue, staff):
    client.force_login(staff)
    assert client.get(url(venue)).status_code == 404
    with pytest.raises(NotAllowed):
        services.update_rule(venue, staff, "booking_horizon_days", 7)
    with pytest.raises(RuleViolation):
        services.update_rule(
            venue, venue.memberships.get(role="owner").user, "max_slots_per_booking", 9
        )


def test_the_database_refuses_out_of_range_values(venue):
    with pytest.raises(IntegrityError), transaction.atomic():
        VenueSettings.objects.filter(venue=venue).update(cancellation_window_hours=100)


def test_every_answer_is_inside_the_database_range(owner, venue):
    """All listed answers save, so no answer the page offers can be refused by the database."""
    for rule in RULES:
        for value, _label in rule.choices:
            services.update_rule(venue, owner, rule.field, value)
