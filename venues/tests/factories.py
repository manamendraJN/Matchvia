import io
import itertools

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from accounts.tests.factories import UserFactory
from venues import services
from venues.models import Area, Court, MemberRole, VenueMembership


def area(slug="malabe"):
    """A launch area (migration 0002). Tests with real transactions wipe them, so recreate."""
    return Area.objects.get_or_create(slug=slug, defaults={"name": slug.title()})[0]


_venue_numbers = itertools.count(1)


def make_venue(owner=None, name=None, area_slug="malabe", **profile):
    """A draft venue. Names are unique by default (one name per area, see services)."""
    owner = owner or UserFactory()
    name = name or f"Arena {next(_venue_numbers)}"
    venue = services.create_venue(owner=owner, name=name, area=area(area_slug), phone=owner.phone)
    if profile:
        services.update_profile(venue, owner, **profile)
    return venue


def make_court(venue, name="Court 1", **fields):
    defaults = {
        "sports": ["futsal"],
        "slot_minutes": 60,
        "off_peak_price_lkr": 3000,
        "peak_price_lkr": 4000,
        "is_indoor": True,
    }
    position = Court.objects.for_venue(venue).count()
    return Court.objects.create(venue=venue, name=name, position=position, **{**defaults, **fields})


def add_staff(venue, user=None):
    user = user or UserFactory()
    VenueMembership.objects.create(venue=venue, user=user, role=MemberRole.STAFF)
    return user


def ready_venue(**kwargs):
    """A venue with everything needed to submit for approval."""
    venue = make_venue(
        address="12 Main Street, Malabe",
        latitude="6.904000",
        longitude="79.954000",
        **kwargs,
    )
    make_court(venue)
    return venue


def image_file(name="photo.jpg", size=(800, 600), fmt="JPEG", exif=None, color="green"):
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color)
    params = {"exif": exif} if exif is not None else {}
    image.save(buffer, format=fmt, **params)
    content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(
        fmt, "application/octet-stream"
    )
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)
