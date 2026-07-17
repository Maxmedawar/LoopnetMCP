"""Penny-exact acceptance tests for the dated cash-needs schedule."""

from cre_mcp.finops.cashneeds import cash_requirements


def test_cash_schedule_and_peak_math_are_penny_exact_across_all_need_types():
    result = cash_requirements(
        30,
        {
            "closings": [
                {"deal": "Acquisition A", "date": "2026-07-15", "equity_cents": 10_001}
            ],
            "capex": [{"date": "2026-07-16", "cents": 2_003}],
            "reserves": [{"date": "2026-07-15", "cents": 3_007}],
            "capital_calls": [{"date": "2026-07-17", "call_cents": 4_009}],
            "operating_shortfalls": [{"date": "2026-07-18", "cents": 5_011}],
            "available_cents": 20_000,
            "opaque_adjustment": "must be surfaced, not silently used",
        },
        as_of="2026-07-14",
    )

    assert "error" not in result
    assert result["totals_cents"] == {
        "closings": 10_001,
        "capex": 2_003,
        "reserves": 3_007,
        "capital_calls": 4_009,
        "operating_shortfalls": 5_011,
        "total_requirement": 24_031,
    }
    assert [row["date"] for row in result["schedule"]] == [
        "2026-07-15",
        "2026-07-16",
        "2026-07-17",
        "2026-07-18",
    ]
    assert [row["total_requirement_cents"] for row in result["schedule"]] == [
        13_008,
        2_003,
        4_009,
        5_011,
    ]
    assert [row["cumulative_requirement_cents"] for row in result["schedule"]] == [
        13_008,
        15_011,
        19_020,
        24_031,
    ]
    assert result["peak_daily_need_cents"] == 13_008
    assert result["peak_need_cents"] == 24_031
    assert result["coverage_vs_available_cents"] == -4_031
    assert result["coverage"]["shortfall_cents"] == 4_031
    assert result["coverage"]["surplus_cents"] == 0
    assert any(
        field.endswith("opaque_adjustment") for field in result["unrecognized_inputs"]
    )
