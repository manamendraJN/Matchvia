"""Upload safety: type and size limits, re-encoding strips EXIF/GPS, resizing (architecture 5.1)."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from core.exceptions import RuleViolation
from venues import images

from .factories import image_file


def gps_exif() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    gps = exif.get_ifd(0x8825)
    gps[2] = (6.0, 54.0, 14.0)  # latitude
    gps[4] = (79.0, 57.0, 14.0)  # longitude
    return exif.tobytes()


def test_photo_is_reencoded_as_jpeg_without_metadata():
    upload = image_file(exif=gps_exif())
    assert Image.open(io.BytesIO(upload.read())).getexif()  # the original has EXIF
    upload.seek(0)

    processed = images.process_photo(upload)

    result = Image.open(io.BytesIO(processed.read()))
    assert result.format == "JPEG"
    assert not result.getexif()
    assert processed.name.endswith(".jpg")
    assert "photo" not in processed.name  # random name, not the uploader's


def test_large_photo_is_shrunk_to_1600px():
    processed = images.process_photo(image_file(size=(4000, 3000)))
    assert Image.open(io.BytesIO(processed.read())).size == (1600, 1200)


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_png_and_webp_accepted(fmt):
    processed = images.process_photo(image_file(name=f"x.{fmt.lower()}", fmt=fmt))
    assert Image.open(io.BytesIO(processed.read())).format == "JPEG"


def test_logo_keeps_transparency_and_is_small():
    buffer = io.BytesIO()
    Image.new("RGBA", (1200, 1200), (0, 0, 0, 0)).save(buffer, format="PNG")
    upload = SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")

    processed = images.process_logo(upload)

    result = Image.open(io.BytesIO(processed.read()))
    assert result.format == "PNG"
    assert result.mode == "RGBA"
    assert result.size == (512, 512)


def test_over_5mb_rejected():
    upload = SimpleUploadedFile("big.jpg", b"0" * (5 * 1024 * 1024 + 1), content_type="image/jpeg")
    with pytest.raises(RuleViolation, match="over 5 MB"):
        images.process_photo(upload)


def test_not_an_image_rejected():
    upload = SimpleUploadedFile("evil.jpg", b"<script>alert(1)</script>", content_type="image/jpeg")
    with pytest.raises(RuleViolation, match="not a valid image"):
        images.process_photo(upload)


def test_gif_rejected():
    upload = image_file(name="anim.gif", fmt="GIF")
    with pytest.raises(RuleViolation, match="JPG, PNG or WebP"):
        images.process_photo(upload)


def test_huge_pixel_count_rejected(monkeypatch):
    monkeypatch.setattr(images, "MAX_SOURCE_PIXELS", 100)
    with pytest.raises(RuleViolation, match="too large"):
        images.process_photo(image_file(size=(20, 20)))


def test_truncated_image_rejected():
    data = image_file().read()[:200]
    upload = SimpleUploadedFile("cut.jpg", data, content_type="image/jpeg")
    with pytest.raises(RuleViolation):
        images.process_photo(upload)
