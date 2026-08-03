"""Listing-source registration and fault-isolated fan-out."""

import asyncio
from collections.abc import Iterable

from cre_mcp.access.context import current_runtime_config
from cre_mcp.config import CreConfig
from cre_mcp.models import AggregatedSearchResult, Listing
from cre_mcp.sources.base import ListingSource, SearchQuery, SourceError
from cre_mcp.sources.dedupe import merge
from cre_mcp.source_rights.gate import SourceRightsDeniedError, require_source
from cre_mcp.source_rights.output import safe_error_message


class SourceRegistry:
    """Registry of enabled listing providers."""

    def __init__(
        self,
        config: CreConfig | None = None,
        sources: Iterable[ListingSource] | None = None,
    ):
        self._config = config or CreConfig()
        self._explicit_sources = sources is not None
        self._sources: dict[str, ListingSource] = {}

        if sources is None:
            for name in (
                "loopnet",
                "crexi",
                "hud_reo",
                "auction_com",
                "county",
            ):
                toggle = self._config.sources.get(name)
                if toggle is not None and toggle.enabled:
                    source = self._build_configured_source(name)
                    if source is not None:
                        self.register(source)
        else:
            for source in sources:
                self.register(source)

    @staticmethod
    def _build_configured_source(name: str) -> ListingSource | None:
        from cre_mcp.sources.crexi.source import CrexiSource
        from cre_mcp.sources.distressed import (
            AuctionComSource,
            CountySource,
            HudReoSource,
        )
        from cre_mcp.sources.loopnet.source import LoopnetSource

        factories = {
            "loopnet": LoopnetSource,
            "crexi": CrexiSource,
            "hud_reo": HudReoSource,
            "auction_com": AuctionComSource,
            "county": CountySource,
        }
        factory = factories.get(name)
        return factory() if factory is not None else None

    def register(self, source: ListingSource) -> None:
        """Add or replace a source by its stable name."""
        self._sources[source.name] = source

    def get(self, name: str) -> ListingSource:
        """Return a named source or raise a source-scoped error."""
        try:
            return self._sources[name]
        except KeyError as exc:
            raise SourceError(name, f"Unknown listing source: {name}") from exc

    def get_authorized(self, name: str) -> ListingSource:
        """Resolve one source under the active feature and rights configuration."""
        config = current_runtime_config() or self._config
        if not self._explicit_sources:
            toggle = config.sources.get(name)
            if toggle is None or not toggle.enabled:
                raise SourceError(name, f"Listing source is disabled: {name}")
            if name not in self._sources:
                source = self._build_configured_source(name)
                if source is None:
                    raise SourceError(name, f"Unknown listing source: {name}")
                self.register(source)
        source = self.get(name)
        require_source(name, config=config)
        return source

    async def search_all(
        self,
        query: SearchQuery,
        sources: list[str] | None = None,
    ) -> AggregatedSearchResult:
        """Fan out a search while isolating every source failure."""
        config = current_runtime_config() or self._config
        requested = self._sources.keys() if sources is None else sources
        requested_names = list(dict.fromkeys(requested))
        selected_names: list[str] = []
        selected_sources: list[ListingSource] = []
        errors: dict[str, str] = {}
        per_source_counts: dict[str, int] = {}

        for name in requested_names:
            try:
                source = self.get_authorized(name)
            except (SourceError, SourceRightsDeniedError) as exc:
                errors[name] = safe_error_message(exc, config=config)
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
                errors[name] = safe_error_message(result, config=config)
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
