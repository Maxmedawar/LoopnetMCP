import pytest

from cre_mcp.notes.pricing import price_note


def test_performing_note_uses_exact_monthly_annuity_pv():
    upb = 100_000.0
    coupon = 0.06
    months = 12
    target_yield = 0.08
    monthly_coupon = coupon / 12
    payment = upb * monthly_coupon / (1 - (1 + monthly_coupon) ** -months)
    monthly_yield = target_yield / 12
    expected = payment * (1 - (1 + monthly_yield) ** -months) / monthly_yield

    result = price_note(
        upb=upb,
        rate=coupon,
        payment_history={"status": "performing", "months_delinquent": 0, "remaining_months": months},
        collateral_value_range=(90_000, 110_000),
        state="CA",
        lien_position=1,
        costs={},
        target_yield_range=target_yield,
    )

    assert result["price"]["low"] == pytest.approx(expected, abs=1e-6)
    assert result["price"]["base"] == pytest.approx(expected, abs=1e-6)
    assert result["price"]["high"] == pytest.approx(expected, abs=1e-6)
    assert result["probability_total"] == 1.0


def _nonperforming(months_delinquent, state="CA"):
    return price_note(
        upb=500_000,
        rate=0.07,
        payment_history={
            "status": "non",
            "months_delinquent": months_delinquent,
            "remaining_months": 120,
        },
        collateral_value_range={"low": 500_000, "base": 600_000, "high": 700_000},
        state=state,
        lien_position=1,
        costs={
            "marketing_discount": {"low": 0.08, "base": 0.1, "high": 0.12},
            "foreclosure": 20_000,
            "legal": 12_000,
            "carry_monthly": 2_000,
            "delinquency_reserve_monthly": 1_000,
            "property_tax_liens": 5_000,
            "reo_marketing_months": (2, 4, 6),
        },
        target_yield_range={"low": 0.10, "base": 0.12, "high": 0.15},
    )


def test_nonperforming_path_probabilities_sum_to_one_and_full_table_is_returned():
    result = _nonperforming(6)

    assert result["probability_total"] == 1.0
    assert sum(row["probability"] for row in result["path_table"]) == pytest.approx(1.0)
    assert {row["path"] for row in result["path_table"]} == {
        "reinstate",
        "modify",
        "foreclose_to_reo",
        "deed_in_lieu",
        "note_sale",
    }
    assert "CONVENTIONS" in result["probability_convention"]


def test_nonperforming_price_falls_with_delinquency_and_longer_state_timeline():
    early = _nonperforming(2, "CA")
    late = _nonperforming(12, "CA")
    slow_state = _nonperforming(2, "NY")

    assert late["price"]["base"] < early["price"]["base"]
    assert slow_state["price"]["base"] < early["price"]["base"]
