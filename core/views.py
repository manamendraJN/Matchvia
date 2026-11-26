import logging

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@never_cache
@require_GET
def healthz(request):
    """Health check for the uptime monitor and deploy script (architecture 4.2, 6.5).

    Reports only coarse status, never versions or error details. The worker heartbeat
    is added in S08.
    """
    checks = {"database": "ok"}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        logger.exception("Health check: database unavailable")
        checks["database"] = "error"

    healthy = all(value == "ok" for value in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "error", **checks},
        status=200 if healthy else 503,
    )
