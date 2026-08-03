"""Real-fixture and synthetic proofs for cited restriction extraction."""

from pathlib import Path

from cre_mcp.leases.reader import read_lease
from cre_mcp.obligations.restrictions import extract_restrictions

FIXTURES = Path(__file__).parents[1] / "fixtures" / "leases"


def test_dollar_tree_real_lease_use_operation_radius_and_transfer_are_cited():
    document = read_lease(FIXTURES / "retail_lease_dollar_tree.htm")
    restrictions = extract_restrictions(document.text, "lease")

    assert any("general merchandise" in str(claim.value).casefold() for claim in restrictions.use_clauses)
    assert restrictions.continuous_operation_requirements
    assert any(claim.value["restricted"] is False for claim in restrictions.radius_restrictions)
    assert restrictions.assignment_subletting_clauses
    claims = [
        *restrictions.use_clauses,
        *restrictions.continuous_operation_requirements,
        *restrictions.radius_restrictions,
        *restrictions.assignment_subletting_clauses,
    ]
    for claim in claims:
        assert claim.status in {"stated", "inferred"}
        assert claim.quote in document.text
        assert claim.locator
        assert len(claim.quote) <= 200


def test_document_silence_is_explicitly_missing():
    restrictions = extract_restrictions("Tenant leases Suite 1 for five years.", "lease")

    assert restrictions.exclusive_use.status == "missing"
    assert restrictions.assignment_subletting_standard.status == "missing"
    assert "exclusive_uses" in restrictions.missing_fields
    assert "assignment_subletting_clauses" in restrictions.missing_fields


def test_ccr_and_lease_clause_families_extract_structured_cited_facts():
    text = (
        "RECORDED DECLARATION. Prohibited Uses: tattoo parlor and cannabis dispensary. "
        "CoffeeCo shall have the exclusive right to sell coffee and espresso in the Property. "
        "CoffeeCo shall not operate a cafe within three (3) miles of the Property. "
        "Co-Tenancy: Target shall remain open and at least 75% of the center shall be occupied; "
        "otherwise Tenant may pay alternative rent or go dark. Tenant shall continuously operate. "
        "Tenant has a Right of First Refusal on any sale of the entire Property."
    )
    restrictions = extract_restrictions(text, "ccr")

    assert restrictions.exclusive_uses
    assert restrictions.prohibited_uses
    assert restrictions.radius_restrictions[0].value["radius_miles"] == 3.0
    assert restrictions.cotenancy_conditions[0].value["occupancy_threshold_pct"] == 75.0
    assert "rent_reduction" in restrictions.cotenancy_conditions[0].value["remedies"]
    assert restrictions.continuous_operation_requirements
    assert restrictions.go_dark_rights
    assert restrictions.rofr_rofo_rights[0].value["scope"] == "whole_property"
    for claims in (
        restrictions.exclusive_uses,
        restrictions.prohibited_uses,
        restrictions.radius_restrictions,
        restrictions.cotenancy_conditions,
        restrictions.rofr_rofo_rights,
    ):
        assert all(claim.quote in text for claim in claims)
