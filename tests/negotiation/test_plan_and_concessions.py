"""Deterministic negotiation planning and hand-checkable concession math."""

from __future__ import annotations

import json

import pytest

from cre_mcp.negotiation.concessions import value_concession
from cre_mcp.negotiation.plan import build_negotiation_plan


def _render(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str).casefold()


def _economics() -> dict:
    return {
        "role": "buyer",
        "value_range": [4_700_000, 5_200_000],
        "walk_away": 5_200_000,
        "target": 4_950_000,
        "daily_carry": 2_000,
        "batna": "Pursue the comparable Elm Street acquisition",
        "approval_limits": {"max_price_without_ic": 5_000_000},
    }


def test_plan_is_deterministic_and_exposes_every_economic_assumption() -> None:
    counterparty = {
        "constraints": ["must close by quarter end"],
        "history": [
            "Seller rejected a price reduction but offered a 15-day closing extension"
        ],
    }
    structures = [
        {"name": "cash", "certainty": "high"},
        {"name": "seller_financing", "seller_note": 500_000},
    ]

    first = build_negotiation_plan(_economics(), counterparty, structures)
    second = build_negotiation_plan(_economics(), counterparty, structures)

    assert first == second
    assert first["anchor"]["amount"] <= _economics()["target"]
    assert first["anchor"]["role"] == "buyer"
    assert first["anchor"]["basis"]
    assert first["anchor"]["rationale"]
    assert first["concessions"] == sorted(
        first["concessions"],
        key=lambda item: item["rank"],
    )
    assert all(
        {"cost_to_us", "value_to_them"} <= item.keys()
        for item in first["concessions"]
    )
    assert first["walk_away_triggers"]

    rendered = _render(first)
    for assumption in ("4700000", "5200000", "4950000", "2000"):
        assert assumption in rendered
    assert "assumption" in rendered
    assert "pursue the comparable elm street acquisition" in rendered
    assert "cash" in rendered and "seller_financing" in rendered
    assert "batna" in first


def test_counterparty_priority_inference_is_labeled_and_quotes_conduct_evidence() -> None:
    conduct = "Seller rejected a price reduction but offered a 15-day closing extension"
    plan = build_negotiation_plan(
        _economics(),
        {"history": [conduct]},
        [{"name": "cash"}],
    )

    assessment = plan["counterparty_assessment"]
    assert assessment["inferences"], "conduct should produce a cautious inference"
    rendered = _render(assessment)
    assert "inference" in rendered
    assert conduct.casefold() in rendered
    assert "evidence" in rendered or "conduct" in rendered
    # No priority was provided, so it must not be represented as a known fact.
    assert "provided priority" not in rendered


def test_plan_carries_explicit_human_authority_and_approval_limit_posture() -> None:
    plan = build_negotiation_plan(_economics(), {}, [])

    assert "explicit human approval" in plan["authority"]["submit_offer_or_loi"]
    assert "never" in plan["authority"]["commit_funds_or_wire"].casefold()
    rendered = _render(plan)
    assert "5000000" in rendered
    assert "approval" in rendered
    assert any("approval" in _render(trigger) for trigger in plan["walk_away_triggers"])


def test_price_cut_math_is_exactly_fifty_thousand_to_both_sides() -> None:
    result = value_concession(
        {"type": "price_cut", "params": {"amount": 50_000}},
        _economics(),
        perspective="both",
    )

    assert result["giver_cost"] == pytest.approx(50_000)
    assert result["receiver_value"] == pytest.approx(50_000)
    assert result["perspective"] == "both"
    assert "amount" in _render(result["calculation"])
    assert "50000" in _render(result["assumptions"])


def test_dd_extension_cost_is_daily_carry_times_days_and_option_value_is_explicit() -> None:
    result = value_concession(
        {
            "type": "dd_extension",
            "params": {"days": 10, "option_value_per_day": 3_500},
        },
        _economics(),
        perspective="both",
    )

    assert result["giver_cost"] == pytest.approx(2_000 * 10)
    assert result["receiver_value"] == pytest.approx(3_500 * 10)
    rendered = _render(result)
    assert "daily_carry" in rendered or "daily carry" in rendered
    assert "option_value" in rendered or "option value" in rendered
    assert "10" in rendered


def test_dd_extension_does_not_invent_unknown_option_value() -> None:
    result = value_concession(
        {"type": "dd_extension", "params": {"days": 10}},
        _economics(),
    )

    assert result["giver_cost"] == pytest.approx(20_000)
    assert result["receiver_value"] is None
    rendered = _render(result)
    assert "option value" in rendered or "option_value" in rendered
    assert "unknown" in rendered or "not provided" in rendered


def test_contingency_waiver_is_never_presented_without_counsel_flag() -> None:
    result = value_concession(
        {
            "type": "contingency_waiver",
            "params": {"contingency": "financing"},
        },
        _economics(),
    )

    assert result["counsel_flags"]
    rendered = _render(result)
    assert "counsel" in rendered
    assert "financ" in rendered
    assert "risk" in rendered


def test_cheap_for_us_valuable_for_them_is_marked_as_trade_candidate() -> None:
    result = value_concession(
        {
            "type": "timing",
            "params": {
                "days": 5,
                "cost_to_giver": 2_500,
                "value_to_receiver": 25_000,
            },
        },
        _economics(),
    )

    assert result["asymmetry_flag"] is True
    assert result["trade_candidate"] is True
