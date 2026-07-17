"""Valuation-approach divergence checks."""

from cre_mcp.valuation.approaches import reconcile_approaches


def test_directional_divergence_rules_fire_without_automatic_average():
    result = reconcile_approaches(
        {"noi": 100, "cap_range": 0.10},
        [{"price_psf": 2.0}],
        {"land": 500, "replacement": 2_000, "depreciation": 0},
        subject_sf=1_000,
    )

    rules = {item["rule"]: item["explanation"] for item in result["divergence_explanations"]}
    assert "income_below_sales" in rules
    assert "below-market leases" in rules["income_below_sales"]
    assert "sales_below_cost" in rules
    assert "functional or economic obsolescence" in rules["sales_below_cost"]
    assert result["reconciliation"]["weighted_value_range"] is None
    assert "not averaged" in result["divergence_comparison_basis"]
    assert result["disclaimer"] == (
        "analytical estimate, NOT an appraisal; USPAP work requires a licensed appraiser"
    )


def test_only_caller_supplied_weights_produce_a_weighted_range():
    result = reconcile_approaches(
        {"noi": 100, "cap_range": 0.10},
        [{"price_psf": 2.0}],
        {"land": 500, "replacement": 2_000, "depreciation": 0},
        subject_sf=1_000,
        weights={"income": 1, "sales": 1, "cost": 2},
    )

    assert result["reconciliation"]["weighted_value_range"] == {
        "low": 2_000,
        "high": 2_000,
    }
    assert result["reconciliation"]["weights"]["source"] == (
        "user choice; not a system recommendation"
    )
