"""Focused regression tests for JV comparison and mandate checks."""

import pytest

from cre_mcp.capital.waterfall import model_waterfall
from cre_mcp.fund.jv import compare_jv_structures
from cre_mcp.fund.mandate import check_mandate_limits


def _jv_structure():
    return {
        "name": "Eight pref / twenty promote",
        "promote_tiers": [
            {"hurdle_pct": 0, "gp_promote_pct": 20},
        ],
        "pref_pct": 8,
        "catchup": True,
        "control_rights": {
            "major_decisions": "unanimous consent",
            "removal": "for cause",
            "forced_sale": "after year five",
            "rofr": "mutual",
        },
        "capital": {
            "gp_coinvest_pct": 0,
            "capital_call_remedies": "governing document input: dilution after notice",
        },
        "fees": {"am_pct": 1.5, "acq_pct": 1},
    }


def _three_scenarios():
    return {
        "total_equity": 1_000_000,
        "deal_ref": "fixture:jv-one",
        "scenarios": {
            "downside": {
                "annual_cash_flows": [1_000_000],
                "source": "approved downside underwriting row 1",
            },
            "base": {
                "annual_cash_flows": [1_500_000],
                "source": "approved base underwriting row 2",
            },
            "upside": {
                "annual_cash_flows": [2_000_000],
                "source": "approved upside underwriting row 3",
            },
        },
    }


def test_jv_hand_split_matches_existing_capital_waterfall():
    comparison = compare_jv_structures([_jv_structure()], _three_scenarios())
    base = comparison["structures"][0]["outcomes"][1]
    direct = model_waterfall(
        {"deal_ref": "fixture:jv-one", "total_equity": 1_000_000},
        {
            "total_equity": 1_000_000,
            "annual_cash_flows": [1_500_000],
            "pref": 8,
            "gp_promote": 20,
            "lp_equity_pct": 100,
            "catch_up": True,
            "lp_residual_split": 80,
            "tiered_splits": [],
        },
    ).model_dump(mode="json")

    assert base["waterfall"]["lp_cash_flows"] == direct["lp_cash_flows"]
    assert base["waterfall"]["gp_cash_flows"] == direct["gp_cash_flows"]
    assert base["waterfall"]["years"] == direct["years"]
    assert base["input_source"] == "approved base underwriting row 2"
    assert base["lp_distribution"] == 1_400_000
    assert base["gp_distribution"] == 100_000
    assert len(comparison["comparison_matrix"]["control_and_downside"]) == 1
    assert comparison["structures"][0]["economic_terms"]["fees"]["acq_pct"] == 1.0
    assert "HARD GATE" in comparison["guardrail"]
    assert "SCENARIOS, NOT PROMISES" in comparison["anti_fraud_warning"]


def test_jv_requires_three_supplied_outcomes_and_refuses_guarantee_language():
    scenarios = _three_scenarios()
    del scenarios["scenarios"]["upside"]
    with pytest.raises(ValueError, match="exactly three"):
        compare_jv_structures([_jv_structure()], scenarios)

    structure = _jv_structure()
    structure["control_rights"]["major_decisions"] = "guaranteed return approval"
    with pytest.raises(ValueError, match="anti-fraud language"):
        compare_jv_structures([structure], _three_scenarios())


def test_mandate_single_asset_21_percent_exceeds_20_percent():
    portfolio = [
        {
            "asset": f"Existing {index}",
            "value_cents": value,
            "geography": "TX",
            "asset_type": "industrial",
            "source": f"fund ledger asset {index}",
        }
        for index, value in enumerate((16_00, 16_00, 16_00, 16_00, 15_00), start=1)
    ]
    proposed = {
        "asset": "Proposed 21",
        "value_cents": 21_00,
        "geography": "CA",
        "asset_type": "office",
        "source": "investment committee packet 44",
    }
    result = check_mandate_limits(
        {
            "max_single_asset_pct": 20,
            "geography_limits": {"CA": 30},
            "asset_type_limits": {"office": 25},
            "side_letters": [],
        },
        portfolio,
        proposed,
    )

    single_asset = next(
        item for item in result["limits"] if item["limit"] == "max_single_asset_pct"
    )
    assert single_asset["passed"] is False
    assert single_asset["computed_exposure_pct"] == 21.0
    assert single_asset["limit_pct"] == 20.0
    assert single_asset["calculation"] == "2100 / 10000"
    assert result["passed"] is False
    assert "REVIEW WITH FUND COUNSEL" in result["counsel_flags"][0]
    assert "HARD GATE" in result["guardrail"]


def test_mandate_leverage_and_side_letter_conflicts_are_explicit():
    portfolio = [
        {
            "asset": "A",
            "value_cents": 60_00,
            "debt_cents": 20_00,
            "geography": "TX",
            "asset_type": "industrial",
        }
    ]
    proposed = {
        "asset": "B",
        "value_cents": 40_00,
        "debt_cents": 30_00,
        "geography": "CA",
        "asset_type": "office",
    }
    result = check_mandate_limits(
        {
            "max_leverage": 45,
            "side_letters": [
                {
                    "investor": "Investor One",
                    "provision": {"prohibited_geographies": ["CA"]},
                },
                {
                    "investor": "Investor Two",
                    "provision": "Most-favored-nation election; counsel to interpret",
                },
            ],
        },
        portfolio,
        proposed,
    )

    leverage = next(item for item in result["limits"] if item["limit"] == "max_leverage")
    assert leverage["computed_exposure_pct"] == 50.0
    assert leverage["passed"] is False
    assert result["side_letter_conflicts"][0]["investor"] == "Investor One"
    assert result["side_letter_reviews"][1]["status"] == "review_required"


def test_unstructured_side_letter_cannot_produce_verified_pass():
    result = check_mandate_limits(
        {
            "max_single_asset_pct": 100,
            "side_letters": [
                {
                    "investor": "Investor One",
                    "provision": "Most-favored-nation election; counsel to interpret",
                }
            ],
        },
        [],
        {"asset": "Only Asset", "value_cents": 100, "source": "IC row 1"},
    )

    assert result["passed"] is False
    assert result["overall_status"] == "review_required"
    assert result["unresolved_side_letters"][0]["investor"] == "Investor One"
