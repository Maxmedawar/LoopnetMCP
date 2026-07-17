from datetime import date

import pytest

from cre_mcp.prospect.rent_adjust import (
    DEFAULT_ADJUSTMENT_CONVENTIONS,
    adjust_rent_comp,
)
from cre_mcp.prospect.stalled import stalled_projects


def test_stalled_threshold_and_successor_logic() -> None:
    permits = {
        "permits": [
            {
                "permit_number": "OLD-WITH-SUCCESSOR",
                "site_address": "10 Main Street",
                "issued_date": "2024-01-01",
            },
            {
                "permit_number": "SUCCESSOR",
                "address": "10 MAIN ST.",
                "issue_date": "2025-06-01",
            },
            {
                "permit_number": "AT-THRESHOLD",
                "project_address": "20 Oak Road",
                "permit_date": "2025-01-01",
            },
            {
                "permit_number": "TOO-NEW",
                "address": "30 Pine Ave",
                "date": "2025-01-02",
            },
            {
                "permit_number": "FUTURE-SHOULD-NOT-SUPPRESS",
                "address": "20 Oak Rd",
                "date": "2027-01-01",
            },
        ]
    }

    result = stalled_projects(permits, min_age_days=365, as_of=date(2026, 1, 1))

    assert [signal["permit_id"] for signal in result["signals"]] == ["AT-THRESHOLD"]
    assert result["signals"][0]["age_days"] == 365
    assert result["signals"][0]["successor_activity_found"] is False
    assert result["verification_notice"] == "verify with the jurisdiction"
    assert "HEURISTIC" in result["signals"][0]["inference_label"]
    assert any("future-dated" in note for note in result["input_notes"])


def test_stalled_surfaces_unrecognized_rows_and_arcgis_attributes() -> None:
    result = stalled_projects(
        {
            "features": [
                {
                    "attributes": {
                        "permit_id": "ARCGIS-1",
                        "property_address": "1 Harbor Blvd",
                        "filing_date": 1_704_067_200_000,
                    }
                },
                {"permit_number": "NO-DATE", "address": "2 Harbor Blvd"},
                None,
            ]
        },
        as_of="2026-01-01",
    )

    assert [signal["permit_id"] for signal in result["signals"]] == ["ARCGIS-1"]
    assert result["records_evaluated"] == 1
    assert len(result["unrecognized_records"]) == 2
    assert "permit date" in result["unrecognized_records"][0]["reason"]
    assert result["unrecognized_records"][1]["value_type"] == "NoneType"


def test_stalled_accepts_zoning_fixture_shaped_split_chicago_address() -> None:
    result = stalled_projects(
        [
            {
                "permit_": "100999",
                "street_number": "121",
                "street_direction": "N",
                "street_name": "LA SALLE",
                "suffix": "ST",
                "issue_date": "2020-07-01",
            }
        ],
        min_age_days=365,
        as_of="2026-01-01",
    )

    assert result["signals"][0]["permit_id"] == "100999"
    assert result["signals"][0]["address"] == "121 N LA SALLE ST"
    assert result["signals"][0]["address_field"].startswith("composed:")


def test_rent_adjustment_exact_arithmetic_and_exposed_table() -> None:
    result = adjust_rent_comp(
        {
            "rent_psf": 20,
            "sf": 1_000,
            "condition": "average",
            "signed_date": "2025-01-01",
        },
        {"sf": 1_200, "condition": "good"},
        as_of="2026-01-01",
    )

    # Size -2%, condition +3%, and time +3% are additive: 20 * 1.04.
    assert result["total_adjustment_pct"] == pytest.approx(0.04)
    assert result["adjusted_psf"] == pytest.approx(20.8)
    assert result["adjusted_psf_range"] == {
        "low": pytest.approx(19.76),
        "high": pytest.approx(21.84),
        "range_pct": pytest.approx(0.05),
    }
    assert [line["factor"] for line in result["adjustments"]] == [
        "size_curve",
        "condition_steps",
        "age_of_comp_time_adjustment",
    ]
    assert result["adjustments"][0]["adjustment_psf"] == pytest.approx(-0.4)
    assert result["adjustments"][1]["adjustment_psf"] == pytest.approx(0.6)
    assert result["adjustments"][2]["adjustment_psf"] == pytest.approx(0.6)
    assert result["convention_table"] == DEFAULT_ADJUSTMENT_CONVENTIONS
    assert result["verification_notice"] == "convention, verify w/ local broker"


def test_rent_adjustment_nullable_factors_and_unrecognized_inputs() -> None:
    result = adjust_rent_comp(
        {"rent_psf": 15, "condition": "mystery", "frontage_ft": 100, "rnt_psf": 14},
        {"condition": "good", "mystery_factor": True},
        as_of="2026-01-01",
    )

    assert result["adjusted_psf"] == pytest.approx(15)
    assert len(result["missing_factors"]) == 3
    assert any("condition labels" in note for note in result["unrecognized_inputs"])
    assert any("frontage_ft" in note for note in result["unrecognized_inputs"])
    assert any("comp.rnt_psf" in note for note in result["unrecognized_inputs"])
    assert any("subject.mystery_factor" in note for note in result["unrecognized_inputs"])
    assert "HEURISTIC" in result["heuristic_label"]
