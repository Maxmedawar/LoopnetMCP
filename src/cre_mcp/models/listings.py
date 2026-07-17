"""Pydantic data models for Loopnet commercial real estate data."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class PropertyType(str, Enum):
    OFFICE = "office"
    RETAIL = "retail"
    INDUSTRIAL = "industrial"
    MULTIFAMILY = "multifamily"
    LAND = "land"
    HOSPITALITY = "hospitality"
    SPECIAL_PURPOSE = "special-purpose"
    HEALTH_CARE = "health-care"


class ListingType(str, Enum):
    FOR_SALE = "for-sale"
    FOR_LEASE = "for-lease"


class PropertySummary(BaseModel):
    """A single property from search results."""

    name: str
    address: str
    city: str
    state: str
    zip_code: Optional[str] = None
    property_type: Optional[str] = None
    listing_type: Optional[str] = None
    price: Optional[str] = None
    price_per_sqft: Optional[str] = None
    size_sqft: Optional[str] = None
    lot_size: Optional[str] = None
    units: Optional[int] = None
    cap_rate: Optional[str] = None
    url: str
    image_url: Optional[str] = None
    broker_name: Optional[str] = None
    broker_company: Optional[str] = None


class PropertyDetail(BaseModel):
    """Full property information from a detail page."""

    name: str
    address: str
    city: str
    state: str
    zip_code: Optional[str] = None
    property_type: Optional[str] = None
    property_subtype: Optional[str] = None
    listing_type: Optional[str] = None
    price: Optional[str] = None
    price_per_sqft: Optional[str] = None
    cap_rate: Optional[str] = None
    noi: Optional[str] = None
    size_sqft: Optional[str] = None
    lot_size: Optional[str] = None
    year_built: Optional[str] = None
    building_class: Optional[str] = None
    zoning: Optional[str] = None
    parking: Optional[str] = None
    stories: Optional[int] = None
    units: Optional[int] = None
    description: Optional[str] = None
    highlights: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    broker_name: Optional[str] = None
    broker_company: Optional[str] = None
    broker_phone: Optional[str] = None
    url: str
    last_updated: Optional[str] = None


class SearchResult(BaseModel):
    """Container for search results with metadata."""

    query_location: str
    query_property_type: Optional[str] = None
    query_listing_type: Optional[str] = None
    total_results: Optional[int] = None
    page: int = 1
    has_next_page: bool = False
    properties: list[PropertySummary] = Field(default_factory=list)


class MarketOverview(BaseModel):
    """Aggregated market statistics for a location."""

    location: str
    property_type: Optional[str] = None
    total_listings: Optional[int] = None
    avg_price: Optional[str] = None
    avg_price_per_sqft: Optional[str] = None
    avg_cap_rate: Optional[str] = None
    avg_size_sqft: Optional[str] = None
    price_range: Optional[str] = None
    size_range: Optional[str] = None
    listing_types_breakdown: dict[str, int] = Field(default_factory=dict)
    property_subtypes_breakdown: dict[str, int] = Field(default_factory=dict)
    sample_listings: list[PropertySummary] = Field(default_factory=list)


class ListingRef(BaseModel):
    """A source-specific reference for a unified listing."""

    source: str
    source_id: str
    url: str | None = None


class SourceCapabilities(BaseModel):
    """Search and detail features supported by a listing source."""

    supports_lease: bool = True
    supports_distressed: bool = False
    supports_price_filter: bool = True
    supports_size_filter: bool = True
    detail_is_expensive: bool = False


class Listing(BaseModel):
    """Unified cross-source commercial real estate listing."""

    source: str
    source_id: str
    refs: list[ListingRef] = Field(default_factory=list)

    name: str
    address: str
    city: str
    state: str
    zip_code: str | None = None
    property_type: str | None = None
    property_subtype: str | None = None
    listing_type: str | None = None
    price: str | None = None
    price_per_sqft: str | None = None
    cap_rate: str | None = None
    noi: str | None = None
    size_sqft: str | None = None
    lot_size: str | None = None
    year_built: str | None = None
    building_class: str | None = None
    zoning: str | None = None
    parking: str | None = None
    stories: int | None = None
    units: int | None = None
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    image_url: str | None = None
    broker_name: str | None = None
    broker_company: str | None = None
    broker_phone: str | None = None
    url: str
    last_updated: str | None = None

    price_usd: float | None = None
    size_sqft_num: float | None = None
    cap_rate_pct: float | None = None
    noi_usd: float | None = None
    year_built_int: int | None = None
    lat: float | None = None
    lon: float | None = None
    is_distressed: bool = False
    distress_type: str | None = None
    also_listed_on: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class AggregatedSearchResult(BaseModel):
    """Listings and source-level metadata returned by registry fan-out."""

    query_location: str
    query_property_type: str | None = None
    query_listing_type: str | None = None
    page: int = 1
    listings: list[Listing] = Field(default_factory=list)
    per_source_counts: dict[str, int] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    deduped: int = 0
