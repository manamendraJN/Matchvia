"""Small PostgreSQL helpers."""

import hashlib

from django.db import connection


def advisory_xact_lock(key: str) -> None:
    """Take a PostgreSQL advisory lock for ``key`` until the current transaction ends.

    Serialises work on something that has no row to lock yet, for example all OTP
    requests for one phone number, so two parallel requests cannot both pass a count check.
    Must be called inside ``transaction.atomic()``.
    """
    if not connection.in_atomic_block:
        raise RuntimeError("advisory_xact_lock() must run inside transaction.atomic()")
    lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        # Parameterised; never string-formatted (CLAUDE.md rule 3).
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])
