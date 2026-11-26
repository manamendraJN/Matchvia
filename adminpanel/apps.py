from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AdminpanelConfig(AppConfig):
    name = "adminpanel"
    verbose_name = _("Platform admin")
