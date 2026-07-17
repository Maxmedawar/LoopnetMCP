"""Coverage-aware sale-comparable and value-estimate models."""

from pydantic import BaseModel, Field


class SaleComp(BaseModel):
    """One normalized arm's-length sale candidate from a public county layer."""

    source: str
    county_fips: str
    parcel_id: str | None = None
    address: str | None = None
    sale_price: float
    sale_date: str | None = None
    sqft: float | None = None
    units: float | None = None
    use_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    distance_miles: float | None = None
    time_adjusted_price: float | None = None


class ValueEstimate(BaseModel):
    """Value range with explicit method, uncertainty, and provenance."""

    value: float | None = None
    low: float | None = None
    mid: float | None = None
    high: float | None = None
    method: str
    n_comps: int = 0
    confidence: float = 0.0
    error_band: float | None = None
    as_of: str | None = None
    source: str


class CompsProviderResult(BaseModel):
    """Normalized boundary between free-first tools and optional paid providers."""

    provider: str
    comps: list[SaleComp] = Field(default_factory=list)
    value_estimate: ValueEstimate | None = None


__all__ = ["CompsProviderResult", "SaleComp", "ValueEstimate"]
