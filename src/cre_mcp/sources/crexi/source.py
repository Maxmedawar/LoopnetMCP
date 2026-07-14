"""Crexi implementation of the listing-source interface."""

import logging
from typing import Any

from cre_mcp.http.errors import (
    FetchBlockedError,
    FetchClientError,
    FetchRateLimitError,
)
from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.models import Listing, ListingRef, SourceCapabilities
from cre_mcp.sources.base import ListingSource, SearchQuery, SourceError
from cre_mcp.sources.crexi.mapping import (
    build_id_search_body,
    build_search_body,
    map_asset,
)

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.crexi.com/universal-search/v2/search"
DETAIL_URL = "https://api.crexi.com/assets/{source_id}"


def _retryable(exc: FetchClientError) -> bool:
    return isinstance(exc, FetchRateLimitError) or not isinstance(
        exc,
        FetchBlockedError,
    )


def _matches_numeric_filters(listing: Listing, query: SearchQuery) -> bool:
    if query.price_min is not None and (
        listing.price_usd is None or listing.price_usd < query.price_min
    ):
        return False
    if query.price_max is not None and (
        listing.price_usd is None or listing.price_usd > query.price_max
    ):
        return False
    if query.size_min is not None and (
        listing.size_sqft_num is None or listing.size_sqft_num < query.size_min
    ):
        return False
    if query.size_max is not None and (
        listing.size_sqft_num is None or listing.size_sqft_num > query.size_max
    ):
        return False
    return True


class CrexiSource(ListingSource):
    """Crexi source backed by its JSON API and the shared FetchClient."""

    name = "crexi"
    capabilities = SourceCapabilities(detail_is_expensive=False)

    def __init__(self, client: FetchClient | None = None):
        self._client = client

    @property
    def client(self) -> FetchClient:
        return self._client or get_fetch_client()

    async def search(self, query: SearchQuery) -> list[Listing]:
        try:
            payload = await self.client.post_json(
                SEARCH_URL,
                build_search_body(query),
            )
        except FetchClientError as exc:
            raise SourceError(self.name, str(exc), retryable=_retryable(exc)) from exc

        assets: Any
        if isinstance(payload, dict):
            assets = payload.get("items", payload.get("data", payload.get("assets")))
        else:
            assets = payload
        if not isinstance(assets, list):
            raise SourceError(
                self.name,
                "Crexi search response did not contain a listing array",
            )

        listings: list[Listing] = []
        for asset in assets:
            if not isinstance(asset, dict):
                logger.debug("Ignoring non-object Crexi search item: %r", asset)
                continue
            listing = map_asset(asset)
            if _matches_numeric_filters(listing, query):
                listings.append(listing)
        return listings

    async def get_detail(self, ref: ListingRef) -> Listing:
        if ref.source != self.name:
            raise SourceError(
                self.name,
                f"Crexi source cannot resolve a {ref.source!r} reference",
            )
        url = DETAIL_URL.format(source_id=ref.source_id)
        try:
            payload = await self.client.get_json(url)
        except FetchClientError as exc:
            raise SourceError(self.name, str(exc), retryable=_retryable(exc)) from exc
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        if not isinstance(payload, dict):
            raise SourceError(self.name, "Crexi detail response was not an object")
        listing = map_asset(payload)
        if listing.broker_name is None:
            # Crexi's detail payload often omits the marketing broker while the
            # targeted universal-search record contains brokers[]. Broker recovery
            # is supplementary: a search failure must not discard valid detail.
            try:
                search_payload = await self.client.post_json(
                    SEARCH_URL,
                    build_id_search_body(ref.source_id),
                )
                items = (
                    search_payload.get("items", [])
                    if isinstance(search_payload, dict)
                    else []
                )
                for item in items if isinstance(items, list) else []:
                    if not isinstance(item, dict):
                        continue
                    candidate = map_asset(item)
                    if candidate.source_id != listing.source_id:
                        continue
                    listing = listing.model_copy(
                        update={
                            "broker_name": candidate.broker_name,
                            "broker_company": candidate.broker_company,
                            "broker_phone": candidate.broker_phone,
                        }
                    )
                    break
            except Exception as exc:
                logger.warning(
                    "Crexi broker recovery failed non-fatally for %s: %s",
                    ref.source_id,
                    exc,
                )
        return listing
