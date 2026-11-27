"""Platform admin screens in the Django admin (A1–A3, US-A01–A03).

Venue status changes go only through venues.services (approve/reject/suspend/unsuspend), from the
Review page, so each one checks the transition, records who did it and SMSes the owner. The status
fields are read-only on the normal edit form.
"""

from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from core.exceptions import DomainError
from pricing.models import PeakPeriod
from venues import services as venue_services
from venues.models import Area, Court, OpeningHours, Venue, VenueMembership, VenueStatus

from . import services
from .forms import VenueDecisionForm
from .models import AccessAction, AdminAccessLog


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "position", "venue_count"]
    list_editable = ["is_active", "position"]
    prepopulated_fields = {"slug": ["name"]}
    search_fields = ["name"]

    @admin.display(description=_("Venues"))
    def venue_count(self, obj):
        return obj.venue_set.count()


class CourtInline(admin.TabularInline):
    model = Court
    extra = 0
    fields = ["name", "sports", "slot_minutes", "off_peak_price_lkr", "peak_price_lkr", "is_active"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class HoursInline(admin.TabularInline):
    model = OpeningHours
    extra = 0
    fields = ["weekday", "is_closed", "opens_minute", "closes_minute"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class PeakInline(admin.TabularInline):
    model = PeakPeriod
    extra = 0
    fields = ["weekday", "starts_minute", "ends_minute"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class MembershipInline(admin.TabularInline):
    """Admins can add owners/staff by hand until the staff screen exists (C6)."""

    model = VenueMembership
    fk_name = "venue"
    extra = 0
    fields = ["user", "role", "created_at"]
    readonly_fields = ["created_at"]
    raw_id_fields = ["user"]


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ["name", "area", "status", "status_changed_at", "review_link"]
    list_filter = ["status", "area"]
    search_fields = ["name", "slug", "phone"]
    ordering = ["status", "status_changed_at"]
    readonly_fields = [
        "slug",
        "status",
        "status_reason",
        "status_changed_at",
        "status_changed_by",
        "created_at",
        "updated_at",
    ]
    inlines = [MembershipInline, CourtInline, HoursInline, PeakInline]

    def has_delete_permission(self, request, obj=None):
        # Venues are suspended, never deleted (data-model 1.1).
        return False

    @admin.display(description=_("Review"))
    def review_link(self, obj):
        url = reverse("admin:venues_venue_review", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, _("Review"))

    def get_urls(self):
        custom = [
            path(
                "<int:venue_id>/review/",
                self.admin_site.admin_view(self.review_view),
                name="venues_venue_review",
            ),
        ]
        return custom + super().get_urls()

    def review_view(self, request, venue_id):
        if not self.has_change_permission(request):
            return redirect("admin:index")
        venue = get_object_or_404(Venue.objects.select_related("area"), pk=venue_id)
        if request.method == "GET":  # the page shows the owners' names and numbers
            services.log_access(request.user, AccessAction.VIEW, "venue", venue.pk)
        form = VenueDecisionForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            decision, reason = form.cleaned_data["decision"], form.cleaned_data["reason"]
            try:
                if decision == form.APPROVE:
                    venue_services.approve_venue(venue, request.user)
                elif decision == form.REJECT:
                    venue_services.reject_venue(venue, request.user, reason)
                elif decision == form.SUSPEND:
                    venue_services.suspend_venue(venue, request.user, reason)
                else:
                    venue_services.unsuspend_venue(venue, request.user)
            except DomainError as exc:
                form.add_error(None, exc.message)
            else:
                messages.success(
                    request,
                    _("%(venue)s is now %(status)s. The owner gets an SMS.")
                    % {"venue": venue.name, "status": venue.get_status_display()},
                )
                return redirect("admin:venues_venue_changelist")

        context = {
            **self.admin_site.each_context(request),
            "title": _("Review %(venue)s") % {"venue": venue.name},
            "opts": self.model._meta,
            "venue": venue,
            "form": form,
            "owners": VenueMembership.objects.for_venue(venue)
            .filter(role="owner")
            .select_related("user"),
            "courts": Court.objects.for_venue(venue),
            "missing": venue_services.missing_for_submission(venue),
            "is_pending": venue.status == VenueStatus.PENDING,
        }
        return TemplateResponse(request, "adminpanel/venue_review.html", context)


@admin.register(AdminAccessLog)
class AdminAccessLogAdmin(admin.ModelAdmin):
    """A5: who looked at personal data. Read-only: no add, change or delete for anyone."""

    list_display = ["created_at", "admin", "action", "object_type", "object_id", "detail"]
    list_filter = [("admin", admin.RelatedOnlyFieldListFilter), "action", "object_type"]
    date_hierarchy = "created_at"
    list_select_related = ["admin"]
    fields = list_display
    readonly_fields = list_display

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
