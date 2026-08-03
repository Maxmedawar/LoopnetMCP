"""Hand-computed and property tests for scenario stress math."""

import pytest

from cre_mcp.scenarios.engine import SCENARIO_PRESETS, stress_test


def _deal(**overrides):
    deal = {
        "price": 1_000_000,
        "noi": 100_000,
        "gross_potential_rent": 150_000,
        "occupancy": 0.90,
        "other_income": 0,
        "operating_expenses": 35_000,
        "rentable_sf": 10_000,
        "loan_amount": 600_000,
        "annual_interest_rate": 0,
        "amortization_years": 30,
        "io_months": 0,
        "hold_years": 1,
        "exit_cap": 0.10,
    }
    deal.update(overrides)
    return deal


def _case(deal, shocks="base"):
    return stress_test(deal, shocks)["scenarios"][
        shocks if isinstance(shocks, str) else "custom"
    ]


def test_base_debt_metrics_match_hand_math_exactly():
    case = _case(_deal())

    assert case["noi"] == 100_000
    assert case["annual_debt_service"] == pytest.approx(20_000)
    assert case["dscr"] == pytest.approx(5.0)
    assert case["cash_on_cash"] == pytest.approx(20.0)
    assert case["remaining_loan_balance"] == pytest.approx(580_000)
    assert case["exit_value"] == pytest.approx(1_000_000)
    assert case["equity_multiple"] == pytest.approx(1.25)


def test_operating_preset_noi_bridges_match_hand_math():
    scenarios = stress_test(_deal())["scenarios"]

    # Downside: 100k - (135k - 121.5k) - 3.5k.
    assert scenarios["downside"]["noi"] == pytest.approx(83_000)
    # Severe: 100k - (135k - 108k) - 5.25k.
    assert scenarios["severe"]["noi"] == pytest.approx(67_750)
    # Lender: 100k - 3% * 135k - $0.25 * 10k SF.
    assert scenarios["lender"]["noi"] == pytest.approx(93_450)


def test_presets_have_exact_shape_shocks_assumptions_and_convention_labels():
    result = stress_test(_deal())

    assert result["scenario_order"] == ["base", "downside", "severe", "lender"]
    assert result["scenarios"].keys() == SCENARIO_PRESETS.keys()
    assert result["scenarios"]["downside"]["shocks"] == {
        "rent": -0.10,
        "opex": 0.10,
        "exit_cap_bps": 100,
    }
    assert result["scenarios"]["severe"]["applied_shocks"][
        "interest_rate_delta"
    ] == pytest.approx(0.015)
    for scenario in result["scenarios"].values():
        assert scenario["is_convention"] is True
        assert "CONVENTION" in scenario["honesty_label"]
        assert scenario["assumptions"]["supplied_deal_inputs"] == _deal()
        assert "normalized_applied_shocks" in scenario["assumptions"]


def test_higher_exit_cap_lowers_irr():
    deal = _deal()
    lower = _case(deal, {"exit_cap": -0.01})
    higher = _case(deal, {"exit_cap": 0.01})

    assert lower["irr"] is not None
    assert higher["irr"] is not None
    assert higher["irr"] < lower["irr"]


def test_higher_rate_lowers_dscr():
    deal = _deal(annual_interest_rate=0.05)
    lower = _case(deal, {"interest_rate_bps": -100})
    higher = _case(deal, {"interest_rate_bps": 100})

    assert higher["dscr"] < lower["dscr"]


def test_more_io_produces_higher_early_cash_on_cash():
    amortizing = _case(_deal(annual_interest_rate=0.06, io_months=0))
    interest_only = _case(_deal(annual_interest_rate=0.06, io_months=12))

    assert interest_only["cash_on_cash"] > amortizing["cash_on_cash"]
    assert interest_only["annual_debt_service"] == pytest.approx(36_000)


def test_custom_named_scenarios_are_supported():
    result = stress_test(
        _deal(),
        {"mild": {"rent": -0.05}, "late_sale": {"sale_timing": 3}},
    )

    assert result["scenario_order"] == ["mild", "late_sale"]
    assert result["scenarios"]["mild"]["noi"] == pytest.approx(93_250)
    assert result["scenarios"]["late_sale"]["assumptions"][
        "effective_hold_months"
    ] == 15


def test_refi_flag_uses_supplied_dscr_and_ltv_thresholds():
    case = _case(_deal(refi_target_dscr=1.25, max_refi_ltv=0.70))

    assert case["refi_ability_flag"] is True
    assert case["refi_ability"]["remaining_loan_balance"] == pytest.approx(580_000)
    assert case["refi_ability"]["maximum_refinance_proceeds"] == pytest.approx(
        700_000
    )


def test_missing_exit_cap_marks_irr_not_computable_but_keeps_dscr():
    deal = _deal()
    del deal["exit_cap"]
    case = _case(deal)

    assert case["irr"] is None
    assert case["dscr"] == pytest.approx(5.0)
    assert "cannot compute IRR because exit_cap is missing" in case["not_computable"]


def test_operating_shock_does_not_invent_missing_components():
    deal = {
        "price": 1_000_000,
        "noi": 100_000,
        "loan_amount": 0,
        "hold_years": 5,
        "exit_cap": 0.07,
    }
    case = _case(deal, "downside")

    assert case["noi"] is None
    assert any(
        message.startswith("cannot compute stressed NOI because")
        for message in case["not_computable"]
    )


def test_missing_debt_is_not_silently_treated_as_all_cash():
    deal = _deal()
    del deal["loan_amount"]
    case = _case(deal)

    assert case["dscr"] is None
    assert case["cash_on_cash"] is None
    assert any("loan_amount or ltv is missing" in message for message in case["not_computable"])


def test_missing_io_months_is_not_silently_treated_as_zero():
    deal = _deal()
    del deal["io_months"]
    case = _case(deal)

    assert case["annual_debt_service"] is None
    assert case["dscr"] is None
    assert any("io_months is missing" in message for message in case["not_computable"])


@pytest.mark.parametrize("noi", [0, -10_000])
def test_zero_and_negative_noi_are_preserved_not_replaced(noi):
    case = _case(_deal(noi=noi))

    assert case["noi"] == noi
    assert case["dscr"] == pytest.approx(noi / 20_000)
    assert case["cash_on_cash"] == pytest.approx(100 * (noi - 20_000) / 400_000)


def test_explicit_all_cash_deal_keeps_returns_and_marks_dscr_not_applicable():
    case = _case(_deal(loan_amount=0))

    assert case["dscr"] is None
    assert case["cash_on_cash"] == pytest.approx(10.0)
    assert case["irr"] is not None
    assert any("no debt" in message for message in case["not_computable"])


def test_zero_hold_is_explicitly_not_computable():
    case = _case(_deal(hold_years=0))

    assert case["irr"] is None
    assert any("hold period must be greater than zero" in message for message in case["not_computable"])
