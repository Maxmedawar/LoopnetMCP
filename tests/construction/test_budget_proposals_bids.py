"""Adversarial contracts for convention budgets, proposals, and bid leveling."""

from __future__ import annotations

from cre_mcp.construction import budget as budget_module
from cre_mcp.construction.bids import level_bids
from cre_mcp.construction.proposals import compare_proposals


def test_budget_exposes_cost_conventions_and_labels_every_estimate_until_bid():
    table = budget_module.COST_CONVENTION_TABLE

    assert isinstance(table, dict)
    assert table
    assert all(isinstance(use, str) and use for use in table)

    result = budget_module.development_budget(
        {
            "use": "office",
            "sf_or_units": 10_000,
            "quality": "standard",
            "site": "infill",
            "escalation_pct": 3,
        },
        local_factor=1.10,
    )

    assert "error" not in result
    assert "convention until bid" in result["convention_label"].casefold()
    assert result["convention_table_key"]
    assert result["line_items"]
    assert all(line["low_cents"] <= line["high_cents"] for line in result["line_items"])
    assert all(line["evidence_tag"] for line in result["line_items"])
    convention_lines = [
        line
        for line in result["line_items"]
        if line["category"] in {"hard_cost", "soft_cost", "contingency"}
        and line["item"] != "sitework"
    ]
    assert convention_lines
    assert all(
        "convention" in line["evidence_tag"].casefold()
        for line in convention_lines
    )
    assert result["totals"]["low_cents"] == sum(
        line["low_cents"] for line in result["line_items"]
    )
    assert result["totals"]["high_cents"] == sum(
        line["high_cents"] for line in result["line_items"]
    )
    assert result["totals"]["low_cents"] < result["totals"]["high_cents"]
    assert {flag["role"] for flag in result["professional_review_flags"]} >= {
        "architect",
        "gc",
        "inspector",
    }


def test_proposal_scope_matrix_marks_silence_and_makes_it_the_loudest_risk():
    result = compare_proposals(
        [
            {
                "firm": "Complete Design",
                "role": "architect",
                "fee_structure": {"type": "fixed", "amount_cents": 2_500_000},
                "scope_items": ["construction documents", "permit support"],
                "exclusions": [],
                "assumptions": [],
            },
            {
                "firm": "Quiet Design",
                "role": "architect",
                "fee_structure": {"type": "fixed", "amount_cents": 2_000_000},
                "scope_items": ["construction documents"],
                "exclusions": [],
                "assumptions": [],
            },
            {
                "firm": "Explicit Design",
                "role": "architect",
                "fee_structure": {"type": "fixed", "amount_cents": 1_900_000},
                "scope_items": ["construction documents"],
                "exclusions": ["permit support"],
                "assumptions": [],
            },
        ],
        ["construction documents", "permit support"],
    )

    assert "error" not in result
    rows = {row["scope_item"]: row["status_by_firm"] for row in result["scope_matrix"]}
    permit = rows["permit support"]
    assert permit["Complete Design"] == "covered"
    assert permit["Explicit Design"] == "excluded"
    assert permit["Quiet Design"] == "silent"

    quiet_risks = [
        risk
        for risk in result["risk_notes"]
        if "Quiet Design" in str(risk) and "silent" in str(risk).casefold()
    ]
    assert quiet_risks
    # Silence must not be downgraded below an expressly priced exclusion.
    assert any(
        str(risk.get("severity", "")).casefold() in {"critical", "high", "highest"}
        for risk in quiet_risks
        if isinstance(risk, dict)
    )
    assert {flag["role"] for flag in result["professional_review_flags"]} >= {
        "architect",
        "gc",
        "inspector",
    }


def test_bid_leveling_adds_exclusion_plug_once_and_preserves_plug_honesty():
    result = level_bids(
        [
            {
                "trade": "electrical",
                "contractor": "Low Spark",
                "base_cents": 10_000_001,
                "alternates": [],
                "allowances": [],
                "exclusions": [
                    {
                        "scope": "lighting controls",
                        "plug_cents": 1_234_567,
                    }
                ],
                "unit_prices": [],
            },
            {
                "trade": "electrical",
                "contractor": "Full Current",
                "base_cents": 11_500_000,
                "alternates": [],
                "allowances": [],
                "exclusions": [],
                "unit_prices": [],
            },
        ],
        ["electrical distribution", "lighting controls"],
    )

    assert "error" not in result
    low = next(
        comparison
        for comparison in result["comparisons"]
        if comparison["contractor"] == "Low Spark"
    )
    assert low["base_cents"] == 10_000_001
    assert low["leveled_total_cents"] == 11_234_568
    assert sum(plug["plug_cents"] for plug in low["exclusion_plugs"]) == 1_234_567
    assert all(plug["is_plug"] is True for plug in low["exclusion_plugs"])
    assert all("plug" in plug["evidence_tag"].casefold() for plug in low["exclusion_plugs"])
    assert any("lighting controls" in str(gap) for gap in result["scope_gaps"])
    assert {flag["role"] for flag in result["professional_review_flags"]} >= {
        "architect",
        "gc",
        "inspector",
    }


def test_low_bid_more_than_fifteen_percent_below_median_is_not_silently_ranked():
    result = level_bids(
        [
            {
                "trade": "roofing",
                "contractor": "Too Low",
                "base_cents": 6_000_000,
                "alternates": [],
                "allowances": [],
                "exclusions": [],
            },
            {
                "trade": "roofing",
                "contractor": "Middle",
                "base_cents": 10_000_000,
                "alternates": [],
                "allowances": [],
                "exclusions": [],
            },
            {
                "trade": "roofing",
                "contractor": "High",
                "base_cents": 11_000_000,
                "alternates": [],
                "allowances": [],
                "exclusions": [],
            },
        ],
        ["roofing"],
    )

    assert "error" not in result
    flagged = [
        row
        for row in result["spread_analysis"]
        if row.get("contractor") == "Too Low" and row.get("flagged_low_bid") is True
    ]
    assert flagged
    assert any("15" in str(row) or "median" in str(row).casefold() for row in flagged)
