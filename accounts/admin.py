from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from adminpanel import services as admin_services
from adminpanel.forms import AccountDeletionForm
from adminpanel.mixins import AccessLoggedMixin
from core.exceptions import DomainError
from core.phone import INVALID_PHONE_MESSAGE, InvalidPhone, normalise_phone

from . import services
from .models import ConsentRecord, User


class _PhoneCleanMixin:
    def clean_phone(self):
        value = self.cleaned_data.get("phone")
        if not value:
            return None
        try:
            return normalise_phone(value)
        except InvalidPhone:
            raise forms.ValidationError(INVALID_PHONE_MESSAGE) from None


class UserCreationAdminForm(_PhoneCleanMixin, AdminUserCreationForm):
    class Meta:
        model = User
        fields = ("phone", "name")


class UserChangeAdminForm(_PhoneCleanMixin, UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class ConsentInline(admin.TabularInline):
    model = ConsentRecord
    extra = 0
    can_delete = False
    readonly_fields = ["document", "version", "accepted_at"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(AccessLoggedMixin, DjangoUserAdmin):
    """Platform admin view of accounts (US-A04 search by phone).

    Players have no password; only platform admins set one for the admin site.
    "Delete account (PDPA request)" runs the same steps as self-service deletion (BR-25).
    """

    access_object_type = "user"
    log_list_views = True
    phone_search_field = "phone"

    form = UserChangeAdminForm
    add_form = UserCreationAdminForm
    inlines = [ConsentInline]

    list_display = ["phone", "name", "is_active", "is_staff", "date_joined", "deleted_at"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    search_fields = ["name"]
    ordering = ["-date_joined"]
    readonly_fields = ["date_joined", "last_login", "deleted_at", "privacy_actions"]

    fieldsets = [
        (None, {"fields": ["phone", "name", "password"]}),
        (
            _("Access"),
            {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]},
        ),
        (_("Dates"), {"fields": ["date_joined", "last_login", "deleted_at"]}),
        (_("Privacy (PDPA)"), {"fields": ["privacy_actions"]}),
    ]
    add_fieldsets = [
        (
            None,
            {
                "classes": ["wide"],
                "fields": ["phone", "name", "usable_password", "password1", "password2"],
            },
        ),
    ]

    def get_inlines(self, request, obj):
        # A user being created has no consent records yet.
        return self.inlines if obj else []

    def has_delete_permission(self, request, obj=None):
        # Users are anonymised, never hard-deleted (BR-25, data-model 1).
        return False

    @admin.display(description=_("Deletion request"))
    def privacy_actions(self, obj):
        if obj is None or obj.pk is None or obj.is_deleted:
            return "-"
        url = reverse("admin:accounts_user_delete_account", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, _("Delete account (PDPA request)"))

    def get_urls(self):
        custom = [
            path(
                "<int:user_id>/delete-account/",
                self.admin_site.admin_view(self.delete_account_view),
                name="accounts_user_delete_account",
            ),
        ]
        return custom + super().get_urls()

    def delete_account_view(self, request, user_id):
        """Carry out a deletion request that came by phone or email (US-P08, BR-25)."""
        user = get_object_or_404(User, pk=user_id, deleted_at__isnull=True)
        change_url = reverse("admin:accounts_user_change", args=[user.pk])
        form = AccountDeletionForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                cancelled = admin_services.delete_account_on_request(
                    admin=request.user, user=user, reason=form.cleaned_data["reason"]
                )
            except DomainError as exc:
                form.add_error(None, exc.message)
            else:
                messages.success(
                    request,
                    ngettext(
                        "Account deleted. %(count)d upcoming booking was cancelled "
                        "and the venue was told.",
                        "Account deleted. %(count)d upcoming bookings were cancelled "
                        "and the venues were told.",
                        cancelled,
                    )
                    % {"count": cancelled},
                )
                return redirect(change_url)
        context = {
            **self.admin_site.each_context(request),
            "title": _("Delete account (PDPA request)"),
            "opts": self.model._meta,
            "account": user,
            "change_url": change_url,
            "form": form,
            "blockers": services.deletion_blockers(user),
            "upcoming": services.upcoming_bookings_to_cancel(user),
        }
        return TemplateResponse(request, "adminpanel/delete_account.html", context)
