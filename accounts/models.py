"""Users, phone OTP sign-in and consent (data-model 3.1)."""

import contextlib

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.fields import PhoneField
from core.phone import InvalidPhone, normalise_phone, validate_phone

DELETED_USER_NAME = "Deleted user"


class Role(models.TextChoices):
    """Shared names for roles. Roles are not stored on User (data-model 3.1):

    - player: every active account
    - admin: platform admin, ``User.is_staff``
    - venue_owner / venue_staff: per venue, ``VenueMembership`` rows (venues app, S04)
    """

    PLAYER = "player", _("Player")
    VENUE_OWNER = "venue_owner", _("Venue owner")
    VENUE_STAFF = "venue_staff", _("Venue staff")
    ADMIN = "admin", _("Platform admin")


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, phone, name, password, **extra_fields):
        try:
            phone = normalise_phone(phone)
        except InvalidPhone as exc:
            raise ValueError("A valid Sri Lankan mobile number is required.") from exc
        user = self.model(phone=phone, name=name, **extra_fields)
        if password:
            user.set_password(password)
        else:
            # Players and venue users sign in with OTP only (data-model 3.1).
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, phone, name="", password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone, name, password, **extra_fields)

    def create_superuser(self, phone, name, password, **extra_fields):
        """A platform admin who can also use the Django admin with a password (C9)."""
        if not password:
            raise ValueError("A platform admin needs a password for the admin site.")
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        return self._create_user(phone, name, password, **extra_fields)

    def get_by_natural_key(self, username):
        # Admin sign-in: accept the number in any common format.
        with contextlib.suppress(InvalidPhone):
            username = normalise_phone(username)
        return self.get(**{self.model.USERNAME_FIELD: username})


class User(AbstractBaseUser, PermissionsMixin):
    """One account per phone number. Anonymised on deletion, never hard-deleted (BR-25)."""

    # Null only for deleted users, so several deleted users can coexist (unique allows NULLs).
    phone = PhoneField(_("mobile number"), unique=True, null=True, blank=True)
    # Blank until the first-time profile step (US-P01).
    name = models.CharField(_("name"), max_length=80, blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    is_staff = models.BooleanField(
        _("platform admin"),
        default=False,
        help_text=_("Can use the platform admin site."),
    )
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)
    deleted_at = models.DateTimeField(_("deleted at"), null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        constraints = [
            # A deleted user keeps no phone number (data-model 3.1).
            models.CheckConstraint(
                condition=Q(deleted_at__isnull=True) | Q(phone__isnull=True),
                name="user_deleted_has_no_phone",
            ),
            # Only normalised Sri Lankan mobile numbers, even if written outside Django.
            models.CheckConstraint(
                condition=Q(phone__isnull=True) | Q(phone__regex=r"^\+947[0-9]{8}$"),
                name="user_phone_e164_lk_mobile",
            ),
        ]

    def __str__(self) -> str:
        if self.deleted_at:
            return DELETED_USER_NAME
        return self.name or f"User #{self.pk}"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def get_full_name(self) -> str:
        return self.name

    def get_short_name(self) -> str:
        return self.name


class OTPChallenge(models.Model):
    """One sign-in or confirmation code sent by SMS (BR-27).

    Only an HMAC of the code is stored. Rows older than 24 hours are deleted by a daily job.
    """

    class Purpose(models.TextChoices):
        LOGIN = "login", _("Sign in")
        DELETE_ACCOUNT = "delete_account", _("Delete account")

    # Not a foreign key: a code can be requested before the account exists.
    phone = models.CharField(max_length=16, validators=[validate_phone])
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    # Wrong guesses on this challenge.
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    # Set when a wrong guess brings the number to 5 wrong codes in 15 minutes: the number is
    # locked for sign-in until then (BR-27).
    locked_until = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = _("OTP challenge")
        indexes = [
            models.Index(fields=["phone", "created_at"], name="otp_phone_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(purpose__in=["login", "delete_account"]),
                name="otp_purpose_valid",
            ),
            models.CheckConstraint(condition=Q(attempts__lte=5), name="otp_attempts_max_5"),
        ]

    def __str__(self) -> str:
        return f"OTP #{self.pk} {self.purpose}"


class ConsentRecord(models.Model):
    """Proof that a user accepted a version of the privacy notice or terms (NFR-07)."""

    class Document(models.TextChoices):
        PRIVACY = "privacy", _("Privacy notice")
        TERMS = "terms", _("Terms of use")

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="consents")
    document = models.CharField(max_length=16, choices=Document.choices)
    version = models.CharField(max_length=20)
    accepted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = _("consent record")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "document", "version"], name="consent_unique_per_version"
            ),
            models.CheckConstraint(
                condition=Q(document__in=["privacy", "terms"]), name="consent_document_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document} {self.version}"
