import pytest
from django.core.exceptions import ValidationError

from core.phone import InvalidPhone, format_local, mask_phone, normalise_phone, validate_phone


@pytest.mark.parametrize(
    "raw",
    [
        "0771234567",
        "771234567",
        "+94771234567",
        "94771234567",
        "0094771234567",
        "077 123 4567",
        "077-123-4567",
        "+94 77 123 4567",
        "(077) 123-4567",
        "077.123.4567",
        "  0771234567  ",
        "077\u00a0123\u00a04567",
    ],
)
def test_common_formats_normalise_to_e164(raw):
    assert normalise_phone(raw) == "+94771234567"


@pytest.mark.parametrize("prefix", ["70", "71", "72", "74", "75", "76", "77", "78"])
def test_all_mobile_prefixes_accepted(prefix):
    assert normalise_phone(f"0{prefix}1234567") == f"+94{prefix}1234567"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "0112345678",  # Colombo landline
        "+94112345678",  # landline in E.164
        "0812345678",  # Kandy landline
        "077123456",  # too short
        "07712345678",  # too long
        "+9477123456",  # too short after +94
        "+447911123456",  # UK mobile
        "+14155552671",  # US
        "+91771234567",  # India, same national digits
        "077123456a",
        "٠٧٧١٢٣٤٥٦٧",  # Arabic-Indic digits
        "+94+771234567",
        "phone",
    ],
)
def test_invalid_numbers_rejected(raw):
    with pytest.raises(InvalidPhone):
        normalise_phone(raw)


def test_non_string_rejected():
    with pytest.raises(InvalidPhone):
        normalise_phone(771234567)  # type: ignore[arg-type]


def test_validate_phone_requires_normalised_form():
    validate_phone("+94771234567")
    for value in ["0771234567", "+94112345678", None]:
        with pytest.raises(ValidationError):
            validate_phone(value)


def test_mask_phone_hides_middle_digits():
    assert mask_phone("+94771234567") == "+9477****567"
    assert mask_phone(None) == "-"
    assert mask_phone("") == "-"
    assert mask_phone("+9477") == "****"


def test_format_local():
    assert format_local("+94771234567") == "077 123 4567"
    assert format_local("") == ""
    assert format_local("not-a-phone") == "not-a-phone"
