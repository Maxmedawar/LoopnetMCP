"""Deterministic listing-prose fact extraction."""

import pytest

from cre_mcp.enrichment.listing_facts import extract_facts
from cre_mcp.models import Listing


def _listing(**overrides) -> Listing:
    values = {
        "source": "fixture",
        "source_id": "listing-facts",
        "name": "Commercial Investment",
        "address": "100 Congress Ave",
        "city": "Austin",
        "state": "TX",
        "property_type": "Retail",
        "url": "https://example.test/listing-facts",
    }
    values.update(overrides)
    return Listing(**values)


def test_extracts_austin_style_nnn_headline_facts():
    listing = _listing(
        name="7-Eleven | Brand-New 16-Year Absolute NNN Lease",
        description=(
            "Single-tenant net-leased investment featuring 1.5% annual increases "
            "and a corporate guaranty."
        ),
        highlights=["New construction", "Long-term lease"],
    )

    facts = extract_facts(listing)

    assert facts.strategy_hint == "nnn_retail"
    assert facts.lease_years_remaining == pytest.approx(16.0)
    assert facts.rent_escalations == pytest.approx(1.5)
    assert facts.nnn_purity == "absolute"
    assert facts.tenant_name == "7-Eleven"
    assert facts.guaranty == "corporate"


def test_periodic_and_flat_rent_are_normalized_to_annual_percent():
    periodic = extract_facts(
        _listing(description="NNN lease with 10% increases every 5 years.")
    )
    flat = extract_facts(_listing(description="Single tenant with flat rent."))

    assert periodic.rent_escalations == pytest.approx(2.0)
    assert flat.rent_escalations == 0.0


def test_multifamily_and_location_retail_strategy_hints():
    multifamily = extract_facts(
        _listing(
            property_type="Multifamily",
            property_subtype="Apartments",
            name="82-Unit Value-Add Apartment Community",
        )
    )
    location = extract_facts(
        _listing(
            name="Downtown Storefront",
            description="Street retail on a signalized hard corner.",
        )
    )

    assert multifamily.strategy_hint == "value_add_multifamily"
    assert location.strategy_hint == "location_retail"


def test_unknown_prose_is_none_safe_and_generic():
    facts = extract_facts(
        _listing(
            name="Commercial Investment",
            property_type=None,
            description=None,
        )
    )

    assert facts.strategy_hint == "generic"
    assert facts.lease_years_remaining is None
    assert facts.rent_escalations is None
    assert facts.nnn_purity is None
    assert facts.guaranty is None


def test_tenant_extraction_handles_context_without_mistaking_target_metrics():
    local = extract_facts(
        _listing(
            name="NNN Investment Opportunity",
            description="Tenant: Local Foods LLC, with a new 12-year lease.",
        )
    )
    metric = extract_facts(
        _listing(
            name="NNN Investment Opportunity",
            description="Target cap rate is 6.5% on this single-tenant property.",
        )
    )

    assert local.tenant_name == "Local Foods LLC"
    assert metric.tenant_name is None
