"""Turn a rate limit that no view handled into the friendly 429 page (P20)."""

from django.shortcuts import render

from core.exceptions import RateLimited


class RateLimitedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, RateLimited):
            response = render(request, "429.html", status=429)
            response["Retry-After"] = str(exception.retry_after)
            return response
        return None
