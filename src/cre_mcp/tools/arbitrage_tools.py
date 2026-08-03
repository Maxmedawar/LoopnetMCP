"""Async MCP boundaries for master-lease arbitrage workflows."""

from __future__ import annotations

import math
from typing import Any

from cre_mcp.arbitrage.economics import master_lease_arbitrage
from cre_mcp.arbitrage.finder import (
    find_arbitrage_opportunities as screen_arbitrage_opportunities,
)
from cre_mcp.arbitrage.proposals import (
    draft_master_lease_proposal as compose_master_lease_proposal,
)
from cre_mcp.arbitrage.proposals import (
    draft_subtenant_outreach as compose_subtenant_outreach,
)
from cre_mcp.control.tenants import TENANTS, match_site
from cre_mcp.source_rights.output import safe_error_message


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _space_number(space: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        number = _number(space.get(key))
        if number is not None:
            return number
    return None


def _space_bool(space: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = space.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"true", "yes", "1", "present"}:
                return True
            if normalized in {"false", "no", "0", "absent"}:
                return False
    return None


def _optional_int(value: float | None) -> int | None:
    return int(value) if value is not None else None


async def analyze_master_lease(
    *,
    master_rent_annual: float,
    building_sqft: float,
    sublease_rent_psf: float,
    sublease_occupancy: float = 0.92,
    ti_psf: float = 0.0,
    free_rent_months: float = 0.0,
    mgmt_pct: float = 0.05,
    other_annual_costs: float = 0.0,
    term_years: int = 5,
    your_rent_escalation_pct: float = 0.03,
    sublease_escalation_pct: float = 0.03,
    personal_guarantee: bool = True,
) -> dict[str, Any]:
    """Analyze first-year and term master-lease economics and negative carry."""

    try:
        return master_lease_arbitrage(
            master_rent_annual=master_rent_annual,
            building_sqft=building_sqft,
            sublease_rent_psf=sublease_rent_psf,
            sublease_occupancy=sublease_occupancy,
            ti_psf=ti_psf,
            free_rent_months=free_rent_months,
            mgmt_pct=mgmt_pct,
            other_annual_costs=other_annual_costs,
            term_years=term_years,
            your_rent_escalation_pct=your_rent_escalation_pct,
            sublease_escalation_pct=sublease_escalation_pct,
            personal_guarantee=personal_guarantee,
        )
    except Exception as exc:
        return {"error": safe_error_message(exc)}


async def find_arbitrage_opportunities(
    spaces: list[dict[str, Any]],
    achievable_sublease_psf: float | None = None,
) -> dict[str, Any]:
    """Screen and rank spaces while reporting filtered and skipped counts."""

    try:
        opportunities = screen_arbitrage_opportunities(
            spaces,
            achievable_sublease_psf=achievable_sublease_psf,
        )
        summary = dict(getattr(opportunities, "screening_summary", {}))
        return {**summary, "count": len(opportunities), "opportunities": opportunities}
    except Exception as exc:
        return {"error": safe_error_message(exc)}


async def draft_master_lease_proposal(
    *,
    address: str,
    building_sqft: float,
    master_rent_offer_psf: float,
    term_years: int,
    owner_name: str | None = None,
    sublet_rights: bool = True,
    guaranteed: bool = True,
) -> dict[str, Any]:
    """Draft a non-binding owner-facing master-lease proposal."""

    try:
        return compose_master_lease_proposal(
            address=address,
            building_sqft=building_sqft,
            master_rent_offer_psf=master_rent_offer_psf,
            term_years=term_years,
            owner_name=owner_name,
            sublet_rights=sublet_rights,
            guaranteed=guaranteed,
        )
    except Exception as exc:
        return {"error": safe_error_message(exc)}


async def draft_subtenant_outreach(
    *,
    tenant_name: str,
    address: str,
    building_sqft: float,
    sublease_rent_psf: float,
    term_years: int,
    aadt: int | None = None,
    foot_traffic_daily: int | None = None,
    parking_spaces: int | None = None,
    amenities: list[str] | None = None,
    nearby_anchors: list[str] | None = None,
    drive_thru: bool | None = None,
) -> dict[str, Any]:
    """Draft factual outreach for a prospective business subtenant."""

    try:
        return compose_subtenant_outreach(
            tenant_name=tenant_name,
            address=address,
            building_sqft=building_sqft,
            sublease_rent_psf=sublease_rent_psf,
            term_years=term_years,
            aadt=aadt,
            foot_traffic_daily=foot_traffic_daily,
            parking_spaces=parking_spaces,
            amenities=amenities,
            nearby_anchors=nearby_anchors,
            drive_thru=drive_thru,
        )
    except Exception as exc:
        return {"error": safe_error_message(exc)}


async def master_lease_playbook(
    space: dict[str, Any],
    *,
    achievable_sublease_psf: float | None = None,
    nearby_anchors: list[str] | None = None,
    top_n_tenants: int = 5,
) -> dict[str, Any]:
    """Package economics, tenant ranking, and both sides of outreach for one site."""

    try:
        if not isinstance(space, dict):
            raise ValueError("space must be a dictionary")
        if (
            isinstance(top_n_tenants, bool)
            or not isinstance(top_n_tenants, int)
            or top_n_tenants < 1
        ):
            raise ValueError("top_n_tenants must be a positive integer")

        address_value = space.get("address") or space.get("id")
        if not address_value or not str(address_value).strip():
            raise ValueError("space requires address or id")
        address = str(address_value).strip()
        building_sqft = _space_number(space, "building_sqft", "size_sqft_num")
        if building_sqft is None:
            raise ValueError("space requires building_sqft")

        master_rent_annual = _space_number(space, "master_rent_annual")
        master_rent_offer_psf = _space_number(
            space, "master_rent_offer_psf", "asking_rent_psf"
        )
        if master_rent_annual is None:
            if master_rent_offer_psf is None:
                raise ValueError(
                    "space requires master_rent_annual or asking_rent_psf"
                )
            master_rent_annual = master_rent_offer_psf * building_sqft
        if master_rent_offer_psf is None:
            master_rent_offer_psf = master_rent_annual / building_sqft

        sublease_psf = _space_number(space, "achievable_sublease_psf")
        if sublease_psf is None:
            sublease_psf = _number(achievable_sublease_psf)
        if sublease_psf is None:
            raise ValueError(
                "space or tool input requires achievable_sublease_psf"
            )

        term_value = _space_number(space, "term_years")
        term_years = int(term_value) if term_value is not None else 5
        occupancy = _space_number(space, "sublease_occupancy")
        ti_psf = _space_number(space, "ti_psf")
        free_rent_months = _space_number(space, "free_rent_months")
        mgmt_pct = _space_number(space, "mgmt_pct")
        other_annual_costs = _space_number(space, "other_annual_costs")
        master_escalation = _space_number(space, "your_rent_escalation_pct")
        sublease_escalation = _space_number(space, "sublease_escalation_pct")
        personal_guarantee = _space_bool(space, "personal_guarantee")
        economics = master_lease_arbitrage(
            master_rent_annual=master_rent_annual,
            building_sqft=building_sqft,
            sublease_rent_psf=sublease_psf,
            sublease_occupancy=occupancy if occupancy is not None else 0.92,
            ti_psf=ti_psf if ti_psf is not None else 0.0,
            free_rent_months=(
                free_rent_months if free_rent_months is not None else 0.0
            ),
            mgmt_pct=mgmt_pct if mgmt_pct is not None else 0.05,
            other_annual_costs=(
                other_annual_costs if other_annual_costs is not None else 0.0
            ),
            term_years=term_years,
            your_rent_escalation_pct=(
                master_escalation if master_escalation is not None else 0.03
            ),
            sublease_escalation_pct=(
                sublease_escalation if sublease_escalation is not None else 0.03
            ),
            personal_guarantee=(
                personal_guarantee if personal_guarantee is not None else True
            ),
        )

        aadt = _optional_int(_space_number(space, "aadt", "traffic_aadt"))
        population_3mi = _optional_int(
            _space_number(space, "population_3mi", "three_mile_population")
        )
        median_income = _optional_int(
            _space_number(space, "median_income", "median_household_income")
        )
        parcel_acres = _space_number(space, "parcel_acres", "lot_acres")
        parking_spaces = _optional_int(_space_number(space, "parking_spaces"))
        foot_traffic = _optional_int(
            _space_number(space, "foot_traffic_daily", "daily_foot_traffic")
        )
        drive_thru = _space_bool(space, "has_drive_thru", "drive_thru")
        raw_categories = space.get("nearby_categories")
        nearby_categories = (
            [str(category) for category in raw_categories]
            if isinstance(raw_categories, list)
            else None
        )
        matches = match_site(
            aadt=aadt,
            population_3mi=population_3mi,
            median_income=median_income,
            parcel_acres=parcel_acres,
            building_sqft=int(building_sqft),
            has_drive_thru=drive_thru,
            nearby_categories=nearby_categories,
        )
        catalog = {tenant.brand: tenant for tenant in TENANTS}
        guaranty_notes = {
            "corporate": (
                "Catalog indicates a corporate guaranty profile; verify the actual "
                "lease entity and guaranty."
            ),
            "franchisee": (
                "Catalog indicates franchisee credit; underwrite the specific operator "
                "and guarantor rather than relying on the brand name."
            ),
            "mixed": (
                "Catalog indicates mixed corporate/franchisee structures; confirm the "
                "actual lease entity and credit support."
            ),
        }
        candidates: list[dict[str, Any]] = []
        for match in matches[:top_n_tenants]:
            tenant = catalog[str(match["brand"])]
            candidate = dict(match)
            candidate.update(
                {
                    "category": tenant.category,
                    "guaranty_tier": tenant.guaranty,
                    "guaranty_note": guaranty_notes[tenant.guaranty],
                    "typical_nnn_rent_psf": tenant.typical_nnn_rent_psf,
                    "criteria_source": tenant.source,
                    "criteria_confidence": tenant.confidence,
                    "screening_note": (
                        "Catalog fit is preliminary; tenant demand, use approval, rent "
                        "tolerance, and credit are not confirmed."
                    ),
                }
            )
            candidates.append(candidate)

        owner_proposal = compose_master_lease_proposal(
            address=address,
            building_sqft=building_sqft,
            master_rent_offer_psf=master_rent_offer_psf,
            term_years=term_years,
            owner_name=(
                str(space["owner_name"])
                if space.get("owner_name") is not None
                else None
            ),
            sublet_rights=True,
            guaranteed=True,
        )
        raw_amenities = space.get("amenities")
        amenities = (
            [str(amenity) for amenity in raw_amenities]
            if isinstance(raw_amenities, list)
            else None
        )
        raw_anchors = space.get("nearby_anchors")
        outreach_anchors = nearby_anchors
        if outreach_anchors is None and isinstance(raw_anchors, list):
            outreach_anchors = [str(anchor) for anchor in raw_anchors]
        sample_outreach = compose_subtenant_outreach(
            tenant_name=str(candidates[0]["brand"]),
            address=address,
            building_sqft=building_sqft,
            sublease_rent_psf=sublease_psf,
            term_years=term_years,
            aadt=aadt,
            foot_traffic_daily=foot_traffic,
            parking_spaces=parking_spaces,
            amenities=amenities,
            nearby_anchors=outreach_anchors,
            drive_thru=drive_thru,
        )
        return {
            "economics": economics,
            "candidate_subtenants": candidates,
            "owner_proposal": owner_proposal,
            "sample_outreach": sample_outreach,
            "risk_flags": economics["risk_flags"],
        }
    except Exception as exc:
        return {"error": safe_error_message(exc)}


__all__ = [
    "analyze_master_lease",
    "draft_master_lease_proposal",
    "draft_subtenant_outreach",
    "find_arbitrage_opportunities",
    "master_lease_playbook",
]
