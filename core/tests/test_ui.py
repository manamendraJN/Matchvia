"""UI foundation: icons, form fields, navigation (screens 1.2, 1.6)."""

import re
from pathlib import Path

import pytest
from django import forms
from django.conf import settings
from django.template import Context, Template
from django.urls import reverse

from accounts.tests.factories import UserFactory
from core.icons import ICONS
from core.templatetags.matchvia import icon

pytestmark = pytest.mark.django_db


def test_icons_are_decorative_unless_labelled():
    svg = icon("calendar", "size-6 text-green-700")
    assert svg.startswith("<svg")
    assert 'aria-hidden="true"' in svg
    assert 'class="size-6 text-green-700"' in svg
    labelled = icon("phone", label='Call "Kasun" <now>')
    assert 'role="img"' in labelled
    assert "aria-hidden" not in labelled
    assert "&lt;now&gt;" in labelled  # the label is escaped
    with pytest.raises(KeyError):
        icon("no-such-icon")


def test_every_icon_is_plain_svg_markup():
    for name, paths in ICONS.items():
        assert "<script" not in paths, name
        assert not re.search(r"\son\w+=", paths), name  # no event handlers
        assert paths.startswith("<"), name


def test_icon_tag_in_a_template():
    html = Template('{% load matchvia %}{% icon "search" "size-4" %}').render(Context())
    assert 'viewBox="0 0 24 24"' in html


class ChoicesForm(forms.Form):
    facilities = forms.MultipleChoiceField(
        label="Facilities",
        choices=[("parking", "Parking"), ("toilets", "Toilets")],
        widget=forms.CheckboxSelectMultiple,
        help_text="Tick what you have.",
    )


def test_checkbox_choices_have_their_labels():
    """Regression: the boxes used to render with no words next to them."""
    form = ChoicesForm(data={})
    form.is_valid()
    html = Template('{% include "components/field.html" with field=form.facilities %}').render(
        Context({"form": form})
    )
    assert '<label for="id_facilities_0" class="choice">' in html
    assert "Parking" in html
    assert "Toilets" in html
    assert "Tick what you have." in html
    assert "This field is required." in html
    assert 'aria-hidden="true"' in html  # the error carries an icon too


def test_tailwind_reads_classes_set_in_python():
    """Regression: field styles live in Python, so Tailwind must scan those files."""
    source = (Path(settings.BASE_DIR) / "assets" / "tailwind.css").read_text(encoding="utf-8")
    assert '@source "../core/*.py";' in source
    assert '@source "../*/forms.py";' in source


def test_player_bottom_bar_has_icons_and_marks_the_current_page(client):
    client.force_login(UserFactory())
    html = client.get(reverse("my_bookings")).content.decode()
    nav = html[html.index('<nav class="fixed') :]
    assert nav.count("<svg") == 4
    assert 'aria-current="page"' in nav
    for label in ("Search", "My bookings", "Teams", "Account"):
        assert label in nav


def test_signed_out_header_offers_sign_in(client):
    html = client.get(reverse("home")).content.decode()
    assert reverse("accounts:phone") in html
