"""Plain-English national-tenant site outreach."""

from __future__ import annotations

import math

from cre_mcp.control.tenants import get_tenant


def _human_join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _optional_nonnegative(name: str, value: float | int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")


def build_tenant_pitch(
    *,
    tenant_brand: str,
    address: str,
    aadt: int | None = None,
    nearby_anchors: list[str] | None = None,
    population_3mi: int | None = None,
    achievable_rent_psf: float | None = None,
) -> dict[str, str | list[str]]:
    """Build factual outreach using only catalog context and caller-supplied facts."""

    tenant_brand = tenant_brand.strip()
    address = address.strip()
    if not tenant_brand:
        raise ValueError("tenant_brand must not be empty")
    if not address:
        raise ValueError("address must not be empty")
    _optional_nonnegative("aadt", aadt)
    _optional_nonnegative("population_3mi", population_3mi)
    _optional_nonnegative("achievable_rent_psf", achievable_rent_psf)

    anchors = [anchor.strip() for anchor in nearby_anchors or [] if anchor.strip()]
    talking_points: list[str] = [f"Standalone retail opportunity at {address}"]
    body_facts: list[str] = []
    if aadt is not None:
        traffic = f"Traffic is ~{aadt:,} cars/day."
        body_facts.append(traffic)
        talking_points.append(f"~{aadt:,} cars/day")
    if anchors:
        anchor_names = _human_join(anchors)
        if len(anchors) == 1:
            body_facts.append(f"Nearby anchor {anchor_names} is within walking distance.")
        else:
            body_facts.append(
                f"Nearby co-tenants {anchor_names} are within walking distance."
            )
        talking_points.append(f"Nearby anchors: {anchor_names}")
    if population_3mi is not None:
        body_facts.append(
            f"The 3-mile population is approximately {population_3mi:,}."
        )
        talking_points.append(f"{population_3mi:,} people within 3 miles")
    if achievable_rent_psf is not None:
        body_facts.append(
            f"The preliminary asking economics are ${achievable_rent_psf:,.2f}/SF."
        )
        talking_points.append(f"Target rent: ${achievable_rent_psf:,.2f}/SF")

    tenant = get_tenant(tenant_brand)
    if tenant is not None:
        talking_points.append(
            f"Catalog use case: {tenant.category.replace('_', ' ')}; "
            f"criteria confidence {tenant.confidence:.0%}"
        )

    facts_paragraph = " ".join(body_facts)
    if facts_paragraph:
        facts_paragraph = f"\n\n{facts_paragraph}"
    body = (
        f"Hello {tenant_brand} Real Estate Team,\n\n"
        f"I am reaching out about a standalone retail opportunity at {address} "
        f"that may fit {tenant_brand}'s expansion plans.{facts_paragraph}\n\n"
        "Would your real estate team be open to a brief site review? I can share "
        "the site plan, access details, photos, and proposed lease economics.\n\n"
        "These are preliminary site facts and should be independently verified."
    )
    return {
        "subject": f"Site opportunity for {tenant_brand} — {address}",
        "body": body,
        "talking_points": talking_points,
    }


__all__ = ["build_tenant_pitch"]
