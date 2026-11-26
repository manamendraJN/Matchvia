"""Booking references like MV-7K3P9Q (requirements 3).

No characters people confuse when reading or typing (0/O, 1/I). 6 characters from 32 gives about
a billion codes; collisions are retried by the service on the unique constraint.
"""

import secrets

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # data-model 3.4
LENGTH = 6


def generate_reference() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def normalise_reference(value: str) -> str:
    """Accept 'mv-7k3p9q', 'MV7K3P9Q' or '7K3P9Q' as typed by people; return '7K3P9Q'."""
    code = "".join(ch for ch in (value or "").upper() if ch.isalnum())
    return code.removeprefix("MV")
