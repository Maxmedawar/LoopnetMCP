"""Risk-adjusted residual probability checks."""

import pytest

from cre_mcp.valuation.residual import risk_adjusted_residual


def test_probability_weighted_residual_components_sum_to_reported_value():
    result = risk_adjusted_residual(
        {
            "units_or_sf": 10,
            "rent": 20,
            "cost": 10,
            "timeline": 2,
        },
        {"entitlement": 0.5, "cost_overrun": 0.2, "lease_up": 0.5},
    )

    # Unadjusted residual = 10 * (20 * 2 - 10) = 300; joint success = .2.
    assert result["probability_math"]["joint_success_probability"] == pytest.approx(0.2)
    assert result["probability_math"]["probability_sum"] == pytest.approx(1.0)
    assert result["probability_math"]["sum_check"] is True
    assert result["risk_adjusted_residual_range"]["base"] == pytest.approx(60)
    assert result["component_sum"]["base"]["total"] == pytest.approx(60)
    assert result["dominant_assumption"] in {
        "rent",
        "cost",
        "timeline",
        "entitlement",
        "cost_overrun",
        "lease_up",
    }
    assert result["honesty"] == "conventions not predictions"
    assert result["disclaimer"] == (
        "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
    )
