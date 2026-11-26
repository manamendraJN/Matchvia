"""Venue dashboard under /manage/ (architecture 2.4).

Every URL with a venue id must have an isolation test (venues/tests/test_isolation.py); a test
fails if one is missing (CLAUDE.md rule 2). Booking pages live in bookings/views_manage.py.
"""

from django.urls import path

from bookings import views_manage as booking_views

from . import views

app_name = "manage"

urlpatterns = [
    path("", views.home, name="home"),
    path("new/", views.create, name="create"),
    # Calendar and bookings (owner and staff)
    path("<int:venue_id>/", booking_views.calendar, name="dashboard"),
    path("<int:venue_id>/week/", booking_views.week, name="week"),
    path("<int:venue_id>/bookings/new/", booking_views.new_booking, name="booking_new"),
    path(
        "<int:venue_id>/bookings/<int:booking_id>/",
        booking_views.booking_detail,
        name="booking_detail",
    ),
    path(
        "<int:venue_id>/bookings/<int:booking_id>/move/",
        booking_views.move_booking,
        name="booking_move",
    ),
    path(
        "<int:venue_id>/bookings/<int:booking_id>/cancel/",
        booking_views.cancel_booking,
        name="booking_cancel",
    ),
    path(
        "<int:venue_id>/bookings/<int:booking_id>/no-show/",
        booking_views.mark_no_show,
        name="booking_no_show",
    ),
    path(
        "<int:venue_id>/bookings/<int:booking_id>/undo-no-show/",
        booking_views.undo_no_show,
        name="booking_undo_no_show",
    ),
    path(
        "<int:venue_id>/bookings/<int:booking_id>/arrived/",
        booking_views.mark_arrived,
        name="booking_arrived",
    ),
    path("<int:venue_id>/blocks/new/", booking_views.new_block, name="block_new"),
    path(
        "<int:venue_id>/blocks/<int:booking_id>/remove/",
        booking_views.remove_block,
        name="block_remove",
    ),
    path("<int:venue_id>/customers/lookup/", booking_views.customer_lookup, name="customer_lookup"),
    # Venue setup (owner edits, staff view)
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
    # Staff (owner only)
    path("<int:venue_id>/staff/", views.staff, name="staff"),
    path(
        "<int:venue_id>/staff/<int:membership_id>/remove/", views.staff_remove, name="staff_remove"
    ),
]
