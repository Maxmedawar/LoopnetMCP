"""Shared test fixtures."""

import json
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


def write_cached_rights_registry(
    tmp_path: Path,
    source_ids: set[str],
    *,
    ttl_seconds: int = 3_600,
) -> Path:
    """Create a test-only registry authorizing raw cache retention.

    Production records stay deny-first. Provider cache tests use this explicit
    fixture to model an operative local license with a finite retention term.
    """
    registry_path = (
        Path(__file__).parents[1]
        / "src"
        / "cre_mcp"
        / "source_rights"
        / "registry.json"
    )
    catalog = json.loads(registry_path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for source in catalog["sources"]:
        source_id = source.get("source_id")
        if source_id not in source_ids:
            continue
        found.add(source_id)
        allowances = {
            **catalog["defaults"]["allowances"],
            **source.get("allowances", {}),
            "raw_retention": True,
        }
        operating_policy = {
            **catalog["defaults"]["operating_policy"],
            **source.get("operating_policy", {}),
            "memory_cache_ttl_seconds": ttl_seconds,
            "persistent_cache_ttl_seconds": ttl_seconds,
            "raw_retention_ttl_seconds": ttl_seconds,
        }
        source["allowances"] = allowances
        source["raw_storage_allowed"] = True
        source["operating_policy"] = operating_policy
    missing = source_ids - found
    if missing:
        raise AssertionError(f"unknown source-rights fixture IDs: {sorted(missing)}")
    output = tmp_path / "source-rights-cache-fixture.json"
    output.write_text(json.dumps(catalog), encoding="utf-8")
    return output


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


@pytest.fixture
def legacy_loopnet_runtime():
    """Declare the trusted-local authority used by legacy LoopNet tool tests."""
    from cre_mcp.access.context import local_context, use_context
    from cre_mcp.config import CreConfig
    from cre_mcp.sources.registry import SourceRegistry

    config = CreConfig(
        _env_file=None,
        transport="stdio",
        sources={"loopnet": {"enabled": True}},
        source_rights_enabled={"listing.loopnet": True},
    )
    registry = SourceRegistry(config=config)
    with use_context(local_context()), patch(
        "cre_mcp.tools.listing_tools.registry",
        registry,
    ):
        yield
