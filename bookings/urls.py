"""Player URLs (architecture 2.4): search, venue pages, booking flow, My bookings."""

from django.urls import path

from . import views

urlpatterns = [
    path("search/", views.search, name="search"),
    path("v/<slug:slug>/", views.venue_page, name="venue_page"),
    path("book/review/", views.review, name="book_review"),
    path("book/confirm/", views.confirm, name="book_confirm"),
    path("book/done/<str:reference>/", views.done, name="book_done"),
    path("book/weekly/", views.weekly_request, name="book_weekly"),
    path("me/weekly/<int:series_id>/", views.my_weekly, name="my_weekly"),
    path("me/weekly/<int:series_id>/cancel/", views.my_weekly_cancel, name="my_weekly_cancel"),
    path("me/bookings/", views.my_bookings, name="my_bookings"),
    path("me/bookings/<str:reference>/", views.booking_detail, name="booking_detail"),
    path("me/bookings/<str:reference>/cancel/", views.booking_cancel, name="booking_cancel"),
]
