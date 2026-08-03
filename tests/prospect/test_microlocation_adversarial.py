from __future__ import annotations

import inspect

import pytest

from cre_mcp.prospect.assemblage import fragmentation_report
from cre_mcp.prospect.microlocation import FACTOR_WEIGHTS, micro_location_score
from cre_mcp.prospect import tools


def _factor(result: dict, name: str) -> dict:
    return next(item for item in result["factors"] if item["factor"] == name)


def test_weights_and_arithmetic_are_exposed_and_uncalibrated() -> None:
    result = micro_location_score(
        {
            "corner": True,
            "frontage_ft": 100,
            "signalized_intersection": True,
            "ingress_egress_count": 2,
            "median_break": False,
            "visibility_notes": "Clear, prominent pylon signage",
        },
        nearby_anchors={"anchor_count": 2, "summary": "two anchors"},
    )

    assert result["calibration"] == "UNCALIBRATED"
    assert result["calibration_label"] == "UNCALIBRATED"
    assert "HEURISTIC" in result["honesty"]
    assert result["factor_weights"] == FACTOR_WEIGHTS
    assert result["factor_weight_total"] == 100
    assert result["coverage_pct"] == 100
    # 15 + 10 + 15 + (20 * 2/3) + 0 + 10 + (10 * 2/5)
    assert result["score_100"] == 67.33
    assert result["score"] == 67.33
    assert _factor(result, "frontage_ft")["basis"].startswith(
        "linear size convention"
    )
    assert _factor(result, "nearby_anchors")["observed_value"] == 2


def test_missing_and_nullable_factors_remain_explicit() -> None:
    result = micro_location_score(
        {
            "corner": None,
            "frontage_ft": None,
            "signalized_intersection": None,
            "ingress_egress_count": None,
            "median_break": None,
            "visibility_notes": None,
        }
    )

    assert result["score_100"] == 0
    assert result["available_factor_score_100"] is None
    assert result["coverage_pct"] == 0
    assert result["missing_factors"] == list(FACTOR_WEIGHTS)
    assert all(not factor["available"] for factor in result["factors"])
    assert "computer-vision" in result["scope_note"]
    assert "out of scope" in result["scope_note"]


def test_false_and_zero_are_observations_not_missing_data() -> None:
    result = micro_location_score(
        {
            "corner": False,
            "frontage_ft": 0,
            "signalized_intersection": False,
            "ingress_egress_count": 0,
            "median_break": False,
            "visibility_notes": "Poor visibility; storefront is obscured",
        },
        nearby_anchors=[],
    )

    assert result["missing_factors"] == []
    assert result["coverage_pct"] == 100
    assert result["score_100"] == 0
    assert _factor(result, "nearby_anchors")["available"] is True


@pytest.mark.parametrize("notes", ["not visible from road", "no signage"])
def test_negated_visibility_cues_do_not_receive_positive_credit(notes: str) -> None:
    result = micro_location_score({"visibility_notes": notes})

    visibility = _factor(result, "visibility_notes")
    assert visibility["normalized_score"] == 0
    assert visibility["weighted_points"] == 0
    assert "negative supplied-note cues" in visibility["basis"]


def test_unknown_inputs_are_surfaced_without_changing_known_factor_score() -> None:
    baseline = micro_location_score({"corner": True})
    with_typo = micro_location_score(
        {"corner": True, "frontge_ft": 999},
        nearby_anchors={"anchor_count": None, "mystery_metric": 10},
    )

    assert with_typo["score_100"] == baseline["score_100"] == 15
    assert with_typo["unrecognized_inputs"] == [
        "nearby_anchors.mystery_metric",
        "site.frontge_ft",
    ]
    assert "frontage_ft" in with_typo["missing_factors"]
    assert "nearby_anchors" in with_typo["missing_factors"]


def test_enrichment_poi_shapes_are_classified_without_fetching() -> None:
    result = micro_location_score(
        {},
        nearby_anchors=[
            {
                "brand": "Target",
                "category": "big_box",
                "distance_m": 200,
                "lat": 34.0,
                "lon": -118.0,
                "osm_id": 1,
            },
            {
                "brand": "Coffee Shop",
                "category": "cafe",
                "distance_m": 300,
                "lat": 34.0,
                "lon": -118.0,
                "osm_id": 2,
            },
            {
                "brand": "Generic Offices",
                "category": "office",
                "distance_m": 400,
                "lat": 34.0,
                "lon": -118.0,
                "osm_id": 3,
            },
        ],
    )

    anchors = _factor(result, "nearby_anchors")
    assert anchors["observed_value"] == 2
    assert anchors["normalized_score"] == 0.4
    assert anchors["weighted_points"] == 4
    assert "classify_anchor" in anchors["basis"]


def test_complementary_collection_is_compatible_with_enrichment_summary() -> None:
    result = micro_location_score(
        {},
        nearby_anchors={
            "anchor_count": None,
            "complementary": [{"brand": "A"}, {"brand": "B"}],
            "competitors": [{"brand": "C"}],
            "brands": ["A", "B", "C"],
            "summary": "three supplied POIs",
        },
    )

    assert _factor(result, "nearby_anchors")["observed_value"] == 2
    assert result["unrecognized_inputs"] == []


def test_invalid_input_uses_error_boundary_instead_of_throwing() -> None:
    assert "error" in micro_location_score("not a mapping")  # type: ignore[arg-type]

    invalid_field = micro_location_score({"corner": "yes"})
    assert invalid_field["error"] == "site.corner must be a boolean or null"

    invalid_anchors = micro_location_score({}, nearby_anchors={"anchor_count": -1})
    assert invalid_anchors["error"].startswith("nearby_anchors.anchor_count")


def test_fragmentation_unknown_rows_break_runs_and_are_not_silently_dropped() -> None:
    result = fragmentation_report(
        [
            {"parcel_id": "1", "owner_name": "Alpha LLC", "unexpected": "seen"},
            None,
            {"parcel_id": "2", "owner_name": "ALPHA LLC"},
        ]
    )

    assert result["parcel_count"] == 3
    assert result["distinct_owners"] == 1
    assert result["largest_contiguous_same_owner_run"] == 1
    assert result["unknown_owner_count"] == 1
    assert result["unrecognized_rows"] == [1]
    assert result["unrecognized_input_fields"] == ["unexpected"]


def test_plain_tool_signatures_do_not_hide_inputs_in_kwargs() -> None:
    boundaries = (
        tools.find_adjacent_parcels,
        tools.sale_leaseback_candidates,
        tools.stalled_project_signals,
        tools.portfolio_owner_scan,
        tools.adjust_rent_comp,
        tools.micro_location_score,
    )

    for boundary in boundaries:
        assert all(
            parameter.kind is not inspect.Parameter.VAR_KEYWORD
            for parameter in inspect.signature(boundary).parameters.values()
        )


def test_micro_location_tool_preserves_unknown_input_audit() -> None:
    result = tools.micro_location_score({"corner": True, "cornner": False})

    assert result["score_100"] == 15
    assert result["unrecognized_inputs"] == ["site.cornner"]
