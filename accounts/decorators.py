from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse

from . import services


def profile_required(view):
    """Signed in, and the first-time name and consent step is done (US-P01, NFR-07)."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if services.needs_profile(request.user):
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"{reverse('accounts:welcome')}?{query}")
        return view(request, *args, **kwargs)

    return wrapper
