"""Player area URLs under /me/ (architecture 2.4). Bookings and teams join later."""

from django.urls import path

from . import views

app_name = "me"

urlpatterns = [
    path("account/", views.account_view, name="account"),
    path("account/delete/", views.delete_view, name="delete"),
    path("account/delete/confirm/", views.delete_confirm_view, name="delete_confirm"),
]
