"""Sign-in, first-time profile, account page, sign-out and account deletion.

Views stay thin: parse the request, call a service, render. Screens: P4-P6, P18, P19.
"""

from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from core import turnstile
from core.exceptions import NotAllowed, RateLimited, RuleViolation
from core.phone import format_local
from core.ratelimit import client_ip

from . import services
from .decorators import profile_required
from .forms import CodeForm, NameForm, PhoneForm, ProfileForm
from .models import OTPChallenge

SESSION_PHONE = "auth_phone"
SESSION_NEXT = "auth_next"
AUTH_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _safe_next(request, value: str | None) -> str:
    """A local path to return to after sign-in, or "" (never an open redirect)."""
    if (
        value
        and value.startswith("/")
        and url_has_allowed_host_and_scheme(
            value, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        )
    ):
        return value
    return ""


def _wait_message(exc: RateLimited) -> str:
    minutes = exc.retry_after_minutes
    if isinstance(exc, services.NumberLocked):
        return ngettext(
            "Too many wrong codes. Try again in %(minutes)d minute.",
            "Too many wrong codes. Try again in %(minutes)d minutes.",
            minutes,
        ) % {"minutes": minutes}
    return ngettext(
        "Too many attempts. Please wait %(minutes)d minute and try again.",
        "Too many attempts. Please wait %(minutes)d minutes and try again.",
        minutes,
    ) % {"minutes": minutes}


def _code_error(form, exc) -> tuple[int, bool]:
    """Put a verification error on the form. Returns (HTTP status, offer a new code)."""
    if isinstance(exc, services.WrongCode):
        form.add_error(
            "code",
            ngettext(
                "Wrong code. %(count)d attempt left.",
                "Wrong code. %(count)d attempts left.",
                exc.remaining,
            )
            % {"count": exc.remaining},
        )
        return 200, False
    if isinstance(exc, RateLimited):
        form.add_error(None, _wait_message(exc))
        return 429, False
    form.add_error(None, exc.message)
    return 200, True


# ---------------------------------------------------------------- sign-in (P4, P5, P6)


@never_cache
@require_http_methods(["GET", "POST"])
def phone_view(request):
    next_url = _safe_next(request, request.POST.get("next") or request.GET.get("next"))
    if request.user.is_authenticated:
        return redirect(next_url or "home")

    form = PhoneForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        if not turnstile.verify(request.POST.get(turnstile.FIELD, ""), client_ip(request)):
            form.add_error(None, _("Please confirm you're not a robot, then try again."))
            context = {"form": form, "next": next_url, "turnstile_site_key": _site_key()}
            return render(request, "accounts/phone.html", context, status=400)
        try:
            services.request_code(
                phone=phone, purpose=OTPChallenge.Purpose.LOGIN, ip=client_ip(request)
            )
        except RateLimited as exc:
            form.add_error(None, _wait_message(exc))
            status = 429
        else:
            # Same reply whether or not the number has an account (architecture 5 A07).
            request.session[SESSION_PHONE] = phone
            request.session[SESSION_NEXT] = next_url
            return redirect("accounts:code")
    context = {"form": form, "next": next_url, "turnstile_site_key": _site_key()}
    return render(request, "accounts/phone.html", context, status=status)


def _site_key() -> str:
    return settings.TURNSTILE_SITE_KEY if turnstile.enabled() else ""


@never_cache
@require_http_methods(["GET", "POST"])
def code_view(request):
    phone = request.session.get(SESSION_PHONE)
    if not phone:
        return redirect("accounts:phone")

    form = CodeForm(request.POST or None)
    status, offer_new_code = 200, False
    if request.method == "POST" and form.is_valid():
        try:
            user, _created = services.sign_in_with_code(
                phone=phone, code=form.cleaned_data["code"], ip=client_ip(request)
            )
        except (services.OTPError, RateLimited) as exc:
            status, offer_new_code = _code_error(form, exc)
        except NotAllowed as exc:
            form.add_error(None, exc.message)
            status = 403
        else:
            next_url = request.session.get(SESSION_NEXT, "")
            login(request, user, backend=AUTH_BACKEND)  # rotates the session id
            request.session.pop(SESSION_PHONE, None)
            request.session.pop(SESSION_NEXT, None)
            if services.needs_profile(user):
                query = urlencode({"next": next_url}) if next_url else ""
                return redirect(reverse("accounts:welcome") + (f"?{query}" if query else ""))
            return redirect(next_url or "home")
    context = {"form": form, "phone_display": format_local(phone), "offer_new_code": offer_new_code}
    return render(request, "accounts/code.html", context, status=status)


@never_cache
@require_POST
def resend_view(request):
    phone = request.session.get(SESSION_PHONE)
    if not phone:
        return redirect("accounts:phone")
    try:
        services.request_code(
            phone=phone, purpose=OTPChallenge.Purpose.LOGIN, ip=client_ip(request)
        )
    except RateLimited as exc:
        messages.error(request, _wait_message(exc))
    else:
        messages.success(request, _("We sent you a new code."))
    return redirect("accounts:code")


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def welcome_view(request):
    next_url = _safe_next(request, request.POST.get("next") or request.GET.get("next"))
    if not services.needs_profile(request.user):
        return redirect(next_url or "home")

    form = ProfileForm(request.POST or None, initial={"name": request.user.name})
    if request.method == "POST" and form.is_valid():
        services.complete_profile(
            request.user, name=form.cleaned_data["name"], accepted=form.cleaned_data["accept"]
        )
        return redirect(next_url or "home")
    return render(request, "accounts/welcome.html", {"form": form, "next": next_url})


# ---------------------------------------------------------------- account (P18, P19)


@never_cache
@profile_required
@require_http_methods(["GET", "POST"])
def account_view(request):
    form = NameForm(request.POST or None, initial={"name": request.user.name})
    if request.method == "POST" and form.is_valid():
        services.update_name(request.user, form.cleaned_data["name"])
        messages.success(request, _("Your name has been updated."))
        return redirect("me:account")
    context = {"form": form, "phone_display": format_local(request.user.phone)}
    return render(request, "accounts/account.html", context)


@never_cache
@profile_required
@require_http_methods(["GET", "POST"])
def delete_view(request):
    """Explain what deletion does; POST sends the confirmation code (US-P08)."""
    status = 200
    blockers = services.deletion_blockers(request.user)
    if request.method == "POST" and not blockers:
        try:
            services.request_deletion_code(request.user, ip=client_ip(request))
        except RateLimited as exc:
            messages.error(request, _wait_message(exc))
            status = 429
        except RuleViolation as exc:  # a venue or team was taken on a moment ago
            messages.error(request, exc.message)
            status = 409
        else:
            return redirect("me:delete_confirm")
    elif blockers:
        status = 409 if request.method == "POST" else 200
    context = {
        "phone_display": format_local(request.user.phone),
        "blockers": blockers,
        "upcoming": services.upcoming_bookings_to_cancel(request.user),
    }
    return render(request, "accounts/delete.html", context, status=status)


@never_cache
@profile_required
@require_http_methods(["GET", "POST"])
def delete_confirm_view(request):
    form = CodeForm(request.POST or None)
    status, offer_new_code = 200, False
    if request.method == "POST" and form.is_valid():
        try:
            services.delete_account(
                request.user, code=form.cleaned_data["code"], ip=client_ip(request)
            )
        except (services.OTPError, RateLimited) as exc:
            status, offer_new_code = _code_error(form, exc)
        except (NotAllowed, RuleViolation) as exc:
            form.add_error(None, exc.message)
            status = 403
        else:
            logout(request)
            return redirect("accounts:deleted")
    context = {
        "form": form,
        "phone_display": format_local(request.user.phone),
        "offer_new_code": offer_new_code,
    }
    return render(request, "accounts/delete_confirm.html", context, status=status)


def deleted_view(request):
    return render(request, "accounts/deleted.html")
