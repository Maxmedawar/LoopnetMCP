"""Base interfaces shared by listing sources."""

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel

from cre_mcp.http.errors import FetchClientError
from cre_mcp.models import (
    Listing,
    ListingRef,
    ListingType,
    PropertyType,
    SourceCapabilities,
)


class SearchQuery(BaseModel):
    """Normalized search criteria supplied to listing sources."""

    location: str
    geo: Any | None = None
    property_type: PropertyType | None = None
    listing_type: ListingType = ListingType.FOR_SALE
    price_min: int | None = None
    price_max: int | None = None
    price_type: str | None = None
    size_min: int | None = None
    size_max: int | None = None
    distressed_only: bool = False
    page: int = 1


class SourceError(FetchClientError):
    """A source-scoped error that callers may safely isolate."""

    def __init__(
        self,
        source_name: str,
        message: str,
        retryable: bool = False,
    ):
        self.source_name = source_name
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class ListingSource(ABC):
    """Interface implemented by every listing provider."""

    name: ClassVar[str]
    capabilities: ClassVar[SourceCapabilities]

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[Listing]:
        """Return listings matching a normalized query."""

    @abstractmethod
    async def get_detail(self, ref: ListingRef) -> Listing:
        """Return a detailed listing for a source reference."""
