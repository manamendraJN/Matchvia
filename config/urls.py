from django.conf import settings
from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView

from core.views import healthz

urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("healthz", healthz, name="healthz"),
    # TODO(S03/S10, accounts branch): path("auth/", include("accounts.urls")) and
    # path("me/", include("accounts.urls_me")) are added together with those modules.
    # Platform admin lives at a private, non-default path (architecture 2.4, D16).
    path(settings.ADMIN_URL_PATH, admin.site.urls),
]
