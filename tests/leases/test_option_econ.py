"""Option rent spread, deadline, and missing-market honesty proofs."""

import pytest

from cre_mcp.leases.models import (
    CitedClaim,
    LeaseAbstract,
    LeaseDates,
    LeaseOption,
    Premises,
)
from cre_mcp.leases.option_econ import price_option_decision


def _claim(value, quote=None):
    return CitedClaim.stated(
        value,
        quote=quote or str(value),
        locator="Synthetic",
        confidence=1.0,
    )


def _fixed_option_lease():
    return LeaseAbstract(
        premises=Premises(rentable_sf=_claim(10_000)),
        dates=LeaseDates(expiration=_claim("2026-12-31")),
        options=[LeaseOption(
            option_type=_claim("renew"),
            notice_deadline_rule=_claim("six (6) months prior to expiration"),
            exercise_window=_claim("six (6) months prior to expiration"),
            rent_basis=_claim(
                {"type": "fixed", "rent_psf": 22.0, "term_years": 5},
                "five-year renewal at fixed rent of $22.00 per square foot",
            ),
        )],
    )


def test_fixed_below_market_option_has_positive_value_and_exercise_frame():
    result = price_option_decision(
        _fixed_option_lease(),
        {
            "market_rent_psf": [28, 32],
            "downtime_months": [2, 4],
            "tilc_psf": [20, 30],
        },
        "2025-01-01",
    )

    option = result["options"][0]
    assert option["option_value_range"] == [300_000, 500_000]
    assert option["adjusted_option_value_range"] == pytest.approx([546_666.67, 906_666.67])
    assert option["decision_frame"]["lean"] == "exercise"
    assert option["decision_frame"]["drivers"]
    assert option["notice_deadline"]["notice_deadline"]["date"] == "2026-06-30"


def test_discount_rate_produces_optional_pv_without_changing_nominal_value():
    result = price_option_decision(
        _fixed_option_lease(),
        {
            "market_rent_psf": [28, 32],
            "downtime_months": [0, 0],
            "tilc_psf": [0, 0],
            "discount_rate": 0.10,
        },
        "2025-01-01",
    )

    option = result["options"][0]
    factor = (1 - 1.1 ** -5) / 0.10 / 5
    assert option["pv_option_value_range"] == pytest.approx([300_000 * factor, 500_000 * factor], abs=0.01)
    assert option["option_value_range"] == [300_000, 500_000]


def test_missing_market_inputs_are_not_zero_filled_per_line():
    result = price_option_decision(_fixed_option_lease(), {}, "2025-01-01")

    option = result["options"][0]
    assert option["option_value_range"] is None
    assert option["economics"]["rent_delta"]["status"] == "not_computable"
    assert "market_rent_psf" in option["economics"]["rent_delta"]["missing_inputs"]
    assert option["economics"]["downtime"]["value_range"] is None
    assert option["economics"]["ti_lc"]["value_range"] is None
    assert option["decision_frame"]["status"] == "not_computable"
    assert option["decision_frame"]["lean"] is None


def test_fmv_option_retains_no_invented_rent_discount():
    lease = _fixed_option_lease()
    lease.options[0].rent_basis = _claim("Base Rent shall equal fair market rent for the five-year extension term")

    result = price_option_decision(
        lease,
        {
            "market_rent_psf": [28, 32],
            "downtime_months": [0, 0],
            "tilc_psf": [0, 0],
        },
        "2025-01-01",
    )

    option = result["options"][0]
    assert option["rent_basis"]["kind"] == "fmv"
    assert option["option_value_range"] == [0, 0]
    assert option["decision_frame"]["lean"] == "renegotiate"
