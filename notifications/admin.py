from django.contrib import admin

from .models import SmsMessage


@admin.register(SmsMessage)
class SmsMessageAdmin(admin.ModelAdmin):
    """Read-only view of the outbox for platform admins. OTP text is never shown."""

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
