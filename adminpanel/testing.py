"""Test helper: an admin session that has passed both sign-in steps."""

from django.utils import timezone

from .sites import SESSION_VERIFIED


def sign_in_admin(client, user) -> None:
    client.force_login(user)
    session = client.session
    session[SESSION_VERIFIED] = {"user": user.pk, "at": timezone.now().timestamp()}
    session.save()
