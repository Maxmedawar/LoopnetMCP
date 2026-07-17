"""Listing-source registration and fault-isolated fan-out."""

import asyncio
from collections.abc import Iterable

from cre_mcp.config import CreConfig
from cre_mcp.models import AggregatedSearchResult, Listing
from cre_mcp.sources.base import ListingSource, SearchQuery, SourceError
from cre_mcp.sources.dedupe import merge


class SourceRegistry:
    """Registry of enabled listing providers."""

    def __init__(
        self,
        config: CreConfig | None = None,
        sources: Iterable[ListingSource] | None = None,
    ):
        self._config = config or CreConfig()
        self._sources: dict[str, ListingSource] = {}

        if sources is None:
            from cre_mcp.sources.crexi.source import CrexiSource
            from cre_mcp.sources.distressed import (
                AuctionComSource,
                CountySource,
                HudReoSource,
            )
            from cre_mcp.sources.loopnet.source import LoopnetSource

            configured_sources: dict[str, ListingSource] = {
                "loopnet": LoopnetSource(),
                "crexi": CrexiSource(),
                "hud_reo": HudReoSource(),
                "auction_com": AuctionComSource(),
                "county": CountySource(),
            }
            for name, source in configured_sources.items():
                toggle = self._config.sources.get(name)
                if toggle is None or toggle.enabled:
                    self.register(source)
        else:
            for source in sources:
                self.register(source)

    def register(self, source: ListingSource) -> None:
        """Add or replace a source by its stable name."""
        self._sources[source.name] = source

    def get(self, name: str) -> ListingSource:
        """Return a named source or raise a source-scoped error."""
        try:
            return self._sources[name]
        except KeyError as exc:
            raise SourceError(name, f"Unknown listing source: {name}") from exc

    async def search_all(
        self,
        query: SearchQuery,
        sources: list[str] | None = None,
    ) -> AggregatedSearchResult:
        """Fan out a search while isolating every source failure."""
        requested = self._sources.keys() if sources is None else sources
        requested_names = list(dict.fromkeys(requested))
        selected_names: list[str] = []
        selected_sources: list[ListingSource] = []
        errors: dict[str, str] = {}
        per_source_counts: dict[str, int] = {}

        for name in requested_names:
            try:
                source = self.get(name)
            except SourceError as exc:
                errors[name] = str(exc)
                per_source_counts[name] = 0
            else:
                selected_names.append(name)
                selected_sources.append(source)

        results = await asyncio.gather(
            *(source.search(query) for source in selected_sources),
            return_exceptions=True,
        )

        listings: list[Listing] = []
        for name, result in zip(selected_names, results):
            if isinstance(result, BaseException):
                errors[name] = str(result)
                per_source_counts[name] = 0
                continue
            per_source_counts[name] = len(result)
            listings.extend(result)

        listings, deduped = merge(listings)
        property_type = (
            query.property_type.value if query.property_type is not None else None
        )
        return AggregatedSearchResult(
            query_location=query.location,
            query_property_type=property_type,
            query_listing_type=query.listing_type.value,
            page=query.page,
            listings=listings,
            per_source_counts=per_source_counts,
            errors=errors,
            deduped=deduped,
        )
