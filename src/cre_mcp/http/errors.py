"""Exceptions raised by shared HTTP fetching infrastructure."""


class FetchClientError(Exception):
    """Base exception for fetch client errors."""


class FetchBlockedError(FetchClientError):
    """Raised when a source returns 403 (blocked/forbidden)."""


class FetchRateLimitError(FetchClientError):
    """Raised when a source returns 429 and retries are exhausted."""
