"""Backward-compatible browser exports."""

from cre_mcp.http.browser import (
    CHALLENGE_DETECTORS,
    BrowserFetchError,
    BrowserFetcher,
    is_challenge_page,
)

__all__ = [
    "BrowserFetchError",
    "BrowserFetcher",
    "CHALLENGE_DETECTORS",
    "is_challenge_page",
]
