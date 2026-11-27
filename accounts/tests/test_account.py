"""Account page (P18), roles, and the admin (US-A04)."""

import pytest
from django.conf import settings
from django.urls import reverse

from accounts import services
from accounts.models import Role, User
from adminpanel.testing import sign_in_admin
from core.exceptions import NotAllowed, RuleViolation

from .factories import UserFactory

pytestmark = pytest.mark.django_db

ACCOUNT_URL = reverse("me:account")


# ---------------------------------------------------------------- account page


def test_account_page_requires_sign_in(client):
    response = client.get(ACCOUNT_URL)
    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:phone')}?next=/me/account/"


def test_account_page_sends_unfinished_profiles_to_welcome(client):
    client.force_login(UserFactory(name="", consented=False))
    response = client.get(ACCOUNT_URL)
    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:welcome')}?next=%2Fme%2Faccount%2F"


def test_account_page_shows_name_and_number(client, user):
    client.force_login(user)
    response = client.get(ACCOUNT_URL)

    assert response.status_code == 200
    assert b"077 123 4567" in response.content
    assert b"Kasun Perera" in response.content
    assert b"Delete my account" in response.content
    assert "no-cache" in response["Cache-Control"]  # personal page: never cached


def test_change_name(client, user):
    client.force_login(user)
    response = client.post(ACCOUNT_URL, {"name": "Kasun P."}, follow=True)

    assert b"Your name has been updated." in response.content
    user.refresh_from_db()
    assert user.name == "Kasun P."


def test_change_name_rejects_blank(client, user):
    client.force_login(user)
    response = client.post(ACCOUNT_URL, {"name": "   "})
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.name == "Kasun Perera"


def test_name_is_escaped_in_html(client):
    user = UserFactory(name="<script>alert(1)</script>")
    client.force_login(user)
    response = client.get(ACCOUNT_URL)
    assert b"<script>alert(1)</script>" not in response.content
    assert b"&lt;script&gt;" in response.content


def test_header_links(client, user):
    assert b"Sign in" in client.get(reverse("home")).content
    client.force_login(user)
    assert b'href="/me/account/"' in client.get(reverse("home")).content


@pytest.mark.parametrize("name", ["privacy", "terms"])
def test_privacy_and_terms_pages_show_version(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 200
    assert services.PRIVACY_VERSION.encode() in response.content
    assert b"DRAFT for legal review" in response.content


# ---------------------------------------------------------------- roles


def test_every_new_account_is_a_player_only():
    user = User.objects.create_user(phone="+94771234567")
    assert services.platform_roles(user) == {Role.PLAYER}


def test_platform_admin_role_comes_from_is_staff():
    user = UserFactory(is_staff=True)
    assert services.platform_roles(user) == {Role.PLAYER, Role.ADMIN}


def test_venue_roles_are_not_account_roles():
    """Owner/staff are per-venue VenueMembership rows (data-model 3.1), added in S04."""
    user = UserFactory(is_staff=True)
    roles = services.platform_roles(user)
    assert Role.VENUE_OWNER not in roles
    assert Role.VENUE_STAFF not in roles
    assert {r.value for r in Role} == {"player", "venue_owner", "venue_staff", "admin"}


def test_no_roles_for_anonymous_inactive_or_deleted(user):
    from django.contrib.auth.models import AnonymousUser
    from django.utils import timezone

    assert services.platform_roles(AnonymousUser()) == frozenset()
    inactive = UserFactory(is_active=False)
    assert services.platform_roles(inactive) == frozenset()
    deleted = User(phone=None, is_active=True, deleted_at=timezone.now())
    deleted.is_authenticated  # noqa: B018  (always True on a User)
    assert services.platform_roles(deleted) == frozenset()


def test_superuser_can_grant_and_remove_platform_admin(user):
    root = User.objects.create_superuser(
        phone="+94711234567", name="Founder", password="a-long-admin-password"
    )

    services.set_platform_admin(user, is_admin=True, actor=root)
    assert Role.ADMIN in services.platform_roles(user)

    services.set_platform_admin(user, is_admin=False, actor=root)
    assert services.platform_roles(user) == {Role.PLAYER}


def test_only_superusers_can_grant_platform_admin(user):
    staff = UserFactory(is_staff=True)
    with pytest.raises(NotAllowed):
        services.set_platform_admin(user, is_admin=True, actor=staff)
    user.refresh_from_db()
    assert not user.is_staff


def test_deleted_user_cannot_become_admin():
    from django.utils import timezone

    root = User.objects.create_superuser(
        phone="+94711234567", name="Founder", password="a-long-admin-password"
    )
    deleted = User.objects.create(phone=None, deleted_at=timezone.now(), is_active=False)
    with pytest.raises(RuleViolation):
        services.set_platform_admin(deleted, is_admin=True, actor=root)


# ---------------------------------------------------------------- admin


@pytest.fixture
def admin_client(client):
    root = User.objects.create_superuser(
        phone="+94711234567", name="Founder", password="a-long-admin-password"
    )
    sign_in_admin(client, root)
    return client


def test_admin_lists_and_searches_users_by_phone(admin_client, user):
    url = reverse("admin:accounts_user_changelist")
    assert url.startswith("/" + settings.ADMIN_URL_PATH)
    response = admin_client.get(url, {"q": "+94771234567"})
    assert response.status_code == 200
    assert b"Kasun Perera" in response.content


def test_admin_change_and_add_pages_render(admin_client, user):
    assert (
        admin_client.get(reverse("admin:accounts_user_change", args=[user.pk])).status_code == 200
    )
    assert admin_client.get(reverse("admin:accounts_user_add")).status_code == 200


def test_admin_add_user_normalises_phone(admin_client):
    response = admin_client.post(
        reverse("admin:accounts_user_add"),
        {"phone": "071 555 1234", "name": "Nimal", "usable_password": "false"},
    )
    assert response.status_code == 302
    user = User.objects.get(phone="+94715551234")
    assert not user.has_usable_password()


def test_admin_add_user_rejects_bad_phone(admin_client):
    response = admin_client.post(
        reverse("admin:accounts_user_add"),
        {"phone": "0112345678", "name": "X", "usable_password": "false"},
    )
    assert response.status_code == 200
    assert b"Enter a valid Sri Lankan mobile number" in response.content


def test_admin_cannot_hard_delete_users(admin_client, user):
    response = admin_client.get(reverse("admin:accounts_user_delete", args=[user.pk]))
    assert response.status_code == 403


def test_admin_sms_outbox_is_read_only(admin_client):
    url = reverse("admin:notifications_smsmessage_changelist")
    assert admin_client.get(url).status_code == 200
    assert admin_client.get(reverse("admin:notifications_smsmessage_add")).status_code == 403


def test_players_cannot_open_the_admin(client, user):
    client.force_login(user)
    response = client.get(reverse("admin:index"))
    assert response.status_code == 302
    assert "login" in response.url


# ---------------------------------------------------------------- name rules


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  Kasun   Perera ", "Kasun Perera"), ("Nimal", "Nimal"), ("ශනිල්", "ශනිල්")],
)
def test_clean_name_tidies_spaces_and_keeps_sinhala(raw, expected):
    assert services.clean_name(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", None, "x" * 81, "Kasun\x07", "Kasun\u009b"])
def test_clean_name_rejects_empty_long_and_control_characters(bad):
    with pytest.raises(RuleViolation):
        services.clean_name(bad)


def test_control_characters_rejected_through_the_form(client, user):
    client.force_login(user)
    response = client.post(ACCOUNT_URL, {"name": "Kasun\x07"})
    assert b"Use letters, numbers and spaces only." in response.content
    user.refresh_from_db()
    assert user.name == "Kasun Perera"
