"""Synthetic DealContext builders shared by scoring tests and golden snapshots."""

from typing import Any

from cre_mcp.models import DealContext, GeoLevel, GeoRef, Listing, MarketPack, MetricValue
from cre_mcp.underwriting.metrics import underwrite_listing


def metric(value: float | None, unit: str = "percent") -> MetricValue:
    return MetricValue(value=value, unit=unit, as_of="2024", source="synthetic")


def market_pack(values: dict[str, float] | None = None) -> MarketPack:
    values = values or {}
    kwargs: dict[str, Any] = {}
    units = {
        "population": "people",
        "median_hh_income": "USD/year",
        "permits_trailing_12m": "housing units",
        "net_migration": "people",
    }
    for key, value in values.items():
        kwargs[key] = metric(value, units.get(key, "percent"))
    coverage = {key: value is not None for key, value in values.items()}
    return MarketPack(
        geo=GeoRef(
            level=GeoLevel.COUNTY,
            state_fips="48",
            county_fips="48453",
            cbsa="12420",
            name="Travis County, TX",
        ),
        coverage=coverage,
        **kwargs,
    )


def deal_context(
    *,
    property_type: str = "retail",
    price: float | None = 1_000_000,
    size: float | None = 5_000,
    units: int | None = None,
    noi: float | None = 70_000,
    cap_rate_pct: float | None = None,
    raw: dict[str, Any] | None = None,
    market: MarketPack | None = None,
    source_id: str = "synthetic-1",
) -> DealContext:
    listing = Listing(
        source="fixture",
        source_id=source_id,
        name=f"Synthetic {property_type.title()} Deal",
        address="100 Congress Ave",
        city="Austin",
        state="TX",
        zip_code="78701",
        property_type=property_type,
        listing_type="for-sale",
        price_usd=price,
        size_sqft_num=size,
        units=units,
        noi_usd=noi,
        cap_rate_pct=cap_rate_pct,
        url=f"https://example.test/{source_id}",
        raw=raw or {},
    )
    underwriting = underwrite_listing(listing)
    return DealContext(
        listing=listing,
        market=market,
        underwriting=underwriting,
    )


def context_from_fixture(payload: dict[str, Any]) -> DealContext:
    market_values = payload.get("market")
    return deal_context(
        property_type=payload.get("property_type", "retail"),
        price=payload.get("price"),
        size=payload.get("size"),
        units=payload.get("units"),
        noi=payload.get("noi"),
        cap_rate_pct=payload.get("cap_rate_pct"),
        raw=payload.get("raw", {}),
        market=market_pack(market_values) if market_values is not None else None,
        source_id=payload["id"],
    )
