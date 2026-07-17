"""Contract and adversarial tests for honest trend extrapolation."""

from cre_mcp.analytics.trends import trend_bands


def test_trend_bands_extends_line_and_labels_honesty() -> None:
    result = trend_bands(
        [
            {"period": 2022, "value": 10},
            {"period": 2023, "value": 12},
            {"period": 2024, "value": 14},
            {"period": 2025, "value": 16},
        ],
        2,
    )

    assert result["trend"]["slope_per_period"] == 2
    assert result["residual_spread"] == 0
    assert result["extrapolation"] == [
        {
            "step": 1,
            "period": 2026,
            "trend": 18,
            "lower_band": 18,
            "upper_band": 18,
        },
        {
            "step": 2,
            "period": 2027,
            "trend": 20,
            "lower_band": 20,
            "upper_band": 20,
        },
    ]
    assert result["honesty"].startswith(
        "extrapolation of history, NOT a forecast; bands show past variability only"
    )
    assert "no coverage probability" in result["band_method"]


def test_trend_bands_refuses_horizon_over_half_of_history() -> None:
    result = trend_bands(
        [
            {"period": "Q1", "value": 1},
            {"period": "Q2", "value": 2},
            {"period": "Q3", "value": 3},
            {"period": "Q4", "value": 4},
        ],
        3,
    )

    assert result["status"] == "REFUSED_HORIZON_TOO_LONG"
    assert result["maximum_horizon"] == 2
    assert "exceeds half" in result["error"]
    assert "add history or shorten" in result["reason"]
    assert "NOT a forecast" in result["honesty"]


def test_trend_bands_surfaces_unknown_row_fields_and_contains_nulls() -> None:
    result = trend_bands(
        [
            {"period": "one", "value": 2, "vaule": 999},
            {"period": "two", "value": 3},
        ],
        1,
    )
    assert result["unrecognized_inputs"] == ["series[0].vaule"]

    invalid = trend_bands(
        [{"period": "one", "value": 2}, {"period": "two", "value": None}],
        1,
    )
    assert invalid["error"].startswith("trend_bands:")
    assert "series[1].value" in invalid["error"]
