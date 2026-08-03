"""Pure tests for the buyer-specific decision frontier."""

from cre_mcp.decision.frontier import decision_frontier


def _row(result: dict, structure: str) -> dict:
    return next(row for row in result["frontier"] if row["structure"] == structure)


def _base_deal(**overrides: object) -> dict:
    deal: dict = {
        "price": 2_000_000,
        "noi": 170_000,
        "cap_rate": 0.085,
        "market_cap_rate": 0.08,
    }
    deal.update(overrides)
    return deal


def test_cash_poor_buyer_prefers_low_cash_structures_to_all_cash() -> None:
    result = decision_frontier(_base_deal(), {"cash_available": 200_000})

    all_cash = _row(result, "all_cash")
    seller_finance = _row(result, "seller_finance")
    option = _row(result, "option_then_lease")
    positions = {row["structure"]: index for index, row in enumerate(result["frontier"])}

    assert all_cash["buyer_fit"] is False
    assert seller_finance["buyer_fit"] is True
    assert option["buyer_fit"] is True
    assert positions["seller_finance"] < positions["all_cash"]
    assert positions["option_then_lease"] < positions["all_cash"]


def test_no_recourse_buyer_penalizes_conventional_debt() -> None:
    result = decision_frontier(
        _base_deal(),
        {
            "cash_available": 1_000_000,
            "recourse_tolerance": "none",
            "hold_pref_years": 5,
            "closing_track_record": "strong",
        },
    )
    conventional = _row(result, "conventional_75ltv")

    assert conventional["buyer_fit"] is False
    assert conventional["buyer_fit_checks"]["recourse"] == "mismatch"
    assert conventional["financing_probability"] < 0.8
    assert any("recourse" in item.casefold() for item in result["buyer_mismatches"])


def test_fatal_flaw_leads_recommendation_and_passes_through() -> None:
    result = decision_frontier(
        _base_deal(fatal_flaws=["SELLER_NOI_OVERSTATED"]),
        {"cash_available": 3_000_000},
    )

    assert result["recommendation"].startswith("SELLER_NOI_OVERSTATED")
    assert "Pursue" not in result["recommendation"]
    assert result["fatal_flaws_passthrough"] == ["SELLER_NOI_OVERSTATED"]


def test_missing_buyer_fields_remain_unknown_without_crashing() -> None:
    result = decision_frontier(_base_deal(), {})
    conventional = _row(result, "conventional_75ltv")

    assert conventional["close_probability"] == "unknown"
    assert conventional["expected_return"]["hold_years"] == "unknown"
    assert conventional["expected_return"]["levered_irr"] == "unknown"
    assert conventional["buyer_fit_checks"]["cash"] == "unknown"
    assert conventional["buyer_fit_checks"]["recourse"] == "unknown"


def test_frontier_is_sorted_by_score_descending() -> None:
    result = decision_frontier(
        _base_deal(),
        {
            "cash_available": 500_000,
            "hold_pref_years": 5,
            "closing_track_record": "some",
        },
    )
    scores = [row["score"] for row in result["frontier"]]

    assert scores == sorted(scores, reverse=True)
    assert all(0 <= score <= 1 for score in scores)
