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
    coverage: dict[str, bool] = Field(default_factory=dict)


MARKET_METRIC_FIELDS = tuple(
    name for name in MarketPack.model_fields if name not in {"geo", "coverage"}
)

