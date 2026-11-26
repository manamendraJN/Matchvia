import pytest
from django.core.exceptions import ValidationError

from core.fields import PhoneField


@pytest.mark.parametrize("typed", ["0764390987", "764390987", "076 439 0987", "+94764390987"])
def test_clean_normalises_any_common_format(typed):
    assert PhoneField().clean(typed, None) == "+94764390987"


@pytest.mark.parametrize("typed", ["0112345678", "+447911123456", "phone"])
def test_clean_rejects_non_mobile_numbers(typed):
    with pytest.raises(ValidationError, match="valid Sri Lankan mobile number"):
        PhoneField().clean(typed, None)


def test_blank_allowed_when_field_allows_it():
    assert PhoneField(null=True, blank=True).clean("", None) == ""
