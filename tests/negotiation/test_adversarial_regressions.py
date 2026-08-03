"""Regressions from the final internal devil's-advocate pass."""

from __future__ import annotations

import pytest

from cre_mcp.negotiation.drift import detect_term_drift
from cre_mcp.negotiation.plan import build_negotiation_plan


def _economics(**changes):
    values = {
        "role": "buyer",
        "value_range": [4_700_000, 5_200_000],
        "walk_away": 5_200_000,
        "target": 4_950_000,
    }
    values.update(changes)
    return values


def test_plan_maps_giver_receiver_to_us_them_explicitly() -> None:
    plan = build_negotiation_plan(
        _economics(
            concessions=[{"type": "price_cut", "params": {"amount": 50_000}}]
        ),
        {},
        [],
    )
    row = plan["concessions"][0]
    assert row["cost_to_us"] == 50_000
    assert row["value_to_them"] == 50_000
    assert row["party_mapping"]["giver"] == "us"


def test_explicit_anchor_cannot_contradict_bounded_rationale() -> None:
    with pytest.raises(ValueError, match="anchor"):
        build_negotiation_plan(_economics(anchor=6_000_000), {}, [])


def test_section_numbers_do_not_win_over_labeled_money() -> None:
    report = detect_term_drift(
        {"price": 5_000_000, "deposit": 100_000, "contingencies": []},
        "Section 2 Purchase Price is $5,000,000. Section 3.1 Deposit shall be $100,000.",
    )
    rows = {row["term"]: row for row in report["term_results"]}
    assert rows["price"]["draft_value"] == 5_000_000
    assert rows["deposit"]["draft_value"] == 100_000


def test_unknown_approval_limit_is_not_pretended_to_be_evaluated() -> None:
    plan = build_negotiation_plan(
        _economics(approval_limits={"special_committee_policy": "consult charter"}),
        {},
        [],
    )
    assert plan["approval_limit_evaluation"][0]["within_limit"] is None
    assert "not automatically interpreted" in plan["approval_limit_evaluation"][0][
        "interpretation"
    ]
