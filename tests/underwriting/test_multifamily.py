"""The multifamily rent-roll build-up, and its refusal to let a gap be filled in.

Two properties are under test and only one of them is arithmetic.

The arithmetic is checked against a worked case rather than against a
restatement of the formula, because a test that recomputes the implementation
proves the implementation equals itself.

The other property is the one that matters more: a missing input has to come
back as a refusal an agent cannot paper over. The failure mode is not a wrong
number, it is a *plausible* one -- a market average presented as this
property's rent is indistinguishable from a real figure to whoever acts on it.
"""

from __future__ import annotations

import pytest

from cre_mcp.models.listings import Listing
from cre_mcp.underwriting.assumptions import UnderwritingAssumptions
from cre_mcp.underwriting.metrics import underwrite_listing
from cre_mcp.underwriting.multifamily import (
    MultifamilyInputError,
    multifamily_income,
    multifamily_offer_inputs,
)

# 148 units, $3,450/mo, 80% occupancy, 3.75% other income, 40% expenses, 7% cap.
# Hand-computed, not derived from the implementation:
#   148 × 3450 × 12          = 6,127,200 gross potential rent
#   × 0.80                   = 4,901,760 annual income
#   × 0.0375                 =   183,816 other income
#   sum                      = 5,085,576 gross income
#   × 0.40                   = 2,034,230.40 expenses
#   difference               = 3,051,345.60 NOI
#   ÷ 0.07                   = 43,590,651.43 price at cap
WORKED = {
    "units": 148,
    "rent_per_unit_month": 3450,
    "occupancy_pct": 80,
    "other_income_pct": 3.75,
    "expense_pct": 40,
}


def test_the_build_up_matches_a_hand_computed_case() -> None:
    result = multifamily_income(**WORKED)
    assert result["status"] == "OK"
    assert result["gross_potential_rent"] == pytest.approx(6_127_200)
    assert result["annual_income"] == pytest.approx(4_901_760)
    assert result["other_income"] == pytest.approx(183_816)
    assert result["gross_income"] == pytest.approx(5_085_576)
    assert result["operating_expenses"] == pytest.approx(2_034_230.40)
    assert result["noi"] == pytest.approx(3_051_345.60)


def test_the_price_at_cap_is_labelled_as_not_an_offer() -> None:
    result = multifamily_offer_inputs(**WORKED, cap_rate_pct=7)
    assert result["price_at_cap_rate"] == pytest.approx(43_590_651.43, rel=1e-9)
    # The label is load-bearing: this number ignores the ask, closed comps, and
    # whether the deal carries its own debt, and an agent that reports it as
    # "the offer" has skipped all three.
    assert "not an offer" in result["not_an_offer"]


def test_expenses_are_taken_on_gross_income_not_on_potential_rent() -> None:
    """The convention, pinned by the difference it makes.

    Against gross potential rent the same ratio yields
    6,127,200 × 0.40 = 2,450,880 of expenses and 2,634,696 of NOI -- 13.7%
    lower, in the same direction every time.
    """
    result = multifamily_income(**WORKED)
    assert result["operating_expenses"] == pytest.approx(
        result["gross_income"] * 0.40
    )
    assert result["operating_expenses"] != pytest.approx(
        result["gross_potential_rent"] * 0.40
    )


# --- the no-invention contract ----------------------------------------------


@pytest.mark.parametrize(
    "supplied, expected",
    [
        ({}, ["units", "rent_per_unit_month"]),
        ({"units": 148}, ["rent_per_unit_month"]),
        ({"rent_per_unit_month": 3450}, ["units"]),
    ],
)
def test_a_missing_required_input_refuses_and_names_it(supplied, expected) -> None:
    result = multifamily_income(**supplied)
    assert result["status"] == "NEEDS_INPUT"
    assert result["missing_inputs"] == expected


def test_a_refusal_carries_no_figures_at_all(supplied=None) -> None:
    """Not even the computable ones.

    A partially-filled result is precisely the shape an agent completes from
    memory: given `gross_potential_rent` and a blank NOI it will produce an
    NOI. So a refusal returns none of it.
    """
    result = multifamily_income(units=148)
    for field in (
        "gross_potential_rent",
        "annual_income",
        "other_income",
        "gross_income",
        "operating_expenses",
        "noi",
    ):
        assert field not in result


def test_every_missing_input_says_how_to_resolve_it() -> None:
    result = multifamily_income()
    assert set(result["resolution"]) == set(result["missing_inputs"])
    for name, text in result["resolution"].items():
        assert text.strip(), name
    # And the instruction names the specific wrong move, not just "do not
    # guess" -- carrying a market average in as the in-place rent is the one
    # that looks right.
    assert "market average" in result["instruction"]


def test_the_rent_resolution_separates_in_place_from_market() -> None:
    resolution = multifamily_income(units=148)["resolution"]
    assert "market average" in resolution["rent_per_unit_month"]


def test_a_defaulted_input_is_reported_rather_than_silent() -> None:
    """An assumption is not a blocker, but it is never invisible."""
    result = multifamily_income(units=148, rent_per_unit_month=3450)
    assert result["status"] == "OK"
    assert set(result["assumed_inputs"]) == {
        "occupancy_pct",
        "other_income_pct",
        "expense_pct",
    }
    for name, entry in result["assumed_inputs"].items():
        assert entry["resolution"].strip(), name


def test_supplied_inputs_are_not_reported_as_assumed() -> None:
    result = multifamily_income(**WORKED)
    assert result["assumed_inputs"] == {}


def test_the_cap_rate_is_required_before_a_price_is_produced() -> None:
    result = multifamily_offer_inputs(**WORKED)
    assert result["status"] == "NEEDS_INPUT"
    assert result["missing_inputs"] == ["cap_rate_pct"]
    assert "price_at_cap_rate" not in result


@pytest.mark.parametrize(
    "field, value",
    [
        ("units", 0),
        ("units", 148.5),
        ("units", "148"),
        ("units", True),
        ("rent_per_unit_month", -1),
        ("occupancy_pct", 101),
        ("expense_pct", -0.5),
    ],
)
def test_an_unusable_input_raises_rather_than_being_coerced(field, value) -> None:
    supplied = {**WORKED, field: value}
    with pytest.raises(MultifamilyInputError):
        multifamily_income(**supplied)


# --- the value-add profile ---------------------------------------------------


def test_low_occupancy_asks_for_the_stabilized_case(capsys) -> None:
    """80% occupancy prices the vacancy, not the property."""
    result = multifamily_offer_inputs(**WORKED, cap_rate_pct=7)
    note = result["value_add_note"]
    assert note["missing_inputs"] == [
        "stabilized_rent_per_unit_month",
        "renovation_capex",
    ]
    assert "value-add" in note["reason"]
    assert set(note["resolution"]) == set(note["missing_inputs"])


def test_a_stabilized_case_is_computed_when_both_inputs_are_supplied() -> None:
    result = multifamily_offer_inputs(
        **WORKED,
        cap_rate_pct=7,
        stabilized_rent_per_unit_month=4_200,
        renovation_capex=3_500_000,
    )
    assert "value_add_note" not in result
    assert result["renovation_capex"] == 3_500_000
    # Same units, same occupancy and ratios, higher rent -> higher NOI.
    assert result["stabilized_noi"] > result["noi"]


def test_a_stabilized_occupancy_raises_no_value_add_note() -> None:
    result = multifamily_offer_inputs(
        **{**WORKED, "occupancy_pct": 95}, cap_rate_pct=7
    )
    assert "value_add_note" not in result


# --- the listing path, which had no way to reach any of this ------------------


def test_the_listing_underwriter_now_takes_expenses_on_effective_gross() -> None:
    """The bug this change corrects, pinned by a case no existing test covered.

    Every golden deal supplies NOI or operating expenses directly, so the
    derived-expense path was never exercised and the whole suite stayed green
    while the ratio was applied to the wrong base.
    """
    listing = Listing(
        source="test",
        source_id="mf-1",
        url="https://example.test/mf-1",
        name="148-unit multifamily",
        address="1 Test Way",
        city="Austin",
        state="TX",
        property_type="multifamily",
        price_usd=43_000_000,
        raw={"gross_potential_rent": 6_127_200, "vacancy_rate": 0.20},
    )
    result = underwrite_listing(
        listing, UnderwritingAssumptions.for_property_type("multifamily")
    )
    effective_gross = 6_127_200 * 0.80
    assert result.assumptions_used["expense_ratio_basis"]["value"] == (
        "effective_gross_income"
    )
    # EGI 4,901,760 − 40% of it = 2,941,056.
    assert result.noi == pytest.approx(effective_gross * 0.60)
    # Against gross potential rent it would have been 2,450,880 of NOI.
    assert result.noi != pytest.approx(effective_gross - 6_127_200 * 0.40)
