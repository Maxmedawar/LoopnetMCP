"""Owner proposals and subtenant outreach for master-lease opportunities."""

from __future__ import annotations

import math
from typing import Any


def _positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(float(value)) or value <= 0:
        raise ValueError(f"{name} must be a finite number greater than zero")
    return float(value)


def _optional_nonnegative(name: str, value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _required_text(name: str, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} must not be empty")
    return cleaned


def _clean_items(items: list[str] | None) -> list[str]:
    return [str(item).strip() for item in items or [] if str(item).strip()]


def _human_join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def draft_master_lease_proposal(
    *,
    address: str,
    building_sqft: float,
    master_rent_offer_psf: float,
    term_years: int,
    owner_name: str | None = None,
    sublet_rights: bool = True,
    guaranteed: bool = True,
) -> dict[str, Any]:
    """Draft an owner-facing master-lease proposal with explicit consent terms."""

    site_address = _required_text("address", address)
    sqft = _positive("building_sqft", building_sqft)
    rent_psf = _positive("master_rent_offer_psf", master_rent_offer_psf)
    if isinstance(term_years, bool) or not isinstance(term_years, int) or term_years < 1:
        raise ValueError("term_years must be a positive integer")
    if not isinstance(sublet_rights, bool) or not isinstance(guaranteed, bool):
        raise ValueError("sublet_rights and guaranteed must be booleans")
    owner = owner_name.strip() if owner_name and owner_name.strip() else "Property Owner"
    annual_rent = sqft * rent_psf
    monthly_rent = annual_rent / 12

    if guaranteed:
        payment_language = (
            f"I am proposing a {term_years}-year master lease with a guaranteed "
            "contractual rent obligation under which the master tenant would owe the "
            "agreed rent throughout the term, including periods when a sublease is "
            "vacant, subject to the final lease terms."
        )
        guarantee_term = "Master tenant rent obligation for the full agreed term"
    else:
        payment_language = (
            f"I am proposing a {term_years}-year master lease, but this draft is not "
            "marked as guaranteed; payment security and credit support remain open "
            "terms for the owner's review."
        )
        guarantee_term = "Not guaranteed in this draft; credit support remains open"

    if sublet_rights:
        rights_language = (
            "A required business term is express written permission to sublease and "
            "assign the premises to qualified business occupants, with a practical "
            "owner-consent standard documented in the lease."
        )
        rights_term = "Express sublet and assignment rights requested"
    else:
        rights_language = (
            "This draft does not assume subletting consent. Because the operating "
            "plan depends on subleasing, express sublet and assignment rights must be "
            "resolved in writing before the transaction can proceed."
        )
        rights_term = "Required open point; no sublet consent is assumed"

    body = (
        f"Hello {owner},\n\n"
        f"I would like to discuss a master lease for the approximately {sqft:,.0f} "
        f"SF premises at {site_address}. {payment_language}\n\n"
        f"The proposed base rent is ${rent_psf:,.2f}/SF/year, or approximately "
        f"${annual_rent:,.2f} annually (${monthly_rent:,.2f} monthly). In return, "
        "my team would serve as the professional operating point of contact, handle "
        "subtenant sourcing and day-to-day management, and perform maintenance only "
        "to the extent allocated to the master tenant in the final lease. This can "
        "provide a more hands-off ownership experience and reduce the owner's leasing "
        "workload, but it does not eliminate the need to underwrite our entity, "
        "operating plan, and credit support.\n\n"
        f"{rights_language}\n\n"
        "If these preliminary terms are of interest, I would welcome a conversation "
        "about use restrictions, insurance, maintenance allocation, reporting, "
        "default remedies, and acceptable subtenant criteria. This is a non-binding "
        "proposal subject to diligence and definitive lease documentation."
    )
    return {
        "subject": f"Master lease proposal — {site_address}",
        "body": body,
        "key_terms": {
            "premises": f"Approximately {sqft:,.0f} SF at {site_address}",
            "master_rent_offer_psf": rent_psf,
            "annual_master_rent": annual_rent,
            "monthly_master_rent": monthly_rent,
            "term_years": term_years,
            "guaranteed": guaranteed,
            "rent_obligation": guarantee_term,
            "sublet_rights_requested": sublet_rights,
            "sublet_assignment_rights": rights_term,
            "operations": (
                "Master tenant handles subleasing and management; maintenance follows "
                "the final negotiated lease allocation"
            ),
            "status": "Non-binding and subject to diligence and definitive documents",
        },
    }


def draft_subtenant_outreach(
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
    """Draft specific subtenant outreach using only caller-supplied site facts."""

    tenant = _required_text("tenant_name", tenant_name)
    site_address = _required_text("address", address)
    sqft = _positive("building_sqft", building_sqft)
    rent_psf = _positive("sublease_rent_psf", sublease_rent_psf)
    if isinstance(term_years, bool) or not isinstance(term_years, int) or term_years < 1:
        raise ValueError("term_years must be a positive integer")
    _optional_nonnegative("aadt", aadt)
    _optional_nonnegative("foot_traffic_daily", foot_traffic_daily)
    _optional_nonnegative("parking_spaces", parking_spaces)
    if drive_thru is not None and not isinstance(drive_thru, bool):
        raise ValueError("drive_thru must be a boolean or None")

    amenity_list = _clean_items(amenities)
    anchor_list = _clean_items(nearby_anchors)
    facts = [f"approximately {sqft:,.0f} SF at {site_address}"]
    talking_points = [f"Approximately {sqft:,.0f} SF at {site_address}"]
    if aadt is not None:
        facts.append(f"visibility to approximately {aadt:,} cars/day (AADT)")
        talking_points.append(f"Approximately {aadt:,} cars/day (AADT)")
    if foot_traffic_daily is not None:
        facts.append(f"approximately {foot_traffic_daily:,} daily pedestrians")
        talking_points.append(
            f"Approximately {foot_traffic_daily:,} people in daily foot traffic"
        )
    if parking_spaces is not None:
        facts.append(f"{parking_spaces:,} parking spaces")
        talking_points.append(f"{parking_spaces:,} parking spaces")
    if drive_thru is True:
        facts.append("an existing drive-thru configuration")
        talking_points.append("Drive-thru configuration")
    elif drive_thru is False:
        facts.append("a current layout without a drive-thru")
        talking_points.append("No drive-thru represented; confirm format compatibility")
    if amenity_list:
        amenities_text = _human_join(amenity_list)
        facts.append(f"site amenities including {amenities_text}")
        talking_points.append(f"Amenities: {amenities_text}")
    if anchor_list:
        anchors_text = _human_join(anchor_list)
        facts.append(f"nearby complementary brands including {anchors_text}")
        talking_points.append(f"Nearby complementary brands: {anchors_text}")

    talking_points.append(
        f"Proposed rent: ${rent_psf:,.2f}/SF/year for {term_years} years"
    )
    body = (
        f"Hello {tenant} Real Estate Team,\n\n"
        f"I am reaching out with a sublease opportunity that may fit {tenant}: "
        f"{'; '.join(facts)}.\n\n"
        f"The proposed economics are ${rent_psf:,.2f}/SF/year for a {term_years}-year "
        "term, subject to final documentation, credit approval, and any agreed "
        "concessions.\n\n"
        "Would your team be open to a brief site review? I can provide the site plan, "
        "access and signage details, photos, permitted-use information, and draft "
        "sublease terms. All site, traffic, parking, and co-tenancy facts are "
        "preliminary and should be independently verified."
    )
    return {
        "subject": f"Sublease opportunity for {tenant} — {site_address}",
        "body": body,
        "talking_points": talking_points,
    }


__all__ = ["draft_master_lease_proposal", "draft_subtenant_outreach"]
