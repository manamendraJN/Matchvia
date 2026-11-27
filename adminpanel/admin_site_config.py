"""App config that swaps Django's default admin site for MatchviaAdminSite (C9).

Kept out of apps.py so Django still picks AdminpanelConfig automatically for "adminpanel".
Listed in INSTALLED_APPS instead of "django.contrib.admin".
"""

from django.contrib.admin.apps import AdminConfig


class MatchviaAdminConfig(AdminConfig):
    default_site = "adminpanel.sites.MatchviaAdminSite"
