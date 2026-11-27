"""The Matchvia admin site: platform admins sign in with number + password (D9, D16).

Replaces Django's default admin site (see adminpanel.admin_site_config), so every
``@admin.register`` in the project lands here. Business rules live in adminpanel.services.

Admin access needs a password sign-in on this site within the last 8 hours (D9). Being signed
in to the player site with an SMS code is not enough, and the admin's 8 hours never shorten
the normal 30-day site session.
"""

from django.contrib import admin
from django.contrib.auth import login
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from core.exceptions import RateLimited
from core.ratelimit import client_ip

from . import services
from .forms import AdminLoginForm

SESSION_VERIFIED = "admin_verified"  # {"user": id, "at": unix time} after a password sign-in
AUTH_BACKEND = "django.contrib.auth.backends.ModelBackend"


def is_verified(request) -> bool:
    """True when this session signed in to the admin with a password, under 8 hours ago."""
    data = request.session.get(SESSION_VERIFIED)
    if not isinstance(data, dict) or data.get("user") != request.user.pk:
        return False
    age = timezone.now().timestamp() - float(data.get("at") or 0)
    return 0 <= age < services.ADMIN_SESSION.total_seconds()


def mark_verified(request, user) -> None:
    request.session[SESSION_VERIFIED] = {"user": user.pk, "at": timezone.now().timestamp()}


def _wait_message(exc: RateLimited) -> str:
    minutes = exc.retry_after_minutes
    return ngettext(
        "Too many attempts. Try again in %(minutes)d minute.",
        "Too many attempts. Try again in %(minutes)d minutes.",
        minutes,
    ) % {"minutes": minutes}


class MatchviaAdminSite(admin.AdminSite):
    site_header = gettext_lazy("Matchvia admin")
    site_title = gettext_lazy("Matchvia admin")
    index_title = gettext_lazy("Platform admin")
    index_template = "adminpanel/index.html"

    def has_permission(self, request):
        user = request.user
        return bool(user.is_active and user.is_staff and is_verified(request))

    def _next(self, request, value) -> str:
        if value and url_has_allowed_host_and_scheme(
            value, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return value
        return reverse("admin:index", current_app=self.name)

    @method_decorator(sensitive_post_parameters("password"))
    @method_decorator(never_cache)
    def login(self, request, extra_context=None):
        """Mobile number and password. Rate limited (CLAUDE.md rule 4)."""
        if request.method == "GET" and self.has_permission(request):
            return redirect(reverse("admin:index", current_app=self.name))
        form = AdminLoginForm(request.POST or None)
        status = 200
        if request.method == "POST" and form.is_valid():
            try:
                user = services.check_password(
                    phone=form.cleaned_data["phone"],
                    password=form.cleaned_data["password"],
                    ip=client_ip(request),
                )
            except RateLimited as exc:
                form.add_error(None, _wait_message(exc))
                status = 429
            except services.BadCredentials as exc:
                form.add_error(None, exc.message)
            else:
                login(request, user, backend=AUTH_BACKEND)  # new session key
                mark_verified(request, user)
                return redirect(self._next(request, request.POST.get("next")))
        context = {
            **self.each_context(request),
            "title": _("Sign in"),
            "form": form,
            "next": request.POST.get("next") or request.GET.get("next", ""),
        }
        request.current_app = self.name
        return TemplateResponse(request, "adminpanel/login.html", context, status=status)

    def index(self, request, extra_context=None):
        return super().index(request, {**services.home(), **(extra_context or {})})
