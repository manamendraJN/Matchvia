import sys
import uuid

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from core.phone import format_local

from .base import BaseSmsBackend


class ConsoleBackend(BaseSmsBackend):
    """Development only: prints each SMS to the worker's terminal instead of sending it.

    It writes to stdout, not to the logging system, so codes never reach log files or
    monitoring. It refuses to run unless DEBUG is on, so it can't be switched on in production.
    """

    def __init__(self, stream=None):
        if not settings.DEBUG:
            raise ImproperlyConfigured("ConsoleBackend is for development only (DEBUG=True).")
        self.stream = stream or sys.stdout

    def send(self, to_phone: str, text: str) -> str:
        message_id = f"console-{uuid.uuid4().hex[:12]}"
        rule = "-" * 60
        self.stream.write(
            f"{rule}\nSMS to {format_local(to_phone)}  [{message_id}]\n{text}\n{rule}\n"
        )
        self.stream.flush()
        return message_id
