from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.utils.translation import gettext_lazy as _

from core.phone import INVALID_PHONE_MESSAGE, InvalidPhone, normalise_phone

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
class UserAdmin(DjangoUserAdmin):
    """Platform admin view of accounts (US-A04 search by phone).

    Players have no password; only platform admins set one for the admin site.
    """

    form = UserChangeAdminForm
    add_form = UserCreationAdminForm
    inlines = [ConsentInline]

    list_display = ["phone", "name", "is_active", "is_staff", "date_joined", "deleted_at"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    search_fields = ["phone", "name"]
    ordering = ["-date_joined"]
    readonly_fields = ["date_joined", "last_login", "deleted_at"]

    fieldsets = [
        (None, {"fields": ["phone", "name", "password"]}),
        (
            _("Access"),
            {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]},
        ),
        (_("Dates"), {"fields": ["date_joined", "last_login", "deleted_at"]}),
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
