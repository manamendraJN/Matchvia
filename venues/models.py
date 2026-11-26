"""Venues, courts, opening hours, settings and staff (data-model 3.2).

Every venue-owned table carries ``venue_id`` directly and uses VenueOwnedQuerySet, so access is
always ``Model.objects.for_venue(venue)`` (data-model 6, CLAUDE.md rule 2).
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.fields import PhoneField
from core.querysets import VenueOwnedQuerySet
from core.timeutils import DAY_END_MINUTE, DAY_START_MINUTE

# Sri Lanka's bounding box, with a small margin (map pin check, V2).
LAT_MIN, LAT_MAX = Decimal("5.85"), Decimal("9.90")
LNG_MIN, LNG_MAX = Decimal("79.50"), Decimal("82.00")

MAX_PRICE_LKR = 100_000  # per slot (BR-18)
SLOT_MINUTES = (30, 60, 90, 120)  # BR-01


class Sport(models.TextChoices):
    FUTSAL = "futsal", _("Futsal")
    INDOOR_CRICKET = "indoor_cricket", _("Indoor cricket")


class Facility(models.TextChoices):
    PARKING = "parking", _("Parking")
    CHANGING_ROOMS = "changing_rooms", _("Changing rooms")
    FLOODLIGHTS = "floodlights", _("Floodlights")
    DRINKING_WATER = "drinking_water", _("Drinking water")
    CAFE = "cafe", _("Cafe")
    TOILETS = "toilets", _("Toilets")


class VenueStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PENDING = "pending", _("Waiting for approval")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    SUSPENDED = "suspended", _("Suspended")


class MemberRole(models.TextChoices):
    OWNER = "owner", _("Owner")
    STAFF = "staff", _("Staff")


def _random_name(folder: str, filename: str) -> str:
    # Random names: never the uploader's file name (architecture 5.1).
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"venues/{folder}/{uuid.uuid4().hex}.{extension}"


def upload_logo(instance, filename):
    return _random_name("logos", filename)


def upload_cover(instance, filename):
    return _random_name("covers", filename)


def upload_photo(instance, filename):
    return _random_name("photos", filename)


class Area(models.Model):
    """Platform list of areas for search (US-A03)."""

    name = models.CharField(_("name"), max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(_("active"), default=True)
    position = models.PositiveSmallIntegerField(_("order"), default=0)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = _("area")

    def __str__(self) -> str:
        return self.name


class VenueQuerySet(models.QuerySet):
    def public(self):
        """Venues players may see and book online: approved only (BR-22, US-P02)."""
        return self.filter(status=VenueStatus.APPROVED)


class Venue(models.Model):
    name = models.CharField(_("venue name"), max_length=100)
    slug = models.SlugField(max_length=60, unique=True)
    area = models.ForeignKey(Area, on_delete=models.PROTECT, verbose_name=_("area"))
    address = models.CharField(_("address"), max_length=255, blank=True)
    # Null until the owner sets the pin; required before submitting for approval.
    latitude = models.DecimalField(
        _("latitude"), max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        _("longitude"), max_digits=9, decimal_places=6, null=True, blank=True
    )
    phone = PhoneField(_("venue phone"))
    description = models.TextField(_("description"), blank=True)
    facilities = ArrayField(
        models.CharField(max_length=30, choices=Facility.choices), default=list, blank=True
    )
    logo = models.ImageField(upload_to=upload_logo, null=True, blank=True)
    cover_photo = models.ImageField(upload_to=upload_cover, null=True, blank=True)
    status = models.CharField(max_length=16, choices=VenueStatus.choices, default=VenueStatus.DRAFT)
    status_reason = models.CharField(max_length=255, blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    status_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = VenueQuerySet.as_manager()

    class Meta:
        verbose_name = _("venue")
        indexes = [models.Index(fields=["area", "status"], name="venue_area_status_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=VenueStatus.values), name="venue_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(phone__regex=r"^\+947[0-9]{8}$"), name="venue_phone_lk_mobile"
            ),
            models.CheckConstraint(
                condition=Q(facilities__contained_by=Facility.values),
                name="venue_facilities_known",
            ),
            models.CheckConstraint(
                condition=Q(latitude__isnull=True, longitude__isnull=True)
                # isnull=False matters: a NULL makes a range check "unknown", which passes.
                | Q(
                    latitude__isnull=False,
                    longitude__isnull=False,
                    latitude__gte=LAT_MIN,
                    latitude__lte=LAT_MAX,
                    longitude__gte=LNG_MIN,
                    longitude__lte=LNG_MAX,
                ),
                name="venue_location_in_sri_lanka",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_public(self) -> bool:
        return self.status == VenueStatus.APPROVED


class VenueSettings(models.Model):
    """Per-venue booking rules (requirements section 5). Typed columns with database ranges."""

    class Approver(models.TextChoices):
        OWNER = "owner", _("Owner only")
        OWNER_OR_STAFF = "owner_or_staff", _("Owner or staff")

    venue = models.OneToOneField(
        Venue, on_delete=models.CASCADE, primary_key=True, related_name="settings"
    )
    booking_horizon_days = models.PositiveSmallIntegerField(default=14)  # BR-04
    min_notice_minutes = models.PositiveSmallIntegerField(default=60)  # BR-05
    max_slots_per_booking = models.PositiveSmallIntegerField(default=3)  # BR-02
    max_upcoming_online_bookings = models.PositiveSmallIntegerField(default=2)  # BR-12
    cancellation_window_hours = models.PositiveSmallIntegerField(default=6)  # BR-08
    reminder_lead_hours = models.PositiveSmallIntegerField(default=3)  # BR-20
    sms_on_phone_bookings = models.BooleanField(default=True)  # BR-21
    sms_on_walk_ins = models.BooleanField(default=False)  # BR-21
    recurring_approver = models.CharField(
        max_length=16, choices=Approver.choices, default=Approver.OWNER_OR_STAFF
    )  # BR-13
    recurring_default_weeks = models.PositiveSmallIntegerField(default=8)  # BR-13
    recurring_max_weeks = models.PositiveSmallIntegerField(default=12)  # BR-13
    staff_can_change_price = models.BooleanField(default=True)  # BR-19
    updated_at = models.DateTimeField(auto_now=True)

    objects = VenueOwnedQuerySet.as_manager()

    class Meta:
        verbose_name = _("venue settings")
        verbose_name_plural = _("venue settings")
        constraints = [
            models.CheckConstraint(
                condition=Q(booking_horizon_days__gte=1, booking_horizon_days__lte=60),
                name="settings_horizon_range",
            ),
            models.CheckConstraint(
                condition=Q(min_notice_minutes__lte=1440), name="settings_notice_range"
            ),
            models.CheckConstraint(
                condition=Q(max_slots_per_booking__gte=1, max_slots_per_booking__lte=6),
                name="settings_max_slots_range",
            ),
            models.CheckConstraint(
                condition=Q(
                    max_upcoming_online_bookings__gte=1, max_upcoming_online_bookings__lte=10
                ),
                name="settings_upcoming_range",
            ),
            models.CheckConstraint(
                condition=Q(cancellation_window_hours__lte=72),
                name="settings_cancellation_range",
            ),
            models.CheckConstraint(
                condition=Q(reminder_lead_hours__gte=1, reminder_lead_hours__lte=24),
                name="settings_reminder_range",
            ),
            models.CheckConstraint(
                condition=Q(recurring_approver__in=["owner", "owner_or_staff"]),
                name="settings_approver_valid",
            ),
            models.CheckConstraint(
                condition=Q(
                    recurring_default_weeks__gte=2,
                    recurring_max_weeks__lte=12,
                    recurring_default_weeks__lte=models.F("recurring_max_weeks"),
                ),
                name="settings_recurring_weeks_range",
            ),
        ]

    def __str__(self) -> str:
        return f"Settings for venue #{self.venue_id}"


class VenueMembership(models.Model):
    """Owner and staff roles, per venue (US-O06). Deleting the row ends access immediately."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="venue_memberships"
    )
    role = models.CharField(max_length=8, choices=MemberRole.choices)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = VenueOwnedQuerySet.as_manager()

    class Meta:
        verbose_name = _("venue member")
        indexes = [models.Index(fields=["user", "venue"], name="membership_user_venue_idx")]
        constraints = [
            models.UniqueConstraint(fields=["venue", "user"], name="membership_one_role"),
            models.CheckConstraint(
                condition=Q(role__in=MemberRole.values), name="membership_role_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} ({self.role})"


class VenuePhoto(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=upload_photo)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = VenueOwnedQuerySet.as_manager()

    class Meta:
        ordering = ["position", "id"]
        verbose_name = _("venue photo")

    def __str__(self) -> str:
        return f"Photo #{self.pk}"


class Court(models.Model):
    """One bookable physical space (BR-29). Both sports on one court is still one space."""

    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="courts")
    name = models.CharField(_("court name"), max_length=40)
    sports = ArrayField(models.CharField(max_length=20, choices=Sport.choices))
    slot_minutes = models.PositiveSmallIntegerField(_("booking slot length"), default=60)
    off_peak_price_lkr = models.PositiveIntegerField(_("normal price (Rs.)"))
    peak_price_lkr = models.PositiveIntegerField(_("peak price (Rs.)"))
    is_indoor = models.BooleanField(_("indoor"), default=True)
    is_active = models.BooleanField(_("active"), default=True)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = VenueOwnedQuerySet.as_manager()

    class Meta:
        ordering = ["position", "id"]
        verbose_name = _("court")
        indexes = [GinIndex(fields=["sports"], name="court_sports_gin")]
        constraints = [
            models.UniqueConstraint(fields=["venue", "name"], name="court_name_unique_per_venue"),
            # Target for composite foreign keys from bookings (data-model 6.3).
            models.UniqueConstraint(fields=["id", "venue"], name="court_id_venue_unique"),
            models.CheckConstraint(
                condition=Q(sports__len__gt=0) & Q(sports__contained_by=Sport.values),
                name="court_sports_known_not_empty",
            ),
            models.CheckConstraint(
                condition=Q(slot_minutes__in=SLOT_MINUTES), name="court_slot_minutes_valid"
            ),
            models.CheckConstraint(
                condition=Q(off_peak_price_lkr__lte=MAX_PRICE_LKR)
                & Q(peak_price_lkr__lte=MAX_PRICE_LKR),
                name="court_prices_max",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_sports_display(self) -> str:
        labels = dict(Sport.choices)
        return " · ".join(str(labels.get(code, code)) for code in self.sports)


class OpeningHours(models.Model):
    """One opening window per weekday, in operating minutes (data-model 1.2, BR-15)."""

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="opening_hours")
    weekday = models.PositiveSmallIntegerField()  # 0 = Monday … 6 = Sunday
    is_closed = models.BooleanField(default=False)
    opens_minute = models.PositiveSmallIntegerField(default=360)  # 06:00
    closes_minute = models.PositiveSmallIntegerField(default=1440)  # 24:00

    objects = VenueOwnedQuerySet.as_manager()

    class Meta:
        ordering = ["weekday"]
        verbose_name = _("opening hours")
        verbose_name_plural = _("opening hours")
        constraints = [
            models.UniqueConstraint(fields=["venue", "weekday"], name="hours_one_row_per_day"),
            models.CheckConstraint(condition=Q(weekday__lte=6), name="hours_weekday_valid"),
            models.CheckConstraint(
                condition=Q(is_closed=True)
                | Q(
                    opens_minute__gte=DAY_START_MINUTE,
                    opens_minute__lt=models.F("closes_minute"),
                    closes_minute__lte=DAY_END_MINUTE,
                ),
                name="hours_window_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"Weekday {self.weekday}"


class VenueCustomer(models.Model):
    """The venue's own customer book: one row per phone number per venue (data-model 3.2).

    Online players, phone/WhatsApp customers and walk-ins who gave a number all land here.
    Walk-ins without a phone have no row; their booking keeps only a name. A block (BR-11) is
    this venue's decision about this number, not a platform-wide ban.
    """

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="customers")
    # Null only after the person deleted their account (BR-25).
    phone = PhoneField(_("phone"), null=True, blank=True)
    name = models.CharField(_("name"), max_length=80)
    # Set when the phone belongs to a registered player, so their bookings show in My bookings.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="venue_customers",
    )
    is_blocked_online = models.BooleanField(default=False)
    blocked_at = models.DateTimeField(null=True, blank=True)
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    block_reason = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects = VenueOwnedQuerySet.as_manager()

    class Meta:
        verbose_name = _("venue customer")
        indexes = [models.Index(fields=["user"], name="customer_user_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["venue", "phone"],
                condition=Q(phone__isnull=False),
                name="customer_one_row_per_phone",
            ),
            # Target for the composite foreign key from bookings (data-model 6.3).
            models.UniqueConstraint(fields=["id", "venue"], name="customer_id_venue_unique"),
        ]

    def __str__(self) -> str:
        return self.name
