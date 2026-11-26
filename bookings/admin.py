"""Read-only booking lookup for platform admins (US-A04). Changes go through the services only."""

from django.contrib import admin

from venues.models import VenueCustomer

from .models import Booking, BookingEvent
from .reference import normalise_reference


class EventInline(admin.TabularInline):
    model = BookingEvent
    extra = 0
    fields = ["created_at", "action", "actor", "changes"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Booking)
class BookingAdmin(ReadOnlyAdmin):
    list_display = [
        "reference",
        "venue",
        "court",
        "kind",
        "start_at",
        "end_at",
        "status",
        "source",
        "price_lkr",
    ]
    list_filter = ["status", "kind", "source", "venue"]
    search_fields = ["reference", "venue_customer__phone"]
    date_hierarchy = "start_at"
    inlines = [EventInline]

    def get_search_results(self, request, queryset, search_term):
        # 'MV-7K3P9Q', 'mv7k3p9q' and '7K3P9Q' all find the same booking.
        code = normalise_reference(search_term)
        if len(code) == 6:
            return queryset.filter(reference=code), False
        return super().get_search_results(request, queryset, search_term)


@admin.register(VenueCustomer)
class VenueCustomerAdmin(ReadOnlyAdmin):
    list_display = ["name", "phone", "venue", "user", "is_blocked_online"]
    list_filter = ["is_blocked_online", "venue"]
    search_fields = ["phone", "name"]
