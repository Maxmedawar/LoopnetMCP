"""Focused tests for read-only, valuation-ranked diligence requests."""

from cre_mcp.leaseops.requests import FIELD_WEIGHTS_BPS, diligence_request_list


def _claim(document_id: str, value: int, unit: str = "usd") -> dict:
    return {
        "field": "fixture",
        "subject": None,
        "figure": {
            "value": value,
            "unit": unit,
            "confidence": 90,
            "lineage": {
                "document_id": document_id,
                "doc_kind": "lease" if document_id == "lease" else "offering_memorandum",
                "page": 12,
                "raw_text": f"Fixture amount {value}",
            },
        },
        "flags": [],
    }


def _truth_report() -> dict:
    return {
        "deal_id": "deal-requests",
        "resolutions": [],
        "conflicts": [
            {
                "field": "noi",
                "subject": None,
                "rule": "source_disagreement",
                "severity": "material",
                "claims": [_claim("lease", 1_000), _claim("om", 1_100)],
                "resolved_value": 1_000,
                "resolution": "unresolved",
                "needs_human_review": True,
                "explanation": "NOI differs across the cited documents.",
            },
            {
                "field": "base_rent",
                "subject": "Suite 101",
                "rule": "source_disagreement",
                "severity": "material",
                "claims": [_claim("lease", 2_000), _claim("om", 2_300)],
                "resolved_value": 2_000,
                "resolution": "auto_hierarchy",
                "needs_human_review": True,
                "explanation": "Base rent differs across the cited documents.",
            },
        ],
        "doc_kinds_present": ["lease", "offering_memorandum"],
        "generated_at": "2026-07-14T00:00:00+00:00",
    }


def _room_index() -> dict:
    return {
        "deal_id": "deal-requests",
        "initialized": True,
        "items": [
            {
                "doc_key": "all_leases",
                "label": "All leases and guaranties",
                "phase": "diligence",
                "status": "missing",
                "required": True,
                "conditional_active": True,
                "graded": True,
                "why_it_matters": "Executed leases establish the controlling economics.",
            },
            {
                "doc_key": "historical_financials",
                "label": "Three years of operating statements",
                "phase": "diligence",
                "status": "requested",
                "required": True,
                "conditional_active": True,
                "graded": True,
                "why_it_matters": "History tests recurring NOI.",
            },
            {
                "doc_key": "tenant_cois",
                "label": "Tenant certificates of insurance",
                "phase": "diligence",
                "status": "missing",
                "required": False,
                "conditional_active": False,
                "graded": False,
                "why_it_matters": "COIs evidence required coverage.",
            },
            {
                "doc_key": "rent_roll",
                "label": "Current certified rent roll",
                "phase": "loi",
                "status": "reviewed",
                "required": True,
                "conditional_active": True,
                "graded": True,
                "why_it_matters": "The rent roll supports occupancy and rent.",
            },
        ],
    }


def test_conflicts_rank_by_integer_cent_magnitude_times_exposed_field_weight():
    result = diligence_request_list("deal-requests", _truth_report(), _room_index())

    assert "error" not in result
    assert [item["field"] for item in result["requests"][:2]] == ["base_rent", "noi"]
    assert result["requests"][0]["conflict_magnitude_cents"] == 30_000
    assert result["requests"][0]["valuation_impact_cents"] == 27_000
    assert result["requests"][1]["valuation_impact_cents"] == 10_000
    conventions = result["valuation_impact_conventions"]
    assert conventions["field_weights_bps"] == FIELD_WEIGHTS_BPS
    assert "conflict_magnitude_cents" in conventions["conflict_formula"]
    assert "not appraisal assumptions" in conventions["limitation"]


def test_missing_documents_are_ready_to_send_and_do_not_invent_dollar_impact():
    result = diligence_request_list("deal-requests", _truth_report(), _room_index())
    documents = [
        request for request in result["requests"] if request["request_type"] == "missing_document"
    ]

    assert [request["doc_key"] for request in documents] == [
        "all_leases",
        "historical_financials",
    ]
    assert documents[0]["valuation_impact_cents"] is None
    assert documents[0]["why_it_matters"]
    assert documents[1]["request_text"].startswith("As a follow-up")
    assert "tenant_cois" not in result["ready_to_send_request_list"]
    assert "Why it matters:" in result["ready_to_send_request_list"]
    assert result["read_only_sources"] == [
        "truth reconciliation report",
        "data-room completeness index",
    ]


def test_unrecognized_or_cross_deal_input_is_rejected_at_the_boundary():
    truth = _truth_report()
    truth["silently_ignored"] = "must not be dropped"
    unrecognized = diligence_request_list("deal-requests", truth, _room_index())

    assert unrecognized["error"] == "unrecognized input fields"
    assert unrecognized["unrecognized_inputs"] == {
        "truth_report": ["silently_ignored"]
    }

    room = _room_index()
    room["deal_id"] = "another-deal"
    mismatch = diligence_request_list("deal-requests", _truth_report(), room)
    assert mismatch["error"] == "data_room_index.deal_id does not match deal_id"


def test_nested_typo_and_malformed_money_are_returned_as_errors():
    truth = _truth_report()
    truth["conflicts"][0]["claims"][0]["figure"]["vale"] = 1_000
    typo = diligence_request_list("deal-requests", truth, _room_index())
    assert typo["error"].startswith("unrecognized input fields at")
    assert "vale" in typo["error"]

    truth = _truth_report()
    truth["conflicts"][0]["claims"][0]["figure"]["value"] = True
    malformed = diligence_request_list("deal-requests", truth, _room_index())
    assert malformed["error"] == "monetary value must be numeric"

    room = _room_index()
    room["items"][0]["statuz"] = "missing"
    nested_room = diligence_request_list("deal-requests", _truth_report(), room)
    assert nested_room["error"].startswith("unrecognized input fields at")
    assert "statuz" in nested_room["error"]


def test_nonmonetary_conflict_is_included_with_an_honest_unquantified_gap():
    truth = _truth_report()
    truth["conflicts"] = [
        {
            "field": "tenant_name",
            "subject": "Suite 101",
            "claims": [
                _claim("lease", "Alpha LLC", "text"),
                _claim("om", "Beta LLC", "text"),
            ],
            "resolved_value": "Alpha LLC",
            "resolution": "unresolved",
            "needs_human_review": True,
            "explanation": "The tenant identity conflicts.",
        }
    ]

    result = diligence_request_list("deal-requests", truth, _room_index())
    conflict = result["requests"][0]

    assert conflict["field"] == "tenant_name"
    assert conflict["valuation_impact_cents"] is None
    assert conflict["ranking_tier"] == "unquantified_conflict"
    assert any("no comparable monetary claims" in gap for gap in result["honest_gaps"])
