"""Sign-in URLs under /auth/ (architecture 2.4)."""

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("phone/", views.phone_view, name="phone"),
    path("code/", views.code_view, name="code"),
    path("code/resend/", views.resend_view, name="resend"),
    path("welcome/", views.welcome_view, name="welcome"),
    # POST only (Django's LogoutView refuses GET), so a link can't sign anyone out.
    path("logout/", LogoutView.as_view(next_page="home"), name="logout"),
    path("deleted/", views.deleted_view, name="deleted"),
]
