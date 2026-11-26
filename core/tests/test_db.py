import threading

import pytest
from django.db import connection, transaction

from core.db import advisory_xact_lock


@pytest.mark.django_db(transaction=True)
def test_advisory_lock_requires_a_transaction():
    with pytest.raises(RuntimeError):
        advisory_xact_lock("otp:+94771234567")


@pytest.mark.django_db(transaction=True)
def test_advisory_lock_blocks_a_second_transaction_until_commit():
    holder_has_lock = threading.Event()
    release = threading.Event()
    order = []

    def holder():
        with transaction.atomic():
            advisory_xact_lock("key-1")
            order.append("holder-locked")
            holder_has_lock.set()
            release.wait(timeout=5)
            order.append("holder-releasing")
        connection.close()

    thread = threading.Thread(target=holder)
    thread.start()
    assert holder_has_lock.wait(timeout=5)

    def try_lock():
        with transaction.atomic():
            advisory_xact_lock("key-1")
            order.append("second-locked")
        connection.close()

    second = threading.Thread(target=try_lock)
    second.start()
    second.join(timeout=0.5)
    assert second.is_alive(), "second transaction should wait for the lock"

    release.set()
    thread.join(timeout=5)
    second.join(timeout=5)
    assert order == ["holder-locked", "holder-releasing", "second-locked"]
