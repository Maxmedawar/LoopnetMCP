"""Shared test fixtures."""

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@dataclass
class MockResponse:
    """Lightweight mock for curl_cffi response objects."""

    status_code: int
    text: str = ""


def load_fixture(name: str) -> str:
    """Read and return the contents of a test fixture file."""
    fixture_path = Path(__file__).parent / "fixtures" / name
    return fixture_path.read_text()


def pytest_addoption(parser):
    """Register opt-in golden snapshot regeneration."""
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate Phase 5 deal-score golden snapshots.",
    )


@pytest.fixture(autouse=True)
def _skip_warmup():
    """Skip the homepage warmup request in all tests."""
    with patch(
        "cre_mcp.scraper.client.LoopnetClient._warmup",
        new_callable=AsyncMock,
    ):
        yield


@pytest.fixture(autouse=True)
def _disable_browser_fetcher():
    """Prevent real browser launches in all tests."""
    with patch(
        "cre_mcp.scraper.browser.BrowserFetcher._ensure_browser",
        new_callable=AsyncMock,
    ):
        yield
