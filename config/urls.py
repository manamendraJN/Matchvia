from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from accounts.services import PRIVACY_VERSION, TERMS_VERSION
from bookings import views as booking_views
from core.views import healthz, offline, service_worker

urlpatterns = [
    path("", booking_views.home, name="home"),
    path("", include("bookings.urls")),
    path("", include("teams.urls")),
    path("healthz", healthz, name="healthz"),
    path("sw.js", service_worker, name="service_worker"),
    path("offline/", offline, name="offline"),
    path("auth/", include("accounts.urls")),
    path("me/", include("accounts.urls_me")),
    path("manage/", include("venues.urls")),
    path(
        "privacy/",
        TemplateView.as_view(
            template_name="pages/privacy.html", extra_context={"version": PRIVACY_VERSION}
        ),
        name="privacy",
    ),
    path(
        "terms/",
        TemplateView.as_view(
            template_name="pages/terms.html", extra_context={"version": TERMS_VERSION}
        ),
        name="terms",
    ),
    # Platform admin lives at a private, non-default path (architecture 2.4, D16).
    path(settings.ADMIN_URL_PATH, admin.site.urls),
]

if settings.DEBUG:
    # Development only: serve uploaded photos. Production serves them from object storage.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
