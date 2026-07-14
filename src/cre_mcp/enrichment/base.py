"""Source-agnostic parcel and comparable-provider interfaces."""

from typing import Protocol

from cre_mcp.market.base import ProviderUnavailableError
from cre_mcp.models.comps import CompsProviderResult
from cre_mcp.models.enrichment import ParcelRecord
from cre_mcp.models.geo import GeoRef
from cre_mcp.models.listings import Listing


class ParcelProvider(Protocol):
    """Interface implemented by public and future paid parcel providers."""

    async def lookup(
        self,
        address: str | None,
        apn: str | None,
        geo: GeoRef | None,
    ) -> ParcelRecord | None:
        """Return the best matching parcel, or ``None`` when none is found."""
        ...


class CompsProvider(Protocol):
    """Interface for opt-in providers that can strengthen a value anchor."""

    async def get_comps(
        self,
        subject: Listing,
        geo: GeoRef | None,
    ) -> CompsProviderResult:
        """Return normalized sale comps and/or a labeled value estimate."""
        ...


# Short name used by provider-facing code while preserving the established error type.
ProviderUnavailable = ProviderUnavailableError


__all__ = [
    "CompsProvider",
    "ParcelProvider",
    "ProviderUnavailable",
    "ProviderUnavailableError",
]
