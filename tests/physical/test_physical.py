"""Black-box contract tests for the structured-v1 physical diligence engine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from cre_mcp.physical.capex import (
    CAPEX_COST_CONVENTIONS,
    findings_to_capex,
    replacement_cost_range,
)
from cre_mcp.physical.code_exposure import VERIFY_LOCAL, ada_code_exposure
from cre_mcp.physical.register import physical_risk_register
from cre_mcp.physical.rul import LIFESPAN_CONVENTIONS, remaining_useful_life
from cre_mcp.physical.tools import (
    ada_code_exposure as safe_ada_code_exposure,
    estimate_capex_from_findings as safe_estimate_capex,
    physical_risk_register as safe_physical_risk_register,
    remaining_useful_life as safe_remaining_useful_life,
    vintage_risk_screen as safe_vintage_risk_screen,
)
from cre_mcp.physical.vintage import vintage_risk_screen


def _risk_ids(result: dict[str, Any]) -> set[str]:
    return {flag["risk_id"] for flag in result["flags"]}


def test_capex_cost_convention_table_is_exposed_and_sourced() -> None:
    expected_systems = {
        "roof",
        "hvac",
        "plumbing",
        "electrical",
        "elevator",
        "paving",
        "facade",
        "structure",
        "ada",
        "fire_life_safety",
    }

    assert expected_systems == set(CAPEX_COST_CONVENTIONS)
    for convention in CAPEX_COST_CONVENTIONS.values():
        assert 0 < convention["low"] <= convention["high"]
        assert convention["unit"]
        assert convention["basis"]
        assert convention["description"]
        assert "convention:" in convention["source_note"].lower()
        assert "local gc" in convention["source_note"].lower()


def test_capex_hand_computed_roof_bucket_and_reserve_math() -> None:
    result = findings_to_capex(
        [{"system": "roof", "condition": "failed"}],
        {"sf": 10_000, "floors": 2, "type": "office"},
    )

    # Roof quantity is footprint: 10,000 sf / 2 floors = 5,000 roof sf.
    # The exposed $8-$18/roof-sf convention therefore yields $40k-$90k.
    assert result["buckets"]["immediate"]["cost_range"] == {
        "low": 40_000.0,
        "high": 90_000.0,
    }
    assert result["total_cost_range"] == {"low": 40_000.0, "high": 90_000.0}
    assert result["reserve_per_sf_recommendation"] == {"low": 0.4, "high": 0.9}
    assert all(
        result["buckets"][name]["cost_range"] == {"low": 0.0, "high": 0.0}
        for name in ("yr-1", "yr-5", "yr-10")
    )
    line = result["buckets"]["immediate"]["items"][0]
    assert line["bucket"] == "immediate"
    assert "local gc" in line["source_note"].lower()
    assert result["input_scope_note"].lower().find("pdf parsing") >= 0
    assert "licensed" in result["disclaimer"].lower()


def test_capex_all_condition_buckets_and_extent_guardrails() -> None:
    result = findings_to_capex(
        [
            {"system": "elevator", "condition": "failed"},
            {"system": "plumbing", "condition": "poor", "extent": 0.10},
            {"system": "electrical", "condition": "fair", "extent": 0.10},
            {"system": "paving", "condition": "good", "extent": 0.10},
        ],
        {"sf": 1_000, "floors": 20, "type": "office"},
    )

    # Missing elevator count is a disclosed one-cab proxy, never floors - 1.
    assert result["buckets"]["immediate"]["cost_range"] == {
        "low": 175_000.0,
        "high": 350_000.0,
    }
    assert result["buckets"]["yr-1"]["cost_range"] == {
        "low": 800.0,
        "high": 2_400.0,
    }
    assert result["buckets"]["yr-5"]["cost_range"] == {
        "low": 700.0,
        "high": 2_000.0,
    }
    assert result["buckets"]["yr-10"]["cost_range"] == {
        "low": 400.0,
        "high": 1_000.0,
    }
    assert "near-term" in result["near_term_funding_warning"].lower()

    with pytest.raises(ValueError, match="100%"):
        replacement_cost_range("roof", building_sf=1_000, extent="150%")
    with pytest.raises(ValueError, match="between 0 and 1"):
        replacement_cost_range(
            "roof", building_sf=1_000, extent={"fraction": 1.5}
        )


def test_rul_table_and_age_condition_ordering() -> None:
    assert {"rooftop_hvac_unit", "single_ply_roof", "elevator"} <= set(
        LIFESPAN_CONVENTIONS
    )
    assert all(
        row["low"] <= row["high"] and row["source_note"]
        for row in LIFESPAN_CONVENTIONS.values()
    )

    newer_good = remaining_useful_life(
        "rooftop_hvac_unit", 1, "good", "good"
    )
    older_poor = remaining_useful_life(
        "rooftop_hvac_unit", 18, "poor", "poor"
    )

    newer_range = newer_good["remaining_useful_life_years"]
    older_range = older_poor["remaining_useful_life_years"]
    assert older_range["low"] < newer_range["low"]
    assert older_range["high"] < newer_range["high"]
    assert newer_good["confidence_label"] in {"low", "medium", "high"}
    assert newer_good["replacement_cost_range"]["source_note"]
    assert "licensed" in newer_good["disclaimer"].lower()


def test_vintage_1975_exact_era_flags() -> None:
    result = vintage_risk_screen(1975, "office", "NY")

    assert _risk_ids(result) == {
        "asbestos",
        "lead_paint",
        "fire_sprinkler_legacy",
    }
    by_id = {flag["risk_id"]: flag for flag in result["flags"]}
    assert "ACM survey" in by_id["asbestos"]["specialist_test"]
    assert by_id["lead_paint"]["why"]
    assert result["limitations"]["pca_pdf_parsing"] == "out_of_scope"
    assert "licensed" in result["disclaimer"].lower()


def test_vintage_1995_exact_era_flags() -> None:
    result = vintage_risk_screen(1995, "office", "NY")

    assert _risk_ids(result) == {"polybutylene_plumbing", "eifs_moisture"}
    assert "asbestos" not in _risk_ids(result)
    eifs = next(flag for flag in result["flags"] if flag["risk_id"] == "eifs_moisture")
    assert "moisture" in eifs["specialist_test"].lower()


def test_change_of_use_triggers_accessibility_energy_and_fire() -> None:
    result = ada_code_exposure(
        {"year_built": 2000, "type": "office", "sf": 10_000, "floors": 1},
        {"change_of_use": True},
    )

    lines = result["triggered_upgrades"]
    assert {line["trigger_id"] for line in lines} == {
        "change_of_use_accessibility",
        "change_of_use_energy",
        "change_of_use_fire",
    }
    assert {line["category"] for line in lines} == {
        "accessibility",
        "energy",
        "fire_life_safety",
    }
    assert all(line["verification"] == VERIFY_LOCAL for line in lines)
    assert all(line["exposure_cost_range"]["low"] > 0 for line in lines)
    assert "jurisdiction-dependent" in result["jurisdiction_warning"]
    assert "licensed" in result["disclaimer"].lower()


def test_register_tags_and_sorts_by_hand_computed_priority() -> None:
    result = physical_risk_register(
        [
            {
                "finding": "Observed roof leak",
                "observed": True,
                "severity": "high",
                "cost_range": {"low": 10, "high": 20},
            },
            {
                "system": "hvac",
                "severity": "medium",
                "cost_range": {"low": 50, "high": 100},
            },
            {
                "title": "Facade concern",
                "specialist_test": "Envelope probe",
                "severity": "high",
                "cost_range": {"low": 25, "high": 50},
            },
        ],
        deal_id="deal-110",
    )

    rows = result["rows"]
    assert [row["description"] for row in rows] == [
        "hvac",
        "Facade concern",
        "Observed roof leak",
    ]
    assert [row["priority_score"] for row in rows] == [300, 200, 80]
    assert {row["tag"] for row in rows} == {
        "observed_fact",
        "model_estimate",
        "professional_opinion_needed",
    }
    assert result["tag_counts"] == {
        "model_estimate": 1,
        "observed_fact": 1,
        "professional_opinion_needed": 1,
    }
    assert "licensed" in result["disclaimer"].lower()


@pytest.mark.parametrize(
    "call",
    [
        lambda: safe_estimate_capex("not-findings", {}),
        lambda: safe_remaining_useful_life("not-a-system", 10, "fair"),
        lambda: safe_vintage_risk_screen("not-a-year", "office"),
        lambda: safe_ada_code_exposure({}, {}),
        lambda: safe_physical_risk_register("not-entries"),
    ],
    ids=["capex", "rul", "vintage", "code", "register"],
)
def test_tool_boundaries_return_error_objects(call: Callable[[], Any]) -> None:
    result = call()

    assert set(result) == {"error"}
    assert isinstance(result["error"], str)
    assert result["error"]
