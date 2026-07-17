"""Incentive-cliff event timeline checks."""

from cre_mcp.valuation.incentives import incentive_cliff


def test_expirations_group_by_date_and_step_noi_in_exact_cents():
    result = incentive_cliff(
        [
            {"type": "abatement", "expires": 2027, "annual_value_cents": 10_000},
            {
                "type": "pilot",
                "expires": "2027",
                "annual_value_cents": 5_000,
                "clawback_terms": "repay on early sale",
            },
            {"type": "credit", "expires": "2028-06-30", "annual_value_cents": 2_500},
        ],
        noi=1_000,
    )

    assert [event["expires"] for event in result["timeline"]] == [
        "2027-12-31",
        "2028-06-30",
    ]
    assert result["timeline"][0]["annual_cliff_cents"] == 15_000
    assert result["timeline"][0]["noi_after_range"]["base"] == 850
    assert result["timeline"][1]["noi_after_range"]["base"] == 825
    assert result["clawback_exposure"] is True
    assert result["counsel_verify"] is True
    assert result["cpa_verify"] is True
    assert result["disclaimer"] == (
        "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
    )
