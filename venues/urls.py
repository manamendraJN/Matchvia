"""Venue dashboard under /manage/ (architecture 2.4).

Every URL with a venue id must have an isolation test (venues/tests/test_isolation.py); a test
fails if one is missing (CLAUDE.md rule 2).
"""

from django.urls import path

from . import views

app_name = "manage"

urlpatterns = [
    path("", views.home, name="home"),
    path("new/", views.create, name="create"),
    path("<int:venue_id>/", views.dashboard, name="dashboard"),
    path("<int:venue_id>/profile/", views.profile, name="profile"),
    path("<int:venue_id>/photos/add/", views.photo_add, name="photo_add"),
    path("<int:venue_id>/photos/<int:photo_id>/remove/", views.photo_remove, name="photo_remove"),
    path("<int:venue_id>/logo/", views.image_upload, {"kind": "logo"}, name="logo"),
    path("<int:venue_id>/cover/", views.image_upload, {"kind": "cover"}, name="cover"),
    path("<int:venue_id>/submit/", views.submit, name="submit"),
    path("<int:venue_id>/courts/", views.courts, name="courts"),
    path("<int:venue_id>/courts/new/", views.court_create, name="court_create"),
    path("<int:venue_id>/courts/<int:court_id>/", views.court_edit, name="court_edit"),
    path("<int:venue_id>/courts/<int:court_id>/toggle/", views.court_toggle, name="court_toggle"),
    path("<int:venue_id>/hours/", views.hours, name="hours"),
    path("<int:venue_id>/prices/", views.prices, name="prices"),
]
