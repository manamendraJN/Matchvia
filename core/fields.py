from django.db import models

from .phone import InvalidPhone, normalise_phone, validate_phone


class PhoneField(models.CharField):
    """A Sri Lankan mobile number, normalised to ``+947XXXXXXXX`` whenever a value is cleaned.

    So ``0771234567`` typed into ``createsuperuser``, the admin or a ModelForm is stored the same
    way as on the sign-in page. Anything that can't be normalised is left as typed and then
    refused by ``validate_phone`` with the usual message.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 16)
        super().__init__(*args, **kwargs)
        if validate_phone not in self.validators:
            self.validators.append(validate_phone)

    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return value
        try:
            return normalise_phone(value)
        except InvalidPhone:
            return value
