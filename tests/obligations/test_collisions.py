"""Synthetic cross-document collision screens and conservative matching."""

import pytest

from cre_mcp.obligations.collisions import detect_collisions
from cre_mcp.obligations.restrictions import extract_restrictions
from cre_mcp.obligations.tools import (
    detect_obligation_collisions,
    extract_lease_restrictions,
)


def _context(text: str, **proposed):
    return {
        "existing_restrictions": [extract_restrictions(text, "lease")],
        "proposed": {
            "tenant_name": "Proposed Tenant",
            "use_description": "",
            "category": "",
            **proposed,
        },
    }


def test_exclusive_coffee_vs_cafe_is_fatal_synonym_overlap_with_both_sides_cited():
    collisions = detect_collisions(
        _context(
            "CoffeeCo shall have the exclusive right to operate a coffee shop and sell espresso.",
            use_description="Neighborhood cafe serving espresso drinks",
            category="cafe",
        )
    )

    finding = next(item for item in collisions if item.type == "exclusive_use_conflict")
    assert finding.severity == "fatal"
    assert finding.match_status == "confirmed_overlap"
    assert "exclusive" in finding.side_a.quote.casefold()
    assert "cafe" in finding.side_b.quote.casefold()
    assert finding.side_a.cite and finding.side_b.cite
    assert "legal conclusion" in finding.why
    assert "counsel" not in finding.counsel_question.casefold() or finding.counsel_question


def test_prohibited_use_hit_is_flagged():
    collisions = detect_collisions(
        _context(
            "Prohibited Uses: adult entertainment, tattoo parlor, and cannabis dispensary.",
            use_description="State-licensed marijuana dispensary",
            category="cannabis",
        )
    )

    finding = next(item for item in collisions if item.type == "prohibited_use")
    assert finding.severity == "fatal"
    assert finding.match_status == "confirmed_overlap"


def test_ambiguous_food_overlap_is_possible_conflict_never_silently_cleared():
    collisions = detect_collisions(
        _context(
            "Tenant has the exclusive use for a bakery selling pastries and prepared food.",
            use_description="Small cafe with sandwiches and beverages",
            category="cafe",
        )
    )

    finding = next(item for item in collisions if item.type == "exclusive_use_conflict")
    assert finding.match_status == "possible_conflict"
    assert finding.severity == "material"
    assert finding.why.startswith("possible_conflict:")


def test_cotenancy_closed_anchor_is_material_risk():
    context = _context(
        "Co-Tenancy condition: Target shall remain open and at least 80% occupancy is required; "
        "otherwise Tenant may pay alternative rent.",
        use_description="General retail",
        category="retail",
    )
    context["portfolio_sites"] = [{"anchor_name": "Target", "is_open": False}]

    finding = next(item for item in detect_collisions(context) if item.type == "cotenancy_risk")
    assert finding.severity == "material"
    assert finding.match_status == "confirmed_overlap"
    assert "is_open=False" in finding.side_b.quote


def test_radius_distance_input_and_assignment_block_are_screened():
    radius_context = _context(
        "Tenant shall not operate another gym within five (5) miles of the Property.",
        tenant_name="Proposed Tenant",
        use_description="Fitness gym",
        category="fitness",
    )
    radius_context["portfolio_sites"] = [
        {"name": "Existing Gym", "category": "gym", "distance_miles": 2.5}
    ]
    radius = next(item for item in detect_collisions(radius_context) if item.type == "radius_violation")
    assert radius.match_status in {"confirmed_overlap", "possible_conflict"}

    assignment = detect_collisions(
        _context(
            "Tenant shall not assign this Lease or sublet the Premises under any circumstances.",
            use_description="Master lease control structure",
            category="retail",
            intended="master_lease",
        )
    )
    blocker = next(item for item in assignment if item.type == "assignment_blocked")
    assert blocker.severity == "fatal"


@pytest.mark.parametrize("input_form", ["object", "serialized", "raw"])
def test_tool_boundary_accepts_all_restriction_input_forms(input_form):
    text = "CoffeeCo has the exclusive right to operate a coffee shop and sell espresso."
    if input_form == "object":
        entry = extract_restrictions(text, "lease")
    elif input_form == "serialized":
        entry = extract_lease_restrictions(text, "lease")
    else:
        entry = {
            "source_label": "Suite 110 lease",
            "kind": "lease",
            "text": text,
        }

    result = detect_obligation_collisions(
        {
            "existing_restrictions": [entry],
            "proposed": {
                "tenant_name": "New Cafe",
                "category": "cafe",
                "use_description": "Cafe serving espresso drinks",
            },
        }
    )

    fatal = next(item for item in result if item["type"] == "exclusive_use_conflict")
    assert fatal["severity"] == "fatal"
    assert fatal["side_a"]["quote"]
    assert fatal["side_a"]["cite"]
    if input_form == "raw":
        assert "Suite 110 lease" in fatal["side_a"]["cite"]


def test_tool_boundary_reports_unusable_entries_even_when_other_input_is_usable():
    result = detect_obligation_collisions(
        {
            "existing_restrictions": [
                {"source_label": "Broken upload", "kind": "lease"},
                {
                    "text": "CoffeeCo has the exclusive right to sell coffee.",
                    "source_label": "Good lease",
                },
            ],
            "proposed": {
                "tenant_name": "CafeCo",
                "category": "cafe",
                "use_description": "Coffee cafe",
            },
        }
    )

    issue = next(item for item in result if item["type"] == "unusable_inputs")
    assert issue["severity"] == "material"
    assert issue["unusable_inputs"][0]["index"] == 0
    assert issue["unusable_inputs"][0]["source_label"] == "Broken upload"
    assert issue["unusable_inputs"][0]["reason"]
    assert any(item["type"] == "exclusive_use_conflict" for item in result)


def test_tool_boundary_never_returns_empty_when_no_restriction_input_is_usable():
    result = detect_obligation_collisions(
        {
            "existing_restrictions": [{"unexpected": "shape"}],
            "proposed": {
                "tenant_name": "CafeCo",
                "category": "cafe",
                "use_description": "Coffee cafe",
            },
        }
    )

    assert result
    assert result[0]["type"] == "input_error"
    assert result[0]["severity"] == "fatal"
    assert "did not run" in result[0]["input_error"]
    assert result[0]["unusable_inputs"][0]["index"] == 0
