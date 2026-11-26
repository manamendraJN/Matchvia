"""Safe image uploads for venue photos and logos (architecture 5.1).

Every upload is opened with Pillow and re-encoded: that strips EXIF data (including GPS), drops
anything hidden after the image data, and shrinks it for mobile (NFR-02). Size, type and pixel
limits stop oversized files and decompression bombs.
"""

import io
import uuid

from django.core.files.base import ContentFile
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError

from core.exceptions import RuleViolation

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB (US-O01)
MAX_SOURCE_PIXELS = 40_000_000  # refuse anything bigger before decoding (decompression bombs)
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
PHOTO_MAX_SIDE = 1600
LOGO_MAX_SIDE = 512


def _open(upload) -> Image.Image:
    if upload.size > MAX_UPLOAD_BYTES:
        raise RuleViolation(_("This photo is over 5 MB. Choose a smaller one."))
    try:
        upload.seek(0)
        image = Image.open(upload)
        if image.format not in ALLOWED_FORMATS:
            raise RuleViolation(_("Use a JPG, PNG or WebP image."))
        width, height = image.size
        if width * height > MAX_SOURCE_PIXELS:
            raise RuleViolation(_("This image is too large. Choose a smaller one."))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise RuleViolation(_("This file is not a valid image.")) from None
    return ImageOps.exif_transpose(image)


def process_photo(upload) -> ContentFile:
    """A JPEG at most 1600 px on its longest side, with no metadata."""
    image = _open(upload).convert("RGB")
    image.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82, optimize=True, progressive=True)
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.jpg")


def process_logo(upload) -> ContentFile:
    """A PNG at most 512 px, keeping transparency, with no metadata."""
    image = _open(upload).convert("RGBA")
    image.thumbnail((LOGO_MAX_SIDE, LOGO_MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.png")
