"""Disposition-readiness rubric, evidence honesty, and critical-path ordering."""

from cre_mcp.disposition.readiness import disposition_readiness


def _text(value):
    if isinstance(value, dict):
        return " ".join(f"{key} {_text(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return str(value)


def test_readiness_exposes_rubric_and_ranks_months_before_weeks(disposition_db):
    result = disposition_readiness(
        "deal-readiness",
        "retail_nnn",
        "2027-03-31",
        {
            "financial_records_complete": False,
            "estoppels_current": False,
            "title_age_months": 18,
            "survey_age_months": 72,
            "open_work_orders": ["roof leak"],
            "capex_flags": ["parking lot replacement"],
            "state": "CA",
            "expected_sale_price": 10_000_000,
            "current_assessed_value": 4_000_000,
            "current_annual_taxes": 48_000,
        },
        as_of="2026-07-14",
    )

    assert set(result["dimensions"]) == {
        "financial_records",
        "lease_file",
        "title_survey",
        "physical",
        "tax",
        "data_room",
    }
    assert result["rubric"]
    assert result["conventions"]
    assert result["limitations"]
    assert "estimate" in result["months_to_ready"]
    assert result["months_to_ready"]["convention"]

    lead_times = [item["lead_time_days"] for item in result["fixes"]]
    assert lead_times == sorted(lead_times, reverse=True)
    survey_index = next(
        index
        for index, fix in enumerate(result["fixes"])
        if "survey" in _text(fix).casefold()
    )
    estoppel_index = next(
        index
        for index, fix in enumerate(result["fixes"])
        if "estoppel" in _text(fix).casefold()
    )
    assert result["fixes"][survey_index]["lead_time_days"] >= 90
    assert result["fixes"][estoppel_index]["lead_time_days"] >= 30
    assert survey_index < estoppel_index


def test_uninitialized_data_room_stays_unknown_instead_of_scoring_complete(disposition_db):
    result = disposition_readiness(
        "deal-no-room",
        "retail_nnn",
        "2027-01-31",
        {},
        as_of="2026-07-14",
    )
    data_room = result["dimensions"]["data_room"]

    assert data_room["status"] == "unknown"
    assert "not initialized" in _text(data_room).casefold()
    assert result["readiness_score_pct"] is None or result["readiness_score_pct"] < 100


def test_unknown_taxecon_jurisdiction_remains_an_evidence_gap(disposition_db):
    result = disposition_readiness(
        "deal-unknown-tax",
        "retail_nnn",
        "2027-01-31",
        {"state": "ZZ"},
        as_of="2026-07-14",
    )
    tax = result["dimensions"]["tax"]

    assert tax["taxecon_screen"]["status"] == "UNKNOWN"
    assert tax["status"] == "unknown"
    assert tax["gaps"]
