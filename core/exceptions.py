"""Domain exceptions raised by services and translated into messages by views (architecture 2.3)."""

import math


class DomainError(Exception):
    """Base class for business-rule failures. ``message`` is safe to show to the user."""

    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


class RuleViolation(DomainError):
    """A business rule refused the action (for example a booking limit)."""


class NotAllowed(DomainError):
    """The acting user may not do this."""


class SlotTaken(DomainError):
    """The database rejected an overlapping booking (CLAUDE.md rule 1)."""


class RateLimited(DomainError):
    """Too many requests. ``retry_after`` is the wait in whole seconds (at least 1)."""

    def __init__(self, retry_after: float, message: str = ""):
        super().__init__(message)
        self.retry_after = max(1, math.ceil(retry_after))

    @property
    def retry_after_minutes(self) -> int:
        return max(1, math.ceil(self.retry_after / 60))
