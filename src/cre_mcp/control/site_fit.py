"""Tenant-to-site fit helpers built on the committed tenant catalog."""

from __future__ import annotations

from cre_mcp.control.tenants import get_tenant, match_site


def match_tenants_to_site(
    *,
    aadt: int | None = None,
    population_3mi: int | None = None,
    median_income: int | None = None,
    parcel_acres: float | None = None,
    building_sqft: int | None = None,
    has_drive_thru: bool | None = None,
    nearby_categories: list[str] | None = None,
) -> list[dict[str, object]]:
    """Rank every catalog tenant against the supplied site facts."""

    return match_site(
        aadt=aadt,
        population_3mi=population_3mi,
        median_income=median_income,
        parcel_acres=parcel_acres,
        building_sqft=building_sqft,
        has_drive_thru=has_drive_thru,
        nearby_categories=nearby_categories,
    )


def evaluate_tenant_site_fit(
    tenant_brand: str,
    *,
    aadt: int | None = None,
    population_3mi: int | None = None,
    median_income: int | None = None,
    parcel_acres: float | None = None,
    building_sqft: int | None = None,
    has_drive_thru: bool | None = None,
    nearby_categories: list[str] | None = None,
) -> dict[str, object]:
    """Evaluate one catalog tenant without changing catalog scoring semantics."""

    tenant = get_tenant(tenant_brand)
    if tenant is None:
        raise ValueError(f"Unknown tenant brand: {tenant_brand}")

    matches = match_tenants_to_site(
        aadt=aadt,
        population_3mi=population_3mi,
        median_income=median_income,
        parcel_acres=parcel_acres,
        building_sqft=building_sqft,
        has_drive_thru=has_drive_thru,
        nearby_categories=nearby_categories,
    )
    return next(result for result in matches if result["brand"] == tenant.brand)


__all__ = ["evaluate_tenant_site_fit", "match_tenants_to_site"]
