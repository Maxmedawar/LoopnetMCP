from __future__ import annotations

from cre_mcp.title.easements import assess_recorded_burdens
from cre_mcp.title.legal_compare import compare_legal_descriptions


def test_legal_description_acreage_mismatch_is_cited_and_unresolved() -> None:
    result = compare_legal_descriptions(
        [
            {
                "source": "deed",
                "text_or_hash": "Lot 4, Block B of Mesa Park, containing 9.75 acres.",
                "acreage": 9.75,
                "lot_block": "Lot 4, Block B",
            },
            {
                "source": "survey",
                "text_or_hash": "Lot 4 Block B of Mesa Park, containing 10.00 acres.",
                "acreage": 10,
                "lot_block": "lot 4 block b",
            },
        ]
    )

    assert "error" not in result
    mismatch = next(issue for issue in result["conflicts"] if issue["issue_type"] == "acreage_mismatch")
    assert mismatch["severity"] == "high"
    assert mismatch["legal_conclusion"] is None
    assert {evidence["value"] for evidence in mismatch["evidence"]} == {"9.75", "10"}
    assert all(evidence["quote"] and evidence["locator"] for evidence in mismatch["evidence"])
    assert mismatch["route_to"] == ["surveyor", "counsel"]


def test_legal_description_normalization_ignores_presentation_only_changes() -> None:
    result = compare_legal_descriptions(
        [
            {"source": "deed", "text_or_hash": "LOT 4, BLOCK B; MESA PARK"},
            {"source": "title", "text_or_hash": "Lot 4 Block B Mesa Park"},
        ]
    )

    assert not any(
        issue["issue_type"] == "legal_description_hash_mismatch"
        for issue in result["conflicts"]
    )


def test_access_easement_through_building_pad_is_fatal_screening_flag() -> None:
    result = assess_recorded_burdens(
        [
            {
                "kind": "easement",
                "text": (
                    "A perpetual access easement crosses through the proposed building pad "
                    "for ingress and egress."
                ),
            }
        ],
        "construct a retail building on the proposed pad",
    )

    assert "error" not in result
    issue = result["issues"][0]
    assert issue["issue_type"] == "access_through_building_pad"
    assert issue["severity"] == "fatal"
    assert issue["fatal_flag"] is True
    assert "access easement" in issue["evidence"][0]["quote"].lower()
    assert issue["legal_conclusion"] is None
    assert "not a legal conclusion" in issue["convention"].lower()
    assert issue["evidence"][0]["quote"]
    assert issue["evidence"][0]["locator"].startswith("items[0].text line")
    assert "counsel" in issue["route_to"]


def test_utility_easement_at_edge_uses_disclosed_routine_convention() -> None:
    result = assess_recorded_burdens(
        [
            {
                "kind": "easement",
                "text": "A ten-foot utility easement lies along the east property line.",
            }
        ],
        "warehouse",
    )

    issue = result["issues"][0]
    assert issue["issue_type"] == "utility_at_edge"
    assert issue["severity"] == "routine"
    assert issue["fatal_flag"] is False
    assert "routine" in issue["convention"].lower()


def test_restriction_scope_delegates_to_obligations_extractor() -> None:
    result = assess_recorded_burdens(
        [
            {
                "kind": "restriction",
                "text": "No portion of the Property shall be used for a liquor store.",
            }
        ],
        "retail liquor store",
    )

    delegated = result["burdens"][0]["restriction_extraction"]
    assert delegated["extraction_owner"] == "cre_mcp.obligations.extract_restrictions"
    assert delegated["kind"] == "ccr"
    claims = delegated["claims"]["prohibited_uses"]
    assert claims
    assert all(claim["quote"] and claim["locator"] for claim in claims)
    issue = result["issues"][0]
    assert issue["issue_type"] == "intended_use_restriction_overlap"
    assert issue["severity"] == "high"
    assert "liquor" in issue["intended_use_overlap_terms"]
    assert issue["legal_conclusion"] is None


def test_empty_burden_input_is_an_explicit_gap_not_clearance() -> None:
    result = assess_recorded_burdens([], "warehouse")

    assert result["issues"] == []
    gap = next(item for item in result["missing_fields"] if item["field"] == "items")
    assert gap["value"] is None
    assert "not evidence" in gap["impact"]


def test_invalid_inputs_return_error_boundary() -> None:
    assert "error" in compare_legal_descriptions([])
    assert "error" in assess_recorded_burdens([{"kind": "easement"}], "warehouse")


def test_equivalent_supplied_sha256_hash_and_single_source_gap() -> None:
    digest = "a" * 64
    result = compare_legal_descriptions(
        [
            {"source": "deed", "text_or_hash": digest},
            {"source": "title", "text_or_hash": f"sha256:{digest}"},
        ]
    )
    assert not any(
        issue["issue_type"] == "legal_description_hash_mismatch"
        for issue in result["conflicts"]
    )

    single = compare_legal_descriptions([{"source": "deed", "text_or_hash": digest}])
    assert single["comparison_gaps"][0]["value"] is None
    assert "not evidence" in single["comparison_gaps"][0]["impact"]


def test_intended_use_overlap_never_downgrades_fatal_pad_access() -> None:
    result = assess_recorded_burdens(
        [
            {
                "kind": "restriction",
                "text": (
                    "An access easement crosses through the proposed building pad. "
                    "No portion of the Property shall be used for a liquor store."
                ),
            }
        ],
        "liquor store",
    )

    issue = result["issues"][0]
    assert issue["issue_type"] == "access_through_building_pad"
    assert issue["severity"] == "fatal"
    assert issue["fatal_flag"] is True
