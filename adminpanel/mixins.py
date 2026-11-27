"""Access logging for admin screens that show personal data (US-A04, A5)."""

from django.contrib.admin.views.main import SEARCH_VAR

from core.phone import InvalidPhone, normalise_phone

from . import services
from .models import AccessAction


class AccessLoggedMixin:
    """Put first in the bases of a ModelAdmin whose records hold personal data.

    Logs opening a record, saving a change and every search (phone numbers masked).
    ``log_list_views`` also logs opening the list itself, for lists that show numbers.
    ``phone_search_field`` lets a search for "077 123 4567" or "+94771234567" find the number.
    """

    access_object_type = ""
    log_list_views = False
    phone_search_field = None

    def change_view(self, request, object_id, form_url="", extra_context=None):
        response = super().change_view(request, object_id, form_url, extra_context)
        if request.method == "GET" and response.status_code == 200:
            services.log_access(request.user, AccessAction.VIEW, self.access_object_type, object_id)
        elif request.method == "POST" and response.status_code == 302:
            services.log_access(
                request.user, AccessAction.CHANGE, self.access_object_type, object_id
            )
        return response

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        if response.status_code == 200:
            term = request.GET.get(SEARCH_VAR, "").strip()
            if term:
                services.log_access(
                    request.user,
                    AccessAction.SEARCH,
                    self.access_object_type,
                    detail=services.masked_term(term),
                )
            elif self.log_list_views:
                services.log_access(
                    request.user, AccessAction.VIEW, self.access_object_type, detail="list"
                )
        return response

    def get_search_results(self, request, queryset, search_term):
        if self.phone_search_field:
            try:
                phone = normalise_phone(search_term)
            except InvalidPhone:
                pass
            else:
                return queryset.filter(**{self.phone_search_field: phone}), False
        return super().get_search_results(request, queryset, search_term)
