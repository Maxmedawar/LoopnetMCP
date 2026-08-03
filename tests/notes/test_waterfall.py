import pytest

from cre_mcp.notes.waterfall import lien_recovery_waterfall


ZERO_COSTS = {"foreclosure": 0, "legal": 0, "carry_monthly": 0, "months": 0}


def _rows(result):
    return {row["holder"]: row for row in result["recovery_by_lien"]}


def test_senior_is_paid_before_junior_by_hand_calculation():
    result = lien_recovery_waterfall(
        collateral_value_range=100,
        marketing_discount=0,
        liens=[
            {"holder": "Senior", "type": "senior_mortgage", "balance": 80},
            {"holder": "Junior", "type": "junior", "balance": 50},
        ],
        costs=ZERO_COSTS,
    )
    rows = _rows(result)

    assert rows["Senior"]["recovery"]["base"] == pytest.approx(80)
    assert rows["Junior"]["recovery"]["base"] == pytest.approx(20)
    assert rows["Junior"]["shortfall"]["base"] == pytest.approx(30)
    assert result["equity_remainder"]["base"] == 0


def test_property_tax_primes_even_when_listed_last():
    result = lien_recovery_waterfall(
        collateral_value_range=100,
        marketing_discount=0,
        liens=[
            {"holder": "Senior", "type": "senior_mortgage", "balance": 80},
            {"holder": "County", "type": "property_tax", "balance": 30},
        ],
        costs=ZERO_COSTS,
    )
    rows = _rows(result)

    assert rows["County"]["effective_position"] == 1
    assert rows["County"]["recovery"]["base"] == 30
    assert rows["Senior"]["recovery"]["base"] == 70
    assert any("moved ahead" in flag for flag in result["professional_review_flags"])


def test_shortfall_cascades_and_per_diem_is_exact():
    result = lien_recovery_waterfall(
        collateral_value_range=100,
        marketing_discount=0,
        liens=[
            {
                "holder": "Senior",
                "type": "senior_mortgage",
                "balance": 90,
                "per_diem": 1,
            },
            {"holder": "Junior", "type": "junior", "balance": 20},
        ],
        costs={"foreclosure": 0, "legal": 0, "carry_monthly": 0, "months": 1},
    )
    rows = _rows(result)

    assert rows["Senior"]["claim"]["base"] == 120
    assert rows["Senior"]["recovery"]["base"] == 100
    assert rows["Senior"]["shortfall"]["base"] == 20
    assert rows["Junior"]["recovery"]["base"] == 0
    assert rows["Junior"]["shortfall"]["base"] == 20
