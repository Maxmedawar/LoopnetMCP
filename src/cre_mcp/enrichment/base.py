"""Source-agnostic parcel-provider interface."""

from typing import Protocol

from cre_mcp.models.enrichment import ParcelRecord
from cre_mcp.models.geo import GeoRef


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


__all__ = ["ParcelProvider"]
