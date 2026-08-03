"""Plain synchronous wrapper smoke tests for the negotiation surface."""

from __future__ import annotations

import inspect

from cre_mcp.config import CreConfig
from cre_mcp.negotiation import tools


EXPECTED = {
    "build_negotiation_plan",
    "value_concession",
    "detect_term_drift",
    "record_negotiation_commitment",
    "list_negotiation_commitments",
    "record_term_approval",
    "negotiation_approval_log",
}


def test_wrappers_are_plain_synchronous_functions() -> None:
    for name in EXPECTED:
        wrapper = getattr(tools, name)
        assert inspect.isfunction(wrapper), f"{name} must remain a plain function"
        assert not inspect.iscoroutinefunction(wrapper), f"{name} must be synchronous"


def test_analytical_wrappers_use_the_documented_call_shapes() -> None:
    economics = {
        "role": "buyer",
        "value_range": [900_000, 1_050_000],
        "walk_away": 1_050_000,
        "target": 1_000_000,
        "daily_carry": 500,
    }
    plan = tools.build_negotiation_plan(economics, {}, [{"name": "cash"}])
    assert plan["anchor"] and plan["assumptions"]

    concession = tools.value_concession(
        {"type": "price_cut", "params": {"amount": 50_000}},
        economics,
        "both",
    )
    assert concession["giver_cost"] == 50_000

    drift = tools.detect_term_drift(
        {"price": 1_000_000, "contingencies": []},
        "Purchase Price: $1,000,000.",
    )
    assert drift.get("term_results", drift.get("terms"))


def test_persistence_wrappers_round_trip_on_configured_cache_path(tmp_path) -> None:
    config = CreConfig(cache_db_path=tmp_path / "wrapper.db")
    commitment = tools.record_negotiation_commitment(
        "deal-wrapper",
        "Seller will deliver the survey",
        "them",
        due="2026-07-25",
        config=config,
    )
    listed = tools.list_negotiation_commitments("deal-wrapper", config=config)
    assert [row["id"] for row in listed] == [commitment["id"]]

    approval = tools.record_term_approval(
        "deal-wrapper",
        "deposit",
        25_000,
        50_000,
        "Acquisitions lead",
        "Deposit remains refundable through diligence",
        config=config,
    )
    log = tools.negotiation_approval_log("deal-wrapper", config=config)
    assert [row["id"] for row in log] == [approval["id"]]
    assert log[0]["approved_by"] == "Acquisitions lead"
    assert log[0]["why"] == "Deposit remains refundable through diligence"

