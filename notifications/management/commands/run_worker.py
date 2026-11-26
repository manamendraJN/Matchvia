"""The background worker: ``python manage.py run_worker`` (architecture 4.1).

Runs in its own process next to the web server. In development, start it in a second terminal
to see SMS (including sign-in codes) printed by the console backend.

S08 adds the worker heartbeat; later steps add expiry and purge jobs to the same loop.
"""

import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from notifications.services import get_backend
from notifications.worker import send_due_messages

logger = logging.getLogger(__name__)

SEND_INTERVAL_SECONDS = 5


class Command(BaseCommand):
    help = "Run background jobs: send queued SMS (every 5 seconds)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one pass and exit.")

    def handle(self, *args, once: bool = False, **options):
        backend = get_backend()
        if not once:
            self.stdout.write("Worker started. Press Ctrl+C to stop.")
        try:
            while True:
                close_old_connections()
                try:
                    send_due_messages(backend=backend)
                except Exception:  # one bad pass must not stop the worker (architecture 4.2)
                    logger.exception("worker.send_sms failed")
                if once:
                    return
                time.sleep(SEND_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")
