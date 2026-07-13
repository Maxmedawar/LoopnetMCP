"""Listing-text and OpenStreetMap attribute enrichment."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlencode

from cre_mcp.http.fetch import FetchClient, get_fetch_client
from cre_mcp.models.attributes import DealAttributes
from cre_mcp.models.listings import Listing

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_DRIVE_THRU_PATTERN = re.compile(
    r"\b(?:drive[- ]?thru|drive[- ]?through|drive[- ]?up window)\b",
    re.IGNORECASE,
)
_NO_DRIVE_THRU_PATTERN = re.compile(
    r"\b(?:no|without)\s+(?:a\s+)?drive[- ]?(?:thru|through)\b",
    re.IGNORECASE,
)
_PARKING_RATIO_PATTERN = re.compile(
    r"(?P<ratio>\d+(?:\.\d+)?)\s*(?:/|per)\s*(?:1,?000|m)\s*(?:sf|sq\.?\s*ft)",
    re.IGNORECASE,
)
_PARKING_SPACES_PATTERN = re.compile(
    r"(?P<spaces>\d[\d,]*)\s+(?:parking\s+)?spaces?\b",
    re.IGNORECASE,
)


def _listing_text(listing: Listing) -> str:
    chunks = [listing.name, listing.description or "", *listing.highlights]
    for key in (
        "description",
        "highlights",
        "amenities",
        "propertyHighlights",
        "marketingRemarks",
    ):
        value = listing.raw.get(key)
        if isinstance(value, list):
            chunks.extend(str(item) for item in value)
        elif value not in (None, ""):
            chunks.append(str(value))
    return " \n".join(chunks)


def drive_thru_from_text(listing: Listing) -> bool | None:
    """Extract an explicit drive-thru assertion from listing copy."""
    text = _listing_text(listing)
    if _NO_DRIVE_THRU_PATTERN.search(text):
        return False
    if _DRIVE_THRU_PATTERN.search(text):
        return True
    return None


def parking_from_listing(listing: Listing) -> str | None:
    """Prefer the source's explicit parking field over public-map inference."""
    if listing.parking:
        return listing.parking.strip() or None
    for key in ("parking", "parkingSpaces", "parking_ratio", "parkingRatio"):
        value = listing.raw.get(key)
        if value not in (None, ""):
            return str(value).strip() or None
    return None


def parking_ratio(parking: str | None, size_sqft: float | None = None) -> float | None:
    """Return spaces per 1,000 square feet when the listing exposes enough data."""
    if not parking:
        return None
    ratio_match = _PARKING_RATIO_PATTERN.search(parking)
    if ratio_match:
        return float(ratio_match.group("ratio"))
    spaces_match = _PARKING_SPACES_PATTERN.search(parking)
    if spaces_match and size_sqft and size_sqft > 0:
        spaces = float(spaces_match.group("spaces").replace(",", ""))
        return spaces / (size_sqft / 1_000)
    return None


class AttributeEnricher:
    """Resolve drive-thru and parking attributes with fault-isolated OSM fallback."""

    def __init__(self, fetch: FetchClient | None = None):
        self.fetch = fetch or get_fetch_client()

    async def _osm_elements(self, listing: Listing) -> list[dict[str, Any]] | None:
        if listing.lat is None or listing.lon is None:
            return None
        query = (
            "[out:json][timeout:15];("
            f'nwr(around:100,{listing.lat},{listing.lon})["drive_through"="yes"];'
            f'nwr(around:100,{listing.lat},{listing.lon})["amenity"="fast_food"];'
            f'nwr(around:100,{listing.lat},{listing.lon})["amenity"="parking"];'
            ");out center tags;"
        )
        try:
            payload = await self.fetch.get_json(f"{OVERPASS_URL}?{urlencode({'data': query})}")
        except Exception as exc:
            logger.warning(
                "OpenStreetMap attributes unavailable for %s: %s",
                listing.address,
                exc,
            )
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
            return None
        return [item for item in payload["elements"] if isinstance(item, dict)]

    async def detect_drive_thru(self, listing: Listing) -> bool | None:
        """Detect drive-thru availability from text, then nearby OSM tags."""
        direct = drive_thru_from_text(listing)
        if direct is not None:
            return direct
        elements = await self._osm_elements(listing)
        if elements is None:
            return None
        for element in elements:
            tags = element.get("tags")
            if isinstance(tags, dict) and str(tags.get("drive_through", "")).casefold() == "yes":
                return True
        return False

    async def parking(self, listing: Listing) -> str | None:
        """Return listing parking text, or an OSM-presence description."""
        direct = parking_from_listing(listing)
        if direct is not None:
            return direct
        elements = await self._osm_elements(listing)
        if elements is None:
            return None
        for element in elements:
            tags = element.get("tags")
            if not isinstance(tags, dict) or tags.get("amenity") != "parking":
                continue
            parking_type = str(tags.get("parking") or "unspecified").replace("_", " ")
            return f"OpenStreetMap parking ({parking_type})"
        return None

    async def attributes_for_listing(self, listing: Listing) -> DealAttributes:
        """Build the compact attribute block without allowing OSM failures to escape."""
        drive_thru = await self.detect_drive_thru(listing)
        parking = await self.parking(listing)
        return DealAttributes(
            drive_thru=drive_thru,
            parking=parking,
            size_sqft=listing.size_sqft_num,
        )


async def detect_drive_thru(listing: Listing) -> bool | None:
    """Convenience function for drive-thru enrichment."""
    return await AttributeEnricher().detect_drive_thru(listing)


async def detect_parking(listing: Listing) -> str | None:
    """Convenience function for parking enrichment."""
    return await AttributeEnricher().parking(listing)


async def parking(listing: Listing, parcel: Any = None) -> str | None:
    """Phase API: resolve parking; parcel is reserved for county-specific fields."""
    del parcel
    return await detect_parking(listing)


__all__ = [
    "AttributeEnricher",
    "OVERPASS_URL",
    "detect_drive_thru",
    "detect_parking",
    "drive_thru_from_text",
    "parking_from_listing",
    "parking_ratio",
    "parking",
]
