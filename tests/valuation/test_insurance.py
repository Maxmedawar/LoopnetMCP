"""Insurance repricing NOI-bridge checks."""

from cre_mcp.valuation.insurance_model import insurance_repricing


def test_premium_delta_flows_exactly_to_noi_and_critical_gaps_warn():
    result = insurance_repricing(
        {
            "premium": 100,
            "deductibles": {"all": 10},
            "limits": {"all": 1_000},
        },
        [
            {
                "carrier": "Example Mutual",
                "premium": 130,
                "deductible": {"all": 20},
                "limits": {"all": 900},
                "exclusions": ["business interruption", "flood", "wind"],
            }
        ],
        noi=1_000,
    )

    impact = result["quote_impacts"][0]
    assert impact["premium_delta"] == 30
    assert impact["noi_delta"] == -30
    assert impact["noi_after"] == 970
    warning_coverages = {
        warning.get("coverage") for warning in impact["warning_details"]
    }
    assert {"business_interruption", "flood", "wind"} <= warning_coverages
    assert impact["broker_verify"] is True
    assert result["broker_verify"] is True
    assert result["disclaimer"] == (
        "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
    )


def test_bi_abbreviation_does_not_match_inside_liability():
    result = insurance_repricing(
        {"premium": 100, "deductibles": 10, "limits": 1_000},
        [
            {
                "carrier": "Example Mutual",
                "premium": 100,
                "deductible": 10,
                "limits": 1_000,
                "exclusions": ["general liability"],
            }
        ],
        noi=1_000,
    )

    codes = {warning["code"] for warning in result["quote_impacts"][0]["warning_details"]}
    assert "BUSINESS_INTERRUPTION_EXCLUSION" not in codes
    assert "BUSINESS_INTERRUPTION_UNVERIFIED" in codes
