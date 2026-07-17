"""Partial-interest split checks."""

from cre_mcp.valuation.interests import value_interest_split


def test_one_year_zero_rate_rent_differential_splits_fee_simple_exactly():
    terms = {
        "contract_rent": 80,
        "market_rent": 100,
        "remaining_term": 1,
        "discount_rate": 0,
    }
    leased_fee = value_interest_split(1_000, "leased_fee", terms)
    leasehold = value_interest_split(1_000, "leasehold", terms)

    assert leased_fee["rent_differential_pv_range"] == {"low": 20, "high": 20}
    assert leased_fee["leased_fee_value_range"] == {"low": 980, "high": 980}
    assert leasehold["leasehold_value_range"] == {"low": 20, "high": 20}
    assert leased_fee["reconciliation"]["point_input_check"] == 1_000
    assert "end-of-period" in leased_fee["method"]
    assert leased_fee["disclaimer"] == (
        "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
    )


def test_air_rights_refuses_to_infer_value_without_zoning_analysis():
    result = value_interest_split([1_000, 1_200], "air_rights", {})

    assert result["interest_value_range"] is None
    assert result["analysis_requirement"] == (
        "requires zoning transfer analysis — see zoning tools"
    )
