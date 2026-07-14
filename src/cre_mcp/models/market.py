"""Normalized market-intelligence models."""

from pydantic import BaseModel, Field

from cre_mcp.models.geo import GeoRef


class MetricValue(BaseModel):
    """One observed or derived market metric with provenance."""

    value: float | None
    unit: str
    as_of: str | None = None
    source: str


class MetricSeries(BaseModel):
    """Time-ordered observations with shared units and provenance."""

    points: list[tuple[str, float]] = Field(default_factory=list)
    unit: str
    source: str


class RentComparable(BaseModel):
    """One observed or modeled monthly rent comparable."""

    source: str
    rent: float
    location: str | None = None
    bedrooms: int | None = None
    property_type: str | None = None
    as_of: str | None = None


class RentComps(BaseModel):
    """Coverage-aware rent benchmarks assembled from free and optional sources."""

    geo: GeoRef
    market_rent_estimate: MetricValue | None = None
    rent_index: MetricValue | None = None
    rent_trend_yoy: MetricValue | None = None
    median_gross_rent: MetricValue | None = None
    fmr_by_bedroom: dict[int, MetricValue] = Field(default_factory=dict)
    comps: list[RentComparable] = Field(default_factory=list)
    coverage: dict[str, bool] = Field(default_factory=dict)
    source: list[str] = Field(default_factory=list)


class MarketPack(BaseModel):
    """Cross-provider market fundamentals for one normalized geography."""

    geo: GeoRef
    population: MetricValue | None = None
    pop_growth_5yr: MetricValue | None = None
    median_hh_income: MetricValue | None = None
    income_growth: MetricValue | None = None
    job_growth_1yr: MetricValue | None = None
    job_growth_5yr: MetricValue | None = None
    unemployment_rate: MetricValue | None = None
    net_migration: MetricValue | None = None
    fmr_2br: MetricValue | None = None
    median_gross_rent: MetricValue | None = None
    rental_vacancy: MetricValue | None = None
    renter_share: MetricValue | None = None
    permits_trailing_12m: MetricValue | None = None
    county_gdp_growth: MetricValue | None = None
    treasury_10yr: MetricValue | None = None
    mortgage_rate: MetricValue | None = None
    sofr: MetricValue | None = None
    fhfa_hpi_growth_1yr: MetricValue | None = None
    coverage: dict[str, bool] = Field(default_factory=dict)


MARKET_METRIC_FIELDS = tuple(
    name for name in MarketPack.model_fields if name not in {"geo", "coverage"}
)
