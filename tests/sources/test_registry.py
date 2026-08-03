"""Tests for source registry fan-out and failure isolation."""

import pytest

from cre_mcp.config import CreConfig
from cre_mcp.models import Listing, ListingRef, SourceCapabilities
from cre_mcp.sources.base import ListingSource, SearchQuery, SourceError
from cre_mcp.sources.registry import SourceRegistry


def _listing(
    source: str,
    source_id: str,
    address: str,
    *,
    name: str | None = None,
) -> Listing:
    url = f"https://{source}.example/{source_id}"
    return Listing(
        source=source,
        source_id=source_id,
        refs=[ListingRef(source=source, source_id=source_id, url=url)],
        name=name or f"{source} listing",
        address=address,
        city="Dallas",
        state="TX",
        zip_code="75201",
        url=url,
    )


class FakeSource(ListingSource):
    capabilities = SourceCapabilities()

    def __init__(
        self,
        name: str,
        listings: list[Listing] | None = None,
        error: Exception | None = None,
    ):
        self.name = name
        self._listings = listings or []
        self._error = error

    async def search(self, query: SearchQuery) -> list[Listing]:
        if self._error is not None:
            raise self._error
        return self._listings

    async def get_detail(self, ref: ListingRef) -> Listing:
        return self._listings[0]


def _rights_config(*source_ids: str) -> CreConfig:
    return CreConfig(
        _env_file=None,
        transport="stdio",
        source_rights_enabled={source_id: True for source_id in source_ids},
    )


async def test_search_all_fans_out_to_both_sources():
    alpha = FakeSource("alpha", [_listing("alpha", "1", "101 Main St")])
    beta = FakeSource("beta", [_listing("beta", "2", "202 Oak Ave")])
    registry = SourceRegistry(
        config=_rights_config("unclassified.network"),
        sources=[alpha, beta],
    )

    result = await registry.search_all(SearchQuery(location="Dallas, TX"))

    assert {listing.source for listing in result.listings} == {"alpha", "beta"}
    assert result.per_source_counts == {"alpha": 1, "beta": 1}
    assert result.errors == {}
    assert result.deduped == 0


async def test_search_all_captures_one_error_and_keeps_other_results():
    working = FakeSource("working", [_listing("working", "1", "101 Main St")])
    failing = FakeSource("failing", error=RuntimeError("source unavailable"))
    registry = SourceRegistry(
        config=_rights_config("unclassified.network"),
        sources=[working, failing],
    )

    result = await registry.search_all(SearchQuery(location="Dallas, TX"))

    assert [listing.source for listing in result.listings] == ["working"]
    assert result.per_source_counts == {"working": 1, "failing": 0}
    assert result.errors == {"failing": "source unavailable"}


async def test_search_all_dedupes_collision_and_unions_refs():
    loopnet = FakeSource(
        "loopnet",
        [_listing("loopnet", "ln-1", "101 Main Street, Suite 200")],
    )
    crexi_listing = _listing("crexi", "cx-1", "101 Main St")
    crexi_listing.price = "$2,000,000"
    crexi = FakeSource("crexi", [crexi_listing])
    registry = SourceRegistry(
        config=_rights_config("listing.loopnet", "listing.crexi"),
        sources=[loopnet, crexi],
    )

    result = await registry.search_all(SearchQuery(location="Dallas, TX"))

    assert len(result.listings) == 1
    assert result.deduped == 1
    merged = result.listings[0]
    assert {ref.source for ref in merged.refs} == {"loopnet", "crexi"}
    assert merged.also_listed_on == ["loopnet"]
    assert merged.source == "crexi"


def test_registry_instantiates_only_enabled_configured_sources():
    registry = SourceRegistry(
        config=CreConfig(
            sources={
                "loopnet": {"enabled": False},
                "crexi": {"enabled": True},
            }
        )
    )

    assert registry.get("crexi").name == "crexi"
    with pytest.raises(SourceError, match="Unknown listing source: loopnet"):
        registry.get("loopnet")


def test_registry_has_no_default_distressed_sources():
    registry = SourceRegistry()

    for source_name in ("hud_reo", "auction_com", "county"):
        with pytest.raises(SourceError, match=f"Unknown listing source: {source_name}"):
            registry.get(source_name)
