"""Async MCP boundaries for the Phase 28 control engine."""

from __future__ import annotations

import math
from typing import Any

from cre_mcp.control.pitch import build_tenant_pitch as compose_tenant_pitch
from cre_mcp.control.site_fit import (
    evaluate_tenant_site_fit as evaluate_site_fit,
)
from cre_mcp.control.site_fit import match_tenants_to_site as rank_site_tenants
from cre_mcp.control.spread import (
    model_lease_creation_spread as calculate_lease_creation_spread,
)
from cre_mcp.control.structures import (
    recommend_control_structure as rank_control_structures,
)
from cre_mcp.control.vacant import detect_vacant
from cre_mcp.models.listings import Listing


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _raw_number(raw: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        number = _number(raw.get(key))
        if number is not None:
            return number
    return None


def _raw_bool(raw: dict[str, Any], key: str) -> bool | None:
    value = raw.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"yes", "true", "1", "present"}:
            return True
        if normalized in {"no", "false", "0", "absent"}:
            return False
    return None


def _spread_score(spread: dict[str, Any] | None) -> float:
    if spread is None or spread.get("return_on_control") is None:
        return 0.5
    return max(0.0, min(1.0, 0.5 + float(spread["return_on_control"]) / 2))


async def find_control_opportunities(
    listings: list[dict[str, Any]],
    *,
    aadt: int | None = None,
    population_3mi: int | None = None,
    median_income: int | None = None,
    parcel_acres: float | None = None,
    building_sqft: int | None = None,
    has_drive_thru: bool | None = None,
    nearby_categories: list[str] | None = None,
    value_vacant: float | None = None,
    achievable_rent_psf: float | None = None,
    market_cap_rate: float | None = None,
    ti_psf: float = 25.0,
    leasing_commission_pct: float = 0.06,
    months_vacant: int = 9,
    carry_annual: float = 0.0,
    execution_risk_haircut: float = 0.15,
) -> dict[str, Any]:
    """Screen listings, match tenants, model available spreads, and rank control."""

    try:
        opportunities: list[dict[str, Any]] = []
        for payload in listings:
            listing = Listing.model_validate(payload)
            raw = listing.raw

            listing_aadt = _raw_number(raw, "aadt", "traffic_aadt")
            listing_population = _raw_number(raw, "population_3mi", "three_mile_population")
            listing_income = _raw_number(raw, "median_income", "median_household_income")
            listing_acres = _raw_number(raw, "parcel_acres", "lot_acres")
            listing_sqft = _raw_number(raw, "building_sqft", "size_sqft_num")
            listing_drive_thru = _raw_bool(raw, "has_drive_thru")
            categories = raw.get("nearby_categories")
            listing_categories = (
                [str(category) for category in categories]
                if isinstance(categories, list)
                else nearby_categories
            )

            site = {
                "aadt": int(listing_aadt) if listing_aadt is not None else aadt,
                "population_3mi": (
                    int(listing_population)
                    if listing_population is not None
                    else population_3mi
                ),
                "median_income": (
                    int(listing_income) if listing_income is not None else median_income
                ),
                "parcel_acres": (
                    listing_acres if listing_acres is not None else parcel_acres
                ),
                "building_sqft": (
                    int(listing_sqft)
                    if listing_sqft is not None
                    else int(listing.size_sqft_num)
                    if listing.size_sqft_num is not None
                    else building_sqft
                ),
                "has_drive_thru": (
                    listing_drive_thru
                    if listing_drive_thru is not None
                    else has_drive_thru
                ),
                "nearby_categories": listing_categories,
            }
            vacancy = detect_vacant(listing)
            tenant_matches = rank_site_tenants(**site)

            vacant_value = _raw_number(raw, "value_vacant", "vacant_value")
            if vacant_value is None:
                vacant_value = listing.price_usd
            if vacant_value is None:
                vacant_value = value_vacant
            rent = _raw_number(raw, "achievable_rent_psf", "market_rent_psf")
            if rent is None:
                rent = achievable_rent_psf
            cap = _raw_number(raw, "market_cap_rate")
            if cap is None:
                cap = market_cap_rate
            if cap is None and listing.cap_rate_pct is not None:
                cap = listing.cap_rate_pct / 100

            spread = None
            if all(
                number is not None
                for number in (vacant_value, rent, site["building_sqft"], cap)
            ):
                spread = calculate_lease_creation_spread(
                    value_vacant=float(vacant_value),
                    achievable_rent_psf=float(rent),
                    building_sqft=float(site["building_sqft"]),
                    market_cap_rate=float(cap),
                    ti_psf=ti_psf,
                    leasing_commission_pct=leasing_commission_pct,
                    months_vacant=months_vacant,
                    carry_annual=carry_annual,
                    execution_risk_haircut=execution_risk_haircut,
                )

            top_fit = float(tenant_matches[0]["fit_score"]) if tenant_matches else 0.0
            vacancy_component = float(vacancy["confidence"])
            if not vacancy["is_vacant_candidate"]:
                vacancy_component *= 0.25
            spread_component = _spread_score(spread)
            control_score = round(
                100
                * (
                    0.55 * vacancy_component
                    + 0.35 * top_fit
                    + 0.10 * spread_component
                ),
                2,
            )
            opportunities.append(
                {
                    "listing": listing.model_dump(mode="json"),
                    "vacancy": vacancy,
                    "tenant_matches": tenant_matches,
                    "spread": spread,
                    "control_score": control_score,
                    "score_components": {
                        "vacancy": round(vacancy_component, 4),
                        "tenant_fit": top_fit,
                        "spread": round(spread_component, 4),
                    },
                }
            )

        opportunities.sort(
            key=lambda item: (
                -float(item["control_score"]),
                str(item["listing"]["address"]).casefold(),
                str(item["listing"]["source_id"]),
            )
        )
        for rank, opportunity in enumerate(opportunities, start=1):
            opportunity["rank"] = rank
        return {
            "count": len(opportunities),
            "opportunities": opportunities,
            "methodology": (
                "Heuristic control score: 55% vacancy evidence, 35% leading tenant "
                "fit, and 10% lease-creation spread. Verify vacancy and tenant demand."
            ),
        }
    except Exception as exc:
        return {"error": str(exc)}


async def match_tenants_to_site(
    *,
    aadt: int | None = None,
    population_3mi: int | None = None,
    median_income: int | None = None,
    parcel_acres: float | None = None,
    building_sqft: int | None = None,
    has_drive_thru: bool | None = None,
    nearby_categories: list[str] | None = None,
) -> dict[str, Any]:
    """Rank all committed-catalog tenants for one site."""

    try:
        matches = rank_site_tenants(
            aadt=aadt,
            population_3mi=population_3mi,
            median_income=median_income,
            parcel_acres=parcel_acres,
            building_sqft=building_sqft,
            has_drive_thru=has_drive_thru,
            nearby_categories=nearby_categories,
        )
        return {"count": len(matches), "matches": matches}
    except Exception as exc:
        return {"error": str(exc)}


async def evaluate_tenant_site_fit(
    tenant_brand: str,
    *,
    aadt: int | None = None,
    population_3mi: int | None = None,
    median_income: int | None = None,
    parcel_acres: float | None = None,
    building_sqft: int | None = None,
    has_drive_thru: bool | None = None,
    nearby_categories: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate one committed-catalog tenant for one site."""

    try:
        return evaluate_site_fit(
            tenant_brand,
            aadt=aadt,
            population_3mi=population_3mi,
            median_income=median_income,
            parcel_acres=parcel_acres,
            building_sqft=building_sqft,
            has_drive_thru=has_drive_thru,
            nearby_categories=nearby_categories,
        )
    except Exception as exc:
        return {"error": str(exc)}


async def model_lease_creation_spread(
    *,
    value_vacant: float,
    achievable_rent_psf: float,
    building_sqft: float,
    market_cap_rate: float,
    ti_psf: float = 25.0,
    leasing_commission_pct: float = 0.06,
    months_vacant: int = 9,
    carry_annual: float = 0.0,
    execution_risk_haircut: float = 0.15,
) -> dict[str, Any]:
    """Model lease-creation value, costs, spread, and return on control."""

    try:
        return calculate_lease_creation_spread(
            value_vacant=value_vacant,
            achievable_rent_psf=achievable_rent_psf,
            building_sqft=building_sqft,
            market_cap_rate=market_cap_rate,
            ti_psf=ti_psf,
            leasing_commission_pct=leasing_commission_pct,
            months_vacant=months_vacant,
            carry_annual=carry_annual,
            execution_risk_haircut=execution_risk_haircut,
        )
    except Exception as exc:
        return {"error": str(exc)}


async def recommend_control_structure(
    *,
    seller_motivation: str | float | int | None = None,
    buyer_liquidity: str | float | int | None = None,
    needs_tenant_first: bool = True,
    timeline_months: int | None = None,
) -> dict[str, Any]:
    """Rank control structures for the seller, buyer, and tenant timeline."""

    try:
        recommendations = rank_control_structures(
            seller_motivation=seller_motivation,
            buyer_liquidity=buyer_liquidity,
            needs_tenant_first=needs_tenant_first,
            timeline_months=timeline_months,
        )
        return {"count": len(recommendations), "recommendations": recommendations}
    except Exception as exc:
        return {"error": str(exc)}


async def build_tenant_pitch(
    *,
    tenant_brand: str,
    address: str,
    aadt: int | None = None,
    nearby_anchors: list[str] | None = None,
    population_3mi: int | None = None,
    achievable_rent_psf: float | None = None,
) -> dict[str, Any]:
    """Build a site-specific national-tenant outreach email."""

    try:
        return compose_tenant_pitch(
            tenant_brand=tenant_brand,
            address=address,
            aadt=aadt,
            nearby_anchors=nearby_anchors,
            population_3mi=population_3mi,
            achievable_rent_psf=achievable_rent_psf,
        )
    except Exception as exc:
        return {"error": str(exc)}


__all__ = [
    "build_tenant_pitch",
    "evaluate_tenant_site_fit",
    "find_control_opportunities",
    "match_tenants_to_site",
    "model_lease_creation_spread",
    "recommend_control_structure",
]
