"""The background worker: ``python manage.py run_worker`` (architecture 4.1).

Runs in its own process next to the web server. In development, start it in a second terminal
to see SMS (including sign-in codes) printed by the console backend.

Jobs: send due SMS every 5 seconds, write a heartbeat for /healthz, and once a day remove
personal data that is no longer needed (OTP rows after 24 h, SMS phone numbers after 90 days).
"""

import logging
import time

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from accounts import services as accounts
from core import heartbeat
from notifications import services as notifications
from notifications.services import get_backend
from notifications.worker import send_due_messages

logger = logging.getLogger(__name__)

SEND_INTERVAL_SECONDS = 5
PURGE_EVERY_SECONDS = 24 * 3600
PURGE_KEY = "worker:last_purge"


def purge_personal_data() -> None:
    """Minimum data (PDPA, architecture 5.2). Runs at most once a day across all workers."""
    if not cache.add(PURGE_KEY, time.time(), timeout=PURGE_EVERY_SECONDS):
        return
    otps = accounts.purge_old_otps()
    phones = notifications.forget_old_phone_numbers()
    logger.info("worker.purge otp_rows=%s sms_numbers=%s", otps, phones)


class Command(BaseCommand):
    help = "Run background jobs: send queued SMS, heartbeat, daily clean-up."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one pass and exit.")

    def handle(self, *args, once: bool = False, **options):
        backend = get_backend()
        if not once:
            self.stdout.write("Worker started. Press Ctrl+C to stop.")
        try:
            while True:
                close_old_connections()
                for job in (lambda: send_due_messages(backend=backend), purge_personal_data):
                    try:
                        job()
                    except Exception:  # one failing job must not stop the others (architecture 4.2)
                        logger.exception("worker.job_failed")
                heartbeat.beat("worker")
                if once:
                    return
                time.sleep(SEND_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")
