"""Team URLs (architecture 2.4): /me/teams/ and the SMS invite link /t/<token>/."""

from django.urls import path

from . import views

urlpatterns = [
    path("me/teams/", views.my_teams, name="my_teams"),
    path("me/teams/new/", views.create, name="team_create"),
    path("me/teams/<int:team_id>/", views.detail, name="team_detail"),
    path(
        "me/teams/<int:team_id>/members/<int:user_id>/remove/",
        views.remove_member,
        name="team_remove_member",
    ),
    path(
        "me/teams/<int:team_id>/members/<int:user_id>/captain/",
        views.make_captain,
        name="team_make_captain",
    ),
    path("me/teams/<int:team_id>/close/", views.close, name="team_close"),
    path(
        "me/teams/<int:team_id>/invites/<int:invite_id>/remove/",
        views.revoke_invite,
        name="team_revoke_invite",
    ),
    path("t/<str:token>/", views.invite_landing, name="team_invite"),
]
