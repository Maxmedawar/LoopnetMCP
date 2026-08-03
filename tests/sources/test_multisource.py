"""Tests for multi-source search aggregation and tool serialization."""

from unittest.mock import patch

import pytest

from cre_mcp.models import Listing, ListingRef, SourceCapabilities
from cre_mcp.sources.base import ListingSource, SearchQuery
from cre_mcp.sources.registry import SourceRegistry
from cre_mcp.tools.listing_tools import search_properties


def _listing(source: str, source_id: str, **overrides) -> Listing:
    values = {
        "source": source,
        "source_id": source_id,
        "refs": [
            ListingRef(
                source=source,
                source_id=source_id,
                url=f"https://{source}.example/{source_id}",
            )
        ],
        "name": "Congress Avenue Office",
        "address": "100 Congress Avenue",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78701",
        "url": f"https://{source}.example/{source_id}",
    }
    values.update(overrides)
    return Listing(**values)


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


@pytest.mark.asyncio
async def test_multisource_merge_prefers_crexi_and_unions_provenance():
    loopnet = FakeSource(
        "loopnet",
        [_listing("loopnet", "ln-1", broker_company="CBRE", units=10)],
    )
    crexi = FakeSource(
        "crexi",
        [_listing("crexi", "cx-1", price_usd=3_500_000, price="$3,500,000")],
    )
    failing = FakeSource("failing", error=RuntimeError("temporarily unavailable"))
    registry = SourceRegistry(sources=[loopnet, crexi, failing])

    result = await registry.search_all(SearchQuery(location="Austin, TX"))

    assert result.per_source_counts == {"loopnet": 1, "crexi": 1, "failing": 0}
    assert result.errors == {"failing": "temporarily unavailable"}
    assert result.deduped == 1
    assert len(result.listings) == 1
    merged = result.listings[0]
    assert merged.source == "crexi"
    assert merged.price_usd == 3_500_000
    assert merged.broker_company == "CBRE"
    assert merged.units == 10
    assert merged.also_listed_on == ["loopnet"]
    assert {ref.source for ref in merged.refs} == {"loopnet", "crexi"}


@pytest.mark.asyncio
async def test_search_properties_explicit_sources_returns_rich_shape():
    registry = SourceRegistry(
        sources=[
            FakeSource("loopnet", [_listing("loopnet", "ln-1")]),
            FakeSource("crexi", [_listing("crexi", "cx-2", address="200 Congress Ave")]),
        ]
    )

    with patch("cre_mcp.tools.listing_tools.registry", registry):
        result = await search_properties(
            "Austin, TX",
            sources=["loopnet", "crexi"],
        )

    assert set(result) == {
        "query_location",
        "query_property_type",
        "query_listing_type",
        "page",
        "listings",
        "per_source_counts",
        "errors",
        "deduped",
    }
    assert result["per_source_counts"] == {"loopnet": 1, "crexi": 1}
    assert len(result["listings"]) == 2
    assert result["errors"] == {}
