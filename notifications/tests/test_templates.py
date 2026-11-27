"""SMS texts: translatable templates, plain GSM-7 characters, one 160-character SMS (C7)."""

from pathlib import Path

import pytest

from notifications import services

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "sms"

# Realistic, slightly long values (a long venue name, a late-night time, a big price).
TYPICAL = {
    "code": "482913",
    "ref": "MV-7K3P9Q",
    "venue": "Kick Off Futsal Arena",
    "court": "Court 2",
    "when": "Sat 12 Dec, 11:00 pm-12:00 am",
    "price": "Rs. 12,000",
    "venue_phone": "077 123 4567",
    "reason": "The photos don't show a sports venue.",
}


def test_every_template_is_tested():
    names = {p.stem for p in TEMPLATES.glob("*.txt")}
    assert names == {
        "otp",
        "booking_confirmation",
        "booking_cancelled",
        "booking_changed",
        "reminder",
        "staff_added",
        "venue_approved",
        "venue_rejected",
        "venue_suspended",
        "venue_unsuspended",
    }


@pytest.mark.parametrize("name", sorted(p.stem for p in TEMPLATES.glob("*.txt")))
def test_one_plain_sms(name):
    text = services.render_sms(name, **TYPICAL)
    assert "{" not in text
    assert "%" not in text
    assert services.is_gsm7(text), f"{name}: {set(text) - services.GSM7_CHARACTERS}"
    assert len(text) <= services.SINGLE_SMS_LENGTH, f"{name}: {len(text)} characters"


@pytest.mark.parametrize("name", sorted(p.stem for p in TEMPLATES.glob("*.txt")))
def test_templates_are_translatable(name):
    source = (TEMPLATES / f"{name}.txt").read_text(encoding="utf-8")
    assert "{% blocktranslate" in source


def test_sms_text_is_not_html_escaped():
    text = services.render_sms("venue_approved", venue="Ball & Bat <Arena>")
    assert "Ball & Bat <Arena>" in text


def test_en_dash_would_break_gsm7():
    assert not services.is_gsm7("7:00 pm–8:00 pm")
    assert services.is_gsm7("7:00 pm-8:00 pm")
