from django.contrib import admin

from adminpanel.mixins import AccessLoggedMixin

from .models import SmsMessage


@admin.register(SmsMessage)
class SmsMessageAdmin(AccessLoggedMixin, admin.ModelAdmin):
    """Read-only view of the outbox for platform admins. OTP text is never shown."""

    access_object_type = "sms"
    log_list_views = True
    phone_search_field = "to_phone"

    list_display = ["id", "purpose", "status", "to_phone", "scheduled_for", "attempts", "sent_at"]
    list_filter = ["status", "purpose"]
    search_fields = ["to_phone"]
    ordering = ["-created_at"]
    exclude = ["encrypted_body"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
