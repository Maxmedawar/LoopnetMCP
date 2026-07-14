"""Pydantic data models for commercial real estate data."""

from cre_mcp.models.attributes import DealAttributes
from cre_mcp.models.comps import SaleComp, ValueEstimate
from cre_mcp.models.deals import Deal, DealContext
from cre_mcp.models.enrichment import ListingFacts, OwnerRecord, ParcelRecord
from cre_mcp.models.execution import LoiDraft, OfferRecommendation
from cre_mcp.models.geo import GeoLevel, GeoRef
from cre_mcp.models.listings import (
    AggregatedSearchResult,
    Listing,
    ListingRef,
    ListingType,
    MarketOverview,
    PropertyDetail,
    PropertySummary,
    PropertyType,
    SearchResult,
    SourceCapabilities,
)
from cre_mcp.models.market import (
    MarketPack,
    MetricSeries,
    MetricValue,
    RentComparable,
    RentComps,
)
from cre_mcp.models.scoring import (
    Band,
    DealScore,
    DisqualifierSpec,
    Rubric,
    RubricResult,
    SignalResult,
    SignalSpec,
)
from cre_mcp.models.underwriting import UnderwritingResult

__all__ = [
    "AggregatedSearchResult",
    "Band",
    "Deal",
    "DealAttributes",
    "DealContext",
    "DealScore",
    "DisqualifierSpec",
    "GeoLevel",
    "GeoRef",
    "Listing",
    "ListingFacts",
    "ListingRef",
    "ListingType",
    "LoiDraft",
    "MarketOverview",
    "MarketPack",
    "MetricSeries",
    "MetricValue",
    "OwnerRecord",
    "OfferRecommendation",
    "ParcelRecord",
    "PropertyDetail",
    "PropertySummary",
    "PropertyType",
    "RentComparable",
    "RentComps",
    "Rubric",
    "RubricResult",
    "SearchResult",
    "SaleComp",
    "SourceCapabilities",
    "SignalResult",
    "SignalSpec",
    "UnderwritingResult",
    "ValueEstimate",
]
