"""Hand-computed standard underwriting metric tests."""

import math

import pytest

from cre_mcp.models import Listing
from cre_mcp.underwriting.assumptions import UnderwritingAssumptions
from cre_mcp.underwriting.metrics import (
    annual_debt_service,
    break_even_occupancy,
    cap_rate,
    cash_on_cash,
    dscr,
    equity_multiple,
    exit_value,
    grm,
    levered_irr,
    mortgage_constant,
    net_operating_income,
    price_per_sf,
    price_per_unit,
    price_vs_replacement,
    tenant_credit_tier,
    underwrite_listing,
    unlevered_irr,
    walt,
)


def test_noi_cap_grm_and_basis_metrics_match_hand_math():
    noi = net_operating_income(120_000, 0.05, 5_000, 35_000)
    assert noi == 84_000
    assert cap_rate(noi, 1_200_000) == 7.0
    assert grm(1_200_000, 120_000) == 10.0
    assert price_per_sf(1_200_000, 10_000) == 120.0
    assert price_per_unit(1_200_000, 12) == 100_000.0
    assert price_vs_replacement(120, 200) == 0.6


def test_debt_cash_on_cash_dscr_and_break_even_match_hand_math():
    constant = mortgage_constant(0.06, 25)
    expected_monthly = 0.06 / 12 / (1 - (1 + 0.06 / 12) ** -(25 * 12))
    assert constant == pytest.approx(expected_monthly * 12)
    debt_service = annual_debt_service(650_000, 0.06, 25)
    assert debt_service == pytest.approx(650_000 * expected_monthly * 12)
    assert cash_on_cash(90_000, debt_service, 350_000) == pytest.approx(
        100 * (90_000 - debt_service) / 350_000
    )
    assert dscr(90_000, debt_service) == pytest.approx(90_000 / debt_service)
    assert break_even_occupancy(30_000, debt_service, 120_000) == pytest.approx(
        100 * (30_000 + debt_service) / 120_000
    )


def test_walt_exit_irr_equity_multiple_and_credit_tier():
    assert walt([(60_000, 10), (40_000, 5)]) == 8.0
    assert exit_value(100_000, 6.0, 50) == pytest.approx(100_000 / 0.065)
    assert unlevered_irr([-100, 0, 121]) == pytest.approx(10.0, abs=1e-6)
    assert levered_irr([-100, 110]) == pytest.approx(10.0, abs=1e-6)
    assert equity_multiple(750_000, 300_000) == 2.5
    assert tenant_credit_tier("Walgreens Store #123") == "BBB-"
    assert tenant_credit_tier("Local Shop") == "unrated"
    assert tenant_credit_tier(None) is None


@pytest.mark.parametrize(
    "function,args",
    [
        (cap_rate, (100, 0)),
        (grm, (100, 0)),
        (price_per_sf, (100, 0)),
        (price_per_unit, (100, 0)),
        (price_vs_replacement, (100, 0)),
        (cash_on_cash, (100, None, None)),
        (dscr, (100, 0)),
        (break_even_occupancy, (100, 100, 0)),
        (walt, ([] ,)),
        (unlevered_irr, ([100, 110],)),
        (equity_multiple, (100, 0)),
    ],
)
def test_missing_or_zero_denominators_return_none(function, args):
    assert function(*args) is None


def test_zero_rate_mortgage_constant_is_supported():
    assert mortgage_constant(0.0, 25) == pytest.approx(1 / 25)
    assert math.isfinite(mortgage_constant(0.0, 25))


def test_underwrite_listing_echoes_known_and_assumed_inputs():
    listing = Listing(
        source="fixture",
        source_id="1",
        name="Walgreens",
        address="1 Main St",
        city="Austin",
        state="TX",
        property_type="retail",
        price_usd=1_200_000,
        size_sqft_num=10_000,
        noi_usd=84_000,
        url="https://example.test/1",
        raw={
            "tenant_name": "Walgreens",
            "gross_potential_rent": 120_000,
            "operating_expenses": 35_000,
        },
    )
    assumptions = UnderwritingAssumptions.for_property_type(
        "retail", {"annual_interest_rate": 0.06}
    )
    result = underwrite_listing(listing, assumptions)

    assert result.cap_rate == 7.0
    assert result.tenant_credit_tier == "BBB-"
    assert result.assumptions_used["noi"]["source"] == "listing"
    assert result.assumptions_used["operating_expenses"]["source"] == "listing"
    assert result.assumptions_used["price"]["source"] == "listing"
    assert result.assumptions_used["other_income"] == {
        "value": 0.0,
        "source": "assumed",
    }
    assert result.assumptions_used["ltv"] == {"value": 0.65, "source": "assumed"}
