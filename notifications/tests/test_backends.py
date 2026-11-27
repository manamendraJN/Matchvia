import io

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import override_settings

from notifications import services
from notifications.backends import locmem
from notifications.backends.base import BaseSmsBackend
from notifications.backends.console import ConsoleBackend
from notifications.backends.locmem import LocmemBackend
from notifications.models import SmsMessage


@override_settings(DEBUG=True)
def test_console_backend_prints_the_sms():
    stream = io.StringIO()
    message_id = ConsoleBackend(stream=stream).send("+94771234567", "Your code is 123456")

    output = stream.getvalue()
    assert "SMS to 077 123 4567" in output
    assert "Your code is 123456" in output
    assert message_id.startswith("console-")


@override_settings(DEBUG=False)
def test_console_backend_refuses_to_run_outside_development():
    with pytest.raises(ImproperlyConfigured, match="development"):
        ConsoleBackend()


def test_base_backend_is_abstract():
    with pytest.raises(NotImplementedError):
        BaseSmsBackend().send("+94771234567", "hi")


def test_get_backend_uses_settings():
    assert isinstance(services.get_backend(), LocmemBackend)


@pytest.fixture(autouse=True)
def _keep_test_connection(monkeypatch):
    # The worker closes stale connections between passes; inside a test that would close
    # the connection holding the test's transaction.
    monkeypatch.setattr(
        "notifications.management.commands.run_worker.close_old_connections", lambda: None
    )


@pytest.mark.django_db
def test_run_worker_once_sends_queued_messages():
    services.queue_sms(to_phone="+94771234567", purpose="venue_notice", body="Game at 7 pm")

    call_command("run_worker", "--once", stdout=io.StringIO())

    assert SmsMessage.objects.get().status == SmsMessage.Status.SENT
    assert locmem.outbox[0].text == "Game at 7 pm"


@pytest.mark.django_db
def test_run_worker_survives_a_failing_pass(monkeypatch, caplog):
    def broken(**kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr("notifications.management.commands.run_worker.send_due_messages", broken)
    call_command("run_worker", "--once", stdout=io.StringIO())
    assert "worker.job_failed" in caplog.text


@pytest.mark.django_db
def test_run_worker_loops_until_interrupted(monkeypatch):
    calls = []

    def fake_sleep(seconds):
        calls.append(seconds)
        if len(calls) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr("notifications.management.commands.run_worker.time.sleep", fake_sleep)
    out = io.StringIO()
    call_command("run_worker", stdout=out)
    assert calls == [5, 5]
    assert "Worker stopped." in out.getvalue()


@pytest.mark.django_db
def test_run_worker_writes_a_heartbeat_and_purges_daily(monkeypatch):
    from core import heartbeat

    calls = []
    monkeypatch.setattr("accounts.services.purge_old_otps", lambda: calls.append("otp") or 0)
    call_command("run_worker", "--once", stdout=io.StringIO())
    call_command("run_worker", "--once", stdout=io.StringIO())
    assert heartbeat.age_seconds("worker") is not None
    assert calls == ["otp"]  # once a day, not every pass
