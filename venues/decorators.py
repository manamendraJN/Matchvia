"""The only way venue-side views get a venue (CLAUDE.md "Code conventions", data-model 6.2).

Each decorator signs the user in (and through the first-time profile), then resolves the venue
from the URL with ``get_venue_for_user()``: anyone who is not a member gets 404. The view receives
the venue object, never the raw id.
"""

from functools import wraps

from django.views.decorators.cache import never_cache

from accounts.decorators import profile_required

from .services import MEMBERS, OWNER, get_venue_for_user

SAFE_METHODS = {"GET", "HEAD"}


def _venue_view(read_roles, write_roles):
    def decorator(view):
        @never_cache
        @profile_required
        @wraps(view)
        def wrapper(request, venue_id, *args, **kwargs):
            roles = read_roles if request.method in SAFE_METHODS else write_roles
            venue = get_venue_for_user(request.user, venue_id, roles)
            return view(request, venue, *args, **kwargs)

        return wrapper

    return decorator


# Owner and staff can look; only owners can change (US-O06: staff can't change courts,
# prices, hours, settings or staff).
members_view_owner_edit = _venue_view(MEMBERS, OWNER)
# Owner-only pages and actions: staff get 404 for every method.
owner_only = _venue_view(OWNER, OWNER)
# Pages and actions open to owner and staff alike (the calendar in C6).
members_only = _venue_view(MEMBERS, MEMBERS)
