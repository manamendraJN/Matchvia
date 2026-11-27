"""Read-only booking lookup for platform admins (US-A04). Changes go through the services only.

Opening a booking or customer, and every search, is written to the access log (A5).
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from adminpanel.mixins import AccessLoggedMixin
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
class BookingAdmin(AccessLoggedMixin, ReadOnlyAdmin):
    """A4: one search box for a reference (MV-...) or the customer's phone number."""

    access_object_type = "booking"
    phone_search_field = "venue_customer__phone"
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
    search_fields = ["reference", "customer_name"]
    search_help_text = _("Booking reference (MV-7K3P9Q) or customer phone number")
    date_hierarchy = "start_at"
    inlines = [EventInline]

    def get_search_results(self, request, queryset, search_term):
        # 'MV-7K3P9Q', 'mv7k3p9q' and '7K3P9Q' all find the same booking.
        code = normalise_reference(search_term)
        if len(code) == 6:
            return queryset.filter(reference=code), False
        return super().get_search_results(request, queryset, search_term)


@admin.register(VenueCustomer)
class VenueCustomerAdmin(AccessLoggedMixin, ReadOnlyAdmin):
    access_object_type = "venue_customer"
    log_list_views = True
    phone_search_field = "phone"

    list_display = ["name", "phone", "venue", "user", "is_blocked_online"]
    list_filter = ["is_blocked_online", "venue"]
    search_fields = ["name"]
