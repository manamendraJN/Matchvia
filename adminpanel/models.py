"""Platform admin records (data-model 3.7)."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AccessAction(models.TextChoices):
    VIEW = "view", _("Viewed")
    SEARCH = "search", _("Searched")
    CHANGE = "change", _("Changed")
    DELETE_ACCOUNT = "delete_account", _("Deleted account (PDPA request)")


class AdminAccessLog(models.Model):
    """Who looked at or changed personal data, and when (US-A04, A5). Append-only.

    Written by the admin site itself; nobody can edit or delete a row from the admin.
    Search terms that are phone numbers are stored masked.
    """

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("admin"),
    )
    action = models.CharField(_("action"), max_length=20, choices=AccessAction.choices)
    object_type = models.CharField(_("record type"), max_length=50)
    object_id = models.BigIntegerField(_("record id"), null=True, blank=True)
    detail = models.CharField(_("detail"), max_length=255, blank=True)
    created_at = models.DateTimeField(_("time"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("access log entry")
        verbose_name_plural = _("access log")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["admin", "created_at"], name="accesslog_admin_time_idx"),
            models.Index(fields=["object_type", "object_id"], name="accesslog_object_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=AccessAction.values), name="accesslog_action_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.object_type} #{self.object_id}"
