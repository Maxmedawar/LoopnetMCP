"""Suite-level rollover hand checks."""

import pytest

from cre_mcp.valuation.rollover import suite_rollover_model


def test_expected_rollover_cost_matches_probability_weighted_hand_math():
    result = suite_rollover_model(
        [
            {
                "suite": "100",
                "sf": 1_000,
                "current_rent_psf": 20,
                "market_rent_psf": {"low": 24, "high": 30},
                "expiry": 1,
                "renewal_prob": 60,
                "months_downtime": {"low": 6, "high": 12},
                "ti_new_psf": 30,
                "ti_renew_psf": 5,
                "lc_pct": 5,
            }
        ],
        hold_years=1,
        analysis_date="2026-01-01",
    )

    # Low: .6*1,000*5 + .4*1,000*30 + .4*24,000*.05 + .4*24,000*6/12.
    # High substitutes $30 market rent and twelve months of downtime.
    assert result["suites"][0]["expected_rollover_cost"] == {
        "low": pytest.approx(20_280),
        "high": pytest.approx(27_600),
    }
    assert result["portfolio"]["sf_weighted_expected_downtime_months"] == {
        "low": pytest.approx(2.4),
        "high": pytest.approx(4.8),
    }
    assert len(result["annual_blended_noi_path"]) == 1
    assert "conventions, not predictions" in result["conventions"]["renewal_probability_note"]
    assert result["disclaimer"] == (
        "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
    )
