"""Entity/vehicle recommendations and hard-trap tests."""

import pytest
from pydantic import ValidationError

from cre_mcp.structure.entity import recommend_structure


def test_multi_member_llc_interest_is_loudly_1031_ineligible():
    advice = recommend_structure(
        {"mode": "syndication", "investors": 4, "passive": False, "state": "TX"}
    )
    all_text = " ".join([*advice.traps, *advice.eligibility_notes.values()])

    assert advice.recommended == "LLC"
    assert "1031-INELIGIBLE" in all_text
    assert "multi-member LLC" in all_text
    assert "SEC GATE" in all_text
    assert "securities attorney" in advice.counsel_gate
    assert "Phase 19" in all_text


def test_passive_1031_recommends_dst_and_marks_it_potentially_eligible():
    advice = recommend_structure(
        {"mode": "1031", "investors": 0, "passive": True, "state": "AZ"}
    )

    assert advice.recommended == "DST"
    assert "1031-eligible" in advice.eligibility_notes["DST"]
    assert "Revenue Ruling 2004-86" in advice.eligibility_notes["DST"]
    assert "no operating control" in advice.eligibility_notes["DST"]
    assert "Qualified Intermediary" in advice.counsel_gate
    assert any("SAME-TAXPAYER-TITLE" in trap for trap in advice.traps)


def test_multiple_1031_taxpayers_route_to_tic_not_partnership_interest():
    advice = recommend_structure(
        {"mode": "1031", "investors": 2, "passive": False}
    )

    assert advice.recommended == "TIC"
    assert "direct undivided" in advice.eligibility_notes["TIC"]
    assert "not a blanket safe harbor" in advice.eligibility_notes["TIC"]


def test_opportunity_zone_mode_explains_ten_year_basis_election():
    advice = recommend_structure({"mode": "oz", "investors": 0, "passive": True})

    assert advice.recommended == "QOF"
    assert "10 years" in advice.eligibility_notes["QOF"]
    assert "fair-market-value basis adjustment" in advice.eligibility_notes["QOF"]
    assert "Opportunity Zone tax counsel" in advice.counsel_gate


def test_bad_structure_intent_is_rejected():
    with pytest.raises(ValidationError):
        recommend_structure({"mode": "flip"})
    with pytest.raises(ValidationError):
        recommend_structure({"mode": "solo", "investors": -1})
