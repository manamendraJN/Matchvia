class SmsSendError(Exception):
    """The gateway did not accept the message. The worker retries with backoff.

    The message text must never be put into this exception: it may end up in logs.
    """


class BaseSmsBackend:
    """Interface every gateway adapter implements."""

    def send(self, to_phone: str, text: str) -> str:
        """Send one SMS and return the provider's message id ("" if it has none).

        Raise SmsSendError on any failure. Must use a timeout (architecture 4.2: 10 s).
        """
        raise NotImplementedError
