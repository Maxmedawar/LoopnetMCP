"""Exact appraisal-divergence arithmetic and mandatory ROV framing tests."""

from __future__ import annotations

import pytest

from cre_mcp.relations.appraisal_challenge import ROV_FRAMING, challenge_appraisal


def test_challenge_appraisal_exact_divergence_table_and_rov_framing() -> None:
    result = challenge_appraisal(
        {
            "value": 10_000_000,
            "cap_rate_used": 0.06,
            "rent_psf_used": 24,
            "expenses_used": 300_000,
            "comps_used": [
                {"id": "A", "address": "1 Main"},
                {"id": "B", "address": "2 Main"},
            ],
        },
        {
            "our_rent_roll_psf": 27,
            "our_noi": 660_000,
            "our_expenses": 360_000,
            "market_comps": [
                {"id": "A", "cap_rate": 0.065, "rent_psf": 27},
                {"id": "C", "cap_rate": 7.0, "rent_psf": 29},
                {"id": "D", "cap_rate": 6.75, "rent_psf": 28},
            ],
        },
    )

    table = result["divergence_table"]
    assert [row["field"] for row in table] == [
        "value",
        "cap_rate_used",
        "rent_psf_used",
        "expenses_used",
        "comps_used",
        "noi_implied_by_value_and_cap_rate",
    ]
    projection = [
        {
            "field": row["field"],
            "their_input": row["their_input"],
            "our_evidence": row["our_evidence"],
            "delta": row["delta"],
            "delta_pct": row["delta_pct"],
            "materiality": row["materiality"],
        }
        for row in table
    ]
    assert projection == [
        {
            "field": "value",
            "their_input": 10_000_000.0,
            "our_evidence": 11_000_000.0,
            "delta": 1_000_000.0,
            "delta_pct": 0.1,
            "materiality": "high",
        },
        {
            "field": "cap_rate_used",
            "their_input": 6.0,
            "our_evidence": 6.75,
            "delta": 0.75,
            "delta_pct": 0.125,
            "materiality": "moderate",
        },
        {
            "field": "rent_psf_used",
            "their_input": 24.0,
            "our_evidence": 27.0,
            "delta": 3.0,
            "delta_pct": 0.125,
            "materiality": "high",
        },
        {
            "field": "expenses_used",
            "their_input": 300_000.0,
            "our_evidence": 360_000.0,
            "delta": 60_000.0,
            "delta_pct": 0.2,
            "materiality": "high",
        },
        {
            "field": "comps_used",
            "their_input": [
                {"id": "A", "address": "1 Main"},
                {"id": "B", "address": "2 Main"},
            ],
            "our_evidence": [
                {"id": "A", "cap_rate": 0.065, "rent_psf": 27},
                {"id": "C", "cap_rate": 7.0, "rent_psf": 29},
                {"id": "D", "cap_rate": 6.75, "rent_psf": 28},
            ],
            "delta": 1,
            "delta_pct": 0.5,
            "materiality": "moderate",
        },
        {
            "field": "noi_implied_by_value_and_cap_rate",
            "their_input": 600_000.0,
            "our_evidence": 660_000.0,
            "delta": 60_000.0,
            "delta_pct": 0.1,
            "materiality": "high",
        },
    ]
    assert table[1]["delta_bps"] == 75.0
    assert table[1]["market_comp_sample_size"] == 3
    assert table[2]["market_comp_median_rent_psf"] == 28.0
    assert table[2]["market_comp_sample_size"] == 3
    assert table[4]["overlap_count"] == 1
    assert [comp["id"] for comp in table[4]["additional_market_comps"]] == ["C", "D"]
    assert result["material_divergence_count"] == 6
    assert result["sample_sizes"] == {"appraisal_comps": 2, "market_comps": 3}
    assert result["rov_framing"] == ROV_FRAMING
    assert result["mandatory_caveat"] == (
        "submit through lender's ROV process; we do not impersonate a licensed appraiser"
    )


def test_challenge_appraisal_nullable_evidence_never_invents_inputs_or_drops_caveat() -> None:
    result = challenge_appraisal(
        {
            "value": None,
            "cap_rate_used": None,
            "rent_psf_used": None,
            "expenses_used": None,
            "comps_used": [],
        },
        {"our_rent_roll_psf": None, "our_noi": None, "market_comps": []},
    )

    assert result["status"] == "NO_MATERIAL_DIVERGENCE_SHOWN"
    assert result["missing_or_unassessable"] == [
        "value",
        "cap_rate_used",
        "rent_psf_used",
        "expenses_used",
        "comps_used",
        "noi_implied_by_value_and_cap_rate",
    ]
    assert all(row["their_input"] in (None, []) for row in result["divergence_table"])
    assert result["mandatory_caveat"] == ROV_FRAMING
    assert "not an appraisal" in result["honesty"].casefold()


def test_challenge_appraisal_rejects_non_mapping_boundaries() -> None:
    with pytest.raises(ValueError, match="appraisal"):
        challenge_appraisal([], {})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="evidence"):
        challenge_appraisal({}, [])  # type: ignore[arg-type]
