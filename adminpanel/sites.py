"""The Matchvia admin site: superusers only, two-step sign-in, 8-hour sessions (C9, D9).

Replaces Django's default admin site (see adminpanel.apps.MatchviaAdminConfig), so every
``@admin.register`` in the project lands here. Business rules live in adminpanel.services.
"""

from django.contrib import admin
from django.contrib.auth import login
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from accounts import services as accounts
from core.exceptions import RateLimited
from core.ratelimit import client_ip

from . import services
from .forms import AdminCodeForm, AdminLoginForm

SESSION_VERIFIED = "admin_verified"  # {"user": id, "at": unix time} after both steps
SESSION_PENDING = "admin_pending"  # {"user": id, "at": unix time, "next": path} after step 1
AUTH_BACKEND = "django.contrib.auth.backends.ModelBackend"


def is_verified(request) -> bool:
    """True when this session finished both sign-in steps for this user, under 8 hours ago."""
    data = request.session.get(SESSION_VERIFIED)
    if not isinstance(data, dict) or data.get("user") != request.user.pk:
        return False
    age = timezone.now().timestamp() - float(data.get("at") or 0)
    return 0 <= age < services.ADMIN_SESSION.total_seconds()


def mark_verified(request, user) -> None:
    request.session[SESSION_VERIFIED] = {"user": user.pk, "at": timezone.now().timestamp()}
    request.session.set_expiry(int(services.ADMIN_SESSION.total_seconds()))


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
        return bool(user.is_active and user.is_superuser and is_verified(request))

    def get_urls(self):
        return [
            path("login/code/", self.login_code, name="login_code"),
            *super().get_urls(),
        ]

    def _next(self, request, value) -> str:
        if value and url_has_allowed_host_and_scheme(
            value, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return value
        return reverse("admin:index", current_app=self.name)

    def _render(self, request, template, context, status=200):
        context = {**self.each_context(request), **context}
        request.current_app = self.name
        return TemplateResponse(request, template, context, status=status)

    @method_decorator(sensitive_post_parameters("password"))
    @method_decorator(never_cache)
    def login(self, request, extra_context=None):
        """Step 1: mobile number and password. A correct pair for a superuser sends a code."""
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
                request.session[SESSION_PENDING] = {
                    "user": user.pk,
                    "at": timezone.now().timestamp(),
                    "next": self._next(request, request.POST.get("next")),
                }
                return redirect(reverse("admin:login_code", current_app=self.name))
        context = {
            "title": _("Sign in"),
            "form": form,
            "next": request.POST.get("next") or request.GET.get("next", ""),
        }
        return self._render(request, "adminpanel/login.html", context, status)

    @method_decorator(never_cache)
    def login_code(self, request):
        """Step 2: the code sent by SMS. Success signs in for 8 hours."""
        pending = request.session.get(SESSION_PENDING) or {}
        user = services.pending_admin(pending.get("user"), pending.get("at"))
        if user is None:
            request.session.pop(SESSION_PENDING, None)
            return redirect(reverse("admin:login", current_app=self.name))
        form = AdminCodeForm(request.POST or None)
        status = 200
        if request.method == "POST" and form.is_valid():
            try:
                services.check_code(user, code=form.cleaned_data["code"], ip=client_ip(request))
            except accounts.WrongCode as exc:
                form.add_error(
                    "code",
                    ngettext(
                        "Wrong code. %(count)d attempt left.",
                        "Wrong code. %(count)d attempts left.",
                        exc.remaining,
                    )
                    % {"count": exc.remaining},
                )
            except RateLimited as exc:
                form.add_error(None, _wait_message(exc))
                status = 429
            except accounts.OTPError as exc:
                form.add_error(None, exc.message)
            else:
                login(request, user, backend=AUTH_BACKEND)  # new session key
                request.session.pop(SESSION_PENDING, None)
                mark_verified(request, user)
                return redirect(self._next(request, pending.get("next")))
        context = {"title": _("Enter the code"), "form": form}
        return self._render(request, "adminpanel/login_code.html", context, status)

    def index(self, request, extra_context=None):
        return super().index(request, {**services.home(), **(extra_context or {})})
