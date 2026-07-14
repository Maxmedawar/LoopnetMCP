"""Source-normalized enrichment models."""

from typing import Any

from pydantic import BaseModel, Field


class ListingFacts(BaseModel):
    """Headline investment facts deterministically extracted from listing prose."""

    strategy_hint: str | None = None
    lease_years_remaining: float | None = None
    rent_escalations: float | None = None
    nnn_purity: str | None = None
    tenant_name: str | None = None
    guaranty: str | None = None


class ParcelRecord(BaseModel):
    """Source-normalized public assessor parcel record."""

    apn: str | None = None
    site_address: str | None = None
    owner_name: str | None = None
    owner_mailing_address: str | None = None
    assessed_value: float | None = None
    land_value: float | None = None
    last_sale_price: float | None = None
    last_sale_date: str | None = None
    year_built: int | None = None
    use_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class OwnerRecord(BaseModel):
    """Normalized owner identity derived from one or more parcel records."""

    name: str
    normalized_name: str
    entity_type: str
    absentee: bool | None = None
    mailing_address: str | None = None
    parcels: list[ParcelRecord] = Field(default_factory=list)


__all__ = ["ListingFacts", "OwnerRecord", "ParcelRecord"]
