"""Backward-compatible browser exports."""

from cre_mcp.http.browser import (
    CHALLENGE_DETECTORS,
    BrowserFetchError,
    BrowserFetcher,
    is_challenge_page,
    is_cloudflare_challenge,
    is_imperva_challenge,
)

__all__ = [
    "BrowserFetchError",
    "BrowserFetcher",
    "CHALLENGE_DETECTORS",
    "is_challenge_page",
    "is_cloudflare_challenge",
    "is_imperva_challenge",
]
